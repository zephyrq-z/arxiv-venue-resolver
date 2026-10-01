#!/usr/bin/env python3
# 安装 skills/arxiv-venue-resolver 到本机 agent 的 skills 目录 (Codex / Claude Code / Hermes).
# 复制安装 (非软链): 安装后与仓库副本解耦, 仓库可移动/删除.
# resolve.py 不随 skill 安装 — skill 脚本运行时定位: --resolver > ARXIV_VENUE_RESOLVER 环境变量 > 常见仓库位置.
# 用法: python3 install_skills.py [--dest DIR ...] [--link]
#   无 --dest: 自动探测 ~/.codex/skills, ~/.claude/skills, ~/.hermes/skills (存在才装)
#   --link: 用符号链接代替复制 (开发时改仓库即刻生效)
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_SRC = os.path.join(HERE, "skills", "arxiv-venue-resolver")
SKILL_NAME = "arxiv-venue-resolver"

# 自动探测顺序; 只装到已存在的目录 (存在即视为该 agent 在用)
AUTO_DESTS = [
    ("Codex", os.path.expanduser("~/.codex/skills")),
    ("Claude Code", os.path.expanduser("~/.claude/skills")),
    ("Hermes", os.path.expanduser("~/.hermes/skills")),
]

# resolve.py 不随 skill 复制; skill 脚本运行时定位顺序: --resolver > 环境变量 > 安装时仓库位置(相对回溯)
RESOLVER_HINT = (
    "Note: resolve.py (and the sqlite databases) are NOT copied with the skill.\n"
    "The skill script locates resolve.py at runtime, in this order:\n"
    "  1. --resolver /path/to/resolve.py argument\n"
    "  2. ARXIV_VENUE_RESOLVER environment variable\n"
    "  3. this repo's location (works while the repo stays where it is)\n"
    "Keep this repo on disk, or set ARXIV_VENUE_RESOLVER in your shell profile,\n"
    "after installing the skill."
)


def install(dest: str, link: bool) -> bool:
    target = os.path.join(dest, SKILL_NAME)
    if not os.path.isdir(dest):
        return False
    # 覆盖旧版本
    if os.path.islink(target):
        os.remove(target)
    elif os.path.isdir(target):
        shutil.rmtree(target)
    if link:
        os.symlink(SKILL_SRC, target)
        print(f"  linked  {target} -> {SKILL_SRC}")
    else:
        shutil.copytree(SKILL_SRC, target)
        _bake_repo_path(target)
        print(f"  copied  {SKILL_SRC} -> {target}")
    return True


def _bake_repo_path(target: str) -> None:
    """把安装时的仓库根位置烧录进 skill 副本, 仓库未移动前副本开箱即用."""
    script = os.path.join(target, "scripts", "resolve_venue.py")
    if not os.path.isfile(script):
        return
    with open(script, encoding="utf-8") as f:
        text = f.read()
    marker = "# BAKED_REPO_PATH"          # 模板里的占位注释行
    baked = f'BAKED_REPO_PATH = {os.path.join(HERE, "resolve.py")!r}'  # 烧录成实赋值
    if marker in text:
        import re
        text = re.sub(rf"^{marker} = .*$", baked, text, flags=re.M)
    else:
        text = text.replace("def find_resolver(",
                            baked + "\n\ndef find_resolver(", 1)
    with open(script, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the arxiv-venue-resolver skill for local agents.")
    ap.add_argument("--dest", action="append", default=[],
                    help="Explicit skills directory (repeatable). Default: auto-detect.")
    ap.add_argument("--link", action="store_true",
                    help="Symlink instead of copy (dev mode; edits to the repo apply instantly).")
    args = ap.parse_args()

    if not os.path.isfile(os.path.join(SKILL_SRC, "SKILL.md")):
        sys.exit(f"skill source missing: {SKILL_SRC}")

    installed = []
    if args.dest:
        for dest in args.dest:
            os.makedirs(dest, exist_ok=True)
            if install(dest, args.link):
                installed.append(dest)
    else:
        for _, dest in AUTO_DESTS:
            if install(dest, args.link):
                installed.append(dest)

    if not installed:
        print("No agent skills directory found. Pass one explicitly, e.g.:")
        print("  python3 install_skills.py --dest ~/.codex/skills")
        return 1

    print()
    print(RESOLVER_HINT)
    print(f"Done: installed to {len(installed)} location(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
