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

## Examples

- `python3 scripts/resolve_venue.py 2407.01489 --json` — PACMSE paper, resolves to FSE · A
- `python3 scripts/resolve_venue.py 2501.12548 0704.0001 --json` — batch resolve
- `python3 scripts/resolve_venue.py 2502.18273 --dblp on --json` — force DBLP fallback for a fresh paper
- If the script reports `resolver_missing`, point `--resolver` at a checkout of the arxiv-venue-resolver repo.


## Resolver Location

`resolve.py` is never bundled with the skill. The wrapper finds it, in order:
`--resolver PATH` → `ARXIV_VENUE_RESOLVER` env → baked install-time path (direct install) → `ARXIV_VENUE_RESOLVER_SKM` env (skills-manager install). If the script reports `resolver_missing`, one of those must be provided.