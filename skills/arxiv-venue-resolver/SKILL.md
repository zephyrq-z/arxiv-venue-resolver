---
name: arxiv-venue-resolver
description: Resolve where an arXiv preprint was formally published — the venue (conference/journal), its CCF rank (A/B/C), DOI link, and BibTeX. Use when the agent needs to know if an arXiv paper is accepted at a conference or journal, what CCF level that venue is, or needs a citation entry. Works offline for journal_ref matches; falls back to Semantic Scholar / DBLP.
---

# arXiv Venue Resolver

## When to Use

- The user asks where an arXiv paper was published / accepted ("这篇发在哪", "accepted at which conference").
- The user asks for the CCF rank of a paper's venue (CCF 分级/等级).
- A citation / BibTeX entry is needed for an arXiv preprint.
- You have a list of arXiv IDs from a search and need to enrich them with venue + CCF info.

## Quick Start

Run the bundled script (it locates `resolve.py` next to the installed skill, or via `--resolver`):

```bash
python3 scripts/resolve_venue.py 2407.01489
python3 scripts/resolve_venue.py https://arxiv.org/abs/1706.03762 --json
```

No service needs to be running. The resolver works in layers:

1. `journal_ref` from local metadata (0 network, author-claimed)
2. arXiv `comments` "Accepted at X" (0 network, author-claimed)
3. Semantic Scholar (authoritative, cached in `~/.cache/arxiv-venue/`)
4. DBLP fallback (`--dblp on` or `--dblp only`)
5. CCF matching: PACM journal wrappers (PACMSE) are disambiguated to the inner conference via the Crossref `issue` field ("FSE"/"ISSTA", cached per DOI); the PACMSE→FSE alias only fires as fallback when that misses

## Output Fields

JSON output (one object per ID) — use these when answering:

- `venue` / `venue_source` / `venue_type`: where published and the evidence chain
- `ccf`: `{abbr, rank, kind, area}` from the CCF catalog, `null` if no match
- `doi` / `link`: DOI link preferred, else paper page
- `bibtex`: ready to paste (`@article` / `@inproceedings` / `@misc` for pure preprints)

## Options

- `--json`: structured output (recommended for agents)
- `--dblp on|only`: DBLP fallback for papers S2 hasn't merged yet
- `--meta-mode auto|local|remote`: local sqlite only, arXiv API only, or auto
- `--no-cache`: bypass `~/.cache/arxiv-venue`
- `--resolver PATH`: explicit path to `resolve.py` (defaults to the copy shipped with this skill)
- Multiple IDs accepted in one invocation; results come back in order

## Interpretation Notes

- `venue_source` ending in `(journal_ref)` or `(author-claimed)` = author-claimed, not verified; Semantic Scholar / DBLP sources are authoritative.
- `venue: null` = no formal publication found (likely still a preprint). Negative S2 results are cached, so re-checking is free.
- `ccf: null` with a non-null `venue` = venue exists but is not in the CCF catalog (could be a workshop, a non-CS venue, or a journal the catalog doesn't cover).
- CCF rank collisions (e.g. FSE is both a crypto B-conference and the software-engineering A-conference) are disambiguated by the paper's arXiv category.
- DBLP `CoRR` results are the arXiv mirror and are treated as *not published*.
- **S2 429 是常态不是故障**：限流 ~1 req/s/key；resolve.py 已内置 key 轮换+指数退避+30s 整轮重试（2026-10 加固），网络解析偶尔慢到 ~40s 是退避在等，不是卡死。仍失败时等 60s 重跑，结果落盘缓存后复查零网络。
- **venue=null 时 bibtex 可能带 `@Inproceedings/@Article` 头**：那是 S2 标题搜索为「另一篇同题已发表文章」返回的 citationStyles，不是本篇已发表的证据——判断发表与否只看 `venue`/`venue_source` 字段。
- OpenAlex 按预印本 DOI 查到的是独立 preprint 记录（venue=arXiv，标题都可能错）——**解析正式 venue 禁用 OpenAlex**。
- 「ccf=null 但 venue 非空」可能是数据事实：先确认该会议真在 CCF 第七版目录里（如 ISIT 就不在，2501.12548 实测）。
- Rebuild `dblp.sqlite`（`build_dblp.py`）时 XML 用 HTML 命名实体（`&uuml;`）：只替换完整 `&name;` 形式（裸子串 replace 会炸 publ**type**/ti**tle**）；产物必须 `ord()` 转码点；流式块边界截断实体名时留 tail 拼下一块。
- 迁移/复制 sqlite 后首开可能报 unable to open（WAL 残留）——重跑一次即恢复。
- **PACMSE（《Proc. ACM Softw. Eng.》）是期刊包裹层**：FSE（2024 起）和 ISSTA（2025 起）的论文都发表在里面，venue 字符串本身分不清是哪个会——resolver 按 DOI 查 Crossref 的 `issue` 字段（缓存为 `xref-*.json`）解出内层会议，venue 仍显示期刊名（BibTeX 按 @article/PACMSE 才是 ACM 官方引用形态）；issue 查不到时才回落 ALIAS 标 FSE。
- **本地 sqlite（分片构建）不含 comments**：auto 模式下对 journal_ref/comments 双空的本地命中会自动补一次 arXiv API，并把 comments/journal_ref/doi 回写库内（懒回填）——同一篇第二次解析恢复零网络。

## Examples

- `python3 scripts/resolve_venue.py 2407.01489 --json` — PACMSE paper, resolves to FSE · A
- `python3 scripts/resolve_venue.py 2502.06193 --json` — ISSTA 2025 paper published in PACMSE: CCF shows **ISSTA · A**（Crossref issue 消歧，不再错标 FSE）
- `python3 scripts/resolve_venue.py 2501.12548 0704.0001 --json` — batch resolve
- `python3 scripts/resolve_venue.py 2502.18273 --dblp on --json` — force DBLP fallback for a fresh paper
- If the script reports `resolver_missing`, point `--resolver` at a checkout of the arxiv-venue-resolver repo.


## Resolver Location

`resolve.py` is never bundled with the skill. The wrapper finds it, in order:
`--resolver PATH` → `ARXIV_VENUE_RESOLVER` env → baked install-time path (direct install) → `ARXIV_VENUE_RESOLVER_SKM` env (skills-manager install). If the script reports `resolver_missing`, one of those must be provided.