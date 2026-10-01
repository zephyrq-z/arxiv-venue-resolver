#!/usr/bin/env python3
# 下载 DBLP 全量 XML (dblp.xml.gz, ~700MB) 构建本地 dblp.sqlite
# 保留 article/proceedings article 的 journal + inproceedings 的 conference 名 + doi + key
# 流式解析, 峰值内存 ~1GB; 64G 机器毫无压力。重复跑安全。
# 用法: python3 build_dblp.py  （完成后 dblp.sqlite 与 resolve.py 同目录即自动启用 --dblp on/only）
import gzip, os, re, sqlite3, sys, time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "dblp.sqlite")
XML = os.path.join(HERE, "dblp.xml")
URL = "https://dblp.org/xml/dblp.xml.gz"
DTD = "https://dblp.org/xml/dblp.dtd"

def main():
    # 1) 下载（已存在则跳过）
    gz = XML + ".gz"
    if not os.path.exists(XML):
        if not os.path.exists(gz):
            print(f"下载 {URL} ...")
            os.system(f'curl -L --retry 3 -o "{gz}" "{URL}"')
        print("解压 ...")
        os.system(f'gunzip -kf "{gz}"')
    size = os.path.getsize(XML) / 1e9
    print(f"dblp.xml {size:.2f} GB, 开始解析入库 ...")

    # 2) 建库（覆盖重建）
    for p in (DB, DB + "-wal", DB + "-shm"):
        if os.path.exists(p):
            os.remove(p)
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("""CREATE TABLE papers (
        key TEXT PRIMARY KEY, title TEXT, venue TEXT, year INT, doi TEXT, type TEXT)""")
    conn.execute("PRAGMA mmap_size=536870912")

    # 3) 流式解析（DBLP XML 用 HTML 命名实体 &uuml; 等, 替换成数字实体; 只动 &xxx; 形式）
    n, t0 = 0, time.time()
    batch = []
    import html.entities
    # ponytail: 只替换 &name; 完整实体, 裸子串替换会炸掉 publtype/title 里的 lt/gt
    ENT_RE = re.compile(
        b"&(" + b"|".join(
            k.encode() for k in html.entities.html5 if not k.endswith(";")
            if k.encode() not in (b"lt", b"gt", b"amp", b"quot", b"apos")) + b");")

    def fix_chunk(data: bytes) -> bytes:
        return ENT_RE.sub(
            lambda m: f"&#{ord(html.entities.html5[m.group(1).decode()])};".encode(), data)

    # 带小缓冲的流: expat 每次拉 16KB; 实体名被边界切断时留尾巴到下一块
    class EntityFix:
        def __init__(self, path):
            self.f = open(path, "rb")
            self.tail = b""
        def read(self, size=-1):
            chunk = self.f.read(65536)
            if not chunk and not self.tail:
                return b""
            data = self.tail + chunk
            # 尾部若截断在实体名中间, 留到下次
            cut = len(data)
            m = data.rfind(b"&")
            if m != -1 and b";" not in data[m:]:
                cut = m
            out, self.tail = data[:cut], data[cut:]
            return fix_chunk(out)

    for ev, el in ET.iterparse(EntityFix(XML), events=("end",)):
        if el.tag not in ("article", "inproceedings"):
            continue
        venue = el.findtext("journal") or el.findtext("booktitle") or ""
        year = el.findtext("year") or ""
        doi_el = el.find("ee")
        doi = (doi_el.text if doi_el is not None and doi_el.text and
               doi_el.text.startswith("10.") else None)
        title = " ".join((el.findtext("title") or "").split())
        if venue and title and year.isdigit():
            batch.append((el.get("key"), title, venue, int(year), doi,
                          "journal" if el.tag == "article" else "conf"))
            if len(batch) >= 20000:
                conn.executemany("INSERT OR REPLACE INTO papers VALUES (?,?,?,?,?,?)", batch)
                n += len(batch); batch = []
                if n % 500000 == 0:
                    print(f"  {n} 行, {time.time()-t0:.0f}s")
        el.clear()
    if batch:
        conn.executemany("INSERT OR REPLACE INTO papers VALUES (?,?,?,?,?,?)", batch)
        n += len(batch)
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    conn.close()
    print(f"完成: {cnt} 行 (写入 {n}), 耗时 {time.time()-t0:.0f}s, 库 {DB}")
    # 清理 3GB 原始 XML（可再下载）
    if os.path.exists(gz):
        os.remove(gz)
        print(f"已删除压缩包 {gz}（保留解压后 XML 便于重跑; 要省 3GB 磁盘可再删 {XML}）")

if __name__ == "__main__":
    main()
