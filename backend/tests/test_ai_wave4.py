"""Synthetic-only Wave 4 contract and deterministic retrieval checks."""

import asyncio
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import app.models.doctor  # noqa: F401 - resolves shared Vault ORM relationships
from tests.test_ai_wave3 import db as assessment_db

from app.services import clinical_ingestion as ingestion
from app.services.ai_assessment import _scope_result
from app.services.ai_answer_scope import number_evidence, validate_scope
from tests.ai_provider_fakes import scope_payload
from app.services.ai_safety import evaluate_safety
from app.services.clinical_embedding import (
    EmbeddingUnavailable, GeminiEmbeddingAdapter, validate_vectors,
)
from app.services.clinical_knowledge import (
    ClinicalEvidenceQuery, EvidenceBundle, EvidenceItem, EvidenceStatus,
    KnowledgeConfig, _conflicting, _medlineplus_relevant, _ranked_merge, query_from_text,
    retrieve_evidence, validate_evidence_references,
)


def item(**changes):
    data = dict(evidence_id="chunk-a", chunk_id="chunk-a", source_id="source-a",
                document_version_id="version-a", title="Synthetic guidance",
                issuing_organization="Test only", jurisdiction="NG", edition="v1",
                publication_date="2026-01-01", effective_date="2026-01-01",
                section="Evaluation", page_start=2, page_end=2, anchor="p2-c0",
                canonical_url="https://example.org/guidance", trust_tier=2,
                indexed_at="2026-01-01", excerpt="Synthetic clinical evidence")
    data.update(changes)
    return EvidenceItem(**data)


def row(**changes):
    data = dict(chunk_id="chunk-a", version_id="version-a", source_id="source-a",
                title="Synthetic guidance", issuing_organization="Test only",
                jurisdiction="NG", edition="v1", publication_date=None,
                effective_date=None, section_title="Evaluation", page_start=2,
                page_end=2, anchor="p2-c0", canonical_url="https://example.org/guidance",
                trust_tier=2, indexed_at="2026-01-01", excerpt="test evidence",
                checksum="a" * 64, build_id="build-a", conflict_group=None,
                conflict_stance=None)
    data.update(changes)
    return data


class FakeEmbedding:
    key = "fake:3"

    async def embed(self, texts, *, task):
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_synthetic_corpus_is_test_only_and_covers_required_cases():
    corpus = json.loads((Path(__file__).parent / "fixtures" /
                         "synthetic_clinical_corpus.json").read_text())
    assert corpus["test_only"] is True
    topics = {doc["topic"] for doc in corpus["documents"]}
    assert {"urinary", "respiratory", "headache", "fever", "medication",
            "skin", "pregnancy", "pediatric", "injection", "superseded",
            "withdrawn", "conflict-a", "conflict-b"} <= topics


def test_privacy_query_drops_identity_and_address():
    query = query_from_text("Ada at 12 Broad Street called 08012345678 about foamy urine",
                            purpose="CONVERSATION")
    assert query.normalized_text() == "foamy urine"


def test_embedding_dimensions_are_consistent_and_configured_output_is_enforced(monkeypatch):
    import google.generativeai as genai

    with pytest.raises(EmbeddingUnavailable):
        validate_vectors([[0.1, 0.2], [0.1, 0.2, 0.3]], 2)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(genai, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(genai, "embed_content", lambda **_kwargs: {
        "embedding": [[0.1, 0.2, 0.3]],
    })
    with pytest.raises(EmbeddingUnavailable, match="differs from configuration"):
        asyncio.run(GeminiEmbeddingAdapter("synthetic-model", 2).embed(
            ["synthetic clinical text"], task="RETRIEVAL_DOCUMENT"))


def test_text_chunking_keeps_heading_and_bounds():
    chunks = ingestion.extract_document(
        ("# Kidney evaluation\n\n" + "Foamy urine may need review. " * 130).encode(),
        "synthetic.md")
    assert chunks and all(len(chunk.text) <= ingestion.MAX_CHUNK_CHARS for chunk in chunks)
    assert all(chunk.section == "Kidney evaluation" for chunk in chunks)
    assert chunks[0].anchor == "p0-c0"


def test_pdf_extraction_retains_page_anchor(monkeypatch):
    class Reader:
        is_encrypted = False
        pages = [SimpleNamespace(extract_text=lambda: "# Fever\n\nReview symptoms."),
                 SimpleNamespace(extract_text=lambda: "Breathing guidance.")]

        def __init__(self, _stream):
            pass
    monkeypatch.setattr(ingestion, "PdfReader", Reader)
    chunks = ingestion.extract_document(b"%PDF-synthetic", "synthetic.pdf")
    assert [chunk.page for chunk in chunks] == [1, 2]
    assert chunks[0].section == "Fever"


def test_actual_pdf_parser_extracts_text_when_pdf_tool_available():
    fpdf = pytest.importorskip("fpdf")
    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, txt="Synthetic fever guidance for clinical review.")
    raw = pdf.output(dest="S")
    data = raw.encode("latin1") if isinstance(raw, str) else bytes(raw)
    chunks = ingestion.extract_document(data, "synthetic.pdf")
    assert chunks[0].page == 1
    assert "Synthetic fever guidance" in chunks[0].text


def test_hybrid_merge_deduplicates_and_diversifies():
    first = row()
    duplicate = row(chunk_id="chunk-b", checksum="a" * 64)
    other = row(chunk_id="chunk-c", source_id="source-c", checksum="c" * 64)
    items = _ranked_merge([first, duplicate, other], [first, other], 5, 900)
    assert [it.evidence_id for it in items] == ["chunk-a", "chunk-c"]
    assert items[0].retrieval_methods == ("lexical", "vector")


@pytest.mark.parametrize(('concepts', 'accepted', 'rejected'), [
    ({'breathing'}, 'Breathing Problems', 'Bad Breath'),
    ({'suicide', 'crisis'}, 'Suicide', 'Child Safety'),
    ({'fever'}, 'Fever', 'Hay Fever'),
    ({'chest', 'pain'}, 'Chest Pain', 'Abdominal Pain'),
    ({'headache'}, 'Headache', 'Norovirus Infections'),
    ({'medicine', 'interact'}, 'Drug Interactions', 'Medicines'),
    ({'urinate', 'fever'}, 'Urinary Tract Infections', 'Hay Fever'),
    ({'urine', 'foamy', 'kidney'}, 'Kidney Tests', 'Kidney Stones'),
    ({'urine', 'foamy', 'kidney'}, 'Urine and Urination', 'Kidney Failure'),
    ({'child', 'fever'}, 'Fever', 'Asthma in Children'),
    ({'pregnant', 'headache', 'swelling'}, 'High Blood Pressure in Pregnancy',
     'Pregnancy and Nutrition'),
    ({'rash', 'medicine', 'drug'}, 'Drug Reactions', 'Drug Safety'),
    ({'blood', 'pressure'}, 'High Blood Pressure', 'High Blood Pressure in Pregnancy'),
    ({'blood', 'pressure', 'low'}, 'Low Blood Pressure', 'High Blood Pressure'),
    ({'blood', 'pressure', 'high'}, 'High Blood Pressure', 'Low Blood Pressure'),
    ({'hypertension'}, 'High Blood Pressure', 'Low Blood Pressure'),
    ({'hay', 'fever'}, 'Hay Fever', 'Fever'),
    ({'kidney', 'stones'}, 'Kidney Stones', 'Kidney Tests'),
    ({'asthma', 'breathing'}, 'Asthma', 'How to Improve Mental Health'),
    ({'headache', 'migraine'}, 'Migraine', 'Norovirus Infections'),
    ({'pregnant', 'nutrition'}, 'Pregnancy and Nutrition', 'High Blood Pressure'),
])
def test_medlineplus_evidence_requires_relevant_topic(concepts, accepted, rejected):
    organization = 'U.S. National Library of Medicine / MedlinePlus'
    assert _medlineplus_relevant(item(title=accepted, issuing_organization=organization),
                                concepts)
    assert not _medlineplus_relevant(item(title=rejected, issuing_organization=organization),
                                    concepts)


@pytest.mark.parametrize('message', [
    'I have new chest pain and sweating. Is this urgent?',
    'I am suddenly short of breath at rest. What should I do?',
    'I have a sudden severe headache unlike my usual headaches.',
    'I am pregnant and have severe headache and swelling.',
    'I have diabetes and feel shaky and confused.',
    'My young child has fever and is unusually sleepy.',
    'I feel unsafe and may harm myself tonight.',
])
def test_launch_red_flags_are_deterministically_urgent(message):
    assert evaluate_safety(message).urgent_override


def test_stable_relevant_nlm_evidence_does_not_gain_unrelated_web_support(monkeypatch):
    from app.services import clinical_knowledge

    async def curated(*_args, **_kwargs):
        return EvidenceBundle(EvidenceStatus.INSUFFICIENT, (item(
            title='Fever', issuing_organization='U.S. National Library of Medicine / MedlinePlus'),))

    class NoSearch:
        async def search(self, *_args):
            raise AssertionError('stable curated evidence must not search')

    monkeypatch.setattr(clinical_knowledge, '_retrieve_curated', curated)
    result = asyncio.run(retrieve_evidence(
        object(), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
        config=KnowledgeConfig(enabled=True, web_enabled=True), web_provider=NoSearch()))
    assert not result.web_checked and result.status == EvidenceStatus.INSUFFICIENT
    assert [entry.title for entry in result.items] == ['Fever']


def test_cache_key_changes_with_relevance_policy():
    from app.services.clinical_cache import cache_key

    parameters = dict(normalized_query='fever', jurisdiction='NG', population=(),
                      minimum_trust=1, min_effective_date=None, revision=1,
                      embedding_key='test:3', limits=(12, 12, 5, 900, 2))
    assert cache_key(**parameters, policy_version='hybrid-1') != cache_key(
        **parameters, policy_version='hybrid-2')


def test_conflict_requires_explicit_opposing_stances():
    a = item(conflict_group="therapy", conflict_stance="a")
    b = item(evidence_id="chunk-b", source_id="source-b",
             conflict_group="therapy", conflict_stance="b")
    assert _conflicting((a, b))
    assert not _conflicting((a, item(evidence_id="chunk-c")))


def test_reference_validation_rejects_forgery_and_provider_urls():
    bundle = EvidenceBundle(EvidenceStatus.SUFFICIENT, (item(),))
    assert validate_evidence_references(["chunk-a"], bundle)[0].title == "Synthetic guidance"
    with pytest.raises(ValueError):
        validate_evidence_references(["invented"], bundle)
    with pytest.raises(ValueError):
        validate_evidence_references(["chunk-a"], bundle,
                                     claimed_urls=["https://invented.example"])


def test_typed_response_rejects_mismatched_citations():
    from pydantic import ValidationError
    from app.services.ai_interaction import (
        InteractionMode, InteractionResponse, MessageResult, ResultKind,
    )

    with pytest.raises(ValidationError):
        InteractionResponse(
            request_id="request-a", interaction_id="interaction-a",
            mode=InteractionMode.CONVERSATION, result_kind=ResultKind.MESSAGE,
            result=MessageResult(text="Answer", evidence_ids=["invented"]),
            evidence_items=[], grounding_status="GROUNDED",
        )


def test_assessment_rejects_forged_reference_and_url():
    fact = SimpleNamespace(id="fact-a", concept="fever", value="fever",
                           provenance="USER_STATED", status="ASSERTED")
    session = SimpleNamespace(facts=[fact])
    data = scope_payload("Further clinical evaluation", sentence_id="E1:S1")
    bundle = EvidenceBundle(EvidenceStatus.SUFFICIENT, (item(),))
    numbered = number_evidence(bundle.model_context())
    scope = validate_scope(data, numbered)
    assert _scope_result(scope, session, numbered.evidence_ids(scope)).evidence_ids == ["chunk-a"]
    with pytest.raises(ValueError):
        validate_scope(scope_payload("Evaluation", sentence_id="E9:S1"), numbered)
    with pytest.raises(ValueError):
        validate_scope(scope_payload("https://invented.example", sentence_id="E1:S1"), numbered)
    with pytest.raises(ValueError):
        validate_scope(data, number_evidence(None))


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self.rows


class FakeRetrievalDb:
    def __init__(self, fail=False):
        self.sql = []
        self.fail = fail

    def begin_nested(self):
        return nullcontext()

    def execute(self, sql, params):
        statement = str(sql)
        self.sql.append(statement)
        if self.fail:
            from sqlalchemy.exc import OperationalError
            raise OperationalError(statement, params, RuntimeError("vector unavailable"))
        if "SELECT v.version_id::text AS version_id" in statement:
            return FakeRows([{"version_id": "version-a"}])
        if "OPERATOR(extensions.<=>)" in statement:
            return FakeRows([row()])
        return FakeRows([row(chunk_id="chunk-b", source_id="source-b",
                             checksum="b" * 64)])


def test_retrieval_vector_lexical_active_only_and_sufficient():
    db = FakeRetrievalDb()
    bundle = asyncio.run(retrieve_evidence(db, ClinicalEvidenceQuery(("fever",),
                           purpose="TEST"), config=KnowledgeConfig(enabled=True),
                           embedding_provider=FakeEmbedding()))
    assert bundle.status == EvidenceStatus.SUFFICIENT
    assert len(bundle.items) == 2
    assert all("v.status = 'ACTIVE'" in sql for sql in db.sql)
    assert all("s.approval_status = 'APPROVED'" in sql for sql in db.sql)


def test_retrieval_failure_is_ungrounded_without_outer_rollback():
    db = FakeRetrievalDb(fail=True)
    bundle = asyncio.run(retrieve_evidence(db, ClinicalEvidenceQuery(("fever",),
                           purpose="TEST"), config=KnowledgeConfig(enabled=True),
                           embedding_provider=FakeEmbedding()))
    assert bundle.status == EvidenceStatus.NONE
    assert bundle.failure_category == "OperationalError"


def test_disabled_retrieval_never_touches_database():
    class NoDatabaseAccess:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("disabled retrieval accessed the database")

    bundle = asyncio.run(retrieve_evidence(
        NoDatabaseAccess(), ClinicalEvidenceQuery(("fever",), purpose="TEST"),
        config=KnowledgeConfig(enabled=False)))
    assert bundle.status == EvidenceStatus.NONE
    assert bundle.items == ()
    assert bundle.failure_category == "disabled"


def test_retrieval_sql_failure_preserves_outer_assessment_transaction():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        db.execute(text("CREATE TABLE assessment_state (value TEXT NOT NULL)"))
        db.execute(text("INSERT INTO assessment_state (value) VALUES ('READY')"))
        bundle = asyncio.run(retrieve_evidence(
            db, ClinicalEvidenceQuery(("fever",), purpose="ASSESSMENT_RESULT"),
            config=KnowledgeConfig(enabled=True), embedding_provider=FakeEmbedding()))
        assert bundle.status == EvidenceStatus.NONE
        db.commit()
        assert db.execute(text("SELECT value FROM assessment_state")).scalar_one() == "READY"
    engine.dispose()


def test_stale_only_corpus_returns_no_old_chunks():
    class StaleDb(FakeRetrievalDb):
        def execute(self, sql, params):
            statement = str(sql)
            self.sql.append(statement)
            if "SELECT v.version_id::text AS version_id" in statement:
                return FakeRows([])
            if "SELECT EXISTS" in statement:
                return SimpleNamespace(scalar=lambda: True)
            return FakeRows([])

    bundle = asyncio.run(retrieve_evidence(
        StaleDb(), ClinicalEvidenceQuery(("fever",), purpose="TEST"),
        config=KnowledgeConfig(enabled=True), embedding_provider=FakeEmbedding()))
    assert bundle.status == EvidenceStatus.STALE
    assert bundle.items == ()


class FakeIngestDb:
    def __init__(self, existing=None):
        self.statements = []
        self.existing = existing

    def execute(self, sql, params):
        statement = str(sql)
        self.statements.append(statement)
        if "SELECT source_id FROM clinical_sources" in statement:
            return SimpleNamespace(first=lambda: SimpleNamespace(source_id="source-a"))
        if "SELECT version_id::text, checksum" in statement:
            return SimpleNamespace(first=lambda: self.existing)
        return SimpleNamespace(first=lambda: None)


def test_ingest_stores_vectors_as_draft_and_index_build_complete():
    db = FakeIngestDb()
    version = asyncio.run(ingestion.ingest_version(
        db, source_id="source-a", edition="v1", publication_date=None,
        effective_date=None, data=b"# Fever\n\nClinical review is appropriate.",
        filename="synthetic.md", embedding_provider=FakeEmbedding()))
    assert version
    assert any("CAST(:vector AS extensions.vector)" in sql for sql in db.statements)
    assert any("'DRAFT'" in sql for sql in db.statements)
    assert not any("status = 'ACTIVE'" in sql for sql in db.statements)


def test_duplicate_version_is_idempotent_and_changed_checksum_rejected():
    import hashlib
    data = b"Clinical guidance."
    existing = SimpleNamespace(version_id="version-a", checksum=hashlib.sha256(data).hexdigest())
    db = FakeIngestDb(existing)
    result = asyncio.run(ingestion.ingest_version(
        db, source_id="source-a", edition="v1", publication_date=None,
        effective_date=None, data=data, filename="synthetic.txt",
        embedding_provider=FakeEmbedding()))
    assert result == "version-a"
    assert not any("INSERT" in sql for sql in db.statements)
    with pytest.raises(ValueError):
        asyncio.run(ingestion.ingest_version(
            db, source_id="source-a", edition="v1", publication_date=None,
            effective_date=None, data=b"Changed text", filename="synthetic.txt",
            embedding_provider=FakeEmbedding()))


def test_failed_embedding_never_creates_active_version():
    class FailingEmbedding(FakeEmbedding):
        async def embed(self, texts, *, task):
            raise EmbeddingUnavailable("offline")
    db = FakeIngestDb()
    with pytest.raises(EmbeddingUnavailable):
        asyncio.run(ingestion.ingest_version(
            db, source_id="source-a", edition="v1", publication_date=None,
            effective_date=None, data=b"Clinical guidance.", filename="synthetic.txt",
            embedding_provider=FailingEmbedding()))
    assert not any("INSERT" in sql for sql in db.statements)


def test_activation_supersedes_then_activates_and_rejects_incomplete():
    class ActivationDb:
        def __init__(self, count):
            self.count = count
            self.statements = []

        def execute(self, sql, params):
            statement = str(sql)
            self.statements.append(statement)
            if "SELECT v.source_id" in statement:
                return SimpleNamespace(first=lambda: SimpleNamespace(
                    source_id="source-a", status="DRAFT", chunk_count=2,
                    actual_chunks=self.count, build_status="COMPLETE"))
            return SimpleNamespace(first=lambda: None)

    db = ActivationDb(2)
    ingestion.activate_version(db, "version-b")
    updates = [sql for sql in db.statements if sql.strip().startswith("UPDATE")]
    assert "SUPERSEDED" in updates[0]
    assert "ACTIVE" in updates[1]
    with pytest.raises(ValueError):
        ingestion.activate_version(ActivationDb(1), "version-b")


def test_source_registration_rejects_patient_document_type():
    with pytest.raises(ValueError):
        ingestion.register_source(FakeIngestDb(), ingestion.SourceRegistration(
            title="Patient PDF", organization="Patient", jurisdiction="NG",
            source_type="PATIENT_DOCUMENT", canonical_url=None, trust_tier=1,
            license_note="claim", approved_by="operator"))


def test_retire_withdraw_are_active_only_and_preserve_history():
    class CloseDb:
        def __init__(self, changed):
            self.changed = changed
            self.statements = []

        def execute(self, sql, params):
            self.statements.append((str(sql), params))
            return SimpleNamespace(rowcount=self.changed)

    for status in ("RETIRED", "WITHDRAWN"):
        db = CloseDb(1)
        ingestion.close_version(db, "version-a", status)
        assert "status = 'ACTIVE'" in db.statements[0][0]
        assert db.statements[0][1]["status"] == status
    with pytest.raises(ValueError):
        ingestion.close_version(CloseDb(0), "version-a", "WITHDRAWN")


def test_conversation_retrieval_outage_keeps_ungrounded_answer(monkeypatch):
    from app.services import ai_orchestrator
    from app.services.ai_interaction import InteractionMode
    from app.services.ai_router import RouterDecision
    from app.services.ai_service import MedicalAIResponse

    async def route(_value):
        return RouterDecision(mode=InteractionMode.CONVERSATION,
                              confidence=1, reason_codes=["education"])

    async def unavailable(_db, _query):
        return EvidenceBundle(EvidenceStatus.NONE, failure_category="database_unavailable")

    async def generate(_message, **kwargs):
        assert kwargs["evidence_context"] is None
        return MedicalAIResponse("Fever can have several causes.")

    monkeypatch.setattr(ai_orchestrator, "route_interaction", route)
    monkeypatch.setattr(ai_orchestrator, "retrieve_evidence", unavailable)
    monkeypatch.setattr(ai_orchestrator.ai_service, "get_medical_response", generate)
    response = asyncio.run(ai_orchestrator.run_interaction(ai_orchestrator.InteractionInput(
        request_id="request-a", interaction_id=None, message="What causes fever?",
        language="English", history=[], user_context={}, db=object(),
    )))
    assert response.result.text == "Fever can have several causes."
    assert response.grounding_status == "UNGROUNDED"
    assert response.evidence_items == []


def test_assessment_retrieval_outage_keeps_ungrounded_result(assessment_db, monkeypatch):
    from app.models.ai_assessment import AIAssessment
    from app.services import ai_assessment
    from tests.test_ai_wave3 import PlanProvider, advance, fact, plan, valid_final

    provider = PlanProvider(
        [plan(facts=[fact("duration", "three months")], ready=True)],
        finals=[valid_final],
    )

    async def unavailable(_db, _query):
        return EvidenceBundle(EvidenceStatus.NONE, failure_category="database_unavailable")

    monkeypatch.setattr(ai_assessment, "get_clinical_ai_provider", lambda: provider)
    monkeypatch.setattr(ai_assessment, "retrieve_evidence", unavailable)
    result = advance(assessment_db, "Foamy urine for three months")
    assessment_db.commit()
    session = assessment_db.query(AIAssessment).one()
    assert session.status == "COMPLETED" and session.usage_committed
    assert result.grounding_status == "UNGROUNDED"
    assert result.result.evidence_ids == [] and result.evidence_items == []
