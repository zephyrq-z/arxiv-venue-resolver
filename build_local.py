#!/usr/bin/env python3
# 从 arXivSearcher 的 embedding shard meta.jsonl 构建本地元数据库 local.sqlite
# 只存 resolver 需要的字段（不存 abstract，省 2/3 体积）。同 arxiv_id 后写覆盖前写，
# 但 comments/journal_ref/doi 里已回填的非空值不被分片里的空值冲掉（分片源不含 comments，
# resolve.py 懒回填会往库里写）。
# 用法: python3 build_local.py   （重复跑安全，幂等）
import glob, json, os, sqlite3, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "local.sqlite")

# 顺序 = 旧 → 新，后写的赢（增量批次覆盖全量里的同 id 旧记录）
SHARD_DIRS = [
    "/Users/zzq/Developer/paperSearcher/arXivSearcher/data/embedding_shards_full",
    "/Users/zzq/Developer/paperSearcher/arXivSearcher/data/embedding_shards_inc2",
    "/Users/zzq/Developer/paperSearcher/arXivSearcher/data/embedding_shards_inc3",
    "/Users/zzq/Developer/paperSearcher/arXivSearcher/data/embedding_shards_inc.20260802",
]

# 回填值优先：excluded 为空时保留库里已有值
UPSERT = """INSERT INTO papers (arxiv_id,title,authors,year,categories,journal_ref,doi,comments)
VALUES (?,?,?,?,?,?,?,?)
ON CONFLICT(arxiv_id) DO UPDATE SET
  title=excluded.title, authors=excluded.authors, year=excluded.year, categories=excluded.categories,
  journal_ref=COALESCE(NULLIF(excluded.journal_ref,''), papers.journal_ref),
  doi=COALESCE(NULLIF(excluded.doi,''), papers.doi),
  comments=COALESCE(NULLIF(excluded.comments,''), papers.comments)"""

def main():
    t0 = time.time()
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS papers (
        arxiv_id TEXT PRIMARY KEY, title TEXT, authors TEXT, year INT,
        categories TEXT, journal_ref TEXT, doi TEXT, comments TEXT)""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(papers)")}
    if "comments" not in cols:   # 旧库迁移（resolve.py 懒回填写的列）
        conn.execute("ALTER TABLE papers ADD COLUMN comments TEXT")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    n = 0
    for d in SHARD_DIRS:
        files = sorted(glob.glob(os.path.join(d, "*.meta.jsonl")))
        if not files:
            print(f"跳过（无分片）: {d}")
            continue
        for f in files:
            batch = []
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    batch.append((r.get("arxiv_id"), r.get("title"),
                                  r.get("authors"), r.get("published_year"),
                                  r.get("primary_category"), r.get("journal_ref"),
                                  r.get("doi"), r.get("comments")))
                    if len(batch) >= 10000:
                        conn.executemany(UPSERT, batch)
                        n += len(batch); batch = []
            if batch:
                conn.executemany(UPSERT, batch)
                n += len(batch)
        print(f"{d}: 累计 {n} 行, {time.time()-t0:.0f}s")
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    j = conn.execute("SELECT COUNT(*) FROM papers WHERE journal_ref IS NOT NULL AND journal_ref != ''").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM papers WHERE comments IS NOT NULL AND comments != ''").fetchone()[0]
    conn.close()
    print(f"完成: {cnt} 篇 (journal_ref 非空 {j}, {j/max(cnt,1):.1%}; comments 非空 {c}, {c/max(cnt,1):.1%}), "
          f"耗时 {time.time()-t0:.0f}s, 库 {DB}")

if __name__ == "__main__":
    main()
