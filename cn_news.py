# -*- coding: utf-8 -*-
"""Validate explicitly sourced CN announcements; never substitute an overseas feed."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
NEWS_PATH = ROOT / 'data/news.json'
STATUS_PATH = ROOT / 'data/news_refresh_status.json'
SOURCE_PATH = ROOT / 'data/cn_official_news.json'


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        else:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        self.parts.append(' ')

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def clean_announcement_text(value):
    parser = _Text()
    parser.feed(str(value or ''))
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def parse_news_payload(payload, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, dict) or payload.get('region') != 'CN' or not isinstance(payload.get('headlines'), list):
        raise ValueError('Expected a CN official announcement document')
    headlines = []
    for item in payload['headlines']:
        if not isinstance(item, dict) or item.get('region') != 'CN':
            continue
        url = urlparse(str(item.get('url') or ''))
        # A qq.com suffix alone does not identify this game's official publisher.
        if url.scheme != 'https' or url.hostname != 'df.qq.com' or not url.path.strip('/'):
            continue
        try:
            published = datetime.fromisoformat(str(item.get('published_at', '')).replace('Z', '+00:00'))
            if published.tzinfo is None:
                continue
        except ValueError:
            continue
        if not timedelta(0) <= now - published <= timedelta(days=30):
            continue
        title = clean_announcement_text(item.get('title'))
        if not title:
            continue
        headlines.append({'title': title[:240], 'summary': clean_announcement_text(item.get('summary'))[:600],
                          'source': '三角洲行动国服官网', 'scope': '国服', 'region': 'CN',
                          'url': url.geturl(), 'published_at': published.isoformat(),
                          'fetched_at': now.isoformat(), 'expires_at': (published + timedelta(days=30)).isoformat(),
                          'tags': ['国服公告', '人工核验来源']})
    headlines.sort(key=lambda item: item['published_at'], reverse=True)
    return {'schema_version': 3, 'region': 'CN', 'updated': now.isoformat(),
            'source': {'name': '三角洲行动国服官网', 'scope': '国服；人工核验链接，自动抓取暂不可用', 'url': 'https://df.qq.com/'},
            'headlines': headlines[:5], 'outlook': [],
            'risk': '仅使用标注CN且带国服官网链接的公告；未接通稳定自动公告源，暂不做消息面价格预测。'}


def fetch_news_payload():
    return json.loads(SOURCE_PATH.read_text(encoding='utf-8'))


def _write(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.cn-news-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def refresh_news(news_path=NEWS_PATH, status_path=STATUS_PATH, fetcher=fetch_news_payload, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        doc = parse_news_payload(fetcher(), now)
        _write(news_path, doc)
        _write(status_path, {'status': 'manual_only', 'region': 'CN', 'checked_at': now.isoformat(),
                             'last_success_at': now.isoformat(), 'headline_count': len(doc['headlines']),
                             'message': '国服自动公告源暂不可用；只展示人工核验的官网链接。', 'error': None})
        print('CN_NEWS_MANUAL_ONLY headlines=%d' % len(doc['headlines']))
        return True
    except (OSError, ValueError, TypeError) as exc:
        # Legacy overseas files may remain on disk but the renderer also rejects their region.
        _write(status_path, {'status': 'error', 'region': 'CN', 'checked_at': now.isoformat(),
                             'message': '国服公告暂不可用', 'error': type(exc).__name__})
        print('CN_NEWS_UNAVAILABLE', type(exc).__name__)
        return False


def main():
    return 0 if refresh_news() else 1


if __name__ == '__main__':
    raise SystemExit(main())
