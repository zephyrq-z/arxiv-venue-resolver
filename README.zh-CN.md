# arxiv-venue-resolver

[English](README.md)

输入一个 arXiv 网址或 ID，回答「这篇预印本**正式发表在哪**」：会议/期刊名、CCF 分级、DOI 链接、可直接粘贴的 BibTeX。纯标准库实现，单文件 CLI。

```text
$ python3 resolve.py https://arxiv.org/abs/2407.01489
arXiv:2407.01489  Agentless: Demystifying LLM-based Software Engineering Agents
  发表: Proc. ACM Softw. Eng.  [Semantic Scholar (title match)]
  CCF : FSE · A · 会议 · 软件工程/系统软件/程序设计语言
  链接: https://doi.org/10.1145/3715754
  BibTeX:
    @inproceedings{Xia2024agentless, ...}
```

## 为什么需要它

arXiv 元数据只告诉你论文**存在**，不告诉你它**落在哪里**。作者填 `journal_ref` 不及时也不完整（CS 论文约 11% 覆盖率），arXiv 的 `comments` 字段把 "Accepted at FSE 2026" 埋在自由文本里，而 CCF 分级——国内计算机学术评价的事实标准——还需要把一堆别名形式（PACMSE → FSE、NeurIPS 各种长名）映射到官方目录上。

本工具按成本从低到高串起所有证据源，命中即停：

```
① local.sqlite journal_ref      (零网络, 作者自报)
①' arXiv comments "accepted at" (零网络, 作者自报)
② Semantic Scholar by-id         (权威, 带缓存)
③ S2 标题搜索                    (查太新的论文)
④ DBLP 本地 sqlite / 网络 API    (兜底, --dblp on|only)
⑤ CCF 目录匹配                   (缩写 / 别名 / 全称, 撞名消歧)
```

S2 结果缓存在 `~/.cache/arxiv-venue/<id>.json`，含 `resolved:false` 负缓存标记——一旦确认未发表，复查零网络成本。

## 前置依赖与伴生项目

设计上可独立运行——`resolve.py` 零配置即可用（回落到 arXiv API + Semantic Scholar + DBLP 网络 API）。两个可选的本地数据库让它又快又离线，第一个的数据来自伴生项目：

| 组件 | 提供什么 | 缺失时 |
|---|---|---|
| [arXivSearcher](https://github.com/aiopsplus/arXivSearcher)（伴生项目；仓库私有——DevOps+ Lab AIOps Team 成员可访问） | arXiv 元数据 embedding 分片（`data/embedding_shards_*/shard_*.meta.jsonl`）；`build_local.py` 读取后生成 `local.sqlite` | 论文元数据回落 arXiv API（每个未知 ID 一次请求） |
| `local.sqlite`（可选，本地构建） | 314 万篇论文元数据：journal_ref / DOI / 分类，毫秒级、零网络 | 失去零请求层（①） |
| `dblp.sqlite`（可选，本地构建） | 843 万条 DBLP 官方收录记录，权威发表索引 | `--dblp` 回落 DBLP 网络 API（可能撞 bot 防护） |

两个项目互补：**arXivSearcher 负责「找出哪些论文相关」**（BM25 + 向量混合检索 300 万预印本）；**本工具负责「每篇预印本正式发在哪」**（venue + CCF 分级 + BibTeX）。典型流程：用 arXivSearcher 检索 → 把得到的 arXiv ID 喂给本工具。

## 安装

```bash
# 可选但推荐：本地 arXiv 元数据（314 万篇，毫秒级查询）
# 需要 arXivSearcher 的 embedding 分片；先改 build_local.py 里的 SHARD_DIRS
python3 build_local.py

# 可选：本地 DBLP 索引（843 万条，让 --dblp 不用联网）
python3 build_dblp.py     # 下载约 700MB XML，构建 1.4GB sqlite

# 零配置：全部回落 arXiv API + S2 + DBLP 网络 API
```

零依赖。Python 3.9+（仅标准库）。S2 API key 可选（环境变量 `SemanticScholar_API_KEY`，或自动读 `~/.zshrc`）——没有 key 就与公共限流共享额度。

## 用法

```bash
python3 resolve.py <arxiv网址或id>... [选项]

  --json                 结构化输出
  --meta-mode auto|local|remote   local = 只用本地库; remote = 只用 arXiv API
  --dblp off|on|only     DBLP 兜底 (on) 或唯一来源 (only)
  --no-cache             绕过 ~/.cache/arxiv-venue
```

一次调用传多个 ID 时共享 CCF 目录加载与数据库连接。

## Agent Skill（Codex / Claude Code / Hermes）

把本工具直接交给你的 agent 用，skill 已内置，两种安装路径：

### 方式 A — 通过 [skills-manager](https://github.com/xingkongliang/skills-manager) 安装（已在用则推荐）

[Skills Manager](https://skillsmanager.dev) 是桌面应用 + CLI，统一管理中央 skill 库（`~/.skills-manager`）并可部署到 50+ 个 coding agent，保留来源元数据、preset 和更新追踪。如果你的机器已经用它管理 skills，装进中央库而不是手工复制：

```bash
SM=~/.skills-manager/bin/skills-manager-cli
"$SM" skills install /path/to/arxiv-venue-resolver/skills/arxiv-venue-resolver   # 本地 clone
# 或从 GitHub:
"$SM" skills install https://github.com/zephyrq-z/arxiv-venue-resolver/tree/main/skills/arxiv-venue-resolver
"$SM" skills deploy arxiv-venue-resolver --agent claude_code --agent codex --agent hermes
```

`skills deploy` 从中央库复制到各 agent 的 skills 目录，agent 即可看到 `arxiv-venue-resolver` skill。部署副本没有烧录的仓库路径（复制由 Skills Manager 完成，不经 `install_skills.py`），需要设一个环境变量让包装脚本找到 `resolve.py`：

```bash
export ARXIV_VENUE_RESOLVER_SKM=/path/to/arxiv-venue-resolver/resolve.py
```

### 方式 B — 直接安装

```bash
python3 install_skills.py
```

自动探测并安装到 `~/.codex/skills`、`~/.claude/skills`、`~/.hermes/skills`（只装已存在的目录；`--dest DIR` 自定义位置，`--link` 开发用软链）。此路径会把仓库位置烧录进每份副本，仓库留在原位期间无需额外配置。

### 两种方式装完后，agent 都这样调用

```bash
python3 scripts/resolve_venue.py 2407.01489 --json   # 在已安装的 skill 目录内
```

skill 用结构化 JSON 错误（`resolver_missing`、`resolver_timeout` 等）包装 `resolve.py`，agent 可以直接决策而不用解析 traceback。`resolve.py` 本身从不随 skill 复制——包装脚本按以下顺序定位：`--resolver PATH` 参数、`ARXIV_VENUE_RESOLVER` 环境变量、安装时烧录的仓库路径（方式 B）、`ARXIV_VENUE_RESOLVER_SKM` 环境变量（方式 A）。安装后请保留仓库在磁盘上，或导出其中一个环境变量。

## 文件

| 文件 | 用途 |
|---|---|
| `skills/arxiv-venue-resolver/` | agent skill（SKILL.md + 包装脚本），适用于 Codex / Claude Code / Hermes |
| `install_skills.py` | 把 skill 安装到本机 agent 的 skills 目录 |
| `resolve.py` | 解析器 CLI 本体 |
| `build_local.py` | 从 arXivSearcher embedding 分片构建 `local.sqlite`（314 万篇） |
| `build_dblp.py` | 从 DBLP 官方 XML 构建本地索引 `dblp.sqlite`（843 万条） |
| `ccf_v7.tsv` | CCF 推荐目录（681 个 venue），TSV 格式 |

生成的数据库（`local.sqlite`、`dblp.sqlite`）已 gitignore——用上面的脚本重建。

## 数据质量说明

- `journal_ref` / `comments` 得到的 venue 是**作者自报**，未经权威验证；S2 和 DBLP 路径是权威来源。
- DBLP 的 `CoRR` 条目（arXiv 镜像）按**未正式发表**处理并跳过——匹配会继续寻找同标题的正式 proceedings 版本。
- CCF 缩写撞名（FSE 既是密码学 B 类会议又是软工 A 类会议）用论文的 arXiv 主分类消歧；未知分类回落 A 级优先。
- 已知局限：旧式带点号子库的 arXiv ID（`math.AG/0701001`）不被解析；comments 提取的 venue 字符串可能带噪声（"CIKM 2026 as a full paper"）而错过 CCF 匹配。

## 许可证

MIT
