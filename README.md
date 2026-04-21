# repo-analysis

**陌生代码仓库深度分析工具。** 从零开始，通过代码签名索引、静态分析、逐模块精读，输出一份包含架构图、模块解读、四层契约分析的完整知识报告（Markdown + HTML）。

---

## 解决什么问题

面对一个从未接触过的代码库，盲目阅读源码效率极低。这个 skill 提供一套有序的分析流程：

- 先用工具建立"信号"（复杂度热点、调用关系、路由表），再用阅读确认信号
- 每个阶段结束后与用户确认，避免在错误方向上浪费时间
- 最终产物可在 HTML 报告中直接浏览，方便团队共享

---

## 前置条件

| 依赖 | 说明 |
|------|------|
| `context-index` skill | Phase 0 用于生成代码签名索引（若不可用，skill 内有等效命令） |
| Node.js | 运行 repomix |
| Python 3 | 运行静态分析脚本 |
| radon | Python 复杂度分析：`pip install radon` |
| pyan3 | Python 调用图：`pip install pyan3` |
| git | clone 仓库 |

> **Windows 用户**：graphviz 在 Windows 下 conda 安装可能失败，skill 内含纯文本解析替代方案。

---

## 触发词

"帮我分析这个仓库"、"读懂这个项目"、"研究一下这个代码库"、"我想了解 X 项目怎么工作的"、"复现这个项目"（前期理解阶段）

---

## 分析流程（4个阶段）

```
Phase 0：准备
├── clone 仓库
└── 生成代码签名索引（调用 context-index skill）

Phase 1：快速定位
├── 读代码签名索引（建立全景图）
├── 读仓库文档（CLAUDE.md → ARCHITECTURE.md → README.md）
└── 创建 architecture.md ← [用户确认点]

Phase 2：结构分析
├── 复杂度分析（radon：找 F/E 级热点函数）
├── 结构提取（AST 脚本：路由、路径、外部 URL）
├── 调用图分析（pyan3：跨模块依赖关系）
└── 生成四层契约分析文档 ← [用户确认点，选择深度解读目标]

Phase 3：深度解读
└── 按优先级逐模块精读（复杂度最高 → 调用最多 → 用户关注）

Phase 4：报告与产物
├── 生成最终解读报告（Markdown）
└── 生成 HTML 知识报告（7个 Tab）
```

> 每个阶段结束后主动停下来与用户确认，不一口气跑完。

---

## 产物

```
PROJECT_INDEX/
├── architecture.md                  架构概览
├── 四层契约分析_<date>.md           结构/数据/协议/失效四层分析
├── <module>_解读_<date>.md          关键模块深度解读
├── 最终解读报告_<date>.md           核心交付物（Markdown）
├── report.html                      可浏览的 HTML 知识报告
├── extract_structure.py             路由/路径/URL 提取脚本
├── parse_callgraph.py               调用图解析脚本
├── call_graph.dot                   pyan3 原始调用图
└── history/
    └── <name>_<date>.md             代码签名索引
```

**HTML 报告共 7 个 Tab**：概览、架构图（数据流/调用图/ASCII）、外部依赖、模块解读、数据契约、完整报告、健康度评估

---

## 快速开始

```bash
# 用户提供仓库地址后，skill 自动执行：
git clone <repo_url>
cd <repo_name>

# Phase 0：生成代码签名索引
bash init_index.sh
# 配置 repomix.config.json 后：
bash init_index.sh --run

# Phase 4：生成 HTML 报告
python ~/.claude/skills/repo-analysis/scripts/generate_report.py ./PROJECT_INDEX
```

---

## 四层契约分析框架

| 层 | 分析内容 |
|----|---------|
| Layer 1 结构层 | 文件规模、V1/V2叠加、模块组织、复杂度热点 |
| Layer 2 数据契约层 | 文件路径依赖、核心数据格式、关键字段枚举 |
| Layer 3 交互协议层 | 对外 API、认证机制、第三方服务依赖 |
| Layer 4 失效边界层 | 降级策略、可选组件、关键失效场景 |

---

## 设计哲学

1. **文档优先**：文档是地图，代码是地形——文档可能过时，以代码为准
2. **工具驱动**：先用静态分析建立信号，再用阅读确认信号（工具有假阳性）
3. **渐进深入**：先宽后深，不要一上来就读万行主文件

---

## 依赖关系

- 依赖 [`context-index`](../context-index/README.md) skill（Phase 0 代码签名索引）
- 针对 Python 项目优化，其他语言替换对应静态分析工具（Node.js: `eslint`，Go: `gocognit`，Java: `pmd`）
