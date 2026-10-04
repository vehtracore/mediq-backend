import asyncio
import csv
import hashlib
import io
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import httpx

from app.services import medlineplus_corpus as corpus
from app.services.medlineplus_corpus import _ArchiveLinks, plan, selected_topics
from app.services.medlineplus_feed import Feed, Topic, parse_feed
from app.services.clinical_knowledge import (EvidenceBundle, EvidenceStatus,
                                             KnowledgeConfig, _without_verified_web,
                                             query_from_text, retrieve_evidence)
from app.services.clinical_web import (WebDocument, _supports_medication_title,
                                       fetch_official)


def _archive(summary='<p>Patient education about a common health topic. ' +
             'This is NLM-produced summary text for general information.</p>'):
    import xml.etree.ElementTree as et

    root = et.Element('health-topics', {'date-generated': '09/26/2026 02:30:41'})
    for index in range(800):
        record = et.SubElement(root, 'health-topic', {
            'id': str(index + 1), 'language': 'English',
            'title': f'Topic {index}', 'url': f'https://medlineplus.gov/topic{index}.html'})
        et.SubElement(record, 'full-summary').text = summary
        et.SubElement(record, 'site', {'title': 'External publisher'}).text = (
            'COPYRIGHTED EXTERNAL CONTENT MUST NEVER APPEAR')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('mplus_topics_2026-09-26.xml', et.tostring(root))
    return buffer.getvalue()


def test_parser_excludes_linked_site_content_and_attribution():
    feed = parse_feed(_archive())
    document = feed.topics['1'].document().decode()
    assert len(feed.topics) == 800
    assert 'Source: MedlinePlus, National Library of Medicine' in document
    assert 'COPYRIGHTED EXTERNAL CONTENT' not in document
    assert feed.topics['1'].checksum == hashlib.sha256(document.encode()).hexdigest()


def test_parser_preserves_table_rows_but_rejects_embedded_media():
    table = ('<p>Intro to health education with sufficient content for patients.</p>'
             '<table><tr><th>Risk</th><th>Action</th></tr>'
             '<tr><td>Fever</td><td>Seek care</td></tr></table>')
    assert 'Risk | Action' in parse_feed(_archive(table)).topics['1'].summary
    with pytest.raises(ValueError, match='unexpected count'):
        parse_feed(_archive('<p>Long enough patient text for this record.</p>'
                            '<img src="licensed-image.jpg">'))


def test_parser_rejects_xml_entities_and_bad_archive():
    data = _archive()
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        parse_feed(data[:30])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read(archive.namelist()[0])
    xml = b'<!DOCTYPE health-topics [<!ENTITY x "bad">]>' + xml
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('mplus_topics_2026-09-26.xml', xml)
    with pytest.raises(Exception):
        parse_feed(buffer.getvalue())


def test_selection_and_checksum_plan(tmp_path):
    topics = [Topic(str(i), f'Topic {i}', f'https://medlineplus.gov/topic{i}.html',
                    (), (), 'A valid summary with enough useful patient information.')
              for i in range(100)]
    feed = Feed(datetime(2026, 9, 26), 'dataset-checksum',
                {topic.topic_id: topic for topic in topics})
    manifest = tmp_path / 'topics.csv'
    with manifest.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['topic_id', 'title', 'coverage_category', 'selection_reason'])
        for topic in topics:
            writer.writerow([topic.topic_id, topic.title, 'general', 'Launch coverage'])
    assert len(selected_topics(feed, manifest)) == 100
    db = MagicMock()
    db.execute.return_value.mappings.return_value.first.side_effect = [
        None,
        {'issuing_organization': 'U.S. National Library of Medicine / MedlinePlus',
         'source_id': 's', 'version_id': 'v', 'checksum': topics[1].checksum},
        {'issuing_organization': 'U.S. National Library of Medicine / MedlinePlus',
         'source_id': 's', 'version_id': 'v', 'checksum': 'old'},
    ]
    assert [item.action for item in plan(db, topics[:3])] == [
        'NEW', 'UNCHANGED', 'CHANGED']
    manifest.write_text(manifest.read_text().replace('Topic 0', 'Wrong title', 1))
    with pytest.raises(ValueError, match='invalid manifest'):
        selected_topics(feed, manifest)


def test_archive_link_allowlist():
    parser = _ArchiveLinks()
    parser.feed('<a href="https://evil.test/xml/mplus_topics_compressed_2026-09-27.zip">bad</a>'
                '<a href="/xml/mplus_topics_compressed_2026-09-26.zip">good</a>')
    assert parser.paths == [('2026-09-26',
                             'https://medlineplus.gov/xml/mplus_topics_compressed_2026-09-26.zip')]


def test_launch_phrase_normalization_avoids_unsafe_ambiguity():
    assert query_from_text('I am short of breath', purpose='EVAL').normalized_text() == 'breathing'
    assert query_from_text('I may harm myself tonight', purpose='EVAL').normalized_text() == 'suicide crisis'
    assert 'hypoglycemia' in query_from_text(
        'I have diabetes and feel shaky and confused', purpose='EVAL').normalized_text()


def test_update_check_marks_only_changed_topics(monkeypatch):
    topics = [Topic(str(i), f'Topic {i}', f'https://medlineplus.gov/topic{i}.html',
                    (), (), 'Patient education summary.') for i in range(2)]
    monkeypatch.setattr(corpus, 'plan', lambda db, items: [
        corpus.TopicAction('0', 'UNCHANGED', 's0', 'v0'),
        corpus.TopicAction('1', 'CHANGED', 's1', 'v1')])
    db = MagicMock()
    actions = corpus.mark_updates(db, topics)
    assert [action.action for action in actions] == ['UNCHANGED', 'CHANGED']
    assert db.execute.call_args_list[0].args[1]['status'] == 'CURRENT'
    assert db.execute.call_args_list[1].args[1]['status'] == 'UPDATE_AVAILABLE'
    assert db.execute.call_args_list[1].args[1]['digest'] == topics[1].checksum


def test_ingestion_activates_only_after_complete_version(monkeypatch):
    topic = Topic('1', 'Fever', 'https://medlineplus.gov/fever.html', (), (),
                  'Fever is a symptom. Seek clinical advice when symptoms are severe. ' * 3)
    monkeypatch.setattr(corpus, '_existing', lambda db, url: None)
    monkeypatch.setattr(corpus, 'register_source', lambda db, source: 'source-id')
    calls = []

    async def ingest(db, **kwargs):
        calls.append(('ingest', kwargs['source_id'], kwargs['data']))
        return 'version-id'

    monkeypatch.setattr(corpus, 'ingest_version', ingest)
    monkeypatch.setattr(corpus, 'activate_version',
                        lambda db, version: calls.append(('activate', version)))
    db = MagicMock()
    result = asyncio.run(corpus.ingest_topic(db, topic, MagicMock(), activate=True))
    assert result.action == 'ACTIVATED'
    assert calls[0][0] == 'ingest' and calls[1] == ('activate', 'version-id')
    assert db.execute.call_args.args[1]['checksum'] == topic.checksum


def test_official_web_rejects_word_match_without_medication_concept():
    async def check(body, terms):
        content = ('<html><title>Drug Interaction Guidance</title><body>' +
                   body + '</body></html>').encode()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                httpx.Response(200, headers={'content-type': 'text/html'}, content=content))) as client:
            return await fetch_official('https://www.fda.gov/safety', terms, client=client)

    unrelated = 'The medicine program holds INTERACT meetings for developers. ' * 4
    relevant = 'This drug may interact with other medicines. Ask a pharmacist. ' * 4
    assert asyncio.run(check(unrelated, 'medicine interact')) is None
    assert asyncio.run(check(relevant, 'medicine interact')) is not None
    unrelated_rash = 'A rash is common. Our medicine safety program has resources. ' * 4
    assert asyncio.run(check(unrelated_rash, 'rash medicine drug safety')) is None
    assert not _supports_medication_title(
        'Expedited Programs for Regenerative Medicine Therapies',
        'https://www.fda.gov/regenerative-medicine', 'medicine interact')
    assert not _supports_medication_title(
        'For Healthcare Professionals: Drug Interactions',
        'https://www.fda.gov/drug-interactions', 'medicine interact')


def test_current_recall_rejects_undated_official_page():
    class Search:
        async def search(self, terms, domains, jurisdiction):
            return ['https://nafdac.gov.ng/medicine-recall']

    async def check():
        content = (b'<html><head><title>Medicine recall alert</title></head><body><main>' +
                   b'Official medicine recall information and safety guidance. ' * 3 +
                   b'</main></body></html>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
                httpx.Response(200, headers={'content-type': 'text/html'}, content=content))) as client:
            return await retrieve_evidence(
                object(), query_from_text('Current medicine recall', purpose='TEST'),
                config=KnowledgeConfig(enabled=False, web_enabled=True),
                web_provider=Search(), web_client=client)

    bundle = asyncio.run(check())
    assert bundle.web_checked and not bundle.items


def test_current_claim_never_uses_general_curated_evidence_when_web_fails():
    generic = EvidenceBundle(EvidenceStatus.SUFFICIENT, items=(object(),))
    result = _without_verified_web(generic, 'current medicine recall', checked=False)
    assert result.status == EvidenceStatus.NONE and not result.items
    assert not result.web_checked
    safety = _without_verified_web(generic, 'rash medicine safety', checked=True)
    assert safety.status == EvidenceStatus.INSUFFICIENT and safety.web_checked


def test_nigerian_official_web_precedes_global_evidence(monkeypatch):
    from app.services import clinical_web

    async def search(*args, **kwargs):
        return (
            WebDocument('https://www.who.int/fever', 'WHO fever', 'WHO', 'GLOBAL',
                        date.today(), 'Official fever guidance', 'global-digest'),
            WebDocument('https://ncdc.gov.ng/fever', 'NCDC fever', 'NCDC', 'NG',
                        date.today(), 'Nigerian fever guidance', 'ng-digest'),
        )

    monkeypatch.setattr(clinical_web, 'search_official', search)
    bundle = asyncio.run(retrieve_evidence(
        object(), query_from_text('current fever', purpose='TEST'),
        config=KnowledgeConfig(enabled=False, web_enabled=True)))
    assert [item.jurisdiction for item in bundle.items] == ['NG', 'GLOBAL']
