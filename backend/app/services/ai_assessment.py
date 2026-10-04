"""Provider-neutral, temporary assessment controller and retention policy."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.api_errors import ApiError
from app.models.ai_assessment import AIAssessment, AIAssessmentFact, AIAssessmentQuestion
from app.services.ai_interaction import (
    AssessmentExplanation, AssessmentQuestionResult, AssessmentResult,
    InteractionMode, InteractionResponse, ResultKind, UrgentResult,
)
from app.services.ai_provider import AIGenerationRequest, AIMedia, get_clinical_ai_provider
from app.services.ai_safety import evaluate_safety
from app.services.ai_answer_scope import (
    AnswerScope, CLINICAL_ANSWER_RULES, ScopeError, generate_scope, number_evidence,
)
from app.services.clinical_knowledge import (
    EvidenceBundle, EvidenceStatus, GroundingStatus, query_from_assessment,
    retrieve_evidence, validate_evidence_references,
)

SCHEMA_VERSION = 1
MAX_ADAPTIVE_QUESTIONS = 6
RESUME_WINDOW = timedelta(hours=24)
RETENTION = timedelta(hours=72)
CONCEPTS = {
    "presenting_concern", "onset", "duration", "pattern", "progression",
    "severity", "functional_impact", "associated_symptom", "relevant_negative",
    "medical_history", "risk_history", "medication", "exposure", "age_context",
    "pregnancy_context", "safety_signal", "urinary_change", "pain", "fever",
    "swelling", "breathing", "bleeding", "hydration", "skin_change",
}
FACT_STATUSES = {"ASSERTED", "DENIED", "UNCERTAIN", "UNKNOWN"}
PROVENANCES = {"USER_STATED", "MODEL_INFERENCE", "ATTACHMENT_DERIVED"}
TERMINAL = {"COMPLETED", "URGENT", "CANCELLED", "EXPIRED"}
UNKNOWN_ANSWER = re.compile(
    r"^(?:i (?:do not|don't) know|(?:i(?:'m| am) )?not sure|"
    r"(?:i )?(?:can't|cannot) remember|unsure)\W*$", re.I,
)
REFUSED_ANSWER = re.compile(
    r"^(?:i(?:'d| would) rather not say|(?:i )?prefer not to (?:say|answer)|"
    r"(?:i )?(?:can't|cannot|am unable to) answer|"
    r"i (?:don't|do not) want to answer|skip|no comment)\W*$", re.I,
)
TOPIC_SWITCH = re.compile(r"^(?:new (?:question|issue|topic)|different (?:question|issue|problem)|switch(?:ing)? topics|on another matter)\b", re.I)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def is_topic_switch(message: str) -> bool:
    return bool(TOPIC_SWITCH.search(message.strip()))


def _touch(session: AIAssessment, request_id: str, now: datetime) -> None:
    session.updated_at = now
    session.last_activity_at = now
    session.expires_at = now + RETENTION
    session.latest_operation_id = request_id
    session.state_version += 1


def owned_session(db: Session, patient_id: int, assessment_id: str, *, lock: bool = False) -> AIAssessment:
    query = db.query(AIAssessment).filter(
        AIAssessment.id == assessment_id, AIAssessment.patient_id == patient_id,
    )
    session = (query.with_for_update() if lock else query).first()
    if session is None:
        raise ApiError(404, "assessment_not_found", "This assessment is no longer available.")
    if session.schema_version != SCHEMA_VERSION:
        raise ApiError(409, "assessment_version_unsupported", "This assessment can no longer be resumed.")
    return session


def _require_mutable(session: AIAssessment, expected_version: int, now: datetime) -> None:
    if session.state_version != expected_version:
        raise ApiError(409, "stale_version", "This assessment changed elsewhere. Refresh to continue.")
    if session.status in TERMINAL or aware(session.expires_at) <= now:
        raise ApiError(409, "assessment_closed", "This assessment is no longer active.")
    if aware(session.last_activity_at) + RESUME_WINDOW <= now:
        session.status = "ABANDONED"
        session.abandoned_at = now
        raise ApiError(409, "assessment_expired", "This assessment can no longer be resumed.")


def _latest_facts(session: AIAssessment) -> list[AIAssessmentFact]:
    latest = {}
    for fact in session.facts:
        if fact.provenance != "MODEL_INFERENCE":
            latest[fact.concept] = fact
    return list(latest.values())


def _contradictions(session: AIAssessment) -> set[str]:
    by_concept: dict[str, set[str]] = {}
    for fact in session.facts:
        if fact.provenance == "USER_STATED" and fact.status in {"ASSERTED", "DENIED"}:
            by_concept.setdefault(fact.concept, set()).add(fact.status)
    resolved = {q.concept for q in session.questions
                if q.semantic_key.startswith("clarify:") and q.answered_at is not None
                and q.answer_status == "ASSERTED"}
    return {concept for concept, values in by_concept.items()
            if len(values) > 1 and concept not in resolved}


def _record_fact(
    db: Session, session: AIAssessment, *, concept: str, value: str,
    status: str, provenance: str, request_id: str,
    attachment_id: str | None = None,
) -> None:
    if concept not in CONCEPTS or status not in FACT_STATUSES or provenance not in PROVENANCES:
        return
    value = " ".join(value.split())[:1000]
    if not value:
        return
    prior = next((fact for fact in reversed(session.facts)
                  if fact.concept == concept and fact.provenance == provenance), None)
    if prior is not None and prior.value.casefold() == value.casefold() and prior.status == status:
        return
    fact = AIAssessmentFact(
        id=str(uuid.uuid4()), assessment_id=session.id, concept=concept,
        value=value, status=status, provenance=provenance,
        source_turn_id=request_id if provenance == "USER_STATED" else None,
        attachment_id=attachment_id if provenance == "ATTACHMENT_DERIVED" else None,
        created_at=utcnow(), supersedes_fact_id=prior.id if prior else None,
    )
    session.facts.append(fact)
    db.add(fact)


def _proposal_payload(result) -> dict:
    if result.completion != "normal":
        raise ValueError("incomplete structured generation")
    data = result.structured_data
    if data is None:
        data = json.loads(result.text)
    if not isinstance(data, dict):
        raise ValueError("structured object required")
    return data


def _state_for_provider(session: AIAssessment) -> dict:
    return {
        "presenting_concern": session.presenting_concern,
        "language": session.language,
        "facts": [{"id": f.id, "concept": f.concept, "value": f.value,
                   "status": f.status, "provenance": f.provenance}
                  for f in session.facts],
        "questions": [{"concept": q.concept, "question": q.text,
                       "answer": q.answer_text, "answer_status": q.answer_status}
                      for q in session.questions],
        "unresolved_contradictions": sorted(_contradictions(session)),
    }


async def _plan(session: AIAssessment, message: str, attachment: AIMedia | None, lab_summary: str | None) -> dict:
    instructions = (
        "You are proposing an adaptive patient assessment step, not making the final decision. "
        "Return JSON object {facts:[{concept,value,status,provenance,evidence_quote}], "
        "needs:[{concept,question,decision_change,safety_impact,next_step_impact,differential_impact,uncertainty_reduction,burden}], "
        "ready:boolean, readiness_reasons:[string], safety_signals:[string]}. "
        "Use safety_signals immediate_emergency if urgent medical care cannot wait. "
        "Use only the controlled concepts listed below. "
        "USER_STATED facts require an exact short evidence_quote from the CURRENT patient message. "
        "Do not infer denials from silence. ATTACHMENT_DERIVED facts require an actually processed attachment. "
        "MODEL_INFERENCE is not a patient fact. Ask at most one focused question in normal patient language. "
        "A detailed initial report may already be ready. Never invent a citation. "
        "A need is permitted ONLY for a specific missing fact whose answer materially changes "
        "urgency, the clinical problem/category, testing or next action/level of care. "
        "decision_change must name that specific decision and how the answer would change it. "
        "Score safety_impact for urgency, differential_impact for category and next_step_impact "
        "for testing/action (0 means no change). Uncertainty reduction alone is insufficient. "
        "Return ready true and needs [] when no such fact exists, the patient does not know, "
        "declines/cannot answer, a substantially identical fact was already asked, remaining "
        "uncertainty requires examination/testing, more detail would not alter action, or six "
        "questions have already been asked. Preserve uncertainty at this operational ceiling; "
        "it does not establish clinical completeness. Never rephrase an unanswered question. "
        f"Controlled concepts: {', '.join(sorted(CONCEPTS))}."
    )
    parts: list[str | AIMedia] = [instructions, json.dumps(_state_for_provider(session)),
                                  "CURRENT_PATIENT_MESSAGE: " + message]
    if lab_summary:
        parts.append("OWNED_LAB_DATA: " + lab_summary)
    if attachment:
        parts.append(attachment)
    result = await get_clinical_ai_provider().generate(AIGenerationRequest(
        purpose="assessment", parts=tuple(parts), output_tokens=1300, structured=True,
    ))
    return _proposal_payload(result)


def _record_proposed_facts(
    db: Session, session: AIAssessment, proposal: dict, message: str,
    request_id: str, attachment_id: str | None,
) -> None:
    facts = proposal.get("facts", [])
    if not isinstance(facts, list):
        return
    for entry in facts[:16]:
        if not isinstance(entry, dict):
            continue
        concept, value, status, provenance = (
            entry.get("concept"), entry.get("value"), entry.get("status"), entry.get("provenance"),
        )
        if not all(isinstance(item, str) for item in (concept, value, status, provenance)):
            continue
        if provenance == "USER_STATED":
            quote = entry.get("evidence_quote")
            if not isinstance(quote, str) or len(quote.strip()) < 2 or quote.casefold() not in message.casefold():
                continue
            if value.casefold() not in message.casefold():
                value = quote
            if status == "DENIED" and not re.search(r"\b(no|not|never|without|don't|do not|den[yi])\b", quote, re.I):
                continue
        elif provenance == "ATTACHMENT_DERIVED":
            if not attachment_id:
                continue
        elif provenance == "MODEL_INFERENCE":
            # Inferences are retained for planning, never shown as patient history.
            pass
        else:
            continue
        _record_fact(db, session, concept=concept, value=value, status=status,
                     provenance=provenance, request_id=request_id, attachment_id=attachment_id)


def _rank_need(entry: dict) -> int:
    def score(name: str) -> int:
        value = entry.get(name, 0)
        return max(0, min(3, value)) if isinstance(value, int) else 0
    return (score("safety_impact") * 10000 + score("next_step_impact") * 1000
            + score("differential_impact") * 100 + score("uncertainty_reduction") * 10
            - score("burden"))


def _choose_question(session: AIAssessment, proposal: dict) -> tuple[str, str, str] | None:
    if (len(session.questions) >= MAX_ADAPTIVE_QUESTIONS or proposal.get("ready") is True
            or proposal.get("remaining_uncertainty_requires_testing") is True
            or any(q.answer_status in {"UNKNOWN", "UNCERTAIN"} for q in session.questions)):
        return None
    contradictions = _contradictions(session)
    fact_key = lambda concept: "duration" if concept == "onset" else concept
    prior_keys = {fact_key(q.concept) for q in session.questions}
    prior_text = {" ".join(q.text.casefold().split()) for q in session.questions}
    known = {f.concept for f in _latest_facts(session)}
    needs = proposal.get("needs", [])
    if not isinstance(needs, list):
        return None
    candidates = sorted((n for n in needs[:16] if isinstance(n, dict)), key=_rank_need, reverse=True)
    for need in candidates:
        impact = any(type(need.get(name)) is int and need[name] > 0 for name in
                     ("safety_impact", "next_step_impact", "differential_impact"))
        decision = need.get("decision_change")
        if not impact or not isinstance(decision, str) or not decision.strip():
            continue
        concept, question = need.get("concept"), need.get("question")
        if (concept not in CONCEPTS or concept == "presenting_concern"
                or fact_key(concept) in prior_keys
                or (concept in known and concept not in contradictions)):
            continue
        if not isinstance(question, str):
            continue
        question = " ".join(question.split())
        if len(question) > 220 or len(question) < 8 or question.count("?") != 1 or not question.endswith("?"):
            continue
        if question.count(",") >= 3:
            focused = {
                "fever": "Have you had a fever?",
                "breathing": "Are you having trouble breathing?",
                "bleeding": "Have you noticed any bleeding?",
            }.get(concept)
            if focused and " ".join(focused.casefold().split()) not in prior_text:
                return concept, concept, focused
            continue
        if re.search(r"would you like|start an assessment|\\bdiagnos|\\bpercent", question, re.I):
            continue
        if " ".join(question.casefold().split()) in prior_text:
            continue
        key = f"clarify:{concept}" if concept in contradictions else concept
        return concept, key, question
    return None


def _result_response(session: AIAssessment, request_id: str, result: AssessmentResult,
                     evidence: EvidenceBundle | None = None) -> InteractionResponse:
    used = validate_evidence_references(result.evidence_ids, evidence) if evidence else ()
    grounding = (GroundingStatus.GROUNDED if used and evidence.status == EvidenceStatus.SUFFICIENT
                 else GroundingStatus.PARTIALLY_GROUNDED if used
                 else GroundingStatus.UNGROUNDED)
    return InteractionResponse(
        request_id=request_id, interaction_id=session.id, assessment_id=session.id,
        state_version=session.state_version, mode=InteractionMode.ASSESSMENT,
        result_kind=ResultKind.ASSESSMENT_RESULT, result=result,
        evidence_items=[item.public_metadata() for item in used],
        grounding_status=grounding,
    )


def _scope_result(scope: AnswerScope, session: AIAssessment,
                  evidence_ids: tuple[str, ...]) -> AssessmentResult:
    facts = [f for f in _latest_facts(session)
             if f.provenance in {"USER_STATED", "ATTACHMENT_DERIVED"}
             and f.status in {"ASSERTED", "DENIED", "UNCERTAIN"}]
    # Facts/provenance remain server-owned; no model-authored patient history.
    stated = [f.value for f in facts if f.status != "DENIED"]
    negatives = [f.value for f in facts if f.status == "DENIED"]
    return AssessmentResult(
        what_you_told=stated,
        possible_explanations=[AssessmentExplanation(text=p.text, fact_ids=[f.id for f in facts])
                               for p in scope.supported_points],
        why_considered=stated if scope.supported_points else [],
        important_negatives=negatives,
        next_steps=[p.text for p in scope.next_steps],
        urgent_help_if=[p.text for p in scope.warning_points],
        limitations=" ".join(scope.not_established), evidence_ids=list(evidence_ids),
    )


async def _final_result(session: AIAssessment,
                        evidence: EvidenceBundle | None = None) -> AssessmentResult:
    numbered = number_evidence(evidence.model_context() if evidence else None)
    instructions = CLINICAL_ANSWER_RULES + (
        f" Communicate exclusively in {session.language}. "
        "Patient facts may conflict or be unknown; do not resolve those by guessing. "
        "The server constructs patient history from verified provenance. "
        "Preserve clinically important uncertainty, including examination/testing "
        "that cannot be replaced by further chat."
    )
    state = _state_for_provider(session)
    state["facts"] = [{"id": f.id, "concept": f.concept, "value": f.value,
                       "status": f.status, "provenance": f.provenance}
                      for f in _latest_facts(session)]
    try:
        scope = await generate_scope(get_clinical_ai_provider(), AIGenerationRequest(
            purpose="assessment_result",
            parts=(instructions, json.dumps(state), numbered.model_context()),
            output_tokens=1700, structured=True,
        ), numbered)
        return _scope_result(scope, session, numbered.evidence_ids(scope))
    except (ScopeError, ValueError, TypeError) as exc:
        raise ApiError(503, "assessment_result_invalid",
                       "We couldn't finish this assessment. Please try again.") from exc


async def advance_assessment(
    db: Session, *, patient_id: int, request_id: str, assessment_id: str | None,
    expected_version: int | None, message: str, language: str,
    attachment: AIMedia | None = None, attachment_id: str | None = None,
    lab_summary: str | None = None, source_summary_id: str | None = None,
) -> InteractionResponse:
    now = utcnow()
    if assessment_id:
        if expected_version is None:
            raise ApiError(422, "assessment_version_required", "Refresh this assessment before continuing.")
        session = owned_session(db, patient_id, assessment_id, lock=True)
        _require_mutable(session, expected_version, now)
        if session.status not in {"ACTIVE", "ABANDONED", "READY"}:
            raise ApiError(409, "assessment_closed", "This assessment is no longer active.")
        if session.status == "ABANDONED":
            session.status = "ACTIVE"
            session.abandoned_at = None
    else:
        session = AIAssessment(
            id=str(uuid.uuid4()), patient_id=patient_id, status="ACTIVE",
            presenting_concern=message[:2000], language=language,
            schema_version=SCHEMA_VERSION, state_version=0, readiness=False,
            readiness_reasons=[], created_at=now, updated_at=now,
            last_activity_at=now, expires_at=now + RETENTION,
            originating_request_id=request_id, source_summary_id=source_summary_id,
            usage_committed=False,
        )
        db.add(session)
        _record_fact(db, session, concept="presenting_concern", value=message,
                     status="ASSERTED", provenance="USER_STATED", request_id=request_id)
    if session.status == "READY" and message.strip():
        # A new answer in READY can refine the case; retry with empty text instead.
        session.status = "ACTIVE"
        session.readiness = False
    if session.status == "ACTIVE" and message.strip():
        unanswered = next((q for q in reversed(session.questions) if q.answered_at is None), None)
        if unanswered:
            answer = message.strip()[:2000]
            unanswered.answer_text = answer
            unanswered.answered_at = now
            unanswered.answer_turn_id = request_id
            normalized_answer = answer.replace("\u2019", "'")
            unanswered.answer_status = ("UNKNOWN" if UNKNOWN_ANSWER.match(normalized_answer) else
                                         "UNCERTAIN" if REFUSED_ANSWER.match(normalized_answer) else "ASSERTED")
            if unanswered.answer_status == "UNKNOWN":
                _record_fact(db, session, concept=unanswered.concept, value=answer,
                             status="UNKNOWN", provenance="USER_STATED", request_id=request_id)
            elif unanswered.answer_status == "UNCERTAIN":
                _record_fact(db, session, concept=unanswered.concept, value=answer,
                             status="UNCERTAIN", provenance="USER_STATED", request_id=request_id)
            elif answer.casefold() in {"no", "nope", "none"}:
                _record_fact(db, session, concept=unanswered.concept, value="No: " + unanswered.text,
                             status="DENIED", provenance="USER_STATED", request_id=request_id)
            elif answer.casefold() in {"yes", "yeah"}:
                _record_fact(db, session, concept=unanswered.concept, value="Yes: " + unanswered.text,
                             status="ASSERTED", provenance="USER_STATED", request_id=request_id)
        safety = evaluate_safety(message)
        if safety.urgent_override:
            _touch(session, request_id, now)
            session.status = "URGENT"
            session.usage_committed = True
            response = InteractionResponse(
                request_id=request_id, interaction_id=session.id, assessment_id=session.id,
                state_version=session.state_version, mode=InteractionMode.URGENT,
                result_kind=ResultKind.URGENT,
                result=UrgentResult(
                    action="Call 112 now or go to the nearest emergency department. Do not wait for an online assessment.",
                    reason="These symptoms may need immediate medical care.",
                ),
            )
            session.last_response_json = response.model_dump(mode="json")
            return response
        proposal = await _plan(session, message, attachment, lab_summary)
        _record_proposed_facts(db, session, proposal, message, request_id, attachment_id)
        if "immediate_emergency" in (proposal.get("safety_signals") or []):
            _touch(session, request_id, now)
            session.status = "URGENT"
            session.usage_committed = True
            response = InteractionResponse(
                request_id=request_id, interaction_id=session.id, assessment_id=session.id,
                state_version=session.state_version, mode=InteractionMode.URGENT,
                result_kind=ResultKind.URGENT,
                result=UrgentResult(
                    action="Call 112 now or go to the nearest emergency department. Do not wait for an online assessment.",
                    reason="These symptoms may need immediate medical care.",
                ),
            )
            session.last_response_json = response.model_dump(mode="json")
            return response
        question = _choose_question(session, proposal)
        if question is not None:
            concept, key, text = question
            session.questions.append(AIAssessmentQuestion(
                id=str(uuid.uuid4()), assessment_id=session.id, concept=concept,
                semantic_key=key, text=text, asked_at=now,
            ))
            _touch(session, request_id, now)
            session.status = "ACTIVE"
            response = InteractionResponse(
                request_id=request_id, interaction_id=session.id, assessment_id=session.id,
                state_version=session.state_version, mode=InteractionMode.ASSESSMENT,
                result_kind=ResultKind.ASSESSMENT_QUESTION,
                result=AssessmentQuestionResult(question=text),
            )
            session.last_response_json = response.model_dump(mode="json")
            return response
        session.status = "READY"
        session.readiness = True
        session.readiness_reasons = [str(code)[:64] for code in proposal.get("readiness_reasons", [])[:8]] if isinstance(proposal.get("readiness_reasons"), list) else []
    _touch(session, request_id, now)
    evidence_query = query_from_assessment(
        (f"{fact.concept} {fact.value}" for fact in _latest_facts(session)
         if fact.status != "UNKNOWN"), session.presenting_concern,
    )
    evidence = await retrieve_evidence(db, evidence_query)
    evidence = replace(evidence, items=evidence.items[:5 if attachment_id or lab_summary else 3])
    try:
        result = (await _final_result(session, evidence) if evidence.items
                  else await _final_result(session))
    except ApiError:
        # Keep validated facts and READY state; an unchanged client may retry with
        # the refreshed version. The provider call failed without charging usage.
        db.commit()
        raise
    session.status = "COMPLETED"
    session.completed_at = utcnow()
    session.result_json = result.model_dump(mode="json")
    session.usage_committed = True
    response = _result_response(session, request_id, result, evidence)
    session.last_response_json = response.model_dump(mode="json")
    return response


def cancel_assessment(db: Session, *, patient_id: int, assessment_id: str,
                      expected_version: int, request_id: str) -> dict:
    session = owned_session(db, patient_id, assessment_id, lock=True)
    if session.status == "CANCELLED" and session.latest_operation_id == request_id:
        if expected_version != session.state_version - 1:
            raise ApiError(409, "request_conflict", "This request ID was used for different content.")
        return {"status": "CANCELLED", "assessment_id": session.id, "state_version": session.state_version}
    _require_mutable(session, expected_version, utcnow())
    if session.status not in {"ACTIVE", "READY", "ABANDONED"}:
        raise ApiError(409, "assessment_closed", "This assessment is no longer active.")
    _touch(session, request_id, utcnow())
    session.status = "CANCELLED"
    db.commit()
    return {"status": "CANCELLED", "assessment_id": session.id, "state_version": session.state_version}


def abandon_for_topic_switch(db: Session, patient_id: int, assessment_id: str,
                             expected_version: int | None, request_id: str) -> None:
    if patient_id is None or expected_version is None:
        raise ApiError(422, "assessment_version_required", "Refresh this assessment before continuing.")
    session = owned_session(db, patient_id, assessment_id, lock=True)
    _require_mutable(session, expected_version, utcnow())
    if session.status not in {"ACTIVE", "READY", "ABANDONED"}:
        raise ApiError(409, "assessment_closed", "This assessment is no longer active.")
    _touch(session, request_id, utcnow())
    session.status = "ABANDONED"
    session.abandoned_at = utcnow()


def assessment_snapshot(session: AIAssessment) -> dict:
    return {
        "assessment_id": session.id, "status": session.status,
        "state_version": session.state_version,
        "presenting_concern": session.presenting_concern,
        "language": session.language,
        "last_activity_at": session.last_activity_at,
        "response": session.last_response_json,
        "questions": [{"question": q.text, "answer": q.answer_text,
                       "answer_status": q.answer_status} for q in session.questions],
    }


def resumable_assessment(db: Session, patient_id: int) -> AIAssessment | None:
    now = utcnow()
    candidates = db.query(AIAssessment).filter(
        AIAssessment.patient_id == patient_id,
        AIAssessment.schema_version == SCHEMA_VERSION,
        AIAssessment.expires_at > now,
        AIAssessment.status.in_(["ACTIVE", "ABANDONED", "READY", "COMPLETED", "URGENT"]),
    ).order_by(AIAssessment.last_activity_at.desc()).limit(5).all()
    for session in candidates:
        if session.status in {"COMPLETED", "URGENT"} or aware(session.last_activity_at) + RESUME_WINDOW > now:
            return session
    return None


def cleanup_assessments() -> tuple[int, int]:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        now = utcnow()
        abandoned = db.query(AIAssessment).filter(
            AIAssessment.status.in_(["ACTIVE", "READY"]),
            AIAssessment.last_activity_at <= now - RESUME_WINDOW,
        ).update({AIAssessment.status: "ABANDONED", AIAssessment.abandoned_at: now},
                 synchronize_session=False)
        expired = db.execute(delete(AIAssessment).where(AIAssessment.expires_at <= now)).rowcount
        db.commit()
        return abandoned, expired
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
