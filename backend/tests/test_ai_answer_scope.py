"""Acquisition stop rules and deterministic scope contracts, not a medical judge."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import ai_assessment, ai_service, ai_orchestrator
from app.services.ai_answer_scope import (
    CLINICAL_ANSWER_RULES, ScopeError, generate_scope, number_evidence,
    render_scope, validate_scope,
)
from app.services.ai_provider import AIGenerationRequest, AIGenerationResult
from app.services.ai_router import RouterDecision
from app.services.clinical_knowledge import EvidenceBundle, EvidenceStatus
from tests.ai_provider_fakes import scope_payload
from tests.test_ai_wave3 import (
    db as assessment_db, PlanProvider, plan, need, fact, advance, valid_final,
)
from tests.test_ai_wave4 import item


def evidence():
    return EvidenceBundle(EvidenceStatus.SUFFICIENT, (
        item(excerpt="Urinalysis checks urine for abnormalities. Urine testing measures protein."),
        item(evidence_id="chunk-b", excerpt="Contact your prescriber about suspected medicine reactions."),
    ))


class ScopeProvider:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        value = self.outputs.pop(0)
        return AIGenerationResult(value if isinstance(value, str) else json.dumps(value), "normal")


def state(questions=(), facts=()):
    return SimpleNamespace(questions=list(questions), facts=list(facts))


def question(concept="duration", answer_status="ASSERTED"):
    return SimpleNamespace(concept=concept, semantic_key=concept, text="When did this start?",
                           answer_status=answer_status, answered_at=ai_assessment.utcnow())


def test_decision_changing_missing_question_is_selected():
    assert ai_assessment._choose_question(state(), plan(needs=[need("duration", "When did this start?")]))


@pytest.mark.parametrize("proposal", [
    plan(), plan(ready=True),
    plan(needs=[dict(need("duration", "When did this start?"),
                    safety_impact=0, next_step_impact=0, differential_impact=0)]),
    plan(needs=[dict(need("duration", "When did this start?"), decision_change="")]),
    dict(plan(needs=[need("duration", "When did this start?")]), remaining_uncertainty_requires_testing=True),
])
def test_no_decision_change_or_testing_uncertainty_stops(proposal):
    assert ai_assessment._choose_question(state(), proposal) is None


@pytest.mark.parametrize("answer", ["I don't know", "I cannot answer", "I prefer not to answer"])
def test_unknown_or_declined_answer_finishes_without_another_question(assessment_db, monkeypatch, answer):
    provider = PlanProvider([plan(needs=[need("duration", "When did this start?")]),
                             plan(needs=[need("fever", "Have you had a fever?", safety=3)])],
                            finals=[valid_final])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    first = advance(assessment_db, "A persistent symptom")
    result = advance(assessment_db, answer, assessment_id=first.assessment_id,
                     version=first.state_version, request_id="second")
    assert result.result_kind.value == "ASSESSMENT_RESULT"
    session = ai_assessment.owned_session(assessment_db, 7, first.assessment_id)
    assert len(session.questions) == 1 and session.usage_committed
    assert not result.evidence_items and not result.result.next_steps


@pytest.mark.parametrize("concept", ["duration", "onset"])
def test_substantially_same_fact_cannot_be_rephrased(concept):
    assert ai_assessment._choose_question(state([question()]),
        plan(needs=[need(concept, "How long have you noticed this?")])) is None


def test_six_question_ceiling_stops_even_with_high_impact_missing_need():
    history = [question(concept) for concept in
               ("duration", "fever", "pain", "swelling", "medication", "hydration")]
    assert ai_assessment._choose_question(state(history),
        plan(needs=[need("breathing", "Are you having trouble breathing?", safety=3)])) is None


def test_six_question_ceiling_completes_with_uncertainty(assessment_db, monkeypatch):
    concepts = ["duration", "pattern", "progression", "severity", "medication", "exposure", "hydration"]
    provider = PlanProvider([plan(needs=[need(c, f"What is the relevant {c} detail?")])
                             for c in concepts], finals=[valid_final])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    result = advance(assessment_db, "A persistent symptom")
    for turn in range(6):
        assert result.result_kind.value == "ASSESSMENT_QUESTION"
        result = advance(assessment_db, "Some details", assessment_id=result.assessment_id,
                         version=result.state_version, request_id=f"answer-{turn}")
    assert result.result_kind.value == "ASSESSMENT_RESULT"
    session = ai_assessment.owned_session(assessment_db, 7, result.assessment_id)
    assert len(session.questions) == 6 and result.result.limitations


def test_urgent_stops_acquisition_before_any_final_scope(assessment_db, monkeypatch):
    provider = PlanProvider([plan(needs=[need("duration", "When did this start?")])])
    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    first = advance(assessment_db, "A persistent symptom")
    result = advance(assessment_db, "I have severe chest pain and I cannot breathe",
                     assessment_id=first.assessment_id, version=first.state_version, request_id="urgent")
    assert result.result_kind.value == "URGENT" and len(provider.requests) == 1


def test_evidence_numbering_is_stable_and_references_reconstruct_real_metadata():
    numbered = number_evidence(evidence().model_context())
    assert numbered == number_evidence(evidence().model_context())
    scope = validate_scope(scope_payload("Urine testing measures protein.", sentence_id="E1:S2"), numbered)
    assert numbered.evidence_ids(scope) == ("chunk-a",)
    assert numbered.context["items"][0]["sentences"][1]["text"] == "Urine testing measures protein."
    assert "E1:S2" not in render_scope(scope)


@pytest.mark.parametrize("sentence_id", ["E1:S99", "E7:S1", "chunk-a", "", 2])
def test_unknown_or_invalid_sentence_is_rejected(sentence_id):
    with pytest.raises(ValueError):
        validate_scope(scope_payload() | {"supported_points": [
            {"text": "A supported point", "evidence_sentence_ids": [sentence_id]}]},
                       number_evidence(evidence().model_context()))


def test_each_medical_collection_requires_nonempty_supplied_references():
    for key in ("supported_points", "next_steps", "warning_points"):
        data = scope_payload()
        data[key] = [{"text": "A point", "evidence_sentence_ids": []}]
        with pytest.raises(ValueError):
            validate_scope(data, number_evidence(evidence().model_context()))


def test_testing_remains_supported_while_cause_and_diagnosis_are_not_established(monkeypatch):
    data = scope_payload("Urine testing can measure protein.", sentence_id="E1:S2")
    data["next_steps"] = [{"text": "Discuss urinalysis as an evaluation.", "evidence_sentence_ids": ["E1:S1"]}]
    data["not_established"] = ["The cause of the urine appearance is not established.",
                               "Whether protein or kidney disease is present is not established."]
    provider = ScopeProvider([data])
    monkeypatch.setattr(ai_service, "get_clinical_ai_provider", lambda: provider)
    response = asyncio.run(ai_service.get_medical_response("Why does my urine look foamy?",
                          evidence_context=evidence().model_context()))
    assert response.answer_scope.not_established == data["not_established"]
    assert response.evidence_ids == ("chunk-a",) and len(provider.requests) == 1
    assert "testing guidance into diagnosis" in provider.requests[0].parts[0]


def test_prescription_and_current_constraints_are_in_the_single_reasoning_contract():
    contract = " ".join(CLINICAL_ANSWER_RULES.split())
    assert "that exact action in this situation" in contract
    assert "require supplied CURRENT evidence" in contract
    assert "only when evidence supports that contact" in contract
    assert "real but unrelated ID" in contract


def test_no_evidence_renders_only_honest_uncertainty(monkeypatch):
    provider = ScopeProvider([scope_payload()])
    monkeypatch.setattr(ai_service, "get_clinical_ai_provider", lambda: provider)
    response = asyncio.run(ai_service.get_medical_response("What is the current recommendation?"))
    assert response.evidence_ids == () and not response.answer_scope.next_steps
    assert response.text == "This information does not establish a diagnosis."
    assert "Sources" not in response.text and "What to do next" not in response.text
    assert len(provider.requests) == 1


def test_conversation_scope_follows_retrieval_and_uses_only_backend_metadata(monkeypatch):
    events = []
    provider = ScopeProvider([scope_payload("Urine testing measures protein.", sentence_id="E1:S2")])

    async def route(_value):
        return RouterDecision(mode="CONVERSATION", confidence=1, reason_codes=["information"])

    async def retrieve(*_args, **_kwargs):
        events.append("retrieval")
        return evidence()

    monkeypatch.setattr(ai_orchestrator, "route_interaction", route)
    monkeypatch.setattr(ai_orchestrator, "retrieve_evidence", retrieve)
    monkeypatch.setattr(ai_service, "get_clinical_ai_provider", lambda: provider)
    result = asyncio.run(ai_orchestrator.run_interaction(ai_orchestrator.InteractionInput(
        request_id="synthetic", interaction_id=None, message="What is urinalysis?",
        language="English", history=[], user_context={}, db=object())))
    assert events == ["retrieval"] and len(provider.requests) == 1
    assert result.evidence_items[0].canonical_url == evidence().items[0].canonical_url
    assert result.result.evidence_ids == ["chunk-a"]


def test_assessment_retrieval_uses_whole_verified_case_and_privacy_normalizer(assessment_db, monkeypatch):
    provider = PlanProvider([plan(facts=[fact("duration", "Three months"),
        fact("fever", "No fever", status="DENIED"), fact("medication", "diabetes medicine")], ready=True)],
        finals=[valid_final])
    seen = []

    async def retrieve(_db, query):
        seen.append(query.normalized_text())
        return EvidenceBundle(EvidenceStatus.NONE)

    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_assessment, "retrieve_evidence", retrieve)
    result = advance(assessment_db, "Ada at 12 Broad Street, 08012345678: Three months. No fever. diabetes medicine")
    assert result.result_kind.value == "ASSESSMENT_RESULT"
    assert {"fever", "diabetes", "medicine"} <= set(seen[0].split())
    assert not any(pii in seen[0] for pii in ("ada", "broad", "08012345678"))
    assert result.result.important_negatives == ["No fever"]
    assert provider.requests[-1].purpose == "assessment_result"


@pytest.mark.parametrize("outputs,success", [
    (["{", scope_payload()], True), ([{}, {}, scope_payload()], False),
])
def test_malformed_scope_has_at_most_one_structure_only_repair(outputs, success):
    provider = ScopeProvider(outputs)
    request = AIGenerationRequest("standard", ("synthetic inputs",), 500, structured=True)
    operation = generate_scope(provider, request, number_evidence(None))
    if success:
        assert asyncio.run(operation).not_established
    else:
        with pytest.raises(ScopeError):
            asyncio.run(operation)
    assert len(provider.requests) == 2
    assert "preserve its clinical meaning" in provider.requests[1].parts[-1]
    assert "Do not perform another medical assessment" in provider.requests[1].parts[-1]


@pytest.mark.parametrize("extra", [{"sources": []}, {"title": "invented"}, {"kind": "MESSAGE"}])
def test_model_source_metadata_or_wrong_result_shape_is_rejected(extra):
    with pytest.raises(ValueError):
        validate_scope(scope_payload() | extra, number_evidence(None))


def test_memory_is_hidden_and_keeps_existing_sanitization(monkeypatch):
    provider = ScopeProvider([scope_payload() | {"memory_update": "<Earlier> reported concern."}])
    monkeypatch.setattr(ai_service, "get_clinical_ai_provider", lambda: provider)
    result = asyncio.run(ai_service.get_medical_response("Follow up", update_memory=True))
    assert result.memory_update == "Earlier reported concern."
    assert "Earlier" not in result.text
