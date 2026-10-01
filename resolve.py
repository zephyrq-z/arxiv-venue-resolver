#!/usr/bin/env python3
# arXiv 网址/ID → 发表在哪 + CCF 评级 + 链接 + BibTeX
# 用法: python3 resolve.py <arxiv网址或id>... [--json] [--meta-mode auto|local|remote] [--dblp on|off|only] [--no-cache]
# 依赖: 仅标准库。S2 API key 可选（env SemanticScholar_API_KEY 或 ~/.zshrc）。
# 模式:
#   --meta-mode auto   本地 sqlite (local.sqlite, 由 build_local.py 从 arXivSearcher 分片构建, 毫秒级) 命中即用,
#                      未命中(太新)回落 arXiv API。local = 只用本地(未命中报错), remote = 只用 arXiv API。
#   --dblp off         默认关。on = S2 未解析出 venue 时查 DBLP(本地 dblp.sqlite 或网络); only = 跳过 S2 只走 DBLP。
#   S2 结果缓存到 ~/.cache/arxiv-venue/<id>.json (含 resolved 标记), 重复解析 0 网络。
# 数据链路: meta(journal_ref/doi, 0请求) → comments 正则提取 "accepted at X" → S2 by-id →
#           S2 标题搜索 → (DBLP 兜底, 默认关) → 本地 ccf_v7.tsv 匹配
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CCF_TSV = os.path.join(HERE, "ccf_v7.tsv")
LOCAL_DB = os.path.join(HERE, "local.sqlite")
DBLP_DB = os.path.join(HERE, "dblp.sqlite")
CACHE_DIR = os.path.expanduser("~/.cache/arxiv-venue")

PREPRINT_VENUES = {"", "arxiv", "arxiv.org", "corr", "preprint", "ssrn"}

def _is_preprint_venue(v):
    """DBLP/S2 返回的 venue 字符串是否只是预印本镜像（CoRR = arXiv 镜像），非正式发表地。"""
    return (v or "").strip().lower() in PREPRINT_VENUES

# 少数官方名/S2 名与 CCF 目录名对不上的硬映射（norm 后的 venue → CCF abbr），遇到再加
ALIAS = {
    "advancesinneuralinformationprocessingsystems": "NeurIPS",
    # PACMSE / FSE 的各种写法（FSE 论文自 2024 起发表在该期刊包裹层里）
    "proceedingsoftheacmonsoftwareengineering": "FSE",
    "pacmse": "FSE", "pacmonsoftwareengineering": "FSE",
    "procacmsoftweng": "FSE", "pacmsoftweng": "FSE",
    "proceedingsoftheacmsoftweng": "FSE",
}

OPTS = {"meta_mode": "auto", "dblp": "off", "cache": True}

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

def s2_keys():
    keys = [os.environ.get(k) for k in
            ("SemanticScholar_API_KEY", "SemanticScholar_API_KEY2", "S2_API_KEY")]
    keys = [k for k in keys if k]
    if not keys and os.path.exists(z := os.path.expanduser("~/.zshrc")):
        txt = open(z, encoding="utf-8", errors="ignore").read()
        for k in ("SemanticScholar_API_KEY2", "SemanticScholar_API_KEY", "S2_API_KEY"):
            m = re.search(rf'export {k}=(["\']?)([A-Za-z0-9_-]+)\1', txt)
            if m:
                keys.append(m.group(2))
    return keys

def s2(path_and_params, _round=0):
    if _round > 1:   # 两个 key + 匿名共 3 轮尝试后仍 429 → 放弃
        raise RuntimeError("S2 API 持续 429")
    last = None
    attempts = s2_keys() + [None]
    for i, key in enumerate(attempts):
        req = urllib.request.Request(
            "https://api.semanticscholar.org/graph/v1" + path_and_params,
            headers={"User-Agent": "arxiv-venue-resolver/1.0"})
        if key:
            req.add_header("x-api-key", key)
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 403):
                # ponytail: 只轮换 key 不退避, 同 key 背靠背必撞限流 (S2 限 1 req/s/key)。
                # 同一 key 重试时指数退避; 全部尝试后仍 429 再睡 30s 整体重试一轮。
                wait = 2 ** i if key else 1.5
                time.sleep(wait)
                if i == len(attempts) - 1:
                    time.sleep(30)
                    return s2(path_and_params, _round + 1)
                continue
            raise
    sys.exit(f"S2 API 不可用（HTTP {last.code}）——需要 key 时设置 env SemanticScholar_API_KEY")

def cache_get(aid):
    if not OPTS["cache"]:
        return None
    p = os.path.join(CACHE_DIR, aid.replace("/", "_") + ".json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None

def cache_put(aid, obj):
    if not OPTS["cache"]:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    p = os.path.join(CACHE_DIR, aid.replace("/", "_") + ".json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)

_LOCAL_CONN = None

def local_meta(aid):
    """local.sqlite 查一篇；未命中返回 None。"""
    global _LOCAL_CONN
    if not os.path.exists(LOCAL_DB):
        if OPTS["meta_mode"] == "local":
            sys.exit(f"本地库不存在: {LOCAL_DB}（先跑 build_local.py）")
        return None
    if _LOCAL_CONN is None:
        import sqlite3
        _LOCAL_CONN = sqlite3.connect(f"file:{LOCAL_DB}?mode=ro", uri=True)
        _LOCAL_CONN.execute("PRAGMA mmap_size=268435456")
    row = _LOCAL_CONN.execute(
        "SELECT title, authors, year, categories, journal_ref, doi FROM papers WHERE arxiv_id=?",
        (aid,)).fetchone()
    if row is None:
        return None
    return {"id": aid, "title": row[0] or "",
            "authors": [a.strip() for a in (row[1] or "").split(",") if a.strip()],
            "year": str(row[2] or ""), "categories": (row[3] or "").split(),
            "journal_ref": row[4] or "", "doi": row[5] or "",
            "meta_source": "local sqlite"}

def parse_arxiv_id(s):
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([^/#?]+)", s)
    if m:
        s = m.group(1)
    s = re.sub(r"(?i)^arxiv:", "", s.strip())
    for pat in (r"^(\d{4}\.\d{4,5})(?:v\d+)?$", r"^([a-z\-]+/\d{7})(?:v\d+)?$"):
        m = re.match(pat, s)
        if m:
            return m.group(1)
    return None

def arxiv_meta(aid):
    xml = urllib.request.urlopen(
        f"https://export.arxiv.org/api/query?id_list={aid}", timeout=30).read()
    ns = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
    e = ET.fromstring(xml).find("a:entry", ns)
    if e is None:
        sys.exit(f"arXiv 查无此 id: {aid}")
    def t(tag, pfx="a"):
        el = e.find(f"{pfx}:{tag}", ns)
        return " ".join(el.text.split()) if el is not None and el.text else ""
    title = t("title")
    if not title or title.lower().startswith("error"):
        sys.exit(f"arXiv 查无此 id: {aid}")
    return {"id": aid, "title": title,
            "authors": [a.find("a:name", ns).text for a in e.findall("a:author", ns)],
            "year": t("published")[:4], "categories": e.find("a:category", ns).get("term").split(),
            "comments": t("comment", "ar"),
            "journal_ref": t("journal_ref", "ar"), "doi": t("doi", "ar"),
            "meta_source": "arXiv API"}

def get_meta(aid):
    """①本地 sqlite（毫秒级）②arXiv API。local 模式未命中即报错。"""
    if OPTS["meta_mode"] != "remote":
        m = local_meta(aid)
        if m is not None:
            return m
        if OPTS["meta_mode"] == "local":
            sys.exit(f"本地库未收录（可能是快照之后的新论文）: {aid}——用 --meta-mode auto 或 remote")
    return arxiv_meta(aid)

def load_ccf():
    rows = []
    with open(CCF_TSV, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 6:
                rows.append({"abbr": p[0], "name": p[1], "rank": p[2], "kind": p[3],
                             "area": p[4], "pub": p[5], "url": p[6] if len(p) > 6 else ""})
    return rows

def ccf_match(venue, rows, area_hint=None):
    v = norm(venue)
    if not v:
        return None
    want = ALIAS.get(v)
    cands = [r for r in rows
             if norm(r["abbr"]) == v or (want and r["abbr"].upper() == want.upper())]
    if cands:
        # 缩写撞名（FSE 既是加密会议又是软工顶会）：有领域提示就按领域筛，否则取 A 级优先
        if area_hint:
            for r in cands:
                if area_hint in r["area"]:
                    return r
        cands.sort(key=lambda r: (r["rank"] != "A", r["rank"] != "B"))
        return cands[0]
    for r in rows:                       # 全称包含（双向），太短的防误伤
        n = norm(r["name"])
        if len(v) >= 10 and (v in n or (len(n) >= 10 and n in v)):
            return r
    return None

def real_doi(d):
    return d if d and not d.startswith("10.48550/") else None  # 10.48550 是 arXiv 自有 DOI

def title_match(a, b):
    if len(a) < 15 or len(b) < 15:
        return False
    # 前缀/后缀匹配且长度相近（防 'Spectral properties of' 误配长标题）
    if a.startswith(b) or b.startswith(a) or a.endswith(b) or b.endswith(a):
        return min(len(a), len(b)) / max(len(a), len(b)) >= 0.6
    return False

CS_AREA_HINT = {  # arXiv 主分类 → CCF 领域名子串（消歧用，不覆盖就退回 A 级优先）
    # 值必须与 ccf_v7.tsv 的 area 列字面对齐（子串匹配），否则撞名消歧落空
    "cs.SE": "软件工程", "cs.PL": "软件工程", "cs.OS": "体系结构",
    "cs.AR": "体系结构", "cs.DC": "体系结构", "cs.NI": "计算机网络",
    "cs.CR": "网络与信息安全", "cs.DB": "数据库", "cs.DS": "理论", "cs.LG": "人工智能",
    "cs.AI": "人工智能", "cs.CL": "人工智能", "cs.CV": "人工智能",
    "cs.IR": "数据库", "cs.HC": "人机交互", "cs.MM": "图形学与多媒体", "cs.GR": "图形学与多媒体",
}

def _cs_hint(meta):
    cats = meta.get("categories") or []
    return next((v for k, v in CS_AREA_HINT.items() if k in cats), None)

# comments 自报接收信息提取（"Accepted at ASE 2026" / "accepted to CIKM 2026" / "to appear in X"）
# ponytail: 词序列贪婪匹配——逗号/句号断句, 长全称会议名能吃到但截到 80 字符; 罕见 "Proc. of X" 写法会截在 Proc, 由 S2/DBLP 兜底
COMMENTS_RE = re.compile(
    r"(?:(?:accepted|publish\w*)\s+(?:at|in|to|by|as)\s+|to\s+appear\s+(?:at|in)\s+)"
    r"(?:an?\s+)?(?:oral|spotlight|poster)?\s*"
    r"(?:the\s+)?[\w\-&']+(?:\s+[\w\-&']+){0,11}", re.I)

def comments_venue(meta):
    """从 comments 提取自报 venue 字符串（仅 remote meta 有 comments；本地库未存）。"""
    c = meta.get("comments") or ""
    if not c:
        return None, None
    m = COMMENTS_RE.search(c)
    if not m:
        return None, None
    v = m.group(0)
    v = re.sub(r"(?i)^(accepted|published|to\s+appear)\s+(at|in|to|by|as)\s*", "", v).strip(" .,")
    v = re.sub(r"(?i)^(an?\s+|the\s+)?(oral|spotlight|poster)\s*", "", v).strip(" .,")
    v = re.sub(r"\s+\d{4}$", "", v).strip(" .,")     # 尾部年份剥掉, "ASE 2026" → "ASE"
    v = re.sub(r"(?i)\s+vol\.?\s*\d+.*$", "", v).strip(" .,")  # "PACMSE Vol 2" → "PACMSE"
    if not v or v.lower() in PREPRINT_VENUES:
        return None, None
    return v[:80], "arXiv comments (author-claimed)"

_DBLP_CONN = None

def dblp_lookup(meta):
    """DBLP 兜底: 先查本地 dblp.sqlite（norm(title) 精确命中）, 无库走网络 API(可能撞 bot 防护)。
    返回 {venue,doi,key,local} 或 None。"""
    global _DBLP_CONN
    tn = norm(meta["title"])
    ty = int(meta["year"]) if str(meta["year"]).isdigit() else 0
    if os.path.exists(DBLP_DB):
        if _DBLP_CONN is None:
            import sqlite3
            _DBLP_CONN = sqlite3.connect(f"file:{DBLP_DB}?mode=ro", uri=True)
            _DBLP_CONN.execute("PRAGMA mmap_size=268435456")
        # ponytail: 全表线性扫 (norm(title) 无法建索引); 400ms/次本地够用, 慢了再加 title_norm 列+索引
        # CoRR = DBLP 对 arXiv 的镜像, 不是正式发表地; 跳过它继续扫能命中同标题的正式版本
        for t, v, y, d, k in _DBLP_CONN.execute(
                "SELECT title, venue, year, doi, key FROM papers"):
            if (not ty or abs((y or 0) - ty) <= 1) and title_match(tn, norm(t or "")) \
                    and not _is_preprint_venue(v):
                return {"venue": v, "doi": d, "key": k, "local": True}
        return None
    # 无本地库 → 网络 API
    q = urllib.parse.quote(meta["title"][:120])
    try:
        req = urllib.request.Request(
            f"https://dblp.org/search/publ/api?q={q}&format=json&h=10",
            headers={"User-Agent": "arxiv-venue-resolver/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        for h in d.get("result", {}).get("hits", {}).get("hit", []):
            i = h.get("info", {})
            if title_match(tn, norm(i.get("title") or "")) and not _is_preprint_venue(i.get("venue")):
                return {"venue": i.get("venue"), "doi": i.get("doi"),
                        "key": i.get("key"), "local": False}
    except Exception as e:
        print(f"  [DBLP 网络查询失败: {e}]", file=sys.stderr)
    return None

# S2 查询的网络步（by-id → 标题搜索），独立成函数便于缓存整个结果
def resolve_s2(aid, meta):
    p = s2(f"/paper/arXiv:{aid}?fields=title,year,venue,publicationVenue,externalIds,citationStyles,paperId")
    doi = real_doi((p.get("externalIds") or {}).get("DOI"))
    bibtex, year = (p.get("citationStyles") or {}).get("bibtex"), p.get("year")
    s2_link = f"https://www.semanticscholar.org/paper/{p.get('paperId')}" if p.get("paperId") else None
    v = p.get("venue") or ""
    if v and not _is_preprint_venue(v):   # ② S2 已合并出正式 venue
        return {"resolved": True, "venue": v, "vtype": (p.get("publicationVenue") or {}).get("type"),
                "source": "Semantic Scholar", "doi": doi, "bibtex": bibtex,
                "year": year, "s2_link": s2_link}
    # ③ S2 没标 → 按标题搜已发表版本
    q = urllib.parse.quote(meta["title"])
    d = s2(f"/paper/search?query={q}&fields=title,year,venue,publicationVenue,externalIds,paperId&limit=20")
    tn, ty = norm(meta["title"]), int(meta["year"])
    for c in d.get("data") or []:
        cv, cy = c.get("venue") or "", int(c.get("year") or 0)
        if not cv or _is_preprint_venue(cv) or cy < ty:
            continue
        if not title_match(tn, norm(c.get("title") or "")):
            continue
        return {"resolved": True, "venue": cv, "vtype": (c.get("publicationVenue") or {}).get("type"),
                "source": "Semantic Scholar (title match)",
                "doi": real_doi((c.get("externalIds") or {}).get("DOI")) or doi,
                "bibtex": bibtex, "year": year, "s2_link":
                f"https://www.semanticscholar.org/paper/{c.get('paperId')}" if c.get("paperId") else s2_link}
    return {"resolved": False, "venue": None, "vtype": None, "source": None,
            "doi": doi, "bibtex": bibtex, "year": year, "s2_link": s2_link}

def resolve(aid, rows):
    meta = get_meta(aid)
    out = {"arxiv_id": aid, "title": meta["title"], "authors": meta["authors"],
           "preprint_year": meta["year"], "meta_source": meta.get("meta_source"),
           "venue": None, "venue_source": None,
           "venue_type": None, "doi": None, "ccf": None, "link": None, "bibtex": None}
    venue, vtype, source, doi, bibtex, year = None, None, None, real_doi(meta["doi"]), None, meta["year"]

    if meta["journal_ref"]:              # ① 作者自报 journal_ref，零额外请求
        venue, source = meta["journal_ref"], "arXiv metadata (journal_ref)"
    else:
        cv, cs = comments_venue(meta)    # ①' comments 自报接收（作者声称，非权威）
        if cv:
            venue, source = cv, cs
        else:
            s2c = cache_get(aid)         # S2 结果缓存（resolved=True 表示确认未发表）
            if s2c is None:
                if OPTS["dblp"] == "only":            # d 开关: 只走 DBLP, 跳过 S2
                    s2c = {"resolved": False, "venue": None, "vtype": None, "source": None,
                           "doi": None, "bibtex": None, "year": None, "s2_link": None, "dblp_only": True}
                else:
                    s2c = resolve_s2(aid, meta)       # ② by-id + ③ 标题搜索，网络步
                    cache_put(aid, s2c)
            if s2c["resolved"]:
                venue, vtype, source = s2c["venue"], s2c["vtype"], s2c["source"]
            elif OPTS["dblp"] == "on" or s2c.get("dblp_only"):   # d 开关: S2 未命中 → DBLP
                dv = dblp_lookup(meta)
                if dv:
                    venue, vtype, source = dv["venue"], "conference", "DBLP (local)" if dv.get("local") else "DBLP"
                    doi = dv.get("doi") or doi
                    s2_link = f"https://dblp.org/rec/{dv['key']}.html" if dv.get("key") else None
            doi = s2c.get("doi") or doi
            bibtex, year = s2c.get("bibtex"), s2c.get("year") or year
            s2_link = s2c.get("s2_link") if not venue else (s2_link if 's2_link' in dir() else s2c.get("s2_link"))

    out.update({"venue": venue, "venue_source": source, "venue_type": vtype, "doi": doi})
    hint = _cs_hint(meta)  # arXiv 分类 → CCF 领域提示，缩写撞名（FSE 双义）时消歧
    out["ccf"] = (lambda r: r and {"abbr": r["abbr"], "rank": r["rank"], "kind": r["kind"], "area": r["area"]})(ccf_match(venue, rows, hint)) if venue else None
    if doi:
        out["link"] = f"https://doi.org/{doi}"
    elif venue and "s2_link" in dir():
        out["link"] = s2_link
    else:
        out["link"] = f"https://arxiv.org/abs/{aid}"

    # BibTeX: S2 现成的优先；它还是 arXiv preprint 形态而我们已经解析出 venue 时才自己拼
    if venue and bibtex and re.search(
            r"arxiv\s*preprint|eprint|journal\s*=\s*\{?\s*arxiv|volume\s*=\s*\{?\s*abs/",
            bibtex, re.I):
        bibtex = None  # S2 给的还是预印本形态，我们已经知道真 venue，自己拼
    if not bibtex:
        key = (meta["authors"][0].split()[-1] if meta["authors"] else "anon") \
              + re.sub(r"\D", "", str(year)) + re.sub(r"\W+", "", meta["title"].split()[0].lower())
        if venue and (vtype == "journal" or (vtype is None and out["ccf"] and out["ccf"]["kind"] == "期刊")):
            typ, body = "article", f"journal = {{{venue}}}"
        elif venue:
            typ, body = "inproceedings", f"booktitle = {{{venue}}}"
        else:
            typ, body = "misc", f"eprint = {{{aid}}},\n  archiveprefix = {{arXiv}}"
        lines = [f"@{typ}{{{key},", f"  title = {{{meta['title']}}},",
                 f"  author = {{{' and '.join(meta['authors'])}}},"]
        if venue:
            lines.append(f"  {body},")
        else:
            lines.append(f"  {body},")
        lines += [f"  year = {{{year}}},"] + ([f"  doi = {{{doi}}},"] if doi else [])
        lines.append(f"  note = {{arXiv:{aid}}}")
        bibtex = "\n".join(lines) + "\n}"
    out["bibtex"] = bibtex
    return out

def show(o):
    print(f"arXiv:{o['arxiv_id']}  {o['title']}")
    print(f"  作者: {', '.join(o['authors'][:6])}{' 等' if len(o['authors']) > 6 else ''}")
    if o["venue"]:
        print(f"  发表: {o['venue']}  [{o['venue_source']}]")
    else:
        print("  发表: 未检出（大概率仍是预印本，或未被 S2/DBLP 收录）")
    if o["ccf"]:
        c = o["ccf"]
        print(f"  CCF : {c['abbr']} · {c['rank']} · {c['kind']} · {c['area']}")
    elif o["venue"]:
        print("  CCF : 目录内无匹配")
    print(f"  链接: {o['link']}")
    print("  BibTeX:")
    for line in o["bibtex"].splitlines():
        print(f"    {line}")
    print()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="arXiv 网址或 id")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--meta-mode", choices=["auto", "local", "remote"], default="auto")
    ap.add_argument("--dblp", choices=["off", "on", "only"], default="off")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()
    OPTS.update(meta_mode=args.meta_mode, dblp=args.dblp, cache=not args.no_cache)
    ids = [parse_arxiv_id(a) for a in args.ids]
    bad = [a for a, i in zip(args.ids, ids) if i is None]
    if bad:
        sys.exit(f"无法解析为 arXiv id: {bad}")
    if not ids:
        sys.exit(f"用法: {sys.argv[0]} <arxiv网址或id>... [--json] [--meta-mode auto|local|remote] [--dblp off|on|only]")
    rows = load_ccf()
    results = [resolve(i, rows) for i in ids]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for o in results:
            show(o)

if __name__ == "__main__":
    main()
