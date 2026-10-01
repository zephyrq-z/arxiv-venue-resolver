#!/usr/bin/env python3
# arxiv-venue-resolver skill 脚本: 定位 resolve.py, 转发参数, 输出结构化 JSON.
# resolve.py 定位顺序: --resolver 参数 > ARXIV_VENUE_RESOLVER 环境变量 > 安装时仓库位置
# 解析器不可用时输出结构化 JSON 错误, 便于 agent 决策.
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 仓库内: skills/arxiv-venue-resolver/scripts/ → 3 层回溯到仓库根;
# 复制安装到 <agent-skills>/ 后 3 层回溯是 skills 目录之外, 仓库不在该处 → 依赖 --resolver/env
DEFAULT_RESOLVER = os.path.normpath(os.path.join(HERE, "..", "..", "..", "resolve.py"))

# install_skills.py 复制安装时会在此行下方烧录本仓库根路径 (BAKED_REPO_PATH)


def find_resolver(explicit: str | None) -> str:
    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("ARXIV_VENUE_RESOLVER")
    if env:
        candidates.append(env)
    candidates.append(DEFAULT_RESOLVER)  # 仓库内运行时 3 层回溯到仓库根
    baked = globals().get("BAKED_REPO_PATH")  # install_skills.py 烧录的安装时仓库位置
    if baked:
        candidates.append(baked)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return ""






def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve arXiv paper venues with CCF ranks (wraps resolve.py).")
    parser.add_argument("ids", nargs="*", help="arXiv URLs or IDs.")
    parser.add_argument("--resolver", default=None,
                        help="Path to resolve.py (default: copy shipped with this skill).")
    parser.add_argument("--json", action="store_true",
                        help="Structured JSON output (recommended for agents).")
    parser.add_argument("--dblp", choices=["off", "on", "only"], default="off")
    parser.add_argument("--meta-mode", choices=["auto", "local", "remote"], default="auto")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Per-invocation subprocess timeout in seconds.")
    args, passthrough = parser.parse_known_args()

    resolver = find_resolver(args.resolver)
    if not resolver:
        print(json.dumps({
            "error": "resolver_missing",
            "detail": f"resolve.py not found at {DEFAULT_RESOLVER}",
            "hint": "Clone the arxiv-venue-resolver repo next to the skill, or pass --resolver /path/to/resolve.py.",
        }), file=sys.stderr)
        return 2

    if not args.ids:
        print(json.dumps({
            "error": "no_ids",
            "hint": "Pass one or more arXiv URLs or IDs, e.g. 2407.01489.",
        }), file=sys.stderr)
        return 2

    cmd = [sys.executable, resolver] + args.ids
    if args.json:
        cmd.append("--json")
    if args.dblp != "off":
        cmd += ["--dblp", args.dblp]
    if args.meta_mode != "auto":
        cmd += ["--meta-mode", args.meta_mode]
    if args.no_cache:
        cmd.append("--no-cache")
    cmd += passthrough

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(json.dumps({
            "error": "resolver_timeout",
            "timeout_seconds": args.timeout,
            "hint": "DBLP local lookups scan 8.4M rows (~1-9s per paper); raise --timeout for large batches.",
        }), file=sys.stderr)
        return 2

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
