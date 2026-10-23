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
    dict(records[0], id='Qwen/Embeddings', pipeline_tag='feature-extraction'),
]
# External strings must remain inert in both HTML and the embedded script.
records[2]['id'] = 'Qwen/<script>alert(1)</script>'
records[2]['tags'] = ['license:"><img src=x onerror=alert(1)>']


def fake_http(url):
    if url == build.COREWEAVE_CATALOG:
        return b'<h3 class="models-grid-item-title">Qwen3.8 27B</h3>'
    if url == build.MODEL_CATALOG:
        return json.dumps({'kimi-code-plan-cn': {'models': {
            'kimi-for-coding': {'name': 'Kimi K2.8 Preview', 'release_date': '2026-09-11'},
            'future-qwen': {'name': 'Qwen 4', 'release_date': (now + dt.timedelta(days=1)).date().isoformat()},
        }}, 'openrouter': {'models': {'qwen4-placeholder': {'name': 'Qwen 4', 'release_date': '2026-01-01'}}}}).encode()
    if url == build.KIMI_RELEASES:
        return (b'<h2>K2.8 Preview September 11, 2026</h2><p>K2.8 Preview is now fully rolled out.</p>'
                b'<h2>K3.1 Pro Series is live October 23, 2026</h2><p>Now available in Kimi Code.</p>')
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
    shutil.copy(build.ROOT / 'focus.json', root / 'focus.json')
    sources = [{'label': 'Fixture evidence', 'url': 'https://example.com/rumor', 'date': now.date().isoformat()}]
    seeds = [
        {'name': 'Qwen Test-Model-1', 'author': 'Qwen', 'match': '^Test-Model-1$', 'status': 'Speculation', 'conf': 'lo', 'what': 'A sourced rumor', 'when': 'Unknown', 'sources': sources},
        {'name': 'Qwen 4', 'author': 'Qwen', 'match': r'^Qwen[ _-]*4(?![.\d])', 'status': 'In training', 'conf': 'md', 'what': 'Training reported', 'when': 'Unknown', 'sources': sources},
    ]
    (root / 'rumors.json').write_text(json.dumps({'reviewed': now.date().isoformat(), 'items': seeds}))
    (root / 'state.json').write_text(json.dumps({'updated': (now - dt.timedelta(days=1)).isoformat(),
                                              'ranks': {'Qwen/Test-Model-0': 99}}))
    with patch.object(build, 'ROOT', root), patch.object(build, 'http', fake_http):
        vetted = build.collect_release_catalog(now)
        # Broader discovery still requires actual weights, not just a task tag.
        for task in ('image-to-video', 'text-to-speech', 'robotics'):
            assert build.normalize(dict(records[0], pipeline_tag=task))['task'] == task
            assert build.normalize(dict(records[0], pipeline_tag=task, siblings=[])) is None
        assert build.normalize(dict(records[0], pipeline_tag='text-to-image', tags=['lora'])) is None
        assert build.normalize(dict(records[0], library_name='peft')) is None
        focused = [build.normalize(dict(records[0], id='thinkingmachines/Inkling', pipeline_tag='image-text-to-text')),
                   build.normalize(dict(records[0], id='reflection/Beam-1.0-501B-A23B')),
                   build.normalize(dict(records[0], id='nvidia/Cosmos3-H-Dreams', pipeline_tag='image-to-video')),
                   build.normalize(dict(records[0], id='Community/Kimi-K3.1'))]
        comparison = build.model_watch(focused, dict(vetted, coreweave=['Reflection Beam 1.0', 'NVIDIA Nemotron 3.5 Ultra',
                                                                      'Thinking Machines Inkling', 'NVIDIA Cosmos3-H-Dreams']))
        inkling = next(i for i in comparison['items'] if i['name'] == 'Inkling')
        assert inkling['weights'] and inkling['total_b'] == 975 and inkling['active_b'] == 41
        assert inkling['coreweave'] == ['Thinking Machines Inkling']
        assert not next(i for i in comparison['items'] if i['name'] == 'Inkling-Small')['coreweave']
        assert next(i for i in comparison['items'] if i['name'] == 'Cosmos3-H-Dreams')['coreweave']
        assert next(i for i in comparison['items'] if i['name'] == 'Beam 1.0')['coreweave']
        assert not next(i for i in comparison['items'] if i['name'] == 'Nemotron 3 Ultra')['coreweave']
        kimi_focus = next(i for i in comparison['items'] if i['name'] == 'Kimi K3.1 Pro')
        assert kimi_focus['released'] == build.KIMI_RELEASES and not kimi_focus['weights']
        assert next(i for i in comparison['items'] if i['kind'] == 'physical' and i['weights'])
        build.main()
        page = (root / 'site/index.html').read_text()
        assert '/*__DATA__*/null' not in page
        payload = page.split('const DATA = ', 1)[1].split(';\nif (window.Chart)', 1)[0]
        data = json.loads(payload)
        assert data['model_count'] == 20 and len(data['top']) == 15
        assert len(data['focus']['items']) == 7 and 'data-focus-filter="physical"' in page
        assert data['previous'] is None, 'A changed source sample must start a new rank baseline'
        assert len(data['releases']) == 20 and len(data['watch']['items']) == 1
        assert data['watch']['items'][0]['name'] == 'Qwen 4'
        assert page.index('id="rumored-models"') < page.index('The quick read')
        assert 'Model family' not in page and 'https://example.com/rumor' in page
        assert 'qwentestmodel1' in data['watch']['landed']
        # Version 4.5 and community lookalikes must not count as official Qwen 4.
        lookalikes = [dict(data['top'][0], author='Qwen', name='Qwen4.5-27B'),
                      dict(data['top'][0], author='Qwen', name='Qwen40-27B'),
                      dict(data['top'][0], author='Community', name='Qwen4-27B')]
        assert any(i['name'] == 'Qwen 4' for i in build.rumored_models([], lookalikes, {}, now, vetted)['items'])
        released = [dict(data['top'][0], author='Qwen', name='Qwen4-27B')]
        landed = build.rumored_models([], released, {}, now, vetted)
        assert not any(i['name'] == 'Qwen 4' for i in landed['items'])
        assert not any(i['name'] == 'Qwen 4' for i in build.rumored_models([], [], landed, now, vetted)['items'])
        # Unreviewed names can be discovered from explicitly future-looking news.
        report = {'title': 'Qwen 6 spotted in upcoming model leak', 'source': 'Example News',
                  'url': 'https://example.com/new-model', 'published': now.isoformat()}
        discovered = build.rumored_models([report], [], {}, now, vetted)
        candidate = next(i for i in discovered['items'] if i['name'] == 'Qwen 6')
        assert candidate['conf'] == 'lo' and candidate['sources'][0]['url'] == report['url']
        assert any(i['name'] == 'Qwen 6' for i in build.rumored_models([], [], discovered, now, vetted)['items'])
        kimi = dict(report, title='Kimi K2.8 rumored to be coming soon')
        excluded = build.rumored_models([kimi], [], {}, now, vetted)
        assert not any(i['name'] == 'Kimi K2.8' for i in excluded['items'])
        assert excluded['released']['kimik2.8']['url'] == build.MODEL_CATALOG
        assert not any(i['name'] == 'Kimi K2.8' for i in build.rumored_models([kimi], [], excluded, now, dict(vetted, records=[]))['items'])
        k31 = dict(report, title='Kimi K3.1 rumored upcoming release')
        assert not any(i['name'] == 'Kimi K3.1' for i in build.rumored_models([k31], [], {}, now, vetted)['items'])
        preview = dict(report, title='Kimi K7 Preview: already serving coding users')
        assert not any(i['name'] == 'Kimi K7' for i in build.rumored_models([preview], [], {}, now, vetted)['items'])
        # An announced weights release is a separate event from a live API.
        weight_seed = dict(seeds[1], event='weights', status='Weights pending')
        (root / 'rumors.json').write_text(json.dumps({'reviewed': now.date().isoformat(), 'items': [weight_seed]}))
        api_qwen = dict(vetted, records=[{'name': 'Qwen 4', 'author': 'Qwen', 'url': build.COREWEAVE_CATALOG}])
        assert build.rumored_models([], [], {}, now, api_qwen)['items'][0]['name'] == 'Qwen 4'
        assert not build.rumored_models([], released, {}, now, api_qwen)['items']
        (root / 'rumors.json').write_text(json.dumps({'reviewed': now.date().isoformat(), 'items': seeds}))
        coverage = build.rumored_models([dict(report, title='Qwen 4 release rumored soon')], [], {}, now, vetted)
        retained = build.rumored_models([], [], coverage, now, vetted)
        assert next(i for i in retained['items'] if i['name'] == 'Qwen 4')['latest']['url'] == report['url']
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
        def catalog_outage(url):
            if url == build.COREWEAVE_CATALOG:
                raise TimeoutError('catalog fixture outage')
            return fake_http(url)
        with patch.object(build, 'http', catalog_outage):
            try:
                build.main()
                raise AssertionError('Release checks were bypassed')
            except TimeoutError:
                pass
        assert (root / 'state.json').read_bytes() == before
print('Mock build passed: filtering, deduplication, data injection, escaping, state, and source outages')
