"""Verify a generated or downloaded page without browser dependencies."""
import datetime as dt
import json
from pathlib import Path
import re
import sys


def verify(page):
    assert 'Open-Weight Model Radar' in page
    assert '/*__DATA__*/null' not in page and not re.search(r'\{\{[A-Z_]+\}\}', page)
    match = re.search(r'const DATA = (.*?);\nif \(window.Chart\)', page, re.S)
    assert match, 'Missing embedded snapshot'
    data = json.loads(match[1])
    assert data['updated'][:10] == dt.datetime.now(dt.timezone.utc).date().isoformat(), 'Snapshot is not from today UTC'
    assert len(data['top']) == 15, 'Expected 15 real trending models'
    assert data['model_count'] >= 15 and data['releases'], 'Empty model data'
    assert page.count('class="digest-card ') == 4
    assert page.count('data-release') == len(data['releases'])
    assert page.count('data-rumor') == len(data['watch']['items'])
    assert page.index('id="rumored-models"') < page.index('The quick read')
    for item in data['watch']['items']:
        assert item['name'] and item['sources']
        assert all(source['url'].startswith(('http://', 'https://')) for source in item['sources'])
    for model in data['top']:
        assert model['url'].startswith('https://huggingface.co/')
    assert not re.search(r'href=["\']\s*(javascript:|data:)', page, re.I)
    print(f"Verified {data['updated']}: {data['model_count']} models, 4 digest cards, {len(data['watch']['items'])} rumored/upcoming models, {len(data['releases'])} new repositories")
    return data


if __name__ == '__main__':
    verify(Path(sys.argv[1]).read_text())
