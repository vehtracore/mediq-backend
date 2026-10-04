"""One clinical generation, deterministic citations and unchanged planning/state."""

import asyncio
import json

import pytest

from app.services import ai_service, ai_assessment, ai_orchestrator, ai_router
from app.services.ai_provider import AIGenerationResult
from app.services.ai_router import RouterDecision, _ROUTER_INSTRUCTION
from app.services.clinical_knowledge import EvidenceBundle, EvidenceStatus
from tests.test_ai_wave4 import item
from tests.ai_provider_fakes import scope_json, scope_payload
from tests.test_ai_wave3 import (
    db as assessment_db, PlanProvider, plan, need, fact, advance, valid_final,
)


class Provider:
    def __init__(self, text, completion='normal'):
        self.text = text
        self.completion = completion
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return AIGenerationResult(self.text, self.completion)


def bundle(count=1, **changes):
    return EvidenceBundle(status=EvidenceStatus.SUFFICIENT,
                          items=tuple(item(evidence_id=f'chunk-{i}', chunk_id=f'chunk-{i}',
                                           **changes) for i in range(count)))


def test_grounded_conversation_has_one_generation_and_no_sentence_reviewer(monkeypatch):
    original = 'Ask your clinician about evaluation and urine testing. The cause is uncertain.'
    provider = Provider(scope_json(original, sentence_id='E1:S1'))
    monkeypatch.setattr(ai_service, 'get_clinical_ai_provider', lambda: provider)
    response = asyncio.run(ai_service.get_medical_response(
        'What does this mean?', evidence_context=bundle().model_context()))
    assert response.text == original and response.evidence_ids == ('chunk-0',)
    assert len(provider.requests) == 1 and provider.requests[0].structured
    assert not hasattr(ai_service, '_evidence_review')
    assert not hasattr(ai_service, 'medical_content_violation')


@pytest.mark.parametrize('evidence', [None, bundle().model_context()])
def test_unknown_evidence_id_rejected_without_medical_regeneration(monkeypatch, evidence):
    provider = Provider(scope_json('An answer.', sentence_id='E9:S1'))
    monkeypatch.setattr(ai_service, 'get_clinical_ai_provider', lambda: provider)
    with pytest.raises(ai_service.AIResponseCompletionError, match='complete response') as error:
        asyncio.run(ai_service.get_medical_response('A question.', evidence_context=evidence))
    assert error.value.finish_category == 'invalid_answer_scope'
    assert len(provider.requests) == 2


@pytest.mark.parametrize('tags', [
    '<evidence_refs>chunk-0', '</evidence_refs>',
    '<evidence_refs>chunk-0</evidence_refs><evidence_refs>chunk-0</evidence_refs>',
])
def test_malformed_citation_structure_fails_without_another_medical_call(monkeypatch, tags):
    provider = Provider('An answer.' + tags)
    monkeypatch.setattr(ai_service, 'get_clinical_ai_provider', lambda: provider)
    with pytest.raises(ai_service.AIResponseCompletionError):
        asyncio.run(ai_service.get_medical_response('A question.', evidence_context=bundle().model_context()))
    assert len(provider.requests) == 2


def test_evidence_unavailable_is_explicit_in_one_generation_contract(monkeypatch):
    text = 'This cannot be determined from the available information.'
    provider = Provider(scope_json(text))
    monkeypatch.setattr(ai_service, 'get_clinical_ai_provider', lambda: provider)
    response = asyncio.run(ai_service.get_medical_response('What is the current advice?',
        evidence_context=json.dumps({'items': [], 'status': 'NONE',
                                     'failure_category': 'current_official_evidence_unavailable'})))
    assert response.text == text and response.evidence_ids == ()
    prompt = ' '.join(provider.requests[0].parts)
    assert 'Do not fill evidence gaps with medical memory' in prompt
    assert 'current_official_evidence_unavailable' in prompt
    assert len(provider.requests) == 1


@pytest.mark.parametrize('action', ['start', 'stop', 'increase', 'decrease', 'switch'])
def test_prescription_action_constrained_in_shared_generation_contract(action):
    contract = ' '.join(ai_service.CLINICAL_ANSWER_RULES.split())
    assert action in contract
    assert 'authoritative evidence explicitly supports that exact action in this situation' in contract
    assert 'contacting the prescriber or pharmacist only when evidence supports' in contract


def test_useful_wording_not_filtered_by_medication_or_causal_phrases(monkeypatch):
    text = 'Discuss a fever-reducing medication with your clinician if needed.'
    provider = Provider(scope_json(text, sentence_id='E1:S1'))
    monkeypatch.setattr(ai_service, 'get_clinical_ai_provider', lambda: provider)
    response = asyncio.run(ai_service.get_medical_response('Fever question.', evidence_context=bundle().model_context()))
    assert response.text == text and len(provider.requests) == 1


def test_grounded_assessment_has_one_final_call_after_adaptive_questions(assessment_db, monkeypatch):
    def final(state):
        return scope_payload('Evaluation is supported.', sentence_id='E1:S1')

    provider = PlanProvider([
        plan(needs=[need('duration', 'When did this start?')]),
        plan(facts=[fact('duration', 'Three months')], ready=True),
    ], finals=[final])
    monkeypatch.setattr(ai_assessment, 'get_clinical_ai_provider', lambda: provider)

    async def retrieve(*_args, **_kwargs):
        return bundle()
    monkeypatch.setattr(ai_assessment, 'retrieve_evidence', retrieve)
    first = advance(assessment_db, 'My urine looks different')
    assert first.result_kind.value == 'ASSESSMENT_QUESTION'
    assert first.result.question == 'When did this start?'
    second = advance(assessment_db, 'Three months', assessment_id=first.assessment_id,
                     version=first.state_version, request_id='second')
    assert second.result_kind.value == 'ASSESSMENT_RESULT'
    assert second.result.evidence_ids == ['chunk-0']
    assert [r.purpose for r in provider.requests] == ['assessment', 'assessment', 'assessment_result']


def test_assessment_schema_repair_once_without_review(assessment_db, monkeypatch):
    provider = PlanProvider([plan(needs=[need('duration', 'When did this start?')]),
                             plan(facts=[fact('duration', 'Three months')], ready=True)],
                            finals=[{'wrong_field': True}, valid_final])
    monkeypatch.setattr(ai_assessment, 'get_clinical_ai_provider', lambda: provider)
    first = advance(assessment_db, 'A persistent symptom')
    second = advance(assessment_db, 'Three months', assessment_id=first.assessment_id,
                     version=first.state_version, request_id='second')
    assert second.result_kind.value == 'ASSESSMENT_RESULT'
    finals = [r for r in provider.requests if r.purpose == 'assessment_result']
    assert len(finals) == 2
    assert 'Repair only the format/schema' in finals[1].parts[-1]
    assert 'wrong_field' in finals[1].parts[-1]


@pytest.mark.parametrize('document,expected', [(None, 3), (b'synthetic PDF bytes', 5)])
def test_generation_bundle_bounded_without_mutating_retrieval_cache(monkeypatch, document, expected):
    evidence = bundle(5)
    seen = []

    async def route(_value):
        return RouterDecision(mode='CONVERSATION', confidence=1, reason_codes=['information'])

    async def retrieve(*_args, **_kwargs):
        return evidence

    async def generate(*_args, **kwargs):
        supplied = json.loads(kwargs['evidence_context'])['items']
        seen.extend(supplied)
        return ai_service.MedicalAIResponse('An answer.', evidence_ids=('chunk-0',))

    monkeypatch.setattr(ai_orchestrator, 'route_interaction', route)
    monkeypatch.setattr(ai_orchestrator, 'retrieve_evidence', retrieve)
    monkeypatch.setattr(ai_service, 'get_medical_response', generate)
    result = asyncio.run(ai_orchestrator.run_interaction(ai_orchestrator.InteractionInput(
        request_id='synthetic', interaction_id=None, message='What is fever?',
        language='English', history=[], user_context={}, db=object(), document_bytes=document)))
    assert len(seen) == expected and len(evidence.items) == 5
    assert result.evidence_items[0].canonical_url == evidence.items[0].canonical_url
    assert result.result.evidence_ids == ['chunk-0']


def test_understanding_plans_current_nigerian_retrieval_without_diagnosis(monkeypatch):
    seen = []
    evidence = bundle(origin='OFFICIAL_WEB', publication_date='2026-09-26', freshness_state='CURRENT',
                      issuing_organization='Federal Ministry of Health and Social Welfare')

    async def route(_value):
        return RouterDecision(mode='CONVERSATION', confidence=1, reason_codes=['current_policy'],
                              clinical_concepts=['pandemic', 'preparedness'],
                              current_information_required=True, jurisdiction_sensitive=True)

    async def retrieve(_db, query):
        seen.append(query)
        return evidence

    async def generate(*_args, **_kwargs):
        return ai_service.MedicalAIResponse('A supported policy summary.', evidence_ids=('chunk-0',))

    monkeypatch.setattr(ai_orchestrator, 'route_interaction', route)
    monkeypatch.setattr(ai_orchestrator, 'retrieve_evidence', retrieve)
    monkeypatch.setattr(ai_service, 'get_medical_response', generate)
    result = asyncio.run(ai_orchestrator.run_interaction(ai_orchestrator.InteractionInput(
        request_id='synthetic', interaction_id=None, message='What is the update?',
        language='English', history=[], user_context={}, db=object())))
    assert {'current', 'pandemic', 'preparedness'} <= set(seen[0].normalized_text().split())
    assert seen[0].jurisdiction == 'NG'
    assert result.evidence_items[0].issuing_organization == evidence.items[0].issuing_organization
    assert result.evidence_items[0].publication_date == '2026-09-26'
    assert 'Do not\ndiagnose or provide a treatment' in _ROUTER_INSTRUCTION


def test_urgent_bypasses_retrieval_and_ordinary_generation(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        pytest.fail('Urgent request reached ordinary generation/retrieval')
    monkeypatch.setattr(ai_orchestrator, 'retrieve_evidence', forbidden)
    monkeypatch.setattr(ai_service, 'get_medical_response', forbidden)
    monkeypatch.setattr(ai_router, 'get_clinical_ai_provider',
                        lambda: pytest.fail('Deterministic urgent route called a provider'))
    response = asyncio.run(ai_orchestrator.run_interaction(ai_orchestrator.InteractionInput(
        request_id='synthetic', interaction_id=None,
        message='I have new chest pain and sweating. Is this urgent?',
        language='English', history=[], user_context={}, db=object())))
    assert response.result_kind.value == 'URGENT'
    assert response.result.emergency_number == '112' and response.evidence_items == []
