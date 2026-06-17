# 技术债务

记录已知的临时方案、妥协决策和潜在风险。修改相关模块前先看这里。

---

## 当前状态

### 已解决

- ~~**分析模块未覆盖转化漏斗（曝光→申请→授信→放款）**~~（2026-06-17发现，
  2026-06-17解决）：新增`api/modules/funnel.py`（`FunnelModule`，category=
  转化/留存），按 user_id 启发式识别各阶段（列名关键词+该列是否非空），输出
  阶段人数/环比转化率，已注册进默认分析流程。详见CHANGELOG.md 2026-06-17续4。

### 待解决

- **LangGraph checkpoint 使用 `MemorySaver`（纯内存）**：`api/core/graph.py`
  当前用 `MemorySaver` 按 `thread_id = session_id` 隔离会话。这意味着：
  - 进程重启（如 `pm2 restart`/部署）会丢失所有**已诊断但尚未提交
    confirmed_schema** 的会话状态，用户需重新上传；
  - 无法跨进程/多 worker 共享（若后续 `uvicorn --workers > 1`，中断状态
    可能落在另一个进程，`/confirm` 会查不到对应 thread）。
  - 单用户/MVP 场景下影响有限（用户通常在同一次会话内连续操作），但部署时
    `uvicorn` 不能开多 worker，且需告知用户"部署更新期间正在进行的分析需
    重新开始"。后续如需持久化可替换为 `SqliteSaver`（轻量、单文件，更适合
    本项目的单机部署）。
- **Node3 清洗 plan 的覆盖范围**：LLM 输出的 JSON plan 必须能表达所有常见清洗操作
  （重命名、类型转换、缺失值处理、去重、单位换算等）。如果 plan schema 设计过窄，
  后续每加一种清洗操作都要改 plan schema + 执行函数两处，需要在实现 Node3 前先把
  plan 的操作类型枚举设计完整，避免频繁破坏性变更。`confirmed_schema`
  （`api/core/schema.py`）已覆盖 rename/drop/fillna/drop_rows 四类操作，Node3
  实现时需确认是否需要补充类型转换、单位换算等操作类型。
- **WeasyPrint 系统依赖（已在本地 Windows 验证为阻塞项，2026-06-15续11决策暂停PDF）**：
  WeasyPrint 依赖 Pango/Cairo/GDK-Pixbuf（GObject）等系统库，`pip install weasyprint`
  本身成功，但 `from weasyprint import HTML` 在未安装这些系统库的 Windows 上直接抛
  `OSError: cannot load library 'gobject-2.0-0'`。
  - **当前处理（2026-06-15续11）**：报告输出改为 HTML 直出
    （`GET /api/report/{session_id}/html`，前端"查看完整报告"按钮 `window.open`
    新标签页），不再依赖 PDF。`api/nodes/node5_report.py` 中 `_write_pdf()`
    函数体与调用已**整段注释**（未删除），`run_report()` 中 `pdf_generated`
    固定为 `False`；`GET /api/report/{session_id}/pdf` 路由与
    `report_pdf_path` 仍保留但实际不会生成文件，调用返回404。后续若重新启用
    PDF，取消注释 `_write_pdf()` 调用并补上系统依赖即可。
  - **历史部署清单**（PDF功能重新启用时适用）：
    1. `apt-get install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0
       libcairo2 libffi-dev` 等 WeasyPrint 官方文档列出的依赖；
    2. **中文字体**：`apt-get install fonts-noto-cjk`（已决策，优先用这个，
       不再考虑 `fonts-wqy-zenhei`），否则即使 WeasyPrint 能正常加载，PDF 中的
       中文也会因字体缺失渲染为方块/空白。`report.html.j2` 的 `font-family` 已
       按"Noto Sans CJK SC -> WenQuanYi Zen Hei -> Microsoft YaHei -> SimHei"
       顺序声明，安装 `fonts-noto-cjk` 后第一项即可命中；
    3. 部署后需用一次真实 session 跑通 Node1-5，确认
       `GET /api/report/{session_id}/pdf` 返回的 PDF 中文正常显示（而不仅是
       `pdf_generated=True`）。
  - **本地开发（Windows）不安装 GTK3 Runtime**（2026-06-15 决策）：PDF 文件本身
    的渲染验证推迟到服务器部署时处理；本地仅验证 `report_html`/置信度/叙事逻辑。
- **transform_approved=False 取消时无法返回 Node2 重新确认（2026-06-16）**：
  当前 `_route_after_preview` 在 `approved=False` 时直接走向 `END`，图线程结束。
  用户无法在同一 session 内重新提交口径确认，需重新上传文件开始新 session。
  后续如需支持"取消后返回口径确认"，需在 graph 中设计从 node3_preview 回到
  node2_confirmation 的路由，并配套前端状态机处理 `transform/cancelled` 事件。
- **`/stream` 防重入仅限同一进程（MemorySaver 内存状态）**：进程重启后 MemorySaver
  清空，`graph.get_state()` 返回空 tasks，防重入检查失效。重启后同一 session_id
  再次调用 `/stream` 会重新执行全流程（node0透传→node1→node2 interrupt），
  之前已执行但 state 丢失的结果无法恢复。详见 MemorySaver 持久化债务。
- **腾讯云服务器内存限制**：empirical-agent 已在同一服务器上因 1.9GB 内存触发过 OOM
  （见 empirical-agent `docs/DEBT.md`）。本项目若与 empirical-agent 共用服务器，
  Pandas 处理大 CSV + WeasyPrint 渲染 PDF 可能进一步加剧内存压力，需在部署前评估
  是否需要限制上传文件大小或升级服务器内存。
