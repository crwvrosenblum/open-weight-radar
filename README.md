# Open-Weight Model Radar

A static, self-updating dashboard of open-weight LLM repositories, Hugging Face momentum, and sourced launch reports.

**Live:** https://crwvrosenblum.github.io/open-weight-radar/

GitHub Actions fetches public sources and deploys to GitHub Pages twice daily. Nothing runs locally after setup. No API keys, OpenRouter account, LLM calls, backend, database, or paid services are required. **This repository and its page are public.**

## What it measures

- Top 15 weight-bearing repositories by Hugging Face trending score, drawn from the top 60 text-generation and top 60 image-text-to-text results.
- Rolling 30-day repository downloads, cumulative likes, and rank movement since the previous successful snapshot. These are community signals, not inference traffic, benchmark scores, or unique user counts.
- New repositories created in the last 30 days among those trending results and the latest 60 repositories per tracked lab. Repository creation dates are not necessarily weight-release dates. Quantizations and fine-tunes may appear separately. This bounded sample is not the entire Hugging Face catalog.
- Latest matching news headline per model family over the last 14 days, via Google News RSS. Reports link to the news item and retain publisher and date. “Rumor” is a headline keyword classification, not an AI confidence judgment. “Report” does not confirm a launch or forecast. A weights link requires an exact model-name match in the headline; “Not verified” does not mean unavailable.

Tracked labs: Mistral, Qwen/Alibaba, DeepSeek, Moonshot Kimi, MiniMax, Z.ai GLM, Meta Llama, Google Gemma, NVIDIA Nemotron, OpenAI gpt-oss, and Reflection. Trending results also surface other labs. Coverage is configured in `build.py` (`LABS`, `TASKS`, and `FAMILIES`).

A repository must have public metadata, a supported LLM task, and at least one `.safetensors`, `.gguf`, `.bin`, `.pt`, or `.pth` weight file. Adapter-only and private repositories are excluded. Gated models can be included; accepting terms or requesting access may be required. Open-weight does not imply an open-source or commercially permissive license. Check the linked model card.

## Sources and real API shapes

The build uses Python 3.12 standard library only. Public API responses were inspected directly during setup:

- `https://huggingface.co/api/models`: an array with `id`, `createdAt`, `downloads`, `likes`, `trendingScore` (trending queries), `pipeline_tag`, `tags`, `gated`, `private`, and `siblings[].rfilename`. Metadata-only repositories do not count as releases. The same model ID is merged across queries.
- `https://news.google.com/rss/search`: RSS XML with `channel/item` containing `title`, `link`, `pubDate`, and `source`. News links open through Google News. No article body is scraped or reproduced.

`state.json` persists the last successful trending ranks and launch-watch reports. Every real build commits an updated timestamp and snapshot; generated `site/` is ignored and deployed only as a workflow artifact. A model-source error fails the build, preserving the deployed page. A news error retains the prior news and research timestamp with a visible warning. The “Updated” time refers to model metadata; news has its own checked timestamp.

The page is pre-rendered HTML. It makes no client data requests; Chart.js 4.5.0 is the only CDN dependency. If it is unavailable, all statistics and tables remain usable. Dynamic HTML is escaped; links accept only HTTP(S); embedded JSON escapes closing HTML tags.

## Setup

```sh
gh auth status
git clone https://github.com/crwvrosenblum/open-weight-radar.git
cd open-weight-radar
```

For a new copy, create a public repository with `gh repo create YOUR_REPO --public --source . --push`, then enable Pages with Actions as its source:

```sh
gh api -X POST repos/YOUR_ACCOUNT/YOUR_REPO/pages -f build_type=workflow
```

Use `-X PUT` if Pages already exists. Update the repository and Pages links in the HTML/README if forking. No secrets or repository variables need to be set.

## Refresh and schedule

```sh
gh workflow run 'Refresh Open-Weight Radar'
gh run watch
```

The cron in `.github/workflows/refresh.yml` is `0 12,22 * * *` (12:00 and 22:00 UTC; 08:00/18:00 US Eastern during daylight saving time, 07:00/17:00 in standard time). GitHub may delay scheduled runs. Change that cron to change the schedule.

Fresh state commits keep the repository active. Before fetching sources, the workflow makes a monthly keepalive commit on the first day if the repository has no commit dated that day. This step can run even if upstream data is unavailable. GitHub’s 60-day inactivity policy can still disable schedules during a prolonged workflow or GitHub failure that prevents commits; check Actions if updates stop. A static page cannot refresh while GitHub Actions is unavailable or disabled.

## Local validation

```sh
python3.12 tests/mock_build.py
python3.12 build.py
python3.12 tests/verify_site.py site/index.html
python3.12 -m http.server 8765 --directory site
```

`mock_build.py` isolates fixtures in a temporary directory, leaving real site output and snapshot state intact. It covers public/gated/metadata-only/adapter repositories, duplicate IDs, safe links, malicious external strings, JSON injection, rank persistence, and upstream failures. The workflow also checks the extracted browser script with `node --check` before deployment.

## Scope update

The initial brief used OpenRouter catalog/usage data and paid AI summaries/research. The revised request explicitly removed OpenRouter and all API keys. Accordingly there are no token-share, token-growth, pricing, AA benchmark, or inferred launch-date claims. The dashboard uses public Hugging Face activity and news instead. Summaries are deterministic; there are no model IDs or LLM costs to report. API and hosting cost per run: $0 on the public GitHub repository, subject to GitHub’s service limits.
