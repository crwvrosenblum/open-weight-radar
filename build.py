"""Build the key-free radar from public Hugging Face metadata and news RSS."""
import datetime as dt
import html
import json
import re
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = Path(__file__).resolve().parent
UTC = dt.timezone.utc
LABS = {
    'Mistral': 'mistralai', 'Qwen / Alibaba': 'Qwen', 'DeepSeek': 'deepseek-ai',
    'Moonshot Kimi': 'moonshotai', 'MiniMax': 'MiniMaxAI', 'Z.ai GLM': 'zai-org',
    'Meta Llama': 'meta-llama', 'Google Gemma': 'google', 'NVIDIA Nemotron': 'nvidia',
    'OpenAI gpt-oss': 'openai', 'Reflection': 'reflection',
}
FAMILIES = {
    'Mistral': r'\bmistral\b', 'Qwen / Alibaba': r'\bqwen\b|\balibaba\b',
    'DeepSeek': r'\bdeepseek\b', 'Moonshot Kimi': r'\bkimi\b|\bmoonshot\b',
    'MiniMax': r'\bminimax\b', 'Z.ai GLM': r'\bglm[ -]?\d|\bz\.ai\b',
    'Meta Llama': r'\bllama\b', 'Google Gemma': r'\bgemma\b',
    'NVIDIA Nemotron': r'\bnemotron\b', 'OpenAI gpt-oss': r'\bgpt[ -]?oss\b',
    'Reflection': r'\breflection\b',
}
TASKS = {'text-generation', 'image-text-to-text', 'text2text-generation', 'any-to-any'}


def http(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Open-Weight-Radar/1.0 (+https://github.com/crwvrosenblum/open-weight-radar)'})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read()


def stamp(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(UTC)
    except (ValueError, TypeError):
        return None


def number(value):
    value = float(value or 0)
    for scale, suffix in ((1e12, 'T'), (1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if abs(value) >= scale:
            return f'{value / scale:.1f}{suffix}'
    return f'{value:,.0f}'


def esc(value):
    return html.escape(str(value if value is not None else '—'), quote=True)


def safe_url(value):
    value = str(value or '')
    parsed = urllib.parse.urlsplit(value)
    return value if parsed.scheme in ('http', 'https') and parsed.netloc and not re.search(r'[\s\x00-\x1f]', value) else ''


def link(url, label):
    url = safe_url(url)
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(label)} ↗</a>' if url else esc(label)


def hf_url(model_id):
    return 'https://huggingface.co/' + urllib.parse.quote(model_id, safe='/')


def normalize(record):
    model_id = record.get('id') or record.get('modelId')
    if not model_id or record.get('private'):
        return None
    tags = record.get('tags') or []
    task = record.get('pipeline_tag') or next((tag for tag in tags if tag in TASKS), None)
    files = [file.get('rfilename', '') for file in record.get('siblings', [])]
    weights = any(re.search(r'\.(safetensors|gguf|bin|pth|pt)$', f, re.I)
                  and not re.search(r'(^|/)(adapter|optimizer|training)', f, re.I) for f in files)
    if task not in TASKS or not weights:
        return None
    return {
        'id': model_id, 'name': model_id.split('/')[-1], 'author': model_id.split('/')[0],
        'created': record.get('createdAt'), 'downloads': int(record.get('downloads') or 0),
        'likes': int(record.get('likes') or 0), 'score': float(record.get('trendingScore') or 0),
        'task': task, 'license': next((t.removeprefix('license:') for t in tags if t.startswith('license:')), 'Not listed'),
        'gated': bool(record.get('gated')), 'url': hf_url(model_id),
    }


def collect_models():
    models, trending_ids, failures = {}, set(), []
    queries = [('Trending: ' + task, {'pipeline_tag': task, 'sort': 'trendingScore', 'limit': 60})
               for task in ('text-generation', 'image-text-to-text')]
    queries += [(lab, {'author': author, 'sort': 'createdAt', 'limit': 60}) for lab, author in LABS.items()]
    for label, params in queries:
        params.update(direction=-1, full='true')
        try:
            records = json.loads(http('https://huggingface.co/api/models?' + urllib.parse.urlencode(params)))
            if not isinstance(records, list):
                raise ValueError('Expected a model array')
            if records:
                print(f'{label}: {len(records)} records; first record keys: {", ".join(sorted(records[0]))}')
            for record in records:
                model = normalize(record)
                if model:
                    previous = models.get(model['id'])
                    if previous:
                        model['score'] = max(previous['score'], model['score'])
                    models[model['id']] = model
                    if label.startswith('Trending:'):
                        trending_ids.add(model['id'])
        except Exception as error:
            failures.append(label)
            print(f'Warning: {label}: {type(error).__name__}')
    # A failed source must not masquerade as a fresh complete snapshot.
    if failures:
        raise RuntimeError('Hugging Face sources unavailable: ' + ', '.join(failures))
    if not trending_ids:
        raise RuntimeError('No public LLM repositories with weight files found')
    return list(models.values()), trending_ids


def collect_news(now):
    query = '(Mistral OR Qwen OR DeepSeek OR Kimi OR MiniMax OR GLM OR Llama OR Gemma OR Nemotron OR gpt-oss OR Reflection) (model OR weights) (release OR launch OR upcoming OR preview OR leak) when:14d'
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    root = ET.fromstring(http(url))
    items = []
    for item in root.findall('./channel/item'):
        try:
            published = parsedate_to_datetime(item.findtext('pubDate')).astimezone(UTC)
        except (TypeError, ValueError):
            continue
        title = item.findtext('title') or ''
        source = item.findtext('source') or 'News report'
        if title.endswith(' - ' + source):
            title = title[:-len(' - ' + source)]
        if not now - dt.timedelta(days=14) <= published <= now or not safe_url(item.findtext('link')):
            continue
        items.append({'title': title, 'source': source, 'url': item.findtext('link'), 'published': published.isoformat()})
    return sorted(items, key=lambda item: item['published'], reverse=True)


def launch_watch(news, models):
    items = []
    for family, pattern in FAMILIES.items():
        report = next((item for item in news if re.search(pattern, item['title'], re.I)), None)
        if not report:
            continue
        # Only an exact model name in a headline can connect a report to weights.
        def words(value):
            return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()
        title = ' ' + words(report['title']) + ' '
        matches = [m for m in models if len(words(m['name'])) >= 8 and ' ' + words(m['name']) + ' ' in title]
        matched = max(matches, key=lambda m: len(m['name']), default=None)
        items.append(dict(report, family=family, signal='Rumor' if re.search(r'rumou?r|leak|unconfirmed|speculat', report['title'], re.I) else 'Report',
                          weights={'name': matched['name'], 'url': matched['url']} if matched else None))
    return sorted(items, key=lambda item: item['published'], reverse=True)[:10]


def render(data):
    top, releases, watch = data['top'], data['releases'], data['watch']['items']
    newest = releases[0] if releases else None
    cards = [
        ('Momentum', top[0]['name'], f"Leads this snapshot with {number(top[0]['score'])} Hugging Face trending score."),
        ('Release', f"{len(releases)} recent repositories", 'Model repositories created in the last 30 days across the tracked sources.'),
        ('Trend', f"{number(sum(m['downloads'] for m in top))} downloads", f"Rolling 30-day downloads across the {len(top)} trending repositories shown below."),
        ('Release', newest['name'] if newest else 'No recent repositories',
         f"Newest repository created {newest['created'][:10]}; {number(newest['likes'])} likes so far." if newest else 'No eligible repositories created in the tracked 30-day window.'),
    ]
    digest = ''.join(f'<article class="digest-card {tag.lower()}"><span class="chip">{esc(tag)}</span><h3>{esc(title)}</h3><p>{esc(detail)}</p></article>' for tag, title, detail in cards)
    kpis = ''.join(f'<article class="kpi"><span>{esc(label)}</span><strong title="{esc(value)}">{esc(value)}</strong><small>{esc(note)}</small></article>' for label, value, note in [
        ('Trending now', top[0]['name'], f"{number(top[0]['score'])} trending score · Hugging Face"),
        ('New repositories · 30d', len(releases), 'Across tracked labs + trending results'),
        ('Most downloaded · trending 15', max(top, key=lambda m: m['downloads'])['name'], 'Hugging Face · rolling 30 days'),
        ('Launch signals', len(watch), 'Sourced reports · last 14 days'),
    ])
    watch_rows = ''.join(f'<tr data-watch><td class="model">{esc(item["family"])}</td><td><span class="pill {"lo" if item["signal"] == "Rumor" else "md"}">{esc(item["signal"])}</span></td><td>{link(item["url"], item["title"])}<small>{esc(item["source"])}</small></td><td class="nowrap">{esc(item["published"][:10])}</td><td>{link(item["weights"]["url"], item["weights"]["name"]) if item["weights"] else "Not verified"}</td></tr>' for item in watch)
    movers = ''.join(f'<tr><td>{index}</td><td class="model">{link(model["url"], model["name"])}<small>{esc(model["author"])}</small></td><td class="numeric">{number(model["score"])}</td><td class="numeric">{number(model["downloads"])}</td><td class="numeric">{number(model["likes"])}</td><td>{"↑ " + str(model["movement"]) if model["movement"] is not None and model["movement"] > 0 else "↓ " + str(-model["movement"]) if model["movement"] is not None and model["movement"] < 0 else "—" if model["movement"] == 0 or not data["previous"] else "New"}</td></tr>' for index, model in enumerate(top, 1))
    release_rows = ''.join(f'<tr data-release><td class="nowrap">{esc(model["created"][:10])}</td><td class="model">{link(model["url"], model["name"])}<small>{esc(model["author"])}</small></td><td>{esc(model["task"])}</td><td>{esc(model["license"])}{" · gated" if model["gated"] else ""}</td><td class="numeric">{number(model["downloads"])}</td><td class="numeric">{number(model["likes"])}</td></tr>' for model in releases)
    coverage = ', '.join(LABS)
    warning = f'<p class="notice">{esc(data["watch"]["warning"])}</p>' if data['watch'].get('warning') else ''
    values = {
        'UPDATED': esc(data['updated'].replace('T', ' ').replace('+00:00', ' UTC')),
        'COUNT': str(data['model_count']), 'KPIS': kpis, 'DIGEST': digest,
        'WATCH_ROWS': watch_rows or '<tr><td colspan="5">No recent matching reports. Check the lab model pages below.</td></tr>',
        'WATCH_TIME': esc(data['watch'].get('updated') or 'unavailable'), 'WATCH_WARNING': warning,
        'TOP_ROWS': movers, 'RELEASE_ROWS': release_rows or '<tr><td colspan="6">No recent repositories in this snapshot.</td></tr>',
        'RELEASE_COUNT': str(len(releases)), 'COVERAGE': esc(coverage),
        'PREVIOUS': esc(data['previous'] or 'First snapshot; rank movement starts after the next refresh.'),
        'LAB_LINKS': ' · '.join(link(hf_url(author), lab) for lab, author in LABS.items()),
    }
    template = (ROOT / 'template.html').read_text()
    for name, value in values.items():
        template = template.replace('{{' + name + '}}', value)
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False).replace('</', '<\\/')
    if template.count('/*__DATA__*/null') != 1:
        raise ValueError('Expected one data placeholder')
    return template.replace('/*__DATA__*/null', payload)


def main():
    now = dt.datetime.now(UTC).replace(microsecond=0)
    state_file = ROOT / 'state.json'
    previous = json.loads(state_file.read_text()) if state_file.exists() else {}
    models, trending_ids = collect_models()
    ranked = sorted((model for model in models if model['id'] in trending_ids), key=lambda model: (-model['score'], -model['likes'], model['id']))
    prior_ranks = previous.get('ranks', {})
    for rank, model in enumerate(ranked, 1):
        model['movement'] = prior_ranks[model['id']] - rank if model['id'] in prior_ranks else None
    releases = sorted((model for model in models if stamp(model['created']) and now - dt.timedelta(days=30) <= stamp(model['created']) <= now), key=lambda model: model['created'], reverse=True)
    try:
        news = collect_news(now)
        if not news:
            raise ValueError('No recent news items')
        watch = {'updated': now.isoformat(), 'items': launch_watch(news, models)}
    except Exception as error:
        print(f'Warning: news refresh failed ({type(error).__name__}); retaining previous reports')
        watch = dict(previous.get('watch', {'updated': None, 'items': []}))
        watch['warning'] = 'News refresh unavailable. Reports below retain their original research and publication dates.'
    data = {'updated': now.isoformat(), 'model_count': len(models), 'top': ranked[:15], 'releases': releases,
            'watch': watch, 'previous': previous.get('updated')}
    site = ROOT / 'site'
    site.mkdir(exist_ok=True)
    (site / 'index.html').write_text(render(data))
    state_file.write_text(json.dumps({'updated': now.isoformat(), 'ranks': {model['id']: rank for rank, model in enumerate(ranked, 1)}, 'watch': watch}, indent=2, ensure_ascii=False) + '\n')
    print(f"Built {data['updated']}: {len(models)} repositories, {len(releases)} recent, {len(watch['items'])} launch signals; no paid APIs")


if __name__ == '__main__':
    main()
