"""Allowlisted NLM health-topic summary extraction from the official XML ZIP."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from defusedxml import ElementTree

FEED_URL = 'https://medlineplus.gov/xml.html'
ATTRIBUTION = 'Source: MedlinePlus, National Library of Medicine'
MAX_ZIP_BYTES = 10 * 1024 * 1024
MAX_XML_BYTES = 50 * 1024 * 1024
MAX_SUMMARY_CHARS = 30000
_INLINE_TAGS = {'a', 'strong', 'em', 'b', 'i'}
_BLOCK_TAGS = {'p', 'ul', 'ol', 'li', 'h2', 'h3', 'h4', 'br', 'table',
               'thead', 'tbody', 'tr'}
_CELL_TAGS = {'td', 'th'}


class _SummaryText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.unsupported = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append('\n')
        elif tag not in _INLINE_TAGS and tag not in _CELL_TAGS:
            self.unsupported = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append('\n')
        elif tag in _CELL_TAGS:
            self.parts.append(' | ')

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_summary(markup: str) -> str:
    parser = _SummaryText()
    parser.feed(markup)
    if parser.unsupported:
        raise ValueError('summary contains unsupported markup')
    paragraphs = [' '.join(line.split()) for line in ''.join(parser.parts).splitlines()]
    return '\n'.join(line for line in paragraphs if line)


@dataclass(frozen=True)
class Topic:
    topic_id: str
    title: str
    url: str
    synonyms: tuple[str, ...]
    groups: tuple[str, ...]
    summary: str

    def document(self) -> bytes:
        lines = [f'# {self.title}', '', f'MedlinePlus topic ID: {self.topic_id}',
                 ATTRIBUTION]
        if self.synonyms:
            lines.append('Also called: ' + '; '.join(self.synonyms))
        if self.groups:
            lines.append('Topic groups: ' + '; '.join(self.groups))
        lines.extend(['', '## Summary', '', self.summary, ''])
        return '\n'.join(lines).encode('utf-8')

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.document()).hexdigest()


@dataclass(frozen=True)
class Feed:
    generated_at: datetime
    checksum: str
    topics: dict[str, Topic]


def parse_feed(data: bytes) -> Feed:
    if not data or len(data) > MAX_ZIP_BYTES:
        raise ValueError('MedlinePlus ZIP outside size limit')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or not re.fullmatch(
                r'mplus_topics_\d{4}-\d{2}-\d{2}\.xml', entries[0].filename):
            raise ValueError('unexpected MedlinePlus archive contents')
        if entries[0].file_size > MAX_XML_BYTES:
            raise ValueError('MedlinePlus XML outside size limit')
        root = ElementTree.fromstring(archive.read(entries[0]))
    if root.tag != 'health-topics':
        raise ValueError('unexpected MedlinePlus root')
    generated_at = datetime.strptime(root.attrib['date-generated'], '%m/%d/%Y %H:%M:%S')
    if generated_at.date().isoformat() not in entries[0].filename:
        raise ValueError('MedlinePlus archive date mismatch')
    topics = {}
    for record in root.findall('health-topic'):
        if record.get('language') != 'English':
            continue
        topic_id = record.get('id', '')
        url = record.get('url', '')
        parsed_url = urlsplit(url)
        if (not topic_id.isdigit() or not re.fullmatch(r'https://medlineplus\.gov/[a-z0-9]+\.html', url)
                or parsed_url.query or parsed_url.fragment or topic_id in topics):
            raise ValueError('invalid or duplicate English MedlinePlus topic identity')
        summary_node = record.find('full-summary')
        if summary_node is None or not summary_node.text:
            continue
        try:
            summary = _plain_summary(summary_node.text)
        except ValueError:
            continue
        title = ' '.join(record.get('title', '').split())
        if not title or len(summary) < 80 or len(summary) > MAX_SUMMARY_CHARS:
            continue
        synonyms = tuple(' '.join(node.text.split()) for node in record.findall('also-called')
                         if node.text and node.text.strip())
        groups = tuple(' '.join(node.text.split()) for node in record.findall('group')
                       if node.text and node.text.strip())
        topics[topic_id] = Topic(topic_id, title, url, synonyms, groups, summary)
    if not 800 <= len(topics) <= 1500:
        raise ValueError('unexpected count of reusable English MedlinePlus summaries')
    return Feed(generated_at, hashlib.sha256(data).hexdigest(), topics)
