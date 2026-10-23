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
MODEL_NAMES = {
    'mistralai': r'\bmistral[ -]+large[ -]+\d+(?:\.\d+)?',
    'Qwen': r'\bqwen[ -]*\d+(?:\.\d+)?(?:[ -]+max)?',
    'deepseek-ai': r'\bdeepseek[ -]*v\d+(?:\.\d+)?(?:[ -]+(?:pro|flash))?',
    'moonshotai': r'\bkimi[ -]*k\d+(?:\.\d+)?',
    'MiniMaxAI': r'\bminimax[ -]*m\d+(?:\.\d+)?(?:[ -]+flash)?',
    'zai-org': r'\bglm[ -]*\d+(?:\.\d+)?(?:[ -]+flash)?',
    'meta-llama': r'\bllama[ -]*\d+(?:\.\d+)?',
    'google': r'\bgemma[ -]*\d+(?:\.\d+)?',
    'nvidia': r'\bnemotron[ -]*\d+(?:\.\d+)?',
    'openai': r'\bgpt[ -]*oss[ -]*\d+',
}
UPCOMING = r'\b(?:rumou?r(?:s|ed)?|leak(?:s|ed)?|upcoming|in training|expected|spotted|teaser|prepar\w*|coming|planned|unreleased)\b'
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
    query = '(Mistral OR Qwen OR DeepSeek OR Kimi OR MiniMax OR GLM OR Llama OR Gemma OR Nemotron OR gpt-oss OR Reflection) (model OR weights) (rumor OR leak OR upcoming OR preview OR training OR teaser OR expected OR release) when:14d'
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


def model_key(name):
    return re.sub(r'[\s_-]+', '', name.casefold())


COREWEAVE_CATALOG = 'https://www.coreweave.com/products/coreweave-forge/serverless-inference'
MODEL_CATALOG = 'https://models.dev/api.json'
KIMI_RELEASES = 'https://www.kimi.com/code/docs/en/kimi-code/whats-new.html'


def text_only(markup):
    return html.unescape(re.sub(r'<[^>]+>', ' ', markup)).strip()


def release_names(text, url):
    records = []
    for author, pattern in MODEL_NAMES.items():
        match = re.search(pattern, text, re.I)
        if match:
            records.append({'author': author, 'name': match[0], 'url': url})
    return records


def collect_release_catalog(now):
    # Availability is broader than public weights: API and product releases count.
    records, checks = [], []
    page = http(COREWEAVE_CATALOG).decode()
    names = re.findall(r'<h3\b[^>]*class="[^"]*\bmodels-grid-item-title\b[^"]*"[^>]*>(.*?)</h3>', page, re.S)
    if not names:
        raise ValueError('CoreWeave public catalog has no model headings')
    for name in names:
        records.extend(release_names(text_only(name), COREWEAVE_CATALOG))
    checks.append({'name': 'CoreWeave public catalog', 'url': COREWEAVE_CATALOG, 'count': len(names)})

    catalog = json.loads(http(MODEL_CATALOG))
    if not isinstance(catalog, dict) or not any(p.get('models') for p in catalog.values()):
        raise ValueError('Empty public API catalog')
    count = 0
    for provider, entry in catalog.items():
        if provider == 'openrouter':
            continue
        for model_id, model in entry.get('models', {}).items():
            date = model.get('release_date') or ''
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) or date > now.date().isoformat():
                continue
            count += 1
            records.extend(release_names(model.get('name', '') + ' ' + model_id, MODEL_CATALOG))
    if not count:
        raise ValueError('Public API catalog has no dated releases')
    checks.append({'name': 'models.dev dated API releases (excluding OpenRouter)', 'url': MODEL_CATALOG, 'count': count})

    page = http(KIMI_RELEASES).decode()
    count = 0
    for heading, body in re.findall(r'<h2\b[^>]*>(.*?)</h2>(.*?)(?=<h2\b|$)', page, re.S):
        title = text_only(heading)
        version = re.search(r'\bK\d+(?:[.]\d+)?', title, re.I)
        date = re.search(r'\b[A-Z][a-z]+ \d{1,2}, \d{4}', title)
        if not version or not date or not re.search(r'fully rolled out|now released|is live|now available', title + text_only(body)[:1200], re.I):
            continue
        released = dt.datetime.strptime(date[0], '%B %d, %Y').date()
        if released <= now.date():
            records.extend(release_names('Kimi ' + version[0], KIMI_RELEASES))
            count += 1
    if not count:
        raise ValueError('Kimi changelog has no recognizable model releases')
    checks.append({'name': 'Kimi official product releases', 'url': KIMI_RELEASES, 'count': count})
    return {'records': records, 'checks': checks, 'updated': now.isoformat()}


def rumored_models(news, models, previous, now, release_catalog):
    curated = json.loads((ROOT / 'rumors.json').read_text())
    items = {model_key(item['name']): dict(item) for item in curated['items']}
    # Persist discovered names so a transient news outage cannot erase a rumor.
    for item in previous.get('items', []):
        if not item.get('name'):
            continue
        key = model_key(item['name'])
        if key in items:
            items[key].update({field: item[field] for field in ('seen', 'latest') if field in item})
        elif item.get('discovered') and re.search(UPCOMING, item.get('what', ''), re.I) and stamp(item.get('seen')) and now - stamp(item['seen']) <= dt.timedelta(days=30):
            items[key] = dict(item)
    for report in news:
        if not re.search(UPCOMING, report['title'], re.I):
            continue
        if re.search(r'weights (?:are )?out|now available|rumou?rs? debunked', report['title'], re.I):
            continue
        for author, pattern in MODEL_NAMES.items():
            match = re.search(pattern, report['title'], re.I)
            if not match:
                continue
            name = match[0]
            key = model_key(name)
            if key not in items:
                model_pattern = re.escape(name).replace(r'\ ', r'[ _-]*').replace(r'\-', r'[ _-]*')
                items[key] = {'name': name, 'author': author, 'match': '^' + model_pattern + r'(?![.\d])',
                              'status': 'Unverified report', 'conf': 'lo', 'what': report['title'],
                              'when': 'No verified date', 'discovered': True,
                              'sources': [{'label': report['source'], 'url': report['url'], 'date': report['published'][:10]}]}
            # Reports arrive newest first; keep the latest matching source.
            item = items[key]
            if report['published'] > item.get('seen', ''):
                item['seen'] = report['published']
                item['latest'] = report
    result = []
    landed = dict(previous.get('landed', {}))
    released = dict(previous.get('released', {}))
    for key, item in items.items():
        item['sources'] = [source for source in item.get('sources', []) if safe_url(source.get('url'))]
        if not item['sources'] or item.get('conf') not in ('hi', 'md', 'lo'):
            continue
        try:
            pattern = re.compile(item['match'], re.I)
        except re.error:
            continue
        matches = [model for model in models if model['author'].casefold() == item['author'].casefold() and pattern.search(model['name'])]
        if matches:
            landed[key] = matches[0]['url']
        if item.get('event') != 'weights':
            shipped = next((record for record in release_catalog['records'] if record['author'].casefold() == item['author'].casefold() and pattern.search(record['name'])), None)
            if shipped:
                released[key] = {'url': shipped['url'], 'checked': release_catalog['updated']}
        if key in landed or (key in released and item.get('event') != 'weights'):
            # Remember both product releases and public weights across snapshots.
            continue
        until = item.get('until')
        if until and now.date().isoformat() > until:
            item['when'] = 'Reported window passed · no weights found in tracked sources'
        item['reviewed'] = curated['reviewed'] if not item.get('discovered') else None
        result.append(item)
    return {'updated': now.isoformat(), 'reviewed': curated['reviewed'], 'items': result[:10], 'landed': landed, 'released': released, 'release_checks': release_catalog['checks'], 'vetted': release_catalog['updated']}


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
        ('Rumored & upcoming', len(watch), 'Named models · source links below'),
    ])
    rumor_rows = []
    for item in watch:
        sources = ''.join(f'<li>{link(source["url"], source["label"])} <span>· {esc(source["date"])}</span></li>' for source in item['sources'])
        latest = item.get('latest')
        latest_link = f'<p class="rumor-latest">Latest coverage: {link(latest["url"], latest["source"])} · {esc(latest["published"][:10])}</p>' if latest else ''
        source_links = ' '.join(link(source['url'], urllib.parse.urlsplit(source['url']).netloc.removeprefix('www.')) for source in item['sources'])
        rumor_rows.append(
            f'<li class="rumor-row" data-rumor><details class="rumor-detail"><summary>'
            f'<strong>{esc(item["name"])}</strong><span class="pill {esc(item["conf"])}">{esc(item["status"])}</span>'
            f'</summary><div class="rumor-expanded"><p>{esc(item["what"])}</p><p class="rumor-when">{esc(item["when"])}</p>'
            f'<ul class="rumor-evidence">{sources}</ul>{latest_link}</div></details>'
            f'<div class="rumor-links" aria-label="Sources for {esc(item["name"])}">{source_links}</div></li>'
        )
    movers = ''.join(f'<tr><td>{index}</td><td class="model">{link(model["url"], model["name"])}<small>{esc(model["author"])}</small></td><td class="numeric">{number(model["score"])}</td><td class="numeric">{number(model["downloads"])}</td><td class="numeric">{number(model["likes"])}</td><td>{"↑ " + str(model["movement"]) if model["movement"] is not None and model["movement"] > 0 else "↓ " + str(-model["movement"]) if model["movement"] is not None and model["movement"] < 0 else "—" if model["movement"] == 0 or not data["previous"] else "New"}</td></tr>' for index, model in enumerate(top, 1))
    release_rows = ''.join(f'<tr data-release><td class="nowrap">{esc(model["created"][:10])}</td><td class="model">{link(model["url"], model["name"])}<small>{esc(model["author"])}</small></td><td>{esc(model["task"])}</td><td>{esc(model["license"])}{" · gated" if model["gated"] else ""}</td><td class="numeric">{number(model["downloads"])}</td><td class="numeric">{number(model["likes"])}</td></tr>' for model in releases)
    coverage = ', '.join(LABS)
    warning = f'<p class="notice">{esc(data["watch"]["warning"])}</p>' if data['watch'].get('warning') else ''
    values = {
        'UPDATED': esc(data['updated'].replace('T', ' ').replace('+00:00', ' UTC')),
        'COUNT': str(data['model_count']), 'KPIS': kpis, 'DIGEST': digest,
        'RUMOR_ROWS': ''.join(rumor_rows) or '<li class="coverage">No sourced, unreleased model candidates in this snapshot.</li>',
        'REVIEWED': esc(data['watch']['reviewed']),
        'RELEASE_CHECKS': ' · '.join(link(check['url'], check['name']) for check in data['watch']['release_checks']),
        'VETTED': esc(data['watch']['vetted'].replace('T', ' ').replace('+00:00', ' UTC')),
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
    # Do not publish a fresh rumor list if mandatory release checks are unavailable.
    release_catalog = collect_release_catalog(now)
    try:
        news = collect_news(now)
        if not news:
            raise ValueError('No recent news items')
        watch = rumored_models(news, models, previous.get('watch', {}), now, release_catalog)
    except Exception as error:
        print(f'Warning: news refresh failed ({type(error).__name__}); retaining previous reports')
        watch = rumored_models([], models, previous.get('watch', {}), now, release_catalog)
        watch['updated'] = previous.get('watch', {}).get('updated')
        watch['warning'] = 'News refresh unavailable. Showing dated source evidence and previous reports; weight availability was checked in this build.'
    data = {'updated': now.isoformat(), 'model_count': len(models), 'top': ranked[:15], 'releases': releases,
            'watch': watch, 'previous': previous.get('updated')}
    site = ROOT / 'site'
    site.mkdir(exist_ok=True)
    (site / 'index.html').write_text(render(data))
    state_file.write_text(json.dumps({'updated': now.isoformat(), 'ranks': {model['id']: rank for rank, model in enumerate(ranked, 1)}, 'watch': watch}, indent=2, ensure_ascii=False) + '\n')
    print(f"Built {data['updated']}: {len(models)} repositories, {len(releases)} recent, {len(watch['items'])} rumored/upcoming models; no paid APIs")


if __name__ == '__main__':
    main()
