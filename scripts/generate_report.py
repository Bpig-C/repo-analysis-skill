#!/usr/bin/env python3
"""
generate_report.py — 将 PROJECT_INDEX/ 分析产物转换为单文件 HTML 报告

用法：
    python generate_report.py <project_index_dir> [output.html]
"""

import sys
import io
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import re
import html
from pathlib import Path
from datetime import datetime


# ─── 数据读取层 ──────────────────────────────────────────────────────────────

def load_project_data(index_dir: Path) -> dict:
    data = {
        "project_name": index_dir.parent.name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "architecture_md": "",
        "modules": [],
        "contract_layers": {},
        "final_report": "",
        "call_graph_dot": "",
        "health_issues": [],
        "dependencies": [],   # [{name, type, files, description}]
        "repo_url": "",
    }

    reports = sorted(index_dir.glob("最终解读报告_*.md"), reverse=True)
    if reports:
        content = reports[0].read_text(encoding="utf-8", errors="replace")
        data["final_report"] = content
        m = re.search(r'分析对象：(https?://\S+)', content)
        if m:
            data["repo_url"] = m.group(1)
        m2 = re.search(r'^#\s+(.+?)(?:最终解读报告|分析报告|Report)', content, re.MULTILINE)
        if m2:
            data["project_name"] = m2.group(1).strip()

    arch = index_dir / "architecture.md"
    if arch.exists():
        data["architecture_md"] = arch.read_text(encoding="utf-8", errors="replace")

    contracts = sorted(index_dir.glob("四层契约分析_*.md"), reverse=True)
    if contracts:
        content = contracts[0].read_text(encoding="utf-8", errors="replace")
        data["contract_layers"] = parse_contract_layers(content)
        data["dependencies"] = extract_dependencies(content, data["final_report"])

    seen = set()
    for pattern in ["*_解读_*.md", "*_模块解读_*.md"]:
        for f in sorted(index_dir.glob(pattern)):
            if f.name in seen:
                continue
            seen.add(f.name)
            stem = f.stem
            name = re.sub(r'[_]?(模块)?解读[_\d\-]+$', '', stem).strip('_')
            content = f.read_text(encoding="utf-8", errors="replace")
            data["modules"].append({
                "name": name or f.stem,
                "content": content,
                "slug": re.sub(r'[^\w]', '_', name or f.stem),
            })

    dot_file = index_dir / "call_graph.dot"
    if dot_file.exists():
        data["call_graph_dot"] = dot_file.read_text(encoding="utf-8", errors="replace")

    if data["final_report"]:
        data["health_issues"] = extract_health_issues(data["final_report"])

    return data


def parse_contract_layers(content: str) -> dict:
    layers = {}
    current_layer = None
    current_lines = []
    for line in content.split('\n'):
        m = re.match(r'^##\s+Layer\s+(\d+)[：:]\s*(.+)', line)
        if m:
            if current_layer:
                layers[current_layer] = '\n'.join(current_lines).strip()
            current_layer = f"Layer {m.group(1)}：{m.group(2)}"
            current_lines = []
        elif current_layer:
            current_lines.append(line)
    if current_layer and current_lines:
        layers[current_layer] = '\n'.join(current_lines).strip()
    return layers


def extract_dependencies(contract_content: str, final_report: str = "") -> list:
    """
    从四层契约分析和最终报告中提取外部依赖项。

    方法：逐行扫描，遇到"依赖/耦合"相关标题后开启收集模式，
    收集该标题以下的所有 Markdown 表格行。这样能处理标题和表格
    在 re.split 后落入不同 section 的情况。
    """
    deps = []
    dep_keywords = {
        '硬耦合', '核心文件依赖', '文件依赖', '依赖清单', '耦合点',
        'dependency', 'dependencies', '外部依赖', '数据来源',
        '硬依赖', '文件路径依赖', '第三方服务依赖', '关键依赖',
    }
    header_skip = {
        '耦合点', '文件路径', '依赖', 'Path', 'Dependency',
        '数据', 'Source', '用途', '说明',
    }

    def classify_type(name: str, detail: str) -> str:
        combined_text = (name + " " + detail).lower()
        if any(k in combined_text for k in ['ws://', 'wss://', 'websocket', 'json-rpc', 'rpc']):
            return "websocket"
        if any(k in combined_text for k in ['http://', 'https://', '.com/', 'api/', 'ingest']):
            return "http"
        if any(k in combined_text for k in ['environ', '环境变量', '_env', 'dotenv']):
            return "env"
        return "file"

    def parse_table_rows(lines_slice: list) -> list:
        rows = []
        headers = []
        for line in lines_slice:
            if not line.startswith('|'):
                break
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if not cells:
                continue
            if re.match(r'^[-: ]+$', cells[0]):
                continue
            if not headers:
                headers = cells
            else:
                rows.append(cells)
        return rows

    combined_text = contract_content + "\n" + final_report
    lines = combined_text.split('\n')
    collecting = False
    table_buf = []
    seen_names = set()

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 检测标题行：是否含依赖关键词
        is_heading = stripped.startswith('#') or (stripped.startswith('**') and stripped.endswith('**'))
        if is_heading:
            # 先处理已积累的 buffer
            if table_buf:
                for row in parse_table_rows(table_buf):
                    if len(row) < 2:
                        continue
                    name = re.sub(r'[`*]', '', row[0]).strip()
                    detail = re.sub(r'[`*]', '', row[1]).strip()
                    consumer = re.sub(r'[`*]', '', row[2]).strip() if len(row) > 2 else ""
                    if name in header_skip or name.startswith('---') or not name:
                        continue
                    key = name[:40]
                    if key not in seen_names:
                        seen_names.add(key)
                        deps.append({
                            "name": name,
                            "detail": detail,
                            "consumer": consumer,
                            "type": classify_type(name, detail),
                        })
                table_buf = []

            heading_text = stripped.lstrip('#').strip().lstrip('*').rstrip('*').strip()
            collecting = any(kw in heading_text for kw in dep_keywords)
            continue

        if collecting:
            if stripped.startswith('|'):
                table_buf.append(stripped)
            elif table_buf and not stripped:
                pass  # 允许表格内的空行
            elif table_buf and not stripped.startswith('|'):
                # 表格结束，处理
                for row in parse_table_rows(table_buf):
                    if len(row) < 2:
                        continue
                    name = re.sub(r'[`*]', '', row[0]).strip()
                    detail = re.sub(r'[`*]', '', row[1]).strip()
                    consumer = re.sub(r'[`*]', '', row[2]).strip() if len(row) > 2 else ""
                    if name in header_skip or name.startswith('---') or not name:
                        continue
                    key = name[:40]
                    if key not in seen_names:
                        seen_names.add(key)
                        deps.append({
                            "name": name,
                            "detail": detail,
                            "consumer": consumer,
                            "type": classify_type(name, detail),
                        })
                table_buf = []
                collecting = False

    # 策略2：fallback — 从文本 backtick 中提取文件路径
    if not deps:
        for m in re.finditer(r'`(~?/[^`\n]{4,})`', combined_text):
            p = m.group(1)
            if p in seen_names:
                continue
            if any(p.startswith(x) for x in ['~/', '/tmp', '/var', '/root', '/sandbox']):
                seen_names.add(p)
                deps.append({"name": p, "detail": p, "consumer": "", "type": "file"})
            if len(deps) >= 15:
                break

    return deps


def extract_health_issues(report_content: str) -> list:
    issues = []
    in_issues_section = False
    for line in report_content.split('\n'):
        if '值得关注' in line or '架构问题' in line or '健康度' in line:
            in_issues_section = True
        if in_issues_section and line.startswith('|') and '|' in line[1:]:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            skip_vals = {'问题', '方面', 'Issue', '位置', 'Location', '---'}
            if len(parts) >= 2 and parts[0] not in skip_vals and not parts[0].startswith('---'):
                issues.append({
                    "title": parts[0],
                    "location": parts[1] if len(parts) > 1 else "",
                    "impact": parts[2] if len(parts) > 2 else "",
                })
        if in_issues_section and re.match(r'^##\s+[^#]', line):
            if not any(kw in line for kw in ('健康', '值得', '问题')):
                in_issues_section = False
    return issues


def dot_to_mermaid_module_graph(dot_content: str) -> str:
    """
    从 pyan3 调用图生成 Mermaid 模块依赖图。
    策略：只用 label==tooltip 的节点作为"模块节点"集合，避免把函数 FQN 误识别为模块。
    pyan3 的模块节点特征：label="clawmetry.cli" 且 tooltip="clawmetry.cli"（两者相同）。
    函数节点：label="_cmd_connect" 但 tooltip="clawmetry.cli._cmd_connect"（两者不同）。
    """
    if not dot_content:
        return ""

    node_fqn = {}    # node_id -> full FQN (from tooltip)
    module_fqns = set()  # 只收集真正的模块节点 FQN（tooltip == label）

    for m in re.finditer(r'"([\w]+)"\s*\[label="([^"]+)"[^\]]*tooltip="([^"\\]+)', dot_content):
        node_id, label, tooltip = m.group(1), m.group(2), m.group(3)
        fqn = tooltip.split('\\n')[0].strip()
        node_fqn[node_id] = fqn
        if fqn == label:          # 模块节点：label 即是完整 FQN
            module_fqns.add(fqn)

    if not module_fqns:
        return ""

    def fqn_to_module(fqn: str) -> str:
        """把函数/类的 FQN 折叠到其所属的包模块。"""
        if fqn in module_fqns:
            return fqn
        parts = fqn.split('.')
        # 从长到短找第一个已知模块前缀
        for end in range(len(parts) - 1, 0, -1):
            candidate = '.'.join(parts[:end])
            if candidate in module_fqns:
                return candidate
        return '.'.join(parts[:-1]) if len(parts) > 1 else fqn

    edge_counts: dict = {}
    for m in re.finditer(r'"([\w]+)"\s*->\s*"([\w]+)"', dot_content):
        s_fqn = node_fqn.get(m.group(1), m.group(1))
        d_fqn = node_fqn.get(m.group(2), m.group(2))
        sm = fqn_to_module(s_fqn)
        dm = fqn_to_module(d_fqn)
        if sm != dm and sm and dm:
            key = (sm, dm)
            edge_counts[key] = edge_counts.get(key, 0) + 1

    if not edge_counts:
        return ""

    sorted_edges = sorted(edge_counts.items(), key=lambda x: -x[1])[:20]

    node_ids: dict = {}
    counter = 0
    for (s, d), _ in sorted_edges:
        for n in (s, d):
            if n not in node_ids:
                node_ids[n] = f"M{counter}"
                counter += 1

    all_srcs = {s for (s, d), _ in sorted_edges}
    all_dsts = {d for (s, d), _ in sorted_edges}
    leaf_nodes = all_dsts - all_srcs
    root_nodes = all_srcs - all_dsts

    lines = ["graph LR"]
    for fqn, nid in node_ids.items():
        label = fqn.split(".")[-1] if "." in fqn else fqn
        if fqn in leaf_nodes:
            lines.append(f'    {nid}(["{label}"])')
            lines.append(f'    style {nid} fill:#f0fdf4,stroke:#16a34a')
        elif fqn in root_nodes:
            lines.append(f'    {nid}["{label}"]')
            lines.append(f'    style {nid} fill:#dbeafe,stroke:#3b82f6')
        else:
            lines.append(f'    {nid}["{label}"]')

    for (s, d), cnt in sorted_edges:
        label = f"|x{cnt}|" if cnt > 1 else ""
        lines.append(f"    {node_ids[s]} -->{label} {node_ids[d]}")

    return "\n".join(lines)


def build_dataflow_mermaid(dependencies: list, project_name: str, modules: list) -> str:
    """
    生成以项目为中心的数据流图：
    外部数据源 → 项目组件 → 输出目标
    这比代码调用图更直观地展示"它读什么、写什么"。
    """
    if not dependencies:
        return ""

    file_deps = [d for d in dependencies if d["type"] == "file"]
    ws_deps = [d for d in dependencies if d["type"] == "websocket"]
    http_deps = [d for d in dependencies if d["type"] in ("http",)]

    if not file_deps and not ws_deps and not http_deps:
        return ""

    lines = ["graph LR"]
    lines.append(f'    subgraph LOCAL["用户本地机器"]')

    # 外部数据源节点
    src_ids: dict = {}
    src_counter = 0

    # 文件路径源
    for dep in file_deps[:8]:
        nid = f"F{src_counter}"
        src_counter += 1
        # 缩短路径显示
        label = dep["detail"] or dep["name"]
        label = label.replace("~/.openclaw/", "~/.openclaw/\n")
        label = label.replace("~/.clawmetry/", "~/.clawmetry/\n")
        # Mermaid 内 label 不能含双引号，用单引号替代
        label_safe = label.replace('"', "'").replace('\n', ' ')
        src_ids[dep["name"]] = nid
        lines.append(f'        {nid}["{label_safe}"]')
        lines.append(f'        style {nid} fill:#fef9c3,stroke:#ca8a04')

    # WebSocket 源
    ws_id = None
    if ws_deps:
        ws_id = "WS0"
        # 从实际数据中提取标签，不硬编码项目专属内容
        first_ws = ws_deps[0]
        ws_name = first_ws.get("name", "WebSocket 端点")
        ws_detail = first_ws.get("detail", "")
        if ws_detail and ws_detail != ws_name:
            ws_label = f"{ws_name}\\n{ws_detail}"
        else:
            ws_label = ws_name
        # Mermaid label 不能含双引号
        ws_label = ws_label.replace('"', "'")
        lines.append(f'        {ws_id}["{ws_label}"]')
        lines.append(f'        style {ws_id} fill:#fce7f3,stroke:#ec4899')

    lines.append(f'    end')

    # 项目核心
    lines.append(f'    subgraph PROJ["{project_name}"]')
    mod_ids: dict = {}
    if modules:
        for i, mod in enumerate(modules[:5]):
            mid = f"MOD{i}"
            mod_ids[mod["name"]] = mid
            lines.append(f'        {mid}["{mod["name"]}"]')
            lines.append(f'        style {mid} fill:#dbeafe,stroke:#3b82f6')
    else:
        lines.append(f'        CORE["核心模块"]')
        lines.append(f'        style CORE fill:#dbeafe,stroke:#3b82f6')
    lines.append(f'    end')

    # 输出目标
    http_out = [d for d in http_deps]
    if http_out:
        lines.append(f'    subgraph CLOUD["云端 / 外部服务"]')
        for i, dep in enumerate(http_out[:4]):
            nid = f"OUT{i}"
            label = dep["detail"] or dep["name"]
            if len(label) > 30:
                label = label[:27] + "..."
            lines.append(f'        {nid}["{label.replace(chr(34), chr(39))}"]')
            lines.append(f'        style {nid} fill:#dcfce7,stroke:#16a34a')
        lines.append(f'    end')

    # 连接线
    core_node = list(mod_ids.values())[0] if mod_ids else "CORE"
    for dep_name, nid in src_ids.items():
        lines.append(f'    {nid} -->|读取| {core_node}')
    if ws_id:
        lines.append(f'    {ws_id} -->|WebSocket RPC| {core_node}')
    for i, dep in enumerate(http_out[:4]):
        lines.append(f'    {core_node} -->|上传/调用| OUT{i}')

    return "\n".join(lines)


def extract_overview_essence(final_report: str) -> dict:
    result = {"essence": "", "ascii_diagram": ""}
    lines = final_report.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^##\s+[一1]\s*[、.]\s*(项目本质|项目简介|Overview)', line):
            essence_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith('## '):
                essence_lines.append(lines[i])
                i += 1
            result["essence"] = '\n'.join(essence_lines).strip()
            continue
        if '全景图' in line or '架构图' in line:
            j = i + 1
            in_block = False
            block_lines = []
            while j < len(lines) and not lines[j].startswith('## '):
                if lines[j].startswith('```'):
                    if in_block:
                        break
                    in_block = True
                elif in_block:
                    block_lines.append(lines[j])
                j += 1
            if block_lines:
                result["ascii_diagram"] = '\n'.join(block_lines)
        i += 1
    return result


# ─── HTML 生成层 ──────────────────────────────────────────────────────────────

TAILWIND_CDN = "https://cdn.tailwindcss.com"
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
MARKED_CDN = "https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"

# 表格样式：用 <style> 强制覆盖 Tailwind preflight 的 border-collapse:collapse 重置
TABLE_STYLE = """
  /* 强制表格边框可见（覆盖 Tailwind preflight 的 border 重置） */
  .md-table table { border-collapse: collapse !important; width: 100%; margin: 0.75em 0; font-size: 0.85em; }
  .md-table th { background: #f0f9ff !important; font-weight: 600; text-align: left; padding: 0.5em 0.75em; border: 1px solid #93c5fd !important; color: #1e40af; }
  .md-table td { padding: 0.4em 0.75em; border: 1px solid #e2e8f0 !important; vertical-align: top; }
  .md-table tr:nth-child(even) td { background: #f8fafc; }
  .md-table tr:hover td { background: #eff6ff; }
"""

PROSE_STYLE = """
  .prose-content h1 { font-weight: 700; font-size: 1.4em; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.3em; margin: 1.2em 0 0.5em; color: #1e293b; }
  .prose-content h2 { font-weight: 600; font-size: 1.15em; margin: 1.1em 0 0.4em; color: #334155; border-left: 3px solid #3b82f6; padding-left: 0.6em; }
  .prose-content h3 { font-weight: 600; font-size: 1em; margin: 0.9em 0 0.3em; color: #475569; }
  .prose-content p { margin-bottom: 0.75em; line-height: 1.7; color: #374151; }
  .prose-content ul, .prose-content ol { padding-left: 1.5em; margin-bottom: 0.75em; }
  .prose-content li { margin-bottom: 0.3em; line-height: 1.6; }
  .prose-content code { background: #f1f5f9; padding: 0.15em 0.4em; border-radius: 3px; font-size: 0.82em; font-family: ui-monospace, 'Cascadia Code', monospace; color: #be185d; }
  .prose-content pre { background: #0f172a; color: #e2e8f0; padding: 1em 1.2em; border-radius: 8px; overflow-x: auto; margin: 0.75em 0; }
  .prose-content pre code { background: none; padding: 0; color: #e2e8f0; font-size: 0.8em; }
  .prose-content blockquote { border-left: 4px solid #93c5fd; padding: 0.5em 1em; color: #64748b; margin: 0.75em 0; background: #f0f9ff; border-radius: 0 4px 4px 0; }
  .prose-content hr { border: none; border-top: 1px solid #e2e8f0; margin: 1.5em 0; }
  .prose-content a { color: #2563eb; text-decoration: underline; }
"""


def dep_type_badge(dep_type: str) -> str:
    colors = {
        "file": ("bg-amber-100 text-amber-800", "文件"),
        "websocket": ("bg-pink-100 text-pink-800", "WS"),
        "http": ("bg-green-100 text-green-800", "HTTP"),
        "env": ("bg-purple-100 text-purple-800", "ENV"),
    }
    cls, label = colors.get(dep_type, ("bg-gray-100 text-gray-600", dep_type))
    return f'<span class="inline-block px-1.5 py-0.5 rounded text-xs font-mono font-semibold {cls}">{label}</span>'


def build_html(data: dict) -> str:
    overview = extract_overview_essence(data["final_report"] or data["architecture_md"])

    # ── 依赖表格 ──
    dep_rows = ""
    for dep in data["dependencies"]:
        badge = dep_type_badge(dep["type"])
        detail = html.escape(dep["detail"]) if dep["detail"] != dep["name"] else ""
        consumer = html.escape(dep["consumer"])
        dep_rows += f'''<tr>
            <td class="py-2 px-3 font-mono text-xs text-gray-700 break-all">{html.escape(dep["name"])}</td>
            <td class="py-2 px-3 text-center">{badge}</td>
            <td class="py-2 px-3 text-xs text-gray-500 font-mono break-all">{detail}</td>
            <td class="py-2 px-3 text-xs text-gray-500">{consumer}</td>
        </tr>'''
    if not dep_rows:
        dep_rows = '<tr><td colspan="4" class="py-6 text-center text-gray-400 text-sm">未从分析产物中提取到外部依赖</td></tr>'

    # ── 架构图选择 ──
    # 优先：数据流图（更直观）；次选：模块调用图；最后：ASCII fallback
    dataflow_mermaid = build_dataflow_mermaid(
        data["dependencies"], data["project_name"], data["modules"]
    )
    module_mermaid = dot_to_mermaid_module_graph(data["call_graph_dot"])
    has_mermaid = bool(dataflow_mermaid or module_mermaid)

    arch_tabs_html = ""
    if dataflow_mermaid:
        arch_tabs_html += f'''
        <div id="arch-dataflow" class="arch-tab-pane">
          <p class="text-xs text-gray-400 mb-3">数据流向：外部来源 → 项目组件 → 输出目标</p>
          <div class="mermaid">{dataflow_mermaid}</div>
        </div>'''
    if module_mermaid:
        arch_tabs_html += f'''
        <div id="arch-modules" class="arch-tab-pane {"hidden" if dataflow_mermaid else ""}">
          <p class="text-xs text-gray-400 mb-3">代码模块调用关系（来自 pyan3 静态分析，蓝=根节点，绿=叶节点）</p>
          <div class="mermaid">{module_mermaid}</div>
        </div>'''
    if overview.get("ascii_diagram"):
        arch_tabs_html += f'''
        <div id="arch-ascii" class="arch-tab-pane {"hidden" if dataflow_mermaid or module_mermaid else ""}">
          <p class="text-xs text-gray-400 mb-3">原始 ASCII 架构图（来自最终报告）</p>
          <pre class="bg-gray-900 text-green-400 text-xs leading-tight font-mono p-4 rounded-lg overflow-x-auto">{html.escape(overview["ascii_diagram"])}</pre>
        </div>'''

    arch_tab_buttons = ""
    if dataflow_mermaid:
        arch_tab_buttons += '<button onclick="showArchTab(\'arch-dataflow\')" id="btn-arch-dataflow" class="arch-tab-btn active-arch-tab px-3 py-1 text-xs rounded font-medium">数据流图</button>'
    if module_mermaid:
        cls = "" if dataflow_mermaid else "active-arch-tab"
        arch_tab_buttons += f'<button onclick="showArchTab(\'arch-modules\')" id="btn-arch-modules" class="arch-tab-btn {cls} px-3 py-1 text-xs rounded font-medium">模块调用图</button>'
    if overview.get("ascii_diagram"):
        arch_tab_buttons += '<button onclick="showArchTab(\'arch-ascii\')" id="btn-arch-ascii" class="arch-tab-btn px-3 py-1 text-xs rounded font-medium">ASCII 图</button>'

    # ── 模块导航 ──
    modules_nav = ""
    modules_content = ""
    for i, mod in enumerate(data["modules"]):
        active_nav = "bg-blue-600 text-white" if i == 0 else "text-gray-600 hover:bg-gray-100"
        active_pane = "" if i == 0 else "hidden"
        modules_nav += f'''
            <button onclick="showModule('{mod['slug']}')" id="nav-{mod['slug']}"
                class="module-nav-btn w-full text-left px-3 py-2 rounded text-sm font-medium {active_nav}">
                {html.escape(mod['name'])}
            </button>'''
        modules_content += f'''
            <div id="mod-{mod['slug']}" class="module-pane {active_pane}">
              <div class="markdown-src hidden">{html.escape(mod['content'])}</div>
              <div class="markdown-out md-table prose-content text-sm leading-relaxed"></div>
            </div>'''

    # ── 契约层 Tab ──
    contract_tabs_nav = ""
    contract_tabs_content = ""
    for i, (layer_name, layer_content) in enumerate(data["contract_layers"].items()):
        tab_id = f"layer_{i}"
        active_tab = "border-b-2 border-blue-600 text-blue-700 font-semibold" if i == 0 else "text-gray-500 hover:text-gray-700"
        active_pane = "" if i == 0 else "hidden"
        short_name = re.sub(r'Layer \d+[：:]\s*', '', layer_name)
        contract_tabs_nav += f'''
            <button onclick="showLayer('{tab_id}')" id="layernav-{tab_id}"
                class="layer-nav-btn whitespace-nowrap px-4 py-2 text-sm {active_tab}">
                {html.escape(short_name)}
            </button>'''
        contract_tabs_content += f'''
            <div id="layer-{tab_id}" class="layer-pane {active_pane} p-5">
              <div class="markdown-src hidden">{html.escape(layer_content)}</div>
              <div class="markdown-out md-table prose-content text-sm leading-relaxed"></div>
            </div>'''

    # ── 健康度 ──
    health_rows = ""
    for issue in data["health_issues"]:
        health_rows += f'''<tr>
            <td class="py-2.5 px-4 text-sm font-medium text-red-700">{html.escape(issue['title'])}</td>
            <td class="py-2.5 px-4 text-sm text-gray-500 font-mono text-xs">{html.escape(issue['location'])}</td>
            <td class="py-2.5 px-4 text-sm text-gray-600">{html.escape(issue['impact'])}</td>
        </tr>'''
    if not health_rows:
        health_rows = '<tr><td colspan="3" class="py-6 text-center text-gray-400 text-sm">未发现架构健康度问题</td></tr>'

    # ── 项目本质摘要 ──
    essence_html = ""
    if overview.get("essence"):
        essence_html = f'''
        <div class="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-5 mb-5">
          <div class="markdown-src hidden">{html.escape(overview["essence"])}</div>
          <div class="markdown-out md-table prose-content text-sm leading-relaxed text-blue-900"></div>
        </div>'''

    repo_link = ""
    if data.get("repo_url"):
        repo_link = f' · <a href="{html.escape(data["repo_url"])}" target="_blank" class="text-blue-400 hover:text-blue-300 underline text-xs">{html.escape(data["repo_url"])}</a>'

    has_modules = bool(data["modules"])
    has_contracts = bool(data["contract_layers"])
    has_deps = bool(data["dependencies"])

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(data["project_name"])} — 仓库分析报告</title>
<script src="{TAILWIND_CDN}"></script>
<script src="{MARKED_CDN}"></script>
{"<script src='" + MERMAID_CDN + "'></script>" if has_mermaid else ""}
<style>
{TABLE_STYLE}
{PROSE_STYLE}
  .tab-btn {{ transition: all 0.15s; }}
  .tab-btn.active {{ border-bottom: 2px solid #2563eb; color: #2563eb; font-weight: 600; }}
  .active-arch-tab {{ background: #dbeafe !important; color: #1d4ed8 !important; }}
  .mermaid svg {{ max-width: 100%; height: auto; }}
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; }}
</style>
</head>
<body class="bg-slate-100 min-h-screen">

<!-- Header -->
<header class="bg-slate-900 text-white shadow-lg sticky top-0 z-20">
  <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
    <div>
      <span class="text-lg font-bold tracking-tight">{html.escape(data["project_name"])}</span>
      <span class="text-slate-400 text-xs ml-3">仓库分析报告 · {html.escape(data["generated_at"])}{repo_link}</span>
    </div>
    <nav class="flex gap-0.5">
      <button onclick="showTab('overview')" id="tab-overview" class="tab-btn active px-3 py-1.5 text-sm text-white">概览</button>
      <button onclick="showTab('arch')" id="tab-arch" class="tab-btn px-3 py-1.5 text-sm text-slate-300">架构图</button>
      {"<button onclick='showTab(\"deps\")' id='tab-deps' class='tab-btn px-3 py-1.5 text-sm text-slate-300'>外部依赖</button>" if has_deps else ""}
      {"<button onclick='showTab(\"modules\")' id='tab-modules' class='tab-btn px-3 py-1.5 text-sm text-slate-300'>模块解读</button>" if has_modules else ""}
      {"<button onclick='showTab(\"contracts\")' id='tab-contracts' class='tab-btn px-3 py-1.5 text-sm text-slate-300'>数据契约</button>" if has_contracts else ""}
      <button onclick="showTab('report')" id="tab-report" class="tab-btn px-3 py-1.5 text-sm text-slate-300">完整报告</button>
      <button onclick="showTab('health')" id="tab-health" class="tab-btn px-3 py-1.5 text-sm text-slate-300">健康度</button>
    </nav>
  </div>
</header>

<main class="max-w-7xl mx-auto px-4 py-5">

<!-- ── 概览 ── -->
<div id="pane-overview" class="tab-pane">
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
    <div class="lg:col-span-2 space-y-4">
      <div class="bg-white rounded-xl p-5 shadow-sm border border-slate-200">
        <h2 class="text-base font-semibold text-slate-800 mb-3 flex items-center gap-2">
          <span class="w-2 h-2 bg-blue-500 rounded-full inline-block"></span> 项目本质
        </h2>
        {essence_html if essence_html else '<p class="text-slate-400 text-sm">（未找到项目本质摘要，请查看完整报告 Tab）</p>'}
      </div>
    </div>
    <div class="space-y-3">
      <div class="bg-white rounded-xl p-4 shadow-sm border border-slate-200">
        <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">分析产物</h3>
        <ul class="text-sm text-slate-600 space-y-1">
          {"<li class='flex items-center gap-2'><span class='text-green-500'>✓</span> 最终解读报告</li>" if data["final_report"] else ""}
          {"<li class='flex items-center gap-2'><span class='text-green-500'>✓</span> 架构文档</li>" if data["architecture_md"] else ""}
          {"<li class='flex items-center gap-2'><span class='text-green-500'>✓</span> 四层契约分析</li>" if data["contract_layers"] else ""}
          {"<li class='flex items-center gap-2'><span class='text-green-500'>✓</span> 模块解读 ×" + str(len(data["modules"])) + "</li>" if data["modules"] else ""}
          {"<li class='flex items-center gap-2'><span class='text-green-500'>✓</span> 调用图</li>" if data["call_graph_dot"] else ""}
          {"<li class='flex items-center gap-2'><span class='text-amber-500'>!</span> " + str(len(data["health_issues"])) + " 个健康度问题</li>" if data["health_issues"] else ""}
          {"<li class='flex items-center gap-2'><span class='text-blue-500'>⊕</span> " + str(len(data["dependencies"])) + " 个外部依赖</li>" if data["dependencies"] else ""}
        </ul>
      </div>
    </div>
  </div>
</div>

<!-- ── 架构图 ── -->
<div id="pane-arch" class="tab-pane hidden">
  <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
    <div class="flex items-center gap-2 px-4 py-3 border-b bg-slate-50">
      <h2 class="text-sm font-semibold text-slate-700 mr-2">架构图</h2>
      <div class="flex gap-1">{arch_tab_buttons}</div>
    </div>
    <div class="p-6 overflow-x-auto">
      {arch_tabs_html if arch_tabs_html else '<p class="text-slate-400 text-sm text-center py-8">未找到调用图或依赖数据，请先完成静态分析（Phase 2）</p>'}
    </div>
  </div>
</div>

<!-- ── 外部依赖 ── -->
{"" if not has_deps else f'''
<div id="pane-deps" class="tab-pane hidden">
  <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
    <div class="px-5 py-3.5 border-b bg-slate-50">
      <h2 class="text-sm font-semibold text-slate-700">外部依赖详情</h2>
      <p class="text-xs text-slate-400 mt-0.5">本项目依赖的外部文件、WebSocket 端点、HTTP API（从四层契约分析自动提取）</p>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full" style="border-collapse:collapse">
        <thead>
          <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0">
            <th style="padding:10px 14px;text-align:left;font-size:0.75em;font-weight:600;color:#475569;border:1px solid #e2e8f0;text-transform:uppercase;letter-spacing:0.05em">依赖点 / 路径</th>
            <th style="padding:10px 14px;text-align:center;font-size:0.75em;font-weight:600;color:#475569;border:1px solid #e2e8f0;text-transform:uppercase;letter-spacing:0.05em;width:80px">类型</th>
            <th style="padding:10px 14px;text-align:left;font-size:0.75em;font-weight:600;color:#475569;border:1px solid #e2e8f0;text-transform:uppercase;letter-spacing:0.05em">具体路径 / 协议</th>
            <th style="padding:10px 14px;text-align:left;font-size:0.75em;font-weight:600;color:#475569;border:1px solid #e2e8f0;text-transform:uppercase;letter-spacing:0.05em">读取方 / 影响</th>
          </tr>
        </thead>
        <tbody style="divide-y:1px solid #e2e8f0">{dep_rows}</tbody>
      </table>
    </div>
  </div>
</div>
'''}

<!-- ── 模块解读 ── -->
{"" if not has_modules else f'''
<div id="pane-modules" class="tab-pane hidden">
  <div class="flex gap-4">
    <div class="w-44 shrink-0">
      <div class="bg-white rounded-xl border border-slate-200 shadow-sm p-2 space-y-1 sticky top-20">
        {modules_nav}
      </div>
    </div>
    <div class="flex-1 bg-white rounded-xl border border-slate-200 shadow-sm p-6">
      {modules_content}
    </div>
  </div>
</div>
'''}

<!-- ── 数据契约 ── -->
{"" if not has_contracts else f'''
<div id="pane-contracts" class="tab-pane hidden">
  <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
    <div class="flex border-b overflow-x-auto bg-slate-50">{contract_tabs_nav}</div>
    {contract_tabs_content}
  </div>
</div>
'''}

<!-- ── 完整报告 ── -->
<div id="pane-report" class="tab-pane hidden">
  <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 lg:p-8">
    <div class="markdown-src hidden">{html.escape(data["final_report"] or data["architecture_md"])}</div>
    <div class="markdown-out md-table prose-content"></div>
  </div>
</div>

<!-- ── 健康度 ── -->
<div id="pane-health" class="tab-pane hidden">
  <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
    <div class="px-5 py-3.5 border-b bg-slate-50">
      <h2 class="text-sm font-semibold text-slate-700">架构健康度问题</h2>
    </div>
    <table class="w-full" style="border-collapse:collapse">
      <thead>
        <tr style="background:#fef2f2;border-bottom:2px solid #fecaca">
          <th style="padding:10px 14px;text-align:left;font-size:0.75em;font-weight:600;color:#991b1b;border:1px solid #fecaca;text-transform:uppercase;letter-spacing:0.05em">问题</th>
          <th style="padding:10px 14px;text-align:left;font-size:0.75em;font-weight:600;color:#991b1b;border:1px solid #fecaca;text-transform:uppercase;letter-spacing:0.05em">位置</th>
          <th style="padding:10px 14px;text-align:left;font-size:0.75em;font-weight:600;color:#991b1b;border:1px solid #fecaca;text-transform:uppercase;letter-spacing:0.05em">影响</th>
        </tr>
      </thead>
      <tbody>{health_rows}</tbody>
    </table>
  </div>
</div>

</main>

<script>
// Tab 切换
const ALL_TABS = ['overview','arch','deps','modules','contracts','report','health'];
function showTab(name) {{
  ALL_TABS.forEach(t => {{
    const pane = document.getElementById('pane-' + t);
    const btn = document.getElementById('tab-' + t);
    if (pane) pane.classList.toggle('hidden', t !== name);
    if (btn) btn.classList.toggle('active', t === name);
  }});
  // 架构图 tab 首次可见时渲染 Mermaid（hidden 状态下无法渲染）
  if (name === 'arch') _runMermaid();
}}

// 模块导航
function showModule(slug) {{
  document.querySelectorAll('.module-pane').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.module-nav-btn').forEach(el => {{
    el.classList.remove('bg-blue-600', 'text-white');
    el.classList.add('text-gray-600');
  }});
  const pane = document.getElementById('mod-' + slug);
  if (pane) pane.classList.remove('hidden');
  const btn = document.getElementById('nav-' + slug);
  if (btn) {{ btn.classList.add('bg-blue-600', 'text-white'); btn.classList.remove('text-gray-600'); }}
}}

// 契约层导航
function showLayer(tabId) {{
  document.querySelectorAll('.layer-pane').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.layer-nav-btn').forEach(el => {{
    el.classList.remove('border-b-2', 'border-blue-600', 'text-blue-700', 'font-semibold');
    el.classList.add('text-gray-500');
  }});
  const pane = document.getElementById('layer-' + tabId);
  if (pane) pane.classList.remove('hidden');
  const btn = document.getElementById('layernav-' + tabId);
  if (btn) {{
    btn.classList.add('border-b-2', 'border-blue-600', 'text-blue-700', 'font-semibold');
    btn.classList.remove('text-gray-500');
  }}
}}

// 架构图子 Tab — Mermaid 懒渲染辅助函数
{"var _mermaidRendered = {};" if has_mermaid else ""}

{"// 渲染前缓存 .mermaid 原始源码到 dataset.mermaidSrc，防止 mermaid.run() 替换 innerHTML 后丢失源码" if has_mermaid else ""}
{"function cacheMermaidSources(root) { var scope = root || document; scope.querySelectorAll('.mermaid').forEach(function(node) { if (node.dataset.mermaidSrc) return; if (node.querySelector('svg')) return; var raw = (node.textContent || '').trim(); if (raw) node.dataset.mermaidSrc = raw; }); }" if has_mermaid else ""}

{"// 判断节点是否曾被 mermaid.run() 标记为 processed 但未成功渲染（无 svg）" if has_mermaid else ""}
{"function mermaidNodeNeedsRetry(node) { if (!node) return false; return node.getAttribute('data-processed') === 'true' && !node.querySelector('svg'); }" if has_mermaid else ""}

{"// 清除已处理标记、还原源码、重新渲染单个节点" if has_mermaid else ""}
{"async function rerenderMermaidNode(node) { if (!node || typeof mermaid === 'undefined') return; cacheMermaidSources(node.parentElement || document); var src = node.dataset.mermaidSrc; if (!src) return; node.removeAttribute('data-processed'); node.textContent = src; await mermaid.run({ nodes: [node] }); }" if has_mermaid else ""}

{"// 渲染一个子Tab pane 内的所有 .mermaid 节点，forceReset=true 时先清除旧状态再渲染" if has_mermaid else ""}
{"async function renderArchPaneMermaid(pane, forceReset) { if (typeof mermaid === 'undefined' || !pane) return false; cacheMermaidSources(pane); var nodes = Array.from(pane.querySelectorAll('.mermaid')); if (!nodes.length) return true; try { if (forceReset) { for (var i = 0; i < nodes.length; i++) await rerenderMermaidNode(nodes[i]); } else { await mermaid.run({ nodes: nodes }); } return true; } catch(err) { console.error('Mermaid render failed:', err); return false; } }" if has_mermaid else ""}

async function showArchTab(tabId) {{
  document.querySelectorAll('.arch-tab-pane').forEach(el => el.classList.add('hidden'));
  document.querySelectorAll('.arch-tab-btn').forEach(el => el.classList.remove('active-arch-tab'));
  const pane = document.getElementById(tabId);
  if (pane) pane.classList.remove('hidden');
  const btn = document.getElementById('btn-' + tabId);
  if (btn) btn.classList.add('active-arch-tab');
  {"if (typeof mermaid === 'undefined' || !pane) return; var firstRender = !_mermaidRendered[tabId]; var retryNeeded = Array.from(pane.querySelectorAll('.mermaid')).some(mermaidNodeNeedsRetry); if (!firstRender && !retryNeeded) return; var ok = await renderArchPaneMermaid(pane, firstRender || retryNeeded); if (ok) _mermaidRendered[tabId] = true;" if has_mermaid else ""}
}}

// Marked.js 渲染所有 markdown
function renderAllMarkdown() {{
  if (typeof marked === 'undefined') return;
  marked.setOptions({{ gfm: true, breaks: false }});
  document.querySelectorAll('.markdown-src').forEach(srcEl => {{
    const outEl = srcEl.nextElementSibling;
    if (outEl && outEl.classList.contains('markdown-out')) {{
      outEl.innerHTML = marked.parse(srcEl.textContent);
    }}
  }});
}}

{"mermaid.initialize({ startOnLoad: false, theme: 'neutral', flowchart: { curve: 'basis', padding: 20 } });" if has_mermaid else ""}
{"cacheMermaidSources(document);" if has_mermaid else ""}

// 点击架构图 Tab 时只渲染当前可见的子Tab，不全量渲染（全量会跳过 display:none 元素并打上 processed 标记）
{"var _mermaidDone = false;" if has_mermaid else ""}
async function _runMermaid() {{
  {"if (_mermaidDone || typeof mermaid === 'undefined') return; var pane = document.querySelector('#pane-arch .arch-tab-pane:not(.hidden)'); if (!pane) return; var ok = await renderArchPaneMermaid(pane, true); if (!ok) return; _mermaidDone = true; if (pane.id) _mermaidRendered[pane.id] = true;" if has_mermaid else ""}
}}

window.addEventListener('DOMContentLoaded', renderAllMarkdown);
</script>
</body>
</html>'''


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("用法: python generate_report.py <PROJECT_INDEX_dir> [output.html]")
        sys.exit(1)

    index_dir = Path(sys.argv[1]).resolve()
    if not index_dir.exists():
        print(f"Error: directory not found: {index_dir}")
        sys.exit(1)

    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else index_dir / "report.html"

    print(f"Reading: {index_dir}")
    data = load_project_data(index_dir)

    ok = lambda v: "[ok]" if v else "[--]"
    print(f"  project      : {data['project_name']}")
    print(f"  final_report : {ok(data['final_report'])}")
    print(f"  architecture : {ok(data['architecture_md'])}")
    print(f"  contract_layers: {ok(data['contract_layers'])} ({len(data['contract_layers'])} layers)")
    print(f"  modules      : {len(data['modules'])} files")
    print(f"  call_graph   : {ok(data['call_graph_dot'])}")
    print(f"  dependencies : {len(data['dependencies'])} items")
    print(f"  health_issues: {len(data['health_issues'])} items")

    html_content = build_html(data)
    output_file.write_text(html_content, encoding="utf-8")
    print(f"\nDone: {output_file}  ({len(html_content) // 1024} KB)")

    import webbrowser
    try:
        webbrowser.open(output_file.as_uri())
        print("Opened in browser.")
    except Exception:
        print(f"Open manually: {output_file}")


if __name__ == "__main__":
    main()
