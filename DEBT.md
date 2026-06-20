# 技术债务

记录已知的临时方案、妥协决策和潜在风险。修改相关模块前先看这里。

---

## 当前状态

### 已解决

- ~~**transform_approved=False 取消时无法返回 Node2 重新确认**~~（2026-06-17发现，
  2026-06-17续5解决）：`node3_preview`的interrupt resume约定改为
  `{"action": "confirm"|"reject", "plan": [...]}`，`_route_after_preview`在
  `reject`时路由回`node2_confirmation`重新触发口径确认interrupt，不再走`END`；
  `ConfirmationForm.js`新增`initialSchema`沿用上一轮编辑结果。同时清洗计划本身
  改为可编辑（删除/修改单条操作），减少了真正需要"整体回退"的场景。详见
  CHANGELOG.md。Join方案阶段的回退（P2，"Join阶段发现口径错误时可返回改口径"）
  暂未做，见下方待解决。

- ~~**分析模块未覆盖转化漏斗（曝光→申请→授信→放款）**~~（2026-06-17发现，
  2026-06-17解决）：新增`api/modules/funnel.py`（`FunnelModule`，category=
  转化/留存），按 user_id 启发式识别各阶段（列名关键词+该列是否非空），输出
  阶段人数/环比转化率，已注册进默认分析流程。详见CHANGELOG.md 2026-06-17续4。

- ~~**AttributionModule遇分类自变量直接500崩溃**~~（2026-06-20线上测试场景7发现，
  2026-06-20修复）：`api/modules/attribution.py`的`run()`新增`_binary_encode()`
  （非数值dependent_column恰好2个取值时映射0/1，否则降级为全表第一个数值列）+
  对非数值independent_columns做one-hot展开（高基数列>15取值时跳过）。生产环境
  用原复现config（5表钱包数据集，`{dependent_column:"loan_result",
  independent_columns:["channel","risk_tier","credit_score","is_blacklist"]}`）
  对真实crash数据重跑确认不再抛`TypeError`，能正确算出`channel_wallet`/
  `risk_tier_高`等one-hot因子。详见CHANGELOG.md。

- ~~**清洗计划LLM补充op生成时看不到字段实际取值，业务特定同义值标准化会漏掉**~~
  （2026-06-20线上测试场景5发现，2026-06-20修复）：`generate_transform_plan()`/
  `_llm_supplementary_ops()`新增`diagnosis`参数，按`original_name`查Node1诊断的
  `sample_values`补充进prompt，要求LLM映射必须基于真实取值。生产环境用5表钱包
  数据集重跑确认`event_name`正确生成`{"touch_click":"tap","click_event":"click"}`
  等基于真实取值的mapping（此前完全被跳过）。详见CHANGELOG.md。

### 待解决

（当前无）

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
- **WeasyPrint 系统依赖（已废弃，2026-06-19决策：除非以后明确要做PDF导出，否则不再保留为TODO）**：
  产品方向已改为HTML报告直出（Minerva综合结论也是HTML，详见`api/templates/minerva_conclusion.html.j2`），
  以下历史记录仅供日后真要重新启用PDF时参考，不在当前待办范围内。
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
- **`/stream` 防重入仅限同一进程（MemorySaver 内存状态）**：进程重启后 MemorySaver
  清空，`graph.get_state()` 返回空 tasks，防重入检查失效。重启后同一 session_id
  再次调用 `/stream` 会重新执行全流程（node0透传→node1→node2 interrupt），
  之前已执行但 state 丢失的结果无法恢复。详见 MemorySaver 持久化债务。
- **腾讯云服务器内存限制**：empirical-agent 已在同一服务器上因 1.9GB 内存触发过 OOM
  （见 empirical-agent `docs/DEBT.md`）。本项目若与 empirical-agent 共用服务器，
  Pandas 处理大 CSV + WeasyPrint 渲染 PDF 可能进一步加剧内存压力，需在部署前评估
  是否需要限制上传文件大小或升级服务器内存。
