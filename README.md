# arxiv-venue-resolver

Resolve where an arXiv preprint was **actually published** — the venue, its CCF rank, DOI link, and a ready-to-paste BibTeX. Pure standard library, single-file CLI.

输入一个 arXiv 网址或 ID，回答「这篇预印本正式发表在哪」：会议/期刊名、CCF 分级、DOI 链接、可直接粘贴的 BibTeX。纯标准库实现，单文件 CLI。

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

arXiv metadata tells you a paper *exists*, not where it *landed*. Authors fill `journal_ref` inconsistently (~11% of CS papers), arXiv's `comments` field has "Accepted at FSE 2026" buried in free text, and CCF ranks — the de-facto standard for Chinese CS venue evaluation — require mapping a dozen alias forms (PACMSE → FSE, NeurIPS long names) onto the official catalog.

This tool chains every evidence source from cheapest to most authoritative, stopping at the first hit:

```
① local.sqlite journal_ref      (0 network, author-claimed)
①' arXiv comments "accepted at" (0 network, author-claimed)
② Semantic Scholar by-id         (authoritative, cached)
③ S2 title search                (for too-new papers)
④ DBLP local sqlite / API        (fallback, --dblp on|only)
⑤ CCF catalog match              (abbr / alias / full name, ambiguity-resolved)
```

S2 results are cached in `~/.cache/arxiv-venue/<id>.json`, including a `resolved:false` negative marker — once confirmed unpublished, re-checking costs zero network.

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

Give your agents direct access to the resolver by installing the bundled skill:

```bash
python3 install_skills.py
```

Auto-detects and installs to `~/.codex/skills`, `~/.claude/skills`, `~/.hermes/skills` (existing directories only; pass `--dest DIR` for custom locations, `--link` for a dev symlink). Agents then invoke it as the `arxiv-venue-resolver` skill:

```bash
python3 scripts/resolve_venue.py 2407.01489 --json   # from inside the skill
```

The skill wraps `resolve.py` with structured JSON errors (`resolver_missing`, `resolver_timeout`, …) so agents can react instead of parsing tracebacks. `resolve.py` itself is not copied with the skill — the wrapper locates it via `--resolver PATH`, the `ARXIV_VENUE_RESOLVER` env var, or the repo path baked in at install time. Keep the repo on disk (or export `ARXIV_VENUE_RESOLVER`) after installing.

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
