"""Article-bound Nigerian publication dates and unchanged trusted-web guards."""

import asyncio
from datetime import date

import httpx
import pytest

from app.services.clinical_web import _article_dateline, search_official
from app.services.clinical_knowledge import ClinicalEvidenceQuery, KnowledgeConfig, retrieve_evidence
from tests.test_ai_wave5 import FakeDb, FakeSearch, CountingEmbedding, client_for

URL = ('https://health.gov.ng/nigeria-reaffirms-commitment-to-stronger-global-'
       'pandemic-preparedness-and-response/')
TITLE = 'Nigeria Reaffirms Commitment To Stronger Global Pandemic Preparedness And Response.'
ARTICLE = (TITLE + '\n26 September 2026: Synthetic pandemic preparedness article '
           'for backend tests, not a clinical corpus source. ' * 3)




@pytest.mark.parametrize('raw,url', [
    (TITLE + '\nUpdated September 26, 2026\nUndated article.', URL),
    ('Other article\n26 September 2026: unrelated content.', URL),
    (TITLE + '\nUndated article.\n26 September 2026: footer news.', URL),
    (TITLE + '\n31 September 2026: invalid date.', URL),
    (ARTICLE, URL.replace('health.gov.ng', 'fake.health.gov.ng')),
    (ARTICLE, URL.replace('health.gov.ng', 'www.who.int')),
])
def test_nigerian_dateline_rejects_unbound_invalid_or_footer_dates(raw, url):
    assert _article_dateline(raw, url) is None


def test_nigerian_dateline_from_content_not_search_metadata(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')
    assert _article_dateline(ARTICLE, URL) == date(2026, 9, 26)

    def handler(request):
        if request.method == 'GET':
            raise httpx.ConnectError('synthetic TLS failure', request=request)
        return httpx.Response(200, json={'results': [{'url': URL, 'raw_content': ARTICLE,
                                                     'published_date': '1999-01-01'}]})

    async def run():
        async with client_for(handler) as client:
            docs = await search_official('current pandemic preparedness', 'NG',
                                         provider=FakeSearch([URL]), client=client)
            assert len(docs) == 1 and docs[0].publication_date == date(2026, 9, 26)
            bundle = await retrieve_evidence(
                FakeDb(items=0), ClinicalEvidenceQuery(('current', 'pandemic'), 'TEST'),
                config=KnowledgeConfig(enabled=True, web_enabled=True),
                embedding_provider=CountingEmbedding(), web_provider=FakeSearch([URL]),
                web_client=client)
            assert bundle.web_checked and len(bundle.items) == 1
            assert bundle.items[0].freshness_state == 'CURRENT'
            assert bundle.items[0].jurisdiction == 'NG'
    asyncio.run(run())


@pytest.mark.parametrize('markup,expected', [
    ('<article><time class="entry-date published" datetime="2026-09-26T10:24:39+00:00">'
     '</time><time class="updated" datetime="2026-09-28"></time></article>', '2026-09-26'),
    ('<article><time class="updated" datetime="2026-09-26"></time></article>', None),
    ('<nav><time class="published" datetime="2026-09-26"></time></nav>', None),
    ('<article>Undated main article</article><article><time class="published" '
     'datetime="2026-09-26"></time></article>', None),
])
def test_primary_article_publication_time_not_modified_or_related_date(markup, expected):
    from app.services.clinical_web import _PageParser
    parser = _PageParser()
    parser.feed('<html><head><meta property="article:modified_time" '
                'content="2026-09-28"></head><body>' + markup + '</body></html>')
    assert (parser.date[:10] if parser.date else None) == expected


def test_official_https_redirect_is_bounded_and_published_date_retained():
    from app.services.clinical_web import fetch_official
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if not str(request.url).endswith('/'):
            return httpx.Response(301, headers={'location': URL})
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=(
            '<title>' + TITLE + '</title><article><time class="entry-date published" '
            'datetime="2026-09-26T10:24:39+00:00"></time><p>' + ARTICLE + '</p></article>'))

    async def run():
        async with client_for(handler) as client:
            doc = await fetch_official(URL.rstrip('/'), 'current pandemic', client=client)
            assert doc.url == URL and doc.publication_date == date(2026, 9, 26)
    asyncio.run(run())
    assert len(calls) == 2


@pytest.mark.parametrize('target', ['http://health.gov.ng/page',
    'https://fake.health.gov.ng/page', 'https://www.who.int/page'])
def test_redirect_cannot_downgrade_or_change_authority(target):
    from app.services.clinical_web import fetch_official
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={'location': target})

    async def run():
        async with client_for(handler) as client:
            assert await fetch_official(URL, 'pandemic', client=client) is None
    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize('dateline', ['26 January 2025', '26 September 2027', ''])
def test_stale_future_undated_extract_never_becomes_current(monkeypatch, dateline):
    monkeypatch.setenv('TAVILY_API_KEY', 'synthetic-test-key')

    def handler(request):
        if request.method == 'GET':
            raise httpx.ConnectError('unavailable', request=request)
        raw = TITLE + '\n' + (dateline + ': ' if dateline else '') + 'Pandemic preparedness text. ' * 8
        return httpx.Response(200, json={'results': [{'url': URL, 'raw_content': raw,
                                                     'published_date': '2026-09-26'}]})

    async def run():
        async with client_for(handler) as client:
            bundle = await retrieve_evidence(
                FakeDb(items=0), ClinicalEvidenceQuery(('current', 'pandemic'), 'TEST'),
                config=KnowledgeConfig(enabled=True, web_enabled=True),
                embedding_provider=CountingEmbedding(), web_provider=FakeSearch([URL]),
                web_client=client)
            assert bundle.items == ()
            assert bundle.failure_category == 'current_official_evidence_unavailable'
    asyncio.run(run())
