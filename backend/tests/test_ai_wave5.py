"""Deterministic launch-knowledge tests; no patient data or live web calls."""

import asyncio
import json
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from app.services import clinical_cache
from app.services.clinical_freshness import FreshnessState, classify, medicine_safety
from app.services.clinical_knowledge import (
    ClinicalEvidenceQuery, EvidenceStatus, KnowledgeConfig, query_from_text,
    retrieve_evidence, validate_evidence_references,
)
from app.services.clinical_web import (
    TavilyOfficialSearch, extract_official, fetch_official, search_official, trusted_url,
)
from app.services.clinical_source_updates import (
    SourceCheck, _fingerprint, check_active_sources, run_due_source_checks,
)
from tests.test_ai_wave4 import row


@pytest.fixture(autouse=True)
def empty_cache():
    clinical_cache.clear()
    yield
    clinical_cache.clear()


class Rows:
    def __init__(self, values):
        self.values = values

    def mappings(self):
        return self

    def all(self):
        return self.values

    def __iter__(self):
        return iter(self.values)


class FakeDb:
    def __init__(self, *, items=2, fail=False):
        self.revision = 1
        self.mutated = False
        self.fail = fail
        self.candidate_queries = 0
        self.items = [row(chunk_id=f'chunk-{number}', source_id=f'source-{number}',
                          version_id=f'version-{number}', build_id=f'build-{number}',
                          checksum=str(number) * 64)
                      for number in range(items)]

    def begin_nested(self):
        return nullcontext()

    def execute(self, sql, params=None):
        statement = str(sql)
        if 'FROM clinical_library_state' in statement:
            return SimpleNamespace(one=lambda: SimpleNamespace(
                revision=self.revision, mutated=self.mutated))
        if self.fail:
            raise OperationalError(statement, params, RuntimeError('database unavailable'))
        if 'SELECT v.version_id::text AS version_id' in statement:
            return Rows([{'version_id': value['version_id']} for value in self.items])
        if 'SELECT EXISTS' in statement:
            return SimpleNamespace(scalar=lambda: False)
        self.candidate_queries += 1
        return Rows(self.items)


class CountingEmbedding:
    key = 'fake:3'

    def __init__(self):
        self.calls = 0

    async def embed(self, texts, *, task):
        self.calls += 1
        return [[1.0, 0.0, 0.0] for _ in texts]


def cached_config(**changes):
    return KnowledgeConfig(enabled=True, cache_enabled=True, **changes)


def test_first_lookup_queries_db_second_uses_revision_keyed_cache():
    db, provider = FakeDb(), CountingEmbedding()
    query = ClinicalEvidenceQuery(('fever',), purpose='TEST')
    first = asyncio.run(retrieve_evidence(db, query, config=cached_config(),
                                          embedding_provider=provider))
    second = asyncio.run(retrieve_evidence(db, query, config=cached_config(),
                                           embedding_provider=provider))
    assert first == second and first.status == EvidenceStatus.SUFFICIENT
    assert db.candidate_queries == 2 and provider.calls == 1


@pytest.mark.parametrize('change', ['activation', 'retirement', 'withdrawal', 'index_change'])
def test_library_revision_change_invalidates_cache(change):
    db, provider = FakeDb(), CountingEmbedding()
    query = ClinicalEvidenceQuery(('fever',), purpose='TEST')
    asyncio.run(retrieve_evidence(db, query, config=cached_config(), embedding_provider=provider))
    db.revision += 1
    asyncio.run(retrieve_evidence(db, query, config=cached_config(), embedding_provider=provider))
    assert provider.calls == 2 and db.candidate_queries == 4, change


def test_uncommitted_clinical_change_never_poison_cache():
    db, provider = FakeDb(), CountingEmbedding()
    db.mutated = True
    query = ClinicalEvidenceQuery(('fever',), purpose='TEST')
    asyncio.run(retrieve_evidence(db, query, config=cached_config(), embedding_provider=provider))
    db.mutated = False
    asyncio.run(retrieve_evidence(db, query, config=cached_config(), embedding_provider=provider))
    assert provider.calls == 2


def test_cache_failure_falls_through_to_database(monkeypatch):
    db, provider = FakeDb(), CountingEmbedding()
    monkeypatch.setattr(clinical_cache, 'get', lambda _key: (_ for _ in ()).throw(OSError('cache down')))
    bundle = asyncio.run(retrieve_evidence(
        db, ClinicalEvidenceQuery(('fever',), purpose='TEST'),
        config=cached_config(), embedding_provider=provider))
    assert bundle.status == EvidenceStatus.SUFFICIENT
    assert provider.calls == 1 and db.candidate_queries == 2


def test_cache_key_contains_no_raw_patient_identifier():
    query = query_from_text('Ada at 12 Broad Street has foamy urine', purpose='TEST')
    key = clinical_cache.cache_key(
        normalized_query=query.normalized_text(), jurisdiction='NG', population=(),
        minimum_trust=1, min_effective_date=None, revision=4,
        embedding_key='fake:3', limits=(12, 12, 5, 900))
    assert query.normalized_text() == 'foamy urine'
    assert len(key) == 64 and 'Ada' not in key and 'Broad' not in key


def test_freshness_age_sensitivity_and_terminal_states():
    common = dict(source_type='GUIDELINE', freshness_class='STANDARD',
                  review_interval_days=365, update_status='CURRENT',
                  effective_date=date(2026, 1, 1), publication_date=None,
                  today=date(2026, 9, 27))
    assert classify(version_status='ACTIVE', sensitive=False, **common) == FreshnessState.CURRENT
    assert classify(version_status='ACTIVE', sensitive=True, **common) == FreshnessState.STALE
    assert classify(version_status='SUPERSEDED', sensitive=False, **common) == FreshnessState.SUPERSEDED
    assert classify(version_status='WITHDRAWN', sensitive=False, **common) == FreshnessState.WITHDRAWN
    assert classify(version_status='ACTIVE', sensitive=False,
                    **{**common, 'update_status': 'UPDATE_AVAILABLE'}) == FreshnessState.STALE
    assert medicine_safety('drug recall')


class FakeSearch:
    def __init__(self, urls=(), fail=False):
        self.urls = list(urls)
        self.calls = []
        self.fail = fail

    async def search(self, terms, domains, jurisdiction):
        self.calls.append((terms, domains, jurisdiction))
        if self.fail:
            raise OSError('web unavailable')
        return self.urls


def page(*, published='2026-09-01', body='Synthetic fever guidance for current clinical review and follow-up. ' * 3):
    return (f'<html><head><title>Official fever guidance</title>'
            f'<meta property="article:published_time" content="{published}"></head>'
            f'<body><main><p>{body}</p></main></body></html>').encode()


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_trusted_domain_and_redirect_spoof_are_rejected():
    assert trusted_url('https://www.who.int/guidance') is not None
    assert trusted_url('https://www.who.int.evil.example/guidance') is None
    assert trusted_url('https://who.int@evil.example/guidance') is None
    assert trusted_url('http://www.who.int/guidance') is None

    async def check():
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={'location': 'https://evil.example/claim'})

        async with client_for(handler) as client:
            result = await fetch_official('https://www.who.int/guidance', 'fever', client=client)
        assert result is None and len(calls) == 1
    asyncio.run(check())


@pytest.mark.parametrize('terms,jurisdiction,domains', [
    ('drug recall', 'NG', ['nafdac.gov.ng']),
    ('outbreak', 'NG', ['ncdc.gov.ng', 'health.gov.ng']),
    ('fever guideline', 'GLOBAL', ['www.who.int', 'iris.who.int', 'www.nice.org.uk']),
])
def test_tavily_request_restricts_approved_topic_domains(
        monkeypatch, terms, jurisdiction, domains):
    from app.services import clinical_web

    original_client = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers.get('authorization'),
                     json.loads(request.content)))
        return httpx.Response(200, json={'results': [
            {'url': 'https://' + domains[0] + '/guidance',
             'title': 'Untrusted provider title'},
        ]})

    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('CLINICAL_WEB_PROVIDER', 'tavily')
    monkeypatch.setattr(clinical_web.httpx, 'AsyncClient',
                        lambda **_kwargs: original_client(transport=httpx.MockTransport(handler)))
    urls = asyncio.run(TavilyOfficialSearch().search(terms, tuple(domains), jurisdiction))
    endpoint, auth, body = seen[0]
    assert endpoint == 'https://api.tavily.com/search'
    assert auth == 'Bearer synthetic-test-key'
    assert body['query'] == terms and body['include_domains'] == domains
    assert body['include_domains_mode'] == 'restrict'
    assert body['search_depth'] == 'basic' and body['max_results'] == 8
    assert body['auto_parameters'] is False
    assert body['include_answer'] is False and body['include_raw_content'] is False
    assert len(urls) == 1


def test_tavily_quota_failure_keeps_core_evidence_path_ungrounded(monkeypatch):
    from app.services import clinical_web

    original_client = httpx.AsyncClient
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(clinical_web.httpx, 'AsyncClient', lambda **_kwargs:
                        original_client(transport=httpx.MockTransport(
                            lambda _request: httpx.Response(429))))
    bundle = asyncio.run(retrieve_evidence(
        FakeDb(fail=True), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
        config=KnowledgeConfig(enabled=True, web_enabled=True),
        embedding_provider=CountingEmbedding()))
    assert bundle.status == EvidenceStatus.NONE and bundle.items == ()
    assert not bundle.web_checked


def test_tavily_never_receives_raw_patient_text(monkeypatch):
    from app.services import clinical_web

    original_client = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'results': []})

    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(clinical_web.httpx, 'AsyncClient', lambda **_kwargs:
                        original_client(transport=httpx.MockTransport(handler)))
    query = query_from_text('Ada at 12 Broad Street has foamy urine', purpose='TEST')
    asyncio.run(retrieve_evidence(object(), query,
                                  config=KnowledgeConfig(enabled=False, web_enabled=True)))
    assert seen[0]['query'] == 'foamy urine'
    assert 'Ada' not in str(seen) and 'Broad' not in str(seen)


def test_raw_patient_text_never_crosses_web_boundary_and_metadata_is_official():
    provider = FakeSearch(['https://evil.example/claim', 'https://www.who.int/guidance'])

    async def check():
        async with client_for(lambda _request: httpx.Response(
                200, headers={'content-type': 'text/html'}, content=page())) as client:
            query = query_from_text('Ada at 12 Broad Street has fever', purpose='TEST')
            bundle = await retrieve_evidence(
                object(), query, config=KnowledgeConfig(enabled=False, web_enabled=True),
                web_provider=provider, web_client=client)
        assert bundle.web_checked and bundle.status == EvidenceStatus.INSUFFICIENT
        assert len(bundle.items) == 1
        item = bundle.items[0]
        assert item.title == 'Official fever guidance'
        assert item.issuing_organization == 'World Health Organization'
        assert item.publication_date == '2026-09-01'
        assert item.canonical_url == 'https://www.who.int/guidance'
        assert item.origin == 'OFFICIAL_WEB'
        assert provider.calls[0][0] == 'fever'
        assert 'Ada' not in str(provider.calls) and 'Broad' not in str(provider.calls)
        assert len(validate_evidence_references([item.evidence_id], bundle)) == 1
        with pytest.raises(ValueError):
            validate_evidence_references(['invented'], bundle)
        with pytest.raises(ValueError):
            validate_evidence_references([item.evidence_id], bundle,
                                         claimed_urls=['https://fake.example'])
    asyncio.run(check())


def test_approved_host_outside_requested_topic_subset_is_rejected():
    provider = FakeSearch(['https://www.ncdc.gov.ng/guidance',
                           'https://www.who.int/guidance'])

    async def check():
        async with client_for(lambda _request: httpx.Response(
                200, headers={'content-type': 'text/html'}, content=page())) as client:
            return await search_official('fever guideline', 'GLOBAL',
                                         provider=provider, client=client)

    documents = asyncio.run(check())
    assert len(documents) == 1
    assert documents[0].url == 'https://www.who.int/guidance'


def test_direct_fetch_success_never_calls_extract(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.method == 'GET'
        return httpx.Response(200, headers={'content-type': 'text/html'}, content=page())

    async def check():
        async with client_for(handler) as client:
            return await search_official('fever', 'GLOBAL',
                                         provider=FakeSearch(['https://www.who.int/guidance']),
                                         client=client)

    assert len(asyncio.run(check())) == 1
    assert calls == ['https://www.who.int/guidance']


def test_direct_disconnect_extract_success_while_extra_subdomain_is_discarded(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    official = 'https://www.who.int/guidance'
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        if request.method == 'GET':
            raise httpx.RemoteProtocolError('disconnected', request=request)
        body = json.loads(request.content)
        assert body['urls'] == official and body['extract_depth'] == 'basic'
        assert body['format'] == 'text' and body['include_images'] is False
        assert request.headers['authorization'] == 'Bearer synthetic-test-key'
        return httpx.Response(200, json={'results': [{
            'url': official,
            'raw_content': 'Synthetic fever guidance for clinical review and follow-up. ' * 3,
            'title': 'Provider supplied untrusted title',
        }]})

    async def check():
        async with client_for(handler) as client:
            return await retrieve_evidence(
                object(), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
                config=KnowledgeConfig(enabled=False, web_enabled=True),
                web_provider=FakeSearch(['https://platform.who.int/evil', official]),
                web_client=client)

    bundle = asyncio.run(check())
    assert calls == [('GET', official), ('POST', 'https://api.tavily.com/extract')]
    assert len(bundle.items) == 1
    item = bundle.items[0]
    assert item.canonical_url == official and item.title == 'guidance'
    assert item.issuing_organization == 'World Health Organization'
    assert len(validate_evidence_references([item.evidence_id], bundle)) == 1
    with pytest.raises(ValueError):
        validate_evidence_references([item.evidence_id], bundle,
                                     claimed_urls=['https://platform.who.int/evil'])


@pytest.mark.parametrize('returned_url', [
    'https://platform.who.int/guidance',
    'https://www.who.int/other',
    'https://www.who.int:444/guidance',
    'http://www.who.int/guidance',
])
def test_extract_returned_url_must_match_exact_requested_url(monkeypatch, returned_url):
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')

    async def check():
        async with client_for(lambda _request: httpx.Response(200, json={'results': [{
                'url': returned_url, 'raw_content': 'Synthetic fever guidance. ' * 5,
        }]})) as client:
            return await extract_official('https://www.who.int/guidance', 'fever', client=client)

    assert asyncio.run(check()) is None


def test_extract_outage_or_oversized_content_never_fabricates_evidence(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    from app.services import clinical_web
    official = 'https://www.who.int/guidance'

    def handler(request):
        if request.method == 'GET':
            raise httpx.RemoteProtocolError('disconnected', request=request)
        return httpx.Response(503)

    async def check(handler_fn):
        async with client_for(handler_fn) as client:
            return await retrieve_evidence(
                object(), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
                config=KnowledgeConfig(enabled=False, web_enabled=True),
                web_provider=FakeSearch([official]), web_client=client)

    outage = asyncio.run(check(handler))
    assert outage.items == () and outage.status == EvidenceStatus.NONE

    monkeypatch.setattr(clinical_web, 'MAX_PAGE_BYTES', 512)

    def oversized(request):
        if request.method == 'GET':
            raise httpx.RemoteProtocolError('disconnected', request=request)
        return httpx.Response(200, json={'results': [{
            'url': official, 'raw_content': 'Synthetic fever guidance. ' * 50,
        }]})

    too_large = asyncio.run(check(oversized))
    assert too_large.items == () and too_large.status == EvidenceStatus.NONE


def test_all_unapproved_search_candidates_yield_no_sources():
    async def check():
        async with client_for(lambda _request: pytest.fail('unapproved URL fetched')) as client:
            return await retrieve_evidence(
                object(), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
                config=KnowledgeConfig(enabled=False, web_enabled=True),
                web_provider=FakeSearch(['https://platform.who.int/guidance']),
                web_client=client)

    bundle = asyncio.run(check())
    assert bundle.items == () and bundle.web_checked


def test_untrusted_redirect_never_invokes_extract(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(302, headers={'location': 'https://evil.example/guidance'})

    async def check():
        async with client_for(handler) as client:
            return await search_official('fever', 'GLOBAL',
                                         provider=FakeSearch(['https://www.who.int/guidance']),
                                         client=client)

    assert asyncio.run(check()) == ()
    assert calls == ['GET']


def test_slow_extract_obeys_total_web_budget(monkeypatch):
    from app.services import clinical_knowledge

    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    monkeypatch.setattr(clinical_knowledge, 'WEB_SEARCH_TIMEOUT_SECONDS', 0.01)

    async def handler(request):
        if request.method == 'GET':
            raise httpx.RemoteProtocolError('disconnected', request=request)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={'results': [{
            'url': 'https://www.who.int/guidance',
            'raw_content': 'Synthetic fever guidance. ' * 5,
        }]})

    async def check():
        async with client_for(handler) as client:
            return await retrieve_evidence(
                object(), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
                config=KnowledgeConfig(enabled=False, web_enabled=True),
                web_provider=FakeSearch(['https://www.who.int/guidance']),
                web_client=client)

    bundle = asyncio.run(check())
    assert bundle.items == () and bundle.status == EvidenceStatus.NONE
    assert not bundle.web_checked


def test_web_not_searched_when_curated_sufficient_and_not_sensitive():
    provider = FakeSearch()
    bundle = asyncio.run(retrieve_evidence(
        FakeDb(), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
        config=KnowledgeConfig(enabled=True, web_enabled=True),
        embedding_provider=CountingEmbedding(), web_provider=provider))
    assert bundle.status == EvidenceStatus.SUFFICIENT
    assert provider.calls == []


def test_current_medicine_warning_invokes_official_search():
    provider = FakeSearch(['https://www.who.int/guidance'])

    async def check():
        async with client_for(lambda _request: httpx.Response(
                200, headers={'content-type': 'text/html'},
                content=page(body='Synthetic drug warning and recall guidance for medicine safety. ' * 3))) as client:
            bundle = await retrieve_evidence(
                FakeDb(), ClinicalEvidenceQuery(('drug', 'warning'), purpose='TEST'),
                config=KnowledgeConfig(enabled=True, web_enabled=True),
                embedding_provider=CountingEmbedding(), web_provider=provider,
                web_client=client)
        assert provider.calls and bundle.web_checked
        assert bundle.items[0].origin == 'OFFICIAL_WEB'
    asyncio.run(check())


def test_newer_official_result_preferred_to_aging_same_authority():
    db = FakeDb(items=1)
    db.items[0]['issuing_organization'] = 'World Health Organization'
    db.items[0]['publication_date'] = date(2025, 1, 1)
    db.items[0]['effective_date'] = date(2025, 1, 1)
    provider = FakeSearch(['https://www.who.int/guidance'])

    async def check():
        async with client_for(lambda _request: httpx.Response(
                200, headers={'content-type': 'text/html'}, content=page())) as client:
            return await retrieve_evidence(
                db, ClinicalEvidenceQuery(('fever',), purpose='TEST'),
                config=KnowledgeConfig(enabled=True, web_enabled=True),
                embedding_provider=CountingEmbedding(), web_provider=provider,
                web_client=client)
    bundle = asyncio.run(check())
    assert len(bundle.items) == 1 and bundle.items[0].origin == 'OFFICIAL_WEB'


def test_web_no_result_and_total_evidence_outage_remain_ungrounded():
    async def check():
        search = FakeSearch(['https://www.who.int/guidance'])
        async with client_for(lambda _request: httpx.Response(
                302, headers={'location': 'https://evil.example'})) as client:
            no_result = await retrieve_evidence(
                FakeDb(items=0), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
                config=KnowledgeConfig(enabled=True, web_enabled=True),
                embedding_provider=CountingEmbedding(), web_provider=search,
                web_client=client)
        unavailable = await retrieve_evidence(
            FakeDb(fail=True), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
            config=KnowledgeConfig(enabled=True, web_enabled=True),
            embedding_provider=CountingEmbedding(), web_provider=FakeSearch(fail=True))
        assert no_result.status == EvidenceStatus.NONE and no_result.items == ()
        assert unavailable.status == EvidenceStatus.NONE and unavailable.items == ()
        assert not unavailable.web_checked
    asyncio.run(check())


def test_slow_web_search_returns_to_ungrounded_core(monkeypatch):
    from app.services import clinical_knowledge

    class SlowSearch:
        async def search(self, terms, domains, jurisdiction):
            await asyncio.sleep(0.1)
            return []

    monkeypatch.setattr(clinical_knowledge, 'WEB_SEARCH_TIMEOUT_SECONDS', 0.01)
    bundle = asyncio.run(retrieve_evidence(
        object(), ClinicalEvidenceQuery(('fever',), purpose='TEST'),
        config=KnowledgeConfig(enabled=False, web_enabled=True),
        web_provider=SlowSearch()))
    assert bundle.status == EvidenceStatus.NONE and bundle.items == ()
    assert not bundle.web_checked


def test_source_update_checker_baselines_then_flags_change_without_activation():
    class SourceDb:
        def __init__(self):
            self.statuses = []
            self.digest = None

        def execute(self, sql, params=None):
            if 'SELECT s.source_id::text' in str(sql):
                source = dict(source_id='source-1', canonical_url='https://www.who.int/guidance',
                              update_status='UNCHECKED' if self.digest is None else 'BASELINED',
                              last_seen_etag=None, last_seen_modified=None,
                              last_seen_sha256=self.digest)
                return Rows([source])
            self.statuses.append(params['status'])
            self.digest = params.get('digest', self.digest)
            return SimpleNamespace(rowcount=1)

    count = 0

    def handler(_request):
        nonlocal count
        count += 1
        return httpx.Response(200, headers={'content-type': 'text/html'},
                              content=page(body=('Fever source version one. ' if count == 1
                                                 else 'Fever source version two. ') * 4))

    async def check():
        db = SourceDb()
        async with client_for(handler) as client:
            first = await check_active_sources(db, client=client)
            second = await check_active_sources(db, client=client)
        assert first[0].status == 'BASELINED'
        assert second[0].status == 'UPDATE_AVAILABLE'
        assert db.statuses == ['BASELINED', 'UPDATE_AVAILABLE']
    asyncio.run(check())


def test_source_checker_rejects_untrusted_redirect():
    async def check():
        async with client_for(lambda _request: httpx.Response(
                302, headers={'location': 'https://evil.example'})) as client:
            return await _fingerprint('https://www.who.int/guidance', client)
    assert asyncio.run(check())[:2] == ('UPDATE_AVAILABLE', 'UNTRUSTED_REDIRECT')


def test_source_checker_network_failure_is_reported_without_activation():
    async def check():
        def handler(request):
            raise httpx.ConnectError('unavailable', request=request)

        async with client_for(handler) as client:
            return await _fingerprint('https://www.who.int/guidance', client)

    assert asyncio.run(check())[:2] == ('CHECK_FAILED', 'NETWORK_ERROR')


@pytest.mark.parametrize('lock_acquired,expected_status,expected_checked', [
    (False, 'already_running', 0),
    (True, 'completed', 2),
])
def test_daily_source_check_uses_transaction_lock(
        monkeypatch, lock_acquired, expected_status, expected_checked):
    from app.core import database
    from app.services import clinical_source_updates

    calls = []

    class LockedSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def begin(self):
            return nullcontext()

        def execute(self, sql, params):
            assert 'pg_try_advisory_xact_lock' in str(sql)
            return SimpleNamespace(scalar=lambda: lock_acquired)

    async def fake_check(_db, *, limit):
        calls.append(limit)
        return [SourceCheck('one', 'UPDATE_AVAILABLE', 'CONTENT_CHANGED'),
                SourceCheck('two', 'CHECK_FAILED', 'NETWORK_ERROR')]

    monkeypatch.setattr(database, 'SessionLocal', LockedSession)
    monkeypatch.setattr(clinical_source_updates, 'check_active_sources', fake_check)
    result = asyncio.run(run_due_source_checks(limit=20))
    assert result['status'] == expected_status
    assert result['checked'] == expected_checked
    assert calls == ([20] if lock_acquired else [])
    if lock_acquired:
        assert result['update_available'] == 1 and result['check_failed'] == 1


def test_source_check_endpoint_requires_worker_secret(monkeypatch):
    from app.api.v1 import clinical_ops

    app = FastAPI()
    app.include_router(clinical_ops.router)
    calls = []

    async def fake_run():
        calls.append(1)
        return {'status': 'completed', 'checked': 0}

    monkeypatch.setattr(clinical_ops, 'run_due_source_checks', fake_run)
    monkeypatch.setenv('CLINICAL_SOURCE_UPDATE_WORKER_TOKEN', 's' * 40)

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://test') as client:
            missing = await client.post('/source-updates/check')
            wrong = await client.post('/source-updates/check',
                                      headers={'X-Clinical-Worker-Token': 'wrong'})
            right = await client.post('/source-updates/check',
                                      headers={'X-Clinical-Worker-Token': 's' * 40})
            return missing, wrong, right

    missing, wrong, right = asyncio.run(check())
    assert missing.status_code == 401 and wrong.status_code == 401
    assert right.status_code == 200 and right.json()['checked'] == 0
    assert calls == [1]


def test_source_check_endpoint_fails_closed_when_secret_unset(monkeypatch):
    from app.api.v1 import clinical_ops

    monkeypatch.delenv('CLINICAL_SOURCE_UPDATE_WORKER_TOKEN', raising=False)
    app = FastAPI()
    app.include_router(clinical_ops.router)

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://test') as client:
            return await client.post('/source-updates/check',
                                     headers={'X-Clinical-Worker-Token': 'anything'})

    assert asyncio.run(check()).status_code == 503
