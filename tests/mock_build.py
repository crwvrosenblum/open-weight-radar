"""Real-shaped public API fixtures, isolated from live state and site output."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('build', Path(__file__).resolve().parents[1] / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
records = [{
    'id': f'Qwen/Test-Model-{index}', 'private': False, 'gated': 'auto' if index == 1 else False,
    'createdAt': (now - dt.timedelta(days=index)).isoformat(),
    'downloads': 100_000 - index * 100, 'likes': 1000 - index,
    'trendingScore': 100 - index, 'pipeline_tag': 'text-generation',
    'tags': ['license:apache-2.0'], 'siblings': [{'rfilename': 'model-00001-of-00002.safetensors'}],
} for index in range(20)]
records += [
    dict(records[0], id='Qwen/Announcement', siblings=[{'rfilename': 'README.md'}]),
    dict(records[0], id='Qwen/Adapter', siblings=[{'rfilename': 'adapter_model.safetensors'}]),
    dict(records[0], id='Qwen/Private', private=True),
    dict(records[0], id='Qwen/Image', pipeline_tag='text-to-image'),
]
# External strings must remain inert in both HTML and the embedded script.
records[2]['id'] = 'Qwen/<script>alert(1)</script>'
records[2]['tags'] = ['license:"><img src=x onerror=alert(1)>']


def fake_http(url):
    if 'huggingface.co/api/models?' in url:
        return json.dumps(records).encode()
    return (f'<rss><channel><item><title>Qwen Test-Model-1 release - Example News</title>'
            f'<link>https://example.com/story?a=1&amp;b=2</link><source>Example News</source>'
            f'<pubDate>{now.strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>'
            '</item><item><title>DeepSeek leak</title><link>javascript:alert(1)</link>'
            f'<pubDate>{now.strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>'
            '</item></channel></rss>').encode()


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    shutil.copy(build.ROOT / 'template.html', root / 'template.html')
    with patch.object(build, 'ROOT', root), patch.object(build, 'http', fake_http):
        build.main()
        page = (root / 'site/index.html').read_text()
        assert '/*__DATA__*/null' not in page
        payload = page.split('const DATA = ', 1)[1].split(';\nif (window.Chart)', 1)[0]
        data = json.loads(payload)
        assert data['model_count'] == 20 and len(data['top']) == 15
        assert len(data['releases']) == 20 and len(data['watch']['items']) == 1
        assert data['watch']['items'][0]['weights']['name'] == 'Test-Model-1'
        assert '<script>alert(1)</script>' not in page
        assert '&lt;img src=x onerror=alert(1)&gt;' in page
        assert not build.safe_url('javascript:alert(1)')
        assert not build.safe_url('https://example.com/\nattack')
        assert build.number(1_500_000) == '1.5M'
        assert all(m['movement'] is None for m in data['top'])
        first_watch = data['watch']
        records[3]['trendingScore'] = 999
        build.main()
        refreshed = json.loads((root / 'site/index.html').read_text().split('const DATA = ', 1)[1].split(';\nif (window.Chart)', 1)[0])
        assert refreshed['top'][0]['id'] == 'Qwen/Test-Model-3'
        assert refreshed['top'][0]['movement'] == 3
        second = json.loads((root / 'state.json').read_text())
        assert second['ranks']['Qwen/Test-Model-0'] == 2
        # A news outage preserves the prior reports and their timestamp.
        def news_outage(url):
            if 'news.google.com' in url:
                raise TimeoutError('fixture outage')
            return fake_http(url)
        with patch.object(build, 'http', news_outage):
            build.main()
        failed_news = json.loads((root / 'state.json').read_text())['watch']
        assert failed_news['items'] == first_watch['items']
        assert failed_news['updated'] == first_watch['updated']
        assert failed_news['warning']
        # A model-source outage must fail rather than publish zeroed fresh data.
        before = (root / 'state.json').read_bytes()
        with patch.object(build, 'http', side_effect=TimeoutError('fixture outage')):
            try:
                build.main()
                raise AssertionError('Model outage did not fail the build')
            except RuntimeError:
                pass
        assert (root / 'state.json').read_bytes() == before
print('Mock build passed: filtering, deduplication, data injection, escaping, state, and source outages')
