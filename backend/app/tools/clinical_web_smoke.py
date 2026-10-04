"""Synthetic-only official web smoke: python -m app.tools.clinical_web_smoke."""

import asyncio
import json
import logging
import sys
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

from app.services.clinical_knowledge import (
    ClinicalEvidenceQuery, KnowledgeConfig, retrieve_evidence,
)
from app.services.clinical_web import TavilyOfficialSearch, requested_url, trusted_url


class RecordingSearch(TavilyOfficialSearch):
    def __init__(self):
        self.domains = ()
        self.urls = []

    async def search(self, terms, domains, jurisdiction):
        self.domains = domains
        self.urls = await super().search(terms, domains, jurisdiction)
        return self.urls


async def main() -> None:
    load_dotenv()
    clinical_web_logger = logging.getLogger('app.services.clinical_web')
    clinical_web_logger.addHandler(logging.StreamHandler())
    clinical_web_logger.setLevel(logging.INFO)
    cases = (
        ('nafdac_medicine_safety', ('drug', 'recall'), 'NG', 'nafdac.gov.ng'),
        ('ncdc_public_health', ('outbreak',), 'NG', 'ncdc.gov.ng'),
        ('who_guidance', ('malaria', 'treatment', 'guideline'), 'GLOBAL', 'who.int'),
    )
    passed = True
    for label, concepts, jurisdiction, expected_host in cases:
        if len(sys.argv) > 1 and label != sys.argv[1]:
            continue
        provider = RecordingSearch()
        bundle = await retrieve_evidence(
            object(), ClinicalEvidenceQuery(concepts, purpose='OPERATOR_SMOKE',
                                            jurisdiction=jurisdiction),
            config=KnowledgeConfig(enabled=False, web_enabled=True),
            web_provider=provider,
        )
        rejected_results = sum(not requested_url(url, provider.domains)
                               for url in provider.urls)
        accepted = [item for item in bundle.items if item.origin == 'OFFICIAL_WEB']
        metadata_valid = bool(accepted) and all(
            item.title and item.issuing_organization and item.canonical_url and
            trusted_url(item.canonical_url) is not None and
            requested_url(item.canonical_url, provider.domains)
            for item in accepted)
        expected_found = any((urlsplit(item.canonical_url).hostname or '') in {
            expected_host, 'www.' + expected_host} for item in accepted)
        case_passed = bool(provider.urls and metadata_valid and expected_found)
        passed = passed and case_passed
        diagnostics = []
        if not case_passed:
            async with httpx.AsyncClient(timeout=12.0) as client:
                for url in provider.urls[:4]:
                    host = urlsplit(url).hostname
                    try:
                        async with client.stream('GET', url, follow_redirects=False) as response:
                            diagnostics.append({
                                'host': host, 'requested': requested_url(url, provider.domains),
                                'status': response.status_code,
                                'content_type': response.headers.get('content-type', '').split(';')[0],
                                'redirect_host': urlsplit(response.headers.get('location', '')).hostname,
                                'content_length': response.headers.get('content-length'),
                            })
                    except httpx.HTTPError as exc:
                        diagnostics.append({'host': host, 'error': type(exc).__name__})
        print(json.dumps({
            'case': label, 'pass': case_passed, 'requested_domains': provider.domains,
            'provider_results': len(provider.urls), 'rejected_provider_results': rejected_results,
            'accepted_evidence': len(accepted),
            'accepted_hosts': [urlsplit(item.canonical_url).hostname for item in accepted],
            'backend_metadata': bool(metadata_valid),
            'diagnostics': diagnostics,
        }))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
