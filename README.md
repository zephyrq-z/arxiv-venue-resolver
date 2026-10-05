# arxiv-venue-resolver

[中文说明](README.zh-CN.md)

Resolve where an arXiv preprint was **actually published** — the venue, its CCF rank, DOI link, and a ready-to-paste BibTeX. Pure standard library, single-file CLI.

```text
$ python3 resolve.py https://arxiv.org/abs/2407.01489
arXiv:2407.01489  Agentless: Demystifying LLM-based Software Engineering Agents
  发表: Proc. ACM Softw. Eng.  [Semantic Scholar (title match)]
  CCF : FSE · A · 会议 · 软件工程/系统软件/程序设计语言
  链接: https://doi.org/10.1145/3715754
  BibTeX:
    @inproceedings{Xia2024agentless, ...}
```

## Why

arXiv metadata tells you a paper *exists*, not where it *landed*. Authors fill `journal_ref` inconsistently (~11% of CS papers), arXiv's `comments` field has "Accepted at FSE 2026" buried in free text, and CCF ranks — the de-facto standard for Chinese CS venue evaluation — require mapping a dozen alias forms (PACMSE wrappers → FSE/ISSTA, NeurIPS long names) onto the official catalog.

This tool chains every evidence source from cheapest to most authoritative, stopping at the first hit:

```
① local.sqlite journal_ref      (0 network, author-claimed)
①' arXiv comments "accepted at" (0 network, author-claimed)
② Semantic Scholar by-id         (authoritative, cached)
③ S2 title search                (for too-new papers)
④ DBLP local sqlite / API        (fallback, --dblp on|only)
⑤ PACM wrapper → Crossref issue  (PACMSE hosts both FSE 2024+ and ISSTA 2025+)
⑥ CCF catalog match              (abbr / alias / full name, ambiguity-resolved)
```

S2 results are cached in `~/.cache/arxiv-venue/<id>.json`, including a `resolved:false` negative marker — once confirmed unpublished, re-checking costs zero network.

## Prerequisites & companion projects

Standalone by design — `resolve.py` runs with zero setup (falls back to the arXiv API + Semantic Scholar + DBLP web API). Two optional local databases make it fast and offline, and one companion project feeds the first of them:

| Component | What it provides | Without it |
|---|---|---|
| [arXivSearcher](https://github.com/aiopsplus/arXivSearcher) (companion; repo is private — accessible to members of the DevOps+ Lab AIOps Team) | arXiv metadata embedding shards (`data/embedding_shards_*/shard_*.meta.jsonl`); `build_local.py` reads them into `local.sqlite` | paper metadata falls back to the arXiv API (1 request per unknown ID) |
| `local.sqlite` (optional, built) | 3.1M-paper metadata: journal_ref / DOI / category at ms-level, zero network | the zero-request tier (①) is lost |
| `dblp.sqlite` (optional, built) | 8.4M-record authoritative publication index from the DBLP XML dump | `--dblp` falls back to the DBLP web API (may hit bot protection) |

The two projects are complementary: **arXivSearcher finds which papers are relevant** (BM25 + embedding hybrid search over 3M preprints); **this resolver answers where each preprint was formally published** (venue + CCF rank + BibTeX). Typical flow: search with arXivSearcher → feed the resulting arXiv IDs to this resolver.

## Setup

```bash
# optional but recommended: local arXiv metadata (3.1M papers, ms-level lookup)
# requires arXivSearcher embedding shards; edit SHARD_DIRS first
python3 build_local.py

# optional: local DBLP index (8.4M records, enables --dblp without network)
python3 build_dblp.py     # downloads ~700MB XML, builds 1.4GB sqlite

# zero setup: everything falls back to arXiv API + S2 + DBLP web API
```

No dependencies. Python 3.9+ (standard library only). S2 API key is optional (env `SemanticScholar_API_KEY` or read from `~/.zshrc`) — without it you share the public rate limit.

## Usage

```bash
python3 resolve.py <arxiv-url-or-id>... [options]

  --json                 structured output
  --meta-mode auto|local|remote   local = sqlite only; remote = arXiv API only
  --dblp off|on|only     DBLP fallback (on) or sole source (only)
  --no-cache             bypass ~/.cache/arxiv-venue
```

Multiple IDs in one invocation share the CCF catalog load and database connections.

## Agent Skill (Codex / Claude Code / Hermes)

Give your agents direct access to the resolver by installing the bundled skill. Two install paths:

### Option A — via [skills-manager](https://github.com/xingkongliang/skills-manager) (recommended if you already use it)

[Skills Manager](https://skillsmanager.dev) is a desktop app + CLI that manages one central skill library (`~/.skills-manager`) and deploys to 50+ coding agents, preserving source metadata, presets, and update tracking. If your machine already manages skills through it, install into the central library instead of copying by hand:

```bash
SM=~/.skills-manager/bin/skills-manager-cli
"$SM" skills install /path/to/arxiv-venue-resolver/skills/arxiv-venue-resolver   # from a local clone
# or from GitHub:
"$SM" skills install https://github.com/zephyrq-z/arxiv-venue-resolver/tree/main/skills/arxiv-venue-resolver
"$SM" skills deploy arxiv-venue-resolver --agent claude_code --agent codex --agent hermes
```

`skills deploy` copies from the central library into each agent's skills directory; agents then see the `arxiv-venue-resolver` skill. Deployed copies have no baked repo path (Skills Manager does the copying, not `install_skills.py`), so set one env var so the wrapper can find `resolve.py`:

```bash
export ARXIV_VENUE_RESOLVER_SKM=/path/to/arxiv-venue-resolver/resolve.py
```

### Option B — direct install

```bash
python3 install_skills.py
```

Auto-detects and installs to `~/.codex/skills`, `~/.claude/skills`, `~/.hermes/skills` (existing directories only; pass `--dest DIR` for custom locations, `--link` for a dev symlink). This path bakes the repo location into each copy, so nothing further is needed while the repo stays where it is.

### Either way, agents call

```bash
python3 scripts/resolve_venue.py 2407.01489 --json   # from inside the installed skill
```

The skill wraps `resolve.py` with structured JSON errors (`resolver_missing`, `resolver_timeout`, …) so agents can react instead of parsing tracebacks. `resolve.py` itself is never copied with the skill — the wrapper locates it in order: `--resolver PATH` argument, `ARXIV_VENUE_RESOLVER` env var, baked install-time repo path (Option B), `ARXIV_VENUE_RESOLVER_SKM` env var (Option A). Keep the repo on disk, or export one of the env vars, after installing.

## Files

| File | Purpose |
|---|---|
| `skills/arxiv-venue-resolver/` | agent skill (SKILL.md + wrapper script) for Codex / Claude Code / Hermes |
| `install_skills.py` | installs the skill into local agent skill directories |
| `resolve.py` | the resolver CLI |
| `build_local.py` | builds `local.sqlite` (3.1M papers) from arXivSearcher embedding shards |
| `build_dblp.py` | builds `dblp.sqlite` (8.4M records) from the official DBLP XML dump |
| `ccf_v7.tsv` | CCF recommended catalog (681 venues), tab-separated |

Generated databases (`local.sqlite`, `dblp.sqlite`) are gitignored — rebuild them with the scripts above.

## Data quality notes

- `journal_ref` / `comments` venues are **author-claimed**, not verified; S2 and DBLP paths are authoritative.
- DBLP's `CoRR` entries (its arXiv mirror) are treated as *not published* and skipped — matching continues to a real proceedings version if one exists.
- CCF abbreviation collisions (FSE is both a crypto B-conference and the software-engineering A-conference) are disambiguated by the paper's arXiv primary category; unknown categories fall back to rank-A preference.
- Known limitation: legacy arXiv IDs with dotted subarchives (`math.AG/0701001`) are not parsed; comments-extracted venue strings can carry noise ("CIKM 2026 as a full paper") and miss the CCF match.

## License

MIT
