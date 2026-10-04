"""Trusted official-web fallback. Search text is de-identified before this boundary."""

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from io import BytesIO


@dataclass(frozen=True)
class TrustedAuthority:
    organization: str
    jurisdiction: str


# Exact hosts only. Additions require a clinical/governance review.
TRUSTED_HOSTS = {
    'health.gov.ng': TrustedAuthority('Federal Ministry of Health and Social Welfare', 'NG'),
    'www.health.gov.ng': TrustedAuthority('Federal Ministry of Health and Social Welfare', 'NG'),
    'ncdc.gov.ng': TrustedAuthority('Nigeria Centre for Disease Control and Prevention', 'NG'),
    'www.ncdc.gov.ng': TrustedAuthority('Nigeria Centre for Disease Control and Prevention', 'NG'),
    'nafdac.gov.ng': TrustedAuthority('National Agency for Food and Drug Administration and Control', 'NG'),
    'www.nafdac.gov.ng': TrustedAuthority('National Agency for Food and Drug Administration and Control', 'NG'),
    'who.int': TrustedAuthority('World Health Organization', 'GLOBAL'),
    'www.who.int': TrustedAuthority('World Health Organization', 'GLOBAL'),
    'iris.who.int': TrustedAuthority('World Health Organization', 'GLOBAL'),
    'www.fda.gov': TrustedAuthority('US Food and Drug Administration', 'GLOBAL'),
    'www.ema.europa.eu': TrustedAuthority('European Medicines Agency', 'GLOBAL'),
    'www.nice.org.uk': TrustedAuthority('National Institute for Health and Care Excellence', 'GLOBAL'),
}
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_EXTRACT_CANDIDATES = 2
logger = logging.getLogger(__name__)
APPROVED_SEARCH_DOMAINS = frozenset({
    'health.gov.ng', 'ncdc.gov.ng', 'nafdac.gov.ng', 'who.int', 'www.who.int',
    'iris.who.int', 'www.nice.org.uk', 'www.fda.gov', 'www.ema.europa.eu',
})


def trusted_url(value: str) -> TrustedAuthority | None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.port is not None or parsed.fragment or
                any(char.isspace() for char in value)):
            return None
        return TRUSTED_HOSTS.get(parsed.hostname.lower())
    except ValueError:
        return None


def search_domains(terms: str, jurisdiction: str) -> tuple[str, ...]:
    words = set(terms.split())
    if words & {'recall', 'withdrawn', 'approval'} and words & {
            'drug', 'medication', 'medicine', 'metformin', 'amoxicillin',
            'paracetamol', 'antibiotic'}:
        return (('nafdac.gov.ng',) if jurisdiction == 'NG'
                else ('www.fda.gov', 'www.ema.europa.eu', 'www.who.int'))
    if words & {'drug', 'medication', 'medicine', 'warning', 'contraindication',
                'metformin', 'amoxicillin', 'paracetamol', 'antibiotic'}:
        return (('nafdac.gov.ng', 'www.who.int', 'www.fda.gov', 'www.ema.europa.eu')
                if jurisdiction == 'NG' else
                ('www.who.int', 'www.fda.gov', 'www.ema.europa.eu'))
    if 'pandemic' in words and jurisdiction == 'NG' and 'outbreak' not in words:
        return ('health.gov.ng',)
    if words & {'outbreak', 'infection', 'vaccination', 'vaccine', 'pandemic'}:
        return (('ncdc.gov.ng', 'health.gov.ng') if jurisdiction == 'NG'
                else ('www.who.int',))
    return (('health.gov.ng', 'www.who.int', 'iris.who.int', 'www.nice.org.uk')
            if jurisdiction == 'NG' else
            ('www.who.int', 'iris.who.int', 'www.nice.org.uk'))


class WebSearchProvider(Protocol):
    async def search(self, terms: str, domains: tuple[str, ...],
                     jurisdiction: str) -> list[str]: ...


class TavilyOfficialSearch:
    async def search(self, terms: str, domains: tuple[str, ...],
                     jurisdiction: str) -> list[str]:
        key = os.getenv('TAVILY_API_KEY')
        if os.getenv('CLINICAL_WEB_PROVIDER', 'tavily').strip().lower() != 'tavily':
            raise RuntimeError('trusted search is not configured')
        if not key or not domains or any(domain not in APPROVED_SEARCH_DOMAINS
                                          for domain in domains):
            raise RuntimeError('trusted search is not configured')
        async with httpx.AsyncClient(timeout=20.0) as client:
            freshness_hint = ({'start_date': (date.today() - timedelta(days=90)).isoformat(),
                               'end_date': date.today().isoformat()}
                              if set(terms.split()) & {'current', 'latest', 'recent',
                                                       'recall', 'withdrawn', 'approval'} else {})
            response = await client.post(
                'https://api.tavily.com/search',
                headers={'Authorization': f'Bearer {key}'},
                json={'query': ('Nigeria ' + terms if jurisdiction == 'NG' and
                                'pandemic' in terms.split() else terms),
                      'search_depth': 'basic', 'topic': 'general',
                      'max_results': 8, 'include_domains': list(domains),
                      'include_domains_mode': 'restrict', 'include_answer': False,
                      'include_raw_content': False, 'auto_parameters': False,
                      **freshness_hint},
            )
            response.raise_for_status()
        body = response.json()
        results = body.get('results')
        if not isinstance(results, list):
            raise ValueError('invalid trusted search response')
        return [entry['url'] for entry in results[:8]
                if isinstance(entry, dict) and isinstance(entry.get('url'), str)]


def requested_url(url: str, domains: tuple[str, ...]) -> bool:
    if trusted_url(url) is None:
        return False
    host = urlsplit(url).hostname.lower()
    return any(host == domain or host == 'www.' + domain for domain in domains)


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ''
        self.date = None
        self.canonical = None
        self.parts = []
        self._title = False
        self._skip = 0
        self._articles = 0
        self._primary_article = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'script', 'style', 'nav', 'footer'}:
            self._skip += 1
        if tag == 'title':
            self._title = True
        if tag == 'article':
            self._articles += 1
            self._primary_article = self._articles == 1
        if (tag == 'time' and self._primary_article and not self._skip and
                'published' in attrs.get('class', '').split() and not self.date):
            self.date = attrs.get('datetime')
        if tag == 'meta':
            name = (attrs.get('property') or attrs.get('name') or '').lower()
            if name in {'article:published_time', 'datepublished', 'pubdate'} and not self.date:
                self.date = attrs.get('content')
        if tag == 'link' and attrs.get('rel', '').lower() == 'canonical':
            self.canonical = attrs.get('href')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'nav', 'footer'} and self._skip:
            self._skip -= 1
        if tag == 'title':
            self._title = False
        if tag == 'article':
            self._primary_article = False

    def handle_data(self, data):
        if self._title:
            self.title += data
        elif not self._skip and data.strip():
            self.parts.append(data.strip())


@dataclass(frozen=True)
class WebDocument:
    url: str
    title: str
    organization: str
    jurisdiction: str
    publication_date: date | None
    excerpt: str
    digest: str


def _article_dateline(raw: str, url: str) -> date | None:
    """Accept an FMOH article's leading dateline, never search metadata/footer dates."""
    if urlsplit(url).hostname not in {'health.gov.ng', 'www.health.gov.ng'}:
        return None
    slug = unquote(urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1])
    normalize = lambda value: ' '.join(re.findall(r'[a-z0-9]+', value.casefold()))
    title = normalize(slug.replace('-', ' '))
    lines = [line.strip().strip('# ').strip() for line in raw[:1600].splitlines()
             if line.strip()]
    for number, line in enumerate(lines[:5]):
        if normalize(line) != title or number + 1 >= len(lines):
            continue
        match = re.match(r'^(\d{1,2}) ([A-Za-z]+) (\d{4}):\s+\S', lines[number + 1])
        if match:
            from datetime import datetime
            try:
                return datetime.strptime(' '.join(match.groups()), '%d %B %Y').date()
            except ValueError:
                return None
    return None


def _supports_medication_intent(body: str, terms: str) -> bool:
    words = set(terms.split())
    medicine = r'(?:drugs?|medicines?|medications?)'
    if words & {'interact', 'interaction'}:
        return bool(re.search(
            rf'\b(?:{medicine}.{{0,100}}interact\w*\s+(?:with|between)|'
            rf'{medicine}\s+interactions?|interact\w*\s+with.{{0,100}}{medicine})\b',
            body, re.I))
    if 'rash' in words and words & {'drug', 'medicine', 'medication'}:
        return bool(re.search(
            rf'\b(?:{medicine}.{{0,120}}(?:cause|trigger|side effects|allergic).{{0,100}}rashes?|'
            rf'rashes?.{{0,100}}(?:from|after|due to|reaction to).{{0,100}}{medicine})\b',
            body, re.I))
    return True


def _supports_medication_title(title: str, url: str, terms: str) -> bool:
    if not set(terms.split()) & {'interact', 'interaction'}:
        return True
    subject = title + ' ' + urlsplit(url).path.replace('-', ' ')
    return (bool(re.search(r'\binteract\w*\b', subject, re.I)) and
            bool(re.search(r'\b(?:drugs?|medicines?|medications?)\b', subject, re.I)) and
            not re.search(r'\bfor healthcare professionals\b', title, re.I))


async def _fetch_official(url: str, terms: str, *,
                          client: httpx.AsyncClient,
                          _redirects: int = 0) -> tuple[WebDocument | None, bool]:
    authority = trusted_url(url)
    if authority is None:
        return None, False
    try:
        async with client.stream('GET', url, follow_redirects=False, timeout=12.0) as response:
            if str(response.url) != url or trusted_url(str(response.url)) is None:
                return None, False
            if response.status_code in {301, 302, 303, 307, 308}:
                target = urljoin(url, response.headers.get('location', ''))
                if (_redirects >= 2 or target == url or
                        trusted_url(target) != authority):
                    return None, False
                return await _fetch_official(target, terms, client=client,
                                             _redirects=_redirects + 1)
            if response.status_code != 200:
                return None, response.status_code in {403, 429, 500, 502, 503, 504}
            content_type = response.headers.get('content-type', '').split(';')[0].lower()
            if content_type not in {'text/html', 'application/pdf'}:
                return None, False
            if int(response.headers.get('content-length', '0')) > MAX_PAGE_BYTES:
                return None, False
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_PAGE_BYTES:
                    return None, False
        if content_type == 'application/pdf':
            reader = await asyncio.to_thread(PdfReader, BytesIO(data))
            if reader.is_encrypted or len(reader.pages) > 30:
                return None, False
            body = ' '.join((page.extract_text() or '') for page in reader.pages[:5])
            title = urlsplit(url).path.rsplit('/', 1)[-1].replace('-', ' ').removesuffix('.pdf')
            published = None
        else:
            parser = _PageParser()
            parser.feed(data.decode('utf-8', errors='replace'))
            if parser.canonical and parser.canonical != url:
                return None, False
            body = ' '.join(parser.parts)
            title = ' '.join(parser.title.split())
            try:
                published = date.fromisoformat((parser.date or '')[:10])
            except ValueError:
                published = None
        body = ' '.join(body.split())
        meaningful = set(terms.split()) - {'current', 'latest', 'recent', 'safety'}
        match = next((found for word in meaningful if (found := re.search(
            r'\b' + re.escape(word) + r'\b', body, re.I))), None)
        if (not title or len(body) < 60 or match is None or
                not _supports_medication_intent(body, terms) or
                not _supports_medication_title(title, url, terms)):
            return None, not title or len(body) < 60
        start = max(0, match.start() - 160)
        return WebDocument(url, title[:240], authority.organization,
                           authority.jurisdiction, published, body[start:start + 900],
                           hashlib.sha256(data).hexdigest()), False
    except (httpx.HTTPError, PdfReadError, OSError):
        return None, True
    except ValueError:
        return None, False


async def fetch_official(url: str, terms: str, *, client: httpx.AsyncClient) -> WebDocument | None:
    document, _ = await _fetch_official(url, terms, client=client)
    return document


async def extract_official(url: str, terms: str, *,
                           client: httpx.AsyncClient) -> WebDocument | None:
    authority = trusted_url(url)
    key = os.getenv('TAVILY_API_KEY')
    if authority is None or not key:
        return None
    try:
        async with client.stream(
            'POST', 'https://api.tavily.com/extract',
            headers={'Authorization': f'Bearer {key}'},
            json={'urls': url, 'extract_depth': 'basic', 'format': 'text',
                  'include_images': False, 'include_favicon': False},
            timeout=10.0,
        ) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > MAX_PAGE_BYTES:
                    return None
        payload = json.loads(data)
        results = payload.get('results') if isinstance(payload, dict) else None
        if not isinstance(results, list) or len(results) != 1:
            logger.info('[KNOWLEDGE] web_extract=empty provider=tavily')
            return None
        result = results[0]
        if not isinstance(result, dict) or result.get('url') != url or trusted_url(
                result['url']) != authority:
            logger.warning('[KNOWLEDGE] web_extract=rejected reason=url_mismatch')
            return None
        raw = result.get('raw_content')
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_PAGE_BYTES:
            logger.warning('[KNOWLEDGE] web_extract=rejected reason=content_bounds')
            return None
        body = ' '.join(html.unescape(raw).split())
        body = ''.join(char for char in body if char.isprintable())
        meaningful = set(terms.split()) - {'current', 'latest', 'recent', 'safety'}
        match = next((found for word in meaningful if (found := re.search(
            r'\b' + re.escape(word) + r'\b', body, re.I))), None)
        if len(body) < 60 or match is None or not _supports_medication_intent(body, terms):
            logger.info('[KNOWLEDGE] web_extract=rejected reason=insufficient_content')
            return None
        slug = unquote(urlsplit(url).path.rstrip('/').rsplit('/', 1)[-1])
        title = ' '.join(re.sub(r'[^\w\s-]', ' ', slug.replace('-', ' ')).split())[:240]
        if not title or not _supports_medication_title(title, url, terms):
            logger.info('[KNOWLEDGE] web_extract=rejected reason=no_url_title')
            return None
        start = max(0, match.start() - 160)
        published = _article_dateline(raw, url)
        logger.info('[KNOWLEDGE] web_extract=accepted provider=tavily '
                    'publication_date=%s date_source=%s', published,
                    'article_dateline' if published else 'unverified')
        return WebDocument(url, title, authority.organization, authority.jurisdiction,
                           published, body[start:start + 900], hashlib.sha256(
                               raw.encode('utf-8')).hexdigest())
    except (httpx.HTTPError, ValueError, OSError, TypeError) as exc:
        logger.warning('[KNOWLEDGE] web_extract=failed failure_category=%s',
                       type(exc).__name__)
        return None


async def search_official(terms: str, jurisdiction: str, *,
                          provider: WebSearchProvider | None = None,
                          client: httpx.AsyncClient | None = None) -> tuple[WebDocument, ...]:
    from app.services.clinical_knowledge import _MEDICAL_TERMS
    from app.services.clinical_freshness import topic_sensitive

    words = terms.split()
    if not words or len(terms) > 240 or any(word not in _MEDICAL_TERMS for word in words):
        raise ValueError('search boundary requires de-identified clinical terms')
    if jurisdiction != 'GLOBAL' and not re.fullmatch(r'[A-Z]{2}', jurisdiction):
        raise ValueError('invalid search jurisdiction')
    domains = search_domains(terms, jurisdiction)
    provider = provider or TavilyOfficialSearch()
    started = time.monotonic()
    try:
        urls = await provider.search(terms, domains, jurisdiction)
    except Exception as exc:
        category = ('quota' if isinstance(exc, httpx.HTTPStatusError) and
                    exc.response.status_code in {429, 432, 433} else type(exc).__name__)
        logger.warning('[KNOWLEDGE] web_search=failed provider=tavily failure_category=%s '
                       'latency_ms=%d', category, int((time.monotonic() - started) * 1000))
        raise
    own_client = client is None
    client = client or httpx.AsyncClient()
    try:
        documents = []
        seen = set()
        rejected = 0
        extracted = 0
        for url in urls[:8]:
            if url in seen or not requested_url(url, domains):
                rejected += 1
                continue
            seen.add(url)
            document, fallback_eligible = await _fetch_official(url, terms, client=client)
            if document is None and fallback_eligible and extracted < MAX_EXTRACT_CANDIDATES:
                extracted += 1
                document = await extract_official(url, terms, client=client)
            if document and topic_sensitive(terms) and (
                    document.publication_date is None or not
                    date.today() - timedelta(days=90) <= document.publication_date <= date.today()):
                document = None
            if document and document.jurisdiction in {jurisdiction, 'GLOBAL'}:
                documents.append(document)
            else:
                rejected += 1
            if len(documents) >= 4 or (document is not None and extracted):
                break
        logger.info('[KNOWLEDGE] web_search=complete provider=tavily results=%d '
                    'accepted=%d rejected=%d extract_attempts=%d latency_ms=%d',
                    len(urls), len(documents), rejected, extracted,
                    int((time.monotonic() - started) * 1000))
        return tuple(documents)
    finally:
        if own_client:
            await client.aclose()
