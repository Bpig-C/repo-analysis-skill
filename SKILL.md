---
name: repo-analysis
description: 从零开始深度分析一个代码仓库：clone → 代码索引 → 文档阅读 → 静态分析 → 关键模块解读 → 最终报告。适用于你需要在无先验知识的情况下快速理解一个陌生仓库的架构、核心逻辑、模块边界和依赖关系。当用户说"帮我分析这个仓库"、"读懂这个项目"、"研究一下这个代码库"、"我想了解 X 项目怎么工作的"时触发。也适用于"复现这个项目"的前期理解阶段。
---

# Repo Analysis Skill

深度理解陌生代码仓库的完整流程。

## 设计哲学

这个 skill 的核心是**认识论**：在你读懂之前，先确定"读什么"和"用什么工具读"。

**三个原则**：

1. **文档优先**：仓库自带的 CLAUDE.md / ARCHITECTURE.md / README 是最快的入口。读文档比读代码快 10 倍——但文档可能过时，所以文档是地图，代码是地形。
2. **工具驱动**：纯凭直觉阅读大文件效率低。先用工具（radon、pyan3、AST 提取）建立"信号"，再用阅读确认信号、解决疑问。工具的假阳性需要人工核查。
3. **渐进深入**：先宽后深。不要一上来就读 33,000 行的主文件。先看结构 → 找热点 → 理解依赖 → 精读关键路径。

**关于通用性**：
这个 skill 针对 AI 工具类仓库（Python 主导）做了参数设置，但框架本身适用于任何语言。Node.js 项目用 `eslint --print-ast`，Java 用 `javap`，Rust 用 `cargo-tree`。遇到非 Python 项目时，用本 skill 的流程框架，替换对应的静态分析工具。

---

## 整体流程

```
Phase 0: 准备（clone + 索引）
Phase 1: 快速定位（文档 + 文件地图）
Phase 2: 结构分析（工具驱动）
Phase 3: 深度解读（人工精读）
Phase 4: 报告与产物
```

**用户交互节奏**：每个 Phase 结束后停下来确认，不要一口气跑完——用户可能对某个模块有特别关注，或者想跳过某个步骤。

---

## Phase 0：准备

### 0.1 Clone 仓库

```bash
# 进入目标父目录，clone 进去（自动创建子目录）
cd <target_dir>
git clone <repo_url>
cd <repo_name>
```

注意事项：
- 确认 clone 只在 `<repo_name>/` 目录内操作，不影响父目录其他文件
- 如果已有本地仓库，跳过 clone，直接 `git pull`

### 0.2 初始化代码签名索引

**第一步：统计文件后缀分布**

在配置 repomix 之前，先列出仓库中所有文件后缀及其数量，避免把大量无关文件（文档、图片、自动生成的 JSON 等）纳入索引，浪费 token。

```bash
# 统计所有文件后缀及数量，按数量降序排列
find . -not -path './.git/*' -type f \
  | sed 's/.*\./\./' \
  | sort | uniq -c | sort -rn \
  | head -40
```

根据统计结果决定 ignore 规则，参考原则：

| 后缀类型 | 建议 | 理由 |
|---------|------|------|
| `.md` / `.rst` / `.txt` | **ignore** | 文档通过直读获取，不需要进签名索引 |
| `.png` / `.jpg` / `.svg` / `.gif` / `.ico` | **ignore** | 二进制，repomix 无法处理 |
| `.json` / `.yaml` / `.yml` | **先看再决定** | 若是配置/schema 无业务逻辑则 ignore；若含关键数据结构则保留 |
| `.lock` / `.sum` / `package-lock.json` | **ignore** | 自动生成，无阅读价值 |
| `.pyc` / `__pycache__/` / `.min.js` | **ignore** | 编译产物 |
| `.py` / `.ts` / `.go` / `.rs` 等源码 | **保留** | 核心分析对象 |
| `.sh` / `Dockerfile` / `Makefile` | **保留** | 安装脚本常含业务逻辑 |
| 语言配置（`pyproject.toml` / `go.mod` / `Cargo.toml`）| **保留** | 依赖信息 |

**第二步：配置并运行 repomix**

检查仓库根目录是否已有 `PROJECT_INDEX/history/` 和 `repomix.config.json`：
- **已有**：确认 ignore 规则仍合适，直接运行 `bash update_index.sh` 更新索引，跳过下方设置步骤
- **没有**：按以下步骤创建

创建 `PROJECT_INDEX/` 目录结构，写入 `init_index.sh` 和 `update_index.sh`。

> 若 `context-index` skill 可用，脚本内容参见该 skill 的 Phase 0；  
> 若不可用，等效命令如下：
> ```bash
> # init_index.sh 核心逻辑
> npx repomix --config repomix.config.json --output PROJECT_INDEX/history/$(basename $(pwd))_$(date +%Y%m%d_%H%M%S).md
> ```

```bash
bash init_index.sh          # 扫描文件结构，查看 token 分布
# 根据后缀统计结果配置 repomix.config.json 的 ignore 规则
bash init_index.sh --run    # 正式生成索引
```

生成产物：
- `repomix.config.json`
- `PROJECT_INDEX/history/<name>_<timestamp>.md`（代码签名索引）

---

## Phase 1：快速定位

### 1.0 读代码签名索引（建立全景图）

Phase 0 生成的签名索引是快速入手的最高效路径——它把整个仓库压缩成函数/类签名，几分钟内就能建立全局结构感知，比逐文件探索快得多。

```
读 PROJECT_INDEX/history/ 下最新的 .md 文件
```

从索引中提取：
- **文件列表与模块划分**：哪些目录/文件是核心？哪些是工具脚本？
- **函数/类分布**：哪个文件定义的 symbol 最多（复杂度热点候选）？
- **入口线索**：有没有 `main`、`cli`、`app`、`server` 之类的顶层符号？
- **依赖轮廓**：import 语句里出现了哪些第三方库？

这一步不要深读，目标是**生成一份心智地图**，供后续 1.1 文档阅读时做交叉校验。

### 1.1 读仓库文档（优先级顺序）

```
CLAUDE.md  →  ARCHITECTURE.md  →  README.md  →  docs/
```

读文档时关注：
- **技术栈**：语言、框架、依赖
- **入口文件**：main 函数在哪，CLI 命令是什么
- **核心设计决策**：单文件 vs 模块化，有状态 vs 无状态，同步 vs 异步
- **对外接口**：HTTP API、WebSocket、CLI、SDK
- **数据存储**：数据库类型、文件路径约定

**警惕**：文档可能严重滞后。如果文档说"~1200 行"但文件实际有 33,000 行，以代码为准。

### 1.2 创建 PROJECT_INDEX/architecture.md

基于文档 + 初步代码扫描，生成架构文档。参考 context-index skill 中的模板格式。

**完成后，向用户展示架构概要并确认理解是否正确，再进入 Phase 2。**

---

## Phase 2：结构分析

### 2.1 复杂度分析（Python：radon）

```bash
pip install radon
# 圈复杂度（找热点函数）
radon cc <package_dir>/ -s -n C --total-average 2>&1 | head -80
# 可维护性指数
radon mi <package_dir>/ -s 2>&1 | head -40
```

其他语言替代工具：
- JavaScript/TypeScript：`npx complexity-report`、`eslint` + `complexity` rule
- Go：`gocognit`
- Java：`pmd`（CPD/CCN metrics）
- Rust：`cargo clippy` 的复杂度警告

**重点看**：F/E 级（CC ≥ 20）的函数——这些是最难维护、最可能有隐藏逻辑的地方。

**识别 V1/V2 叠加模式**：如果同一文件有两次 `app = Flask()`、`app = Express()`、`class Config` 等，说明旧代码没有删除被新代码覆盖——实际行数可能是文档声称的 3 倍，且存在大量死代码。

### 2.2 结构提取（根据语言选择工具）

目标：提取路由表、文件路径依赖、RPC 调用、关键字段格式。

**Python（自写 AST 提取脚本）**

创建 `PROJECT_INDEX/extract_structure.py`，提取：
- Flask/FastAPI 路由（`@app.route`、`@router.get` 等）
- 文件路径字符串（`os.path.join`、`Path()` 等）
- 外部 API 调用 URL
- 关键数据结构字段

参考脚本框架：
```python
import re, ast, sys
from pathlib import Path

target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
results = {"routes": [], "paths": [], "urls": []}

for f in target.rglob("*.py"):
    text = f.read_text(errors="replace")
    # 路由提取
    for m in re.finditer(r'@\w+\.(?:route|get|post|put|delete|patch)\(["\']([^"\']+)', text):
        results["routes"].append({"file": str(f), "route": m.group(1)})
    # 路径字符串提取
    for m in re.finditer(r'["\'](\~?/[^"\']{5,})["\']', text):
        p = m.group(1)
        if not p.startswith("http"):
            results["paths"].append(p)
    # URL 提取
    for m in re.finditer(r'["\']https?://[^"\']+["\']', text):
        results["urls"].append(m.group(0).strip("\"'"))

# 输出到文件（避免 Windows 编码问题）
out = Path("PROJECT_INDEX/structure_extract.json")
import json
out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Extracted: {len(results['routes'])} routes, {len(results['paths'])} paths, {len(results['urls'])} URLs")
```

**注意**：静态分析会产生误报（HTML 模板中的路径字符串、动态拼接的路由）。提取结果是信号，需要人工确认。

### 2.3 调用图分析（Python：pyan3）

```bash
pip install pyan3
cd <repo_root>
python -m pyan <package>/**/*.py --dot --no-defines > PROJECT_INDEX/call_graph.dot
```

然后创建 `PROJECT_INDEX/parse_callgraph.py` 解析 dot 文件（无需 graphviz）：

```python
import re
from collections import defaultdict
from pathlib import Path

text = (Path(__file__).parent / "call_graph.dot").read_text(encoding="utf-8", errors="replace")

# 解析节点（tooltip 字段含完整限定名）
node_fqn = {}
for m in re.finditer(r'"([\w]+)"\s*\[.*?tooltip="([^\\]+)', text):
    node_fqn[m.group(1)] = m.group(2).split("\\n")[0].strip()

# 解析边
edges = []
for m in re.finditer(r'"([\w]+)"\s*->\s*"([\w]+)"', text):
    s = node_fqn.get(m.group(1), m.group(1))
    d = node_fqn.get(m.group(2), m.group(2))
    # 从 fqn 提取模块（去掉最后一段函数名）
    sm = ".".join(s.split(".")[:-1]) if "." in s else s
    dm = ".".join(d.split(".")[:-1]) if "." in d else d
    if sm != dm:
        edges.append((sm, s.split(".")[-1], dm, d.split(".")[-1]))

# 统计跨模块调用
from collections import Counter
matrix = Counter((sm, dm) for sm, _, dm, _ in edges)
print("跨模块调用矩阵（次数最多的前20）：")
for (sm, dm), cnt in matrix.most_common(20):
    print(f"  {sm:40} → {dm}  ×{cnt}")
```

**pyan3 的已知问题**：
- 文件顶层的 `import X` 有时被误归因为某个函数调用 X
- 确认方法：读对应源文件的函数实现，看有没有实际调用

**调用图用途**：找到叶节点（纯被调用模块，通常是抽象基类）、根节点（入口模块）、意外耦合（A → B 出乎意料时，值得重点核查）。

### 2.4 生成四层契约分析文档

创建 `PROJECT_INDEX/四层契约分析_<date>.md`，结构：

```markdown
## Layer 1：结构层
- 文件规模（实际行数 vs 文档声称）
- V1/V2 叠加情况（如有）
- 模块组织（Blueprint/Router/Package 架构）
- 复杂度热点（F/E 级函数列表）

## Layer 2：数据契约层
- 文件路径依赖（包括历史别名）
- 核心数据格式（JSON schema / DB schema）
- 关键字段枚举（支持哪些值）
- 字段格式演变（如 camelCase → snake_case 迁移痕迹）

## Layer 3：交互协议层
- 对外 API 表面（HTTP / WebSocket / CLI）
- 认证机制
- 第三方服务依赖（URL + 用途）

## Layer 4：失效边界层
- 降级策略（主路径失败时怎么处理）
- 可选组件（opt-in 的功能模块）
- 防御性编程模式
- 关键失效场景矩阵
```

**完成后展示分析摘要，征求用户意见：哪些模块需要深入解读？**

---

## Phase 3：深度解读

### 3.1 选择解读目标

优先级排序：
1. 最高复杂度的模块（radon F 级）
2. 调用图中的核心枢纽（被调用最多的模块）
3. 用户特别关注的功能路径
4. 意外耦合/依赖需要人工确认的部分

### 3.2 逐文件解读流程

对每个目标文件：
1. 先看文件头注释——通常直接说明职责（**不要假设，先看**）
2. 找函数/类列表，建立脑图
3. 从入口函数（main / run / start）追踪核心路径
4. 重点读 F/E 级函数（已知热点）
5. 确认静态分析的疑点（pyan3 误判？意外依赖？）

**记录关键发现**：创建 `PROJECT_INDEX/<module>_解读_<date>.md`，记录：
- 模块本质（一句话定性）
- 重要发现（颠覆初始认知的点）
- 核心数据流
- 与其他模块的真实耦合关系

### 3.3 常见陷阱

| 陷阱 | 症状 | 处理方式 |
|------|------|---------|
| 文档与代码不符 | 行数/功能描述差异明显 | 以代码为准，记录差异 |
| V1/V2 叠加 | 同名函数/变量定义两次 | 确认哪个版本实际运行（Python 中后定义覆盖前定义） |
| 静态分析误判 | pyan3 报告意外耦合 | 读源码确认，检查顶层 import vs 函数内调用 |
| 单文件巨型架构 | 一个文件 >5000 行 | 先用 radon 找分界线，再按功能域分段阅读 |
| 死代码 | 函数定义但从未被调用 | pyan3 叶节点 + grep 确认 |

---

## Phase 4：报告与产物

### 4.1 最终解读报告（Markdown）

**先写 Markdown 报告，HTML 脚本依赖它**——`generate_report.py` 首先读取 `最终解读报告_*.md` 来填充"项目本质"、"完整报告"、"健康度"等 Tab，若文件不存在这几个 Tab 会是空白。

创建 `PROJECT_INDEX/最终解读报告_<date>.md`，结构：

```markdown
# <项目名> 最终解读报告

> 生成日期：<date>
> 分析对象：<repo_url>
> 基于：项目索引、四层契约分析、<模块列表> 逐文件阅读

## 一、项目本质
（一段话说清楚这个项目是什么）

## 二、系统全景图
（ASCII 架构图，展示主要组件和数据流向）

## 三、各模块职责精要
（按模块逐一说明，包含：本质定性、核心数据流、与其他模块的边界）

## 四、关键依赖与耦合边界
（硬依赖 vs 软依赖 vs 可选组件）

## 五、架构健康度评估
（优点表 + 值得关注的问题表）

## 六、对后续分析/开发的指引
（如果这是前期调研，这里写对下一步工作最有价值的发现）

## 七、产物清单
（列出所有生成的分析文件）
```

### 4.2 生成 HTML 报告（自动）

Markdown 报告写完后，运行报告生成脚本：

```bash
python <skill_scripts_dir>/generate_report.py <PROJECT_INDEX_dir>
# 例：
python ~/.claude/skills/repo-analysis/scripts/generate_report.py ./PROJECT_INDEX
```

脚本自动读取 `PROJECT_INDEX/` 下所有分析产物，生成 `PROJECT_INDEX/report.html`，并在浏览器中打开。

**HTML 报告包含 7 个 Tab**：

| Tab | 内容 | 数据来源 |
|-----|------|---------|
| 概览 | 项目本质摘要 + 分析产物清单 | 最终报告 |
| 架构图 | Mermaid 可交互图（三个子Tab） | call_graph.dot + 依赖列表 |
| 外部依赖 | 具体文件路径/协议/消费方明细表 | 四层契约分析 |
| 模块解读 | 各模块解读（左侧导航，右侧内容） | *_解读_*.md 文件 |
| 数据契约 | 四层契约分析（分层 Tab 展示） | 四层契约分析.md |
| 完整报告 | 最终解读报告全文（Markdown 渲染） | 最终解读报告 |
| 健康度 | 架构问题表格 | 最终报告中的"值得关注"章节 |

**架构图 Tab 内含三个子Tab**（按优先级自动选择可用项）：
- **数据流图**：外部文件/WebSocket/HTTP → 项目组件 → 输出目标（最直观）
- **模块调用图**：来自 pyan3 `.dot` 文件的跨模块静态调用关系（蓝=根节点，绿=叶节点）
- **ASCII 图**：最终报告中的原始文本架构图（兜底）

### 4.3 标准产物清单

```
PROJECT_INDEX/
├── architecture.md              架构概览文档
├── 四层契约分析_<date>.md       结构/数据/协议/失效四层分析
├── <module>_解读_<date>.md      各关键模块深度解读（按需）
├── 最终解读报告_<date>.md       核心交付物
├── report.html                  可浏览的单文件 HTML 知识报告（7个Tab）
├── extract_structure.py         AST/路由提取脚本（复用价值高）
├── parse_callgraph.py           调用图解析脚本
├── call_graph.dot               pyan3 原始调用图
└── history/
    └── <name>_<date>.md         代码签名索引
```

---

## 增量更新

仓库有变更时：

```bash
git pull
bash update_index.sh
```

然后：
1. 查看 `PROJECT_INDEX/latest_changes.diff`，判断变更范围
2. 如有新模块 → 更新 architecture.md
3. 如有关键接口变更 → 重新解读对应模块
4. 追加更新日志到 `PROJECT_INDEX/CHANGELOG.md`

---

## 工具可用性速查

| 工具 | 用途 | 安装 | 替代方案 |
|------|------|------|---------|
| repomix | 代码签名索引 | `npx repomix` | — |
| radon | Python 复杂度 | `pip install radon` | 手动统计行数 |
| pyan3 | Python 调用图 | `pip install pyan3` | 手动追踪 import |
| graphviz | dot 文件可视化 | `conda install graphviz` | 解析 dot 文本（Windows 推荐） |

**Windows 注意**：graphviz 在 Windows 下 conda 安装可能失败。直接解析 dot 文件文本（见 Phase 2.3 的脚本）是更可靠的替代方案。

**输出编码**：在 Windows 上运行含中文字符的 Python 脚本时，将输出重定向到文件（`python script.py > output.txt`）并指定 UTF-8 编码，避免终端乱码。
