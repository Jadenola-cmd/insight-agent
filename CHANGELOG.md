# CHANGELOG

只追加，不删旧内容。回溯历史时手动提供给 Claude。

---

## 2026-06-17（续2）

### 部署脚本 + 本次部署

- 新增 `scripts/deploy.sh`：`git archive HEAD` 通过 SSH 直接打包传到腾讯云服务器解压
  （服务器侧 `git pull` GitHub HTTPS 经常超时，疑似GFW间歇性干扰，改用此方式绕开
  服务器出网依赖），再远程 `pip install` + `pnpm install && pnpm build` +
  `pm2 restart insight-api insight-web` + 健康检查
- 用该脚本完成 Join 方案确认 bug 修复的实际部署，`http://175.178.91.42:3001` 验证
  前端 200，后端 `/health` 本地 curl 200 OK

## 2026-06-17（续）

### Node2 Join 方案确认 bug 修复

- `api/core/state.py`：`AnalysisState` 补充 `session_id: str` 字段。问题：LangGraph
  会静默丢弃 schema 之外的 key，`_initial_state()` 传入的 `session_id` 一直没声明在
  TypedDict 里，导致 `node2_confirmation.py` 内 `state.get("session_id", "")` 永远拿到
  空字符串，多表 join 方案生成全部读错目录（自动降级成单表分支），功能实际未生效。
  已用最小复现脚本验证 LangGraph 丢弃额外 key 的行为，修复后 graph 编译通过
- `api/nodes/node2_confirmation.py`：单表上传场景（`tables/` 目录下只有 1 个文件）
  直接返回空 join plan，跳过 Phase 2/3 的 `interrupt()`，避免单表用户被迫多走一轮
  无意义的"选主表才能确认"步骤

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

## 2026-06-17

### Node2 Join方案确认中断点

- `api/core/schema.py`：新增 `JoinEntry`/`JoinPlan` TypedDict 和 `JoinEntryRequest`/`JoinPlanRequest` Pydantic 模型
- `api/core/state.py`：新增 `proposed_join_plan`/`confirmed_join_plan`/`merged_data_path` 三个字段
- `api/core/paths.py`：新增 `merged_data_path()` helper
- `api/nodes/node2_confirmation.py`：新建双阶段确认节点
  - Phase 1：字段口径确认（interrupt 推送 diagnosis）
  - Phase 2：LLM 生成 join_plan 提案，interrupt 推送 `join_plan` + `table_columns`
  - LLM 规则：行数最多的事实表做主表、事实表间 left join、维度表 left join 补充属性
  - LLM 不可用时降级：全 left join，主表选行数最多的，key 用 user_id
- `api/core/graph.py`：`node2_confirmation` 改用 `run_node2_confirmation()`，`node3_transform`/`node4_analysis`/`node5_report`/`node6_followup` 优先使用 `merged_data_path`
- `api/routes/analyze.py`：
  - `_initial_state()` 新增 join 相关字段和 `session_id`
  - `POST /api/analyze/{session_id}/confirm` SSE 新增 `join_plan/waiting_confirmation` 事件处理
  - 新增 `POST /api/analyze/{session_id}/confirm/join` 路由，提交 join 方案确认
- `api/routes/upload.py`：多文件上传时额外保存每个文件到 `tables/` 子目录（供 join 使用）
- `api/nodes/node3_transform.py`：
  - `run_transform()` 新增 `join_plan`/`merged_data_path` 参数
  - 新增 `_execute_join_plan()`：固定 `pd.merge()` 调用，严禁 eval/exec
  - 清洗前先执行 merge，结果写入 `merged_data_path`
- `pages/index.js`：新增 `waiting_join_confirm` 状态和 `handleConfirmJoin` 处理函数，时间线新增"多表关联"节点
- `components/JoinPlanForm.js`：新建 join 方案确认组件，支持主表选择、新增/删除 join 行、编辑关联键和 JOIN 方式，展示各表可用字段列表
## 2026-06-16

### P2 UI 美化 + 运行动效（#4 + #8）

- 新增 `styles/globals.css`：CSS 变量（颜色/圆角/阴影）、`.ia-card`、`.btn`/`.btn-primary`/
  `.btn-outline`/`.btn-ghost`、`.ia-spinner`（旋转动画）、`.ia-pulse`；`_app.js` 导入
- `pages/index.js` 重构：粘性 Header + 品牌 Logo；流程进度改为时间线（进行中显示
  spinner + 预估时间，完成显示绿色✓，等待显示⏸，失败显示✕）；过渡等待卡片显示
  spinner；卡片/按钮使用 CSS 类
- 5 个组件（`ClarificationChat`/`ConfirmationForm`/`TransformPreview`/
  `AnalysisReport`/`FollowupChat`）：移除 `style.card` 改用 `.ia-card`；
  按钮改用 `.btn-primary`/`.btn-outline`/`.btn-ghost`；移除"Step0 ·"等前缀标签；
  输入框改用 `.ia-input` 风格

### P0 #2 Nginx timeout

- `/etc/nginx/sites-available/insight-agent`：`proxy_read_timeout 300s → 600s`，`nginx -s reload` 热重载

### P1 #1 多文件上传

- `api/routes/upload.py`：接收参数改为 `List[UploadFile]`，用 `pd.concat` 纵向合并
  多文件后存为单个 `raw.csv`，下游节点（node1~node6）无需任何改动；
  返回值增加 `file_count`/`row_count` 字段
- `pages/index.js`：`<input multiple>` 支持多选，`files` 状态改为数组，
  `FormData` 循环 append；多文件时显示"已选 N 个文件，将纵向合并"提示

### 用户体验优化 Round 1（P0 + P1 小改批次）

- **P0 #2 类型转换报错修复**：`api/nodes/node3_transform.py` `op_cast_type` 全函数包 try/except，
  转换失败时打印日志并跳过该列（原来直接抛异常导致 502）；`run_transform` 执行循环同样加
  try/except，单个操作失败不阻断后续清洗步骤
- **P1 #3 流程进度中文化**：`pages/index.js` 新增 `NODE_LABELS`/`STATUS_LABELS` 映射表，
  进度列表展示中文节点名和状态名（diagnosis/transform/analysis/report 等）
- **P1 #5 表级问题文案**：`components/ConfirmationForm.js` 勾选框文案由"已处理/已知晓"
  改为"我已了解，忽略此问题继续分析"，问题描述与勾选框分行展示
- **P1 #6 字段预计操作说明**：`ConfirmationForm.js` 新增 `getOperationHint(col)`，
  在每个字段下实时显示当前设置对应的操作预览（重命名/空值填充/删除行/排除列）
- **P1 #7 提交过渡反馈**：`pages/index.js` 新增 `confirmPhase` 状态区分两个确认阶段；
  口径确认后过渡提示由"正在清洗数据..."改为"口径已确认，正在准备清洗计划..."
- **P1 #9 清洗预览可读性**：`components/TransformPreview.js` 新增 `describeOp`/`OP_LABELS`，
  将 op 英文 key 映射为中文标签并生成自然语言描述（重命名/填充空值/去重等）

> Nginx `proxy_read_timeout` 300s → 600s 需在服务器执行，见下方说明

### 澄清流程跳转 bug 修复

- `api/routes/v03.py`：`clarify_stream` 根据 `analysis_goal` 是否有值决定返回
  `status: "reply"`（LLM 仍在追问）或 `status: "done"`（目标已确认），原来永远
  返回 `"done"` 导致发完第一条消息就跳到上传步骤
- `components/ClarificationChat.js`：`onmessage` 中增加 `analysis_goal` 非空保护，
  避免 `status === "done"` 但目标为空时误触发 `onComplete`

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

### InsightAgent 部署到腾讯云服务器

- 文件传输：本地打包（排除 venv/node_modules/.next/api/data）→ scp → 服务器解压到 `/www/insight-agent`
- 系统依赖：`python3.10-venv`、`fonts-noto-cjk`
- Python 环境：`api/venv` 虚拟环境 + `requirements.txt` 全量安装
- 环境变量：`api/.env`（DASHSCOPE_API_KEY/API_PORT=8001）、`.env.local`（NEXT_PUBLIC_API_URL）
- 前端构建：`pnpm install && pnpm build`（Next.js 14 静态优化通过）
- PM2 进程：`insight-api`（uvicorn:8001）+ `insight-web`（next:3002），已 `pm2 save` + systemd 自启
- Nginx：`/etc/nginx/sites-enabled/insight-agent`，监听 3001，`/api/*`→8001，`/`→3002，与 empirical-agent（80端口）共存
- 腾讯云安全组：开放 TCP 3001 入站规则
- 验证：`http://175.178.91.42:3001/health` → `{"status":"ok"}`，前端 HTTP 200

**访问地址：`http://175.178.91.42:3001`**

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

### Playwright E2E 全流程验证通过

**修复内容**
- `api/core/graph.py`：`node0_clarification` 改为纯透传（去除 interrupt 循环），
  澄清流程完全由 v03.py 独立路由处理，graph 只读 `analysis_goal` from state
- `api/routes/v03.py`：`clarify_stream` SSE 事件 node 名从 `node0_clarification`
  改为 `clarification`，与 ClarificationChat.js 的 done 判断匹配
- `api/nodes/node4_analysis.py`：每个分析模块加 try/except 隔离，单模块异常
  记录 error 字段并跳过，不阻断整体分析流程
- `e2e_test.js`：修复 `waitForFunction` 调用参数错误（第二参数是 arg 不是 options，
  正确传参方式为第三参数），修复口径确认 h2 文本匹配（"等待口径确认"）

**E2E 验证结果（全流程通过）**

| 步骤 | 状态 |
|------|------|
| Step0 澄清对话框渲染 + 消息发送 + 完成澄清 | ✓ |
| Step1 上传 + SSE 进度 + diagnosis/done | ✓ |
| Step2 口径确认表单渲染 + 提交 | ✓ |
| Step4 清洗计划预览（5条操作）+ 确认执行 | ✓ |
| Step3/5 report/done + 4个ECharts图表 + 置信度 + 三段式叙事 + 完整报告HTML | ✓ |
| Step7 追问对话框渲染 + 追问发送 | ✓ |
| 控制台错误 | 1条（PDF 404，符合预期） |

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

### Node0/Node3预览/Node6 接入 LangGraph graph.py

**后端**
- `api/core/state.py`：新增 `transform_approved: bool`、`followup_history: bool`（`followup_done: bool`）字段
- `api/core/graph.py`：完整重构，图结构更新为
  `node0 → node1 → node2(interrupt) → node3_preview(interrupt) → node3_transform → node4 → node5 → node6(interrupt, self-loop) → END`；
  node0 先检查 `analysis_goal` 是否已预设（v03.py 流程写入），是则透传，否则进入多轮 interrupt 澄清；
  node6 采用单次 interrupt + 条件 self-loop 设计，确保每次追问后 state 写入 checkpoint
- `api/routes/analyze.py`：`_initial_state()` 从 `session_state.json` 读取 `analysis_goal`；
  `/stream` 加防重入保护；`/confirm` SSE 流在 node3_preview interrupt 处推送 `transform/waiting_preview` 事件并结束
- `api/routes/v03.py`：`/transform/confirm` 改为 StreamingResponse，恢复 node3_preview interrupt 并推送后续 node3→node6 事件；
  `/followup` POST 优先走图 interrupt resume（`Command(resume=message)`），回退到直接 `run_followup()` 兼容旧 session
- `api/routes/upload.py`：接受可选 FormData 字段 `analysis_goal`，写入 `session_state.json` 供 node0 读取

**前端**
- `components/TransformPreview.js`：`handleConfirm` 去掉自己的 fetch，直接调 `onConfirm?.()` 让父组件处理流
- `pages/index.js`：提取 `readSseStream()` 工具函数；
  `handlePrepareTransform` 改为调 `/confirm` SSE 并在 `transform/waiting_preview` 时展示 TransformPreview（真实 plan）；
  `handleRunPipeline` 改为调 `/transform/confirm` SSE 处理 transform→analysis→report→followup 事件；
  新增 `analysisGoal` state，从 ClarificationChat `onComplete(goal)` 获取并在上传时随 FormData 传给后端

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

## 2026-06-15（续14）

**后端新增 Node0/Node3预览确认/Node6 三个设计阶段节点（未接入 graph.py）**

- `api/core/state.py`：`AnalysisState` 新增 `analysis_goal: str`/
  `transform_plan: list`/`followup_history: list`（仅作为未来接入图时的
  state契约参考，当前不经过 MemorySaver）。
- 新增 `api/nodes/node0_clarification.py`：`run_clarification(state)`，
  对话式问题澄清最多3轮，第3轮强制收敛输出 `analysis_goal`，
  LLM不可用时降级为直接采用用户输入。
- 新增 `api/nodes/node3_preview.py`：`generate_transform_plan`/
  `describe_plan`/`run_preview` 复用 `node3_transform.py` 的
  `_build_deterministic_ops`/`_llm_supplementary_ops`/`_order_plan`，
  生成带人类可读描述的清洗 plan 但不执行；另含 `node3_preview(state)`
  （含 `interrupt()`，仅为未来 graph 接入预留，当前路由不调用）。
- 新增 `api/nodes/node6_followup.py`：`run_followup(state)`，LLM判断追问
  能否用现有数据回答，可回答时复用 `default_registry`+
  `VisualizationModule`+`node5_report._generate_narrative` 生成补充分析并
  插入 `report_html`（`</body>`前），不可回答时返回 `data_request`。
- `api/modules/registry.py`：`AnalysisRegistry` 新增 `get_module(name)`
  按name查找（Node6按LLM判断结果定位模块）。
- 新增 `api/core/session_state.py`：JSON文件持久化
  （`api/data/<session_id>/session_state.json`），承载上述三个节点不经过
  graph checkpoint 的新增字段。
- 新增 `api/routes/v03.py` 并在 `api/main.py` 注册，实现
  `POST /api/clarify/{session_id}/message`、
  `GET /api/clarify/{session_id}/stream`、
  `GET /api/analyze/{session_id}/transform/preview`、
  `POST /api/analyze/{session_id}/transform/confirm`、
  `POST /api/analyze/{session_id}/followup`、
  `GET /api/analyze/{session_id}/followup/stream`。
  `api/core/graph.py` 未改动。
- curl 端到端验证通过：澄清对话3轮正确收敛 `analysis_goal`；
  清洗plan预览/确认（含 approved=false 取消、空plan/非空plan、未预览即确认的404）；
  追问对话可回答（追加报告章节+chart_spec）与不可回答（`data_request`）两条路径
  均正确写入 `session_state.json`。

## 2026-06-15（续13）

**前端新增 Step0/Step4/Step7 占位界面**

- 新增 `components/ClarificationChat.js`（Step0问题澄清对话）、
  `components/TransformPreview.js`（Step4清洗计划预览确认）、
  `components/FollowupChat.js`（Step7追问对话），三者均为UI占位，
  接口地址写死、调用失败不阻断流程（聊天/预览组件内置“跳过/完成”按钮
  保证流程可走通）。
- `pages/index.js` 接入完整流程：Step0澄清完成后才显示上传区；口径确认
  提交后先进入Step4清洗预览（`buildMockTransformPlan` 根据confirmedSchema
  生成占位计划），确认后才真正调用 `/confirm` 启动清洗/分析/报告流程；
  报告完成后底部追加Step7追问框。
- `components/AnalysisReport.js` 的“查看完整报告”按钮已在此前改为
  `window.open` 打开 `/api/report/{session_id}/html`（本次确认无需改动）。
- 本地 `pnpm dev`（端口3001）验证编译通过、首屏渲染Step0对话框，
  无控制台报错；未启动后端，接口调用报错均被忽略。

## 2026-06-15（续12）

**报告输出由 PDF 改为 HTML 直出**

- 新增 `GET /api/report/{session_id}/html`（`api/routes/analyze.py`）：从
  LangGraph state（`graph.get_state(config).values["report_html"]`）读取
  Node5生成的报告HTML，以 `text/html` 返回；state中无该字段时返回404。
- `api/nodes/node5_report.py`：`_write_pdf()` 函数体与调用整段注释（未删除），
  `pdf_generated` 固定返回 `False`；`report_path` 参数与
  `GET /api/report/{session_id}/pdf` 路由保留但不再产出文件，详见 `DEBT.md`。
- `components/AnalysisReport.js`："下载PDF报告"按钮改为"查看完整报告"，点击
  `window.open(${apiUrl}/api/report/${sessionId}/html, '_blank')`；
  `pages/index.js` 传入 `sessionId` prop。
- 端到端验证（Playwright + 系统Chrome）：上传->确认->分析报告区块出现后点击
  "查看完整报告"，新标签页正确打开 `/api/report/{session_id}/html`，置信度徽标、
  三段式文字、图表占位均正常显示。验证过程中发现新增路由未被uvicorn
  `--reload` 自动加载（reloader子进程未重启监听），手动重启进程后
  `openapi.json` 正确包含新路由，与本次代码改动无关。

## 2026-06-15（续11）

**前端 Step②③④ 完成：口径确认交互 + 分析结果展示 + 报告预览/PDF下载**

- 后端附加改动（为前端Step③④提供数据，非破坏性）：`api/nodes/node5_report.py`
  的 `run_report()` 返回的 `modules` 增加 `narrative` 字段；
  `api/core/graph.py` 的 `node5_report()` 将 `pdf_generated`/`llm_available`
  一并归入 `analysis_results.report`；`api/routes/analyze.py` 的
  `report/done` SSE 事件新增 `pdf_generated` 字段（`modules`/`pdf_url` 不变）。
- 新增 `components/ConfirmationForm.js`（Step②）：每个字段展示
  字段名/业务含义可编辑输入框、纳入分析勾选、缺失值处理策略选择；疑似问题字段
  （`issues` 非空）整行高亮（橙色左边框+底色），并列出表级口径问题供逐项勾选
  "已处理/已知晓"；提交时组装 `ConfirmedSchemaRequest` 调用 `onSubmit`。
- 新增 `components/AnalysisReport.js`（Step③④）：用
  `next/dynamic`（`ssr:false`）按需加载 `echarts-for-react` 渲染各模块
  `chart_spec`；置信度徽标按高/中/低显示对应颜色
  （#67c23a/#e6a23c/#f56c6c），并列出三维度判定依据；展示
  "结论/数据支撑/运营建议"三段式文字；底部PDF区块根据 `pdf_generated`
  显示下载链接或"本地环境缺少WeasyPrint依赖"提示。
- `pages/index.js`：接入上述两个组件；新增 `handleConfirm()` —— 因
  `/api/analyze/{session_id}/confirm` 是 POST 且返回 SSE 格式流，
  `EventSource` 不支持POST，改用 `fetch()` + `res.body.getReader()` +
  `TextDecoder` 手动按 `\n\n` 分割解析 `data: {...}` 事件，依次处理
  `confirmation/confirmed`、`transform/done`、`analysis/done`、
  `report/done`、`confirmation/error`。
- 端到端验证（Playwright + 系统Chrome，30行测试CSV）：上传 -> 诊断 ->
  口径确认表单正常渲染（含表级问题勾选、字段高亮）-> 点击"确认并开始清洗"
  -> 流程进度依次显示 confirmed/transform done/analysis done/report done ->
  分析报告区块4个模块（趋势/对比/人群/归因）的ECharts图表（4个canvas）、
  置信度徽标、三段式文字均正常渲染；PDF区块正确显示"暂未生成"提示
  （本地无WeasyPrint，符合预期）。验证过程中发现本地8001端口的uvicorn进程
  代码未热重载（仍是旧版本响应），手动重启后恢复正常，与代码本身无关。

## 2026-06-15（续10）

**前端 Step① 完成：项目初始化 + 上传 + SSE 流程进度骨架**

- 确认前端依赖版本与 empirical-agent 一致（Next.js 14.2.35 / React 18），统一
  使用 `pnpm`；`pnpm install` 完成，生成 `pnpm-lock.yaml`（echarts 5.6.0、
  echarts-for-react 3.0.6）。
- 新增 `next.config.js`、`.env.local`/`.env.example`
  （`NEXT_PUBLIC_API_URL=http://localhost:8001`），`.gitignore` 补充
  `.env.local`。
- 新增 `pages/_app.js`、`pages/index.js`：文件上传（FormData ->
  `POST /api/upload`）+ `EventSource` 订阅 `/api/analyze/{session_id}/stream`，
  按 `{node, status}` 展示流程进度列表；收到
  `confirmation/waiting_confirmation` 时关闭连接并展示诊断结果 JSON（口径确认
  交互界面留待 Step②）。
- 端到端验证：本地启动后端（`api/venv` 下 `uvicorn api.main:app --port 8001`）
  与前端（`pnpm dev`，3000端口）；用 Playwright（系统 Chrome，
  `chromium.launch({executablePath: ...})`，因官方 Chromium 未安装）驱动浏览器
  上传30行测试CSV，截图确认三个阶段均正常渲染：初始页 -> 上传后"流程进度"
  列表（diagnosis running/done -> confirmation waiting_confirmation）->
  "等待口径确认"区块展示诊断 JSON（中文正常显示），`console --errors` 为空。

## 2026-06-15（续9）

**Node4 主流程 + VisualizationModule + Node5 叙事/置信度/PDF**

Node4：
- `api/modules/registry.py` 新增 `default_registry` 单例，注册
  Trend/Comparison/Segmentation/Attribution/Prediction 五个模块
  （`PredictionModule` 为空壳，`validate` 始终 `False`）。
- 新增 `api/modules/prediction.py`：`PredictionModule` 空壳。
- 新增 `api/modules/visualization.py`：`VisualizationModule`，对 `chart_spec`
  做轻量默认值补全（`color`/`tooltip`/`legend`），不修改 `series`（CLAUDE.md
  约束5）。
- 新增 `api/nodes/node4_analysis.py`：`run_analysis()` 读取
  `cleaned_data_path`，遍历 `default_registry.get_runnable_modules()`，输出
  `{results: {module_name: {category, metrics}}, charts: {module_name: option}}`。
- `api/core/graph.py`：图扩展为 `... -> node3_transform -> node4_analysis -> END`。
- `api/routes/analyze.py`：`/confirm` SSE 新增 `analysis/done` 事件。
- 冒烟测试：构造30行模拟数据（日期+分类+用户ID+两个数值列），4个模块（Trend/
  Comparison/Segmentation/Attribution）均正确运行并输出合法 `chart_spec`；
  Prediction 正确被 `validate=False` 排除。

Node5：
- 新增 `api/nodes/node5_report.py`：
  - `_compute_confidence()`：按 `docs/ARCHITECTURE.md` 5.1节规则，对样本量/
    相关字段空值率/分析方法三维度分别评级，取最低值为最终置信度，`reasons`
    记录每维度依据；规则写死不经过LLM。
  - `_generate_narrative()`：调用 LLM 生成"结论-数据支撑-运营建议"三段式
    JSON；LLM 不可用时降级为基于 `metrics` 的通用文案，不阻断流程。
  - `run_report()`：组装 Jinja2 模板 `api/templates/report.html.j2`
    （含置信度徽标、图表 chart_spec 占位区），调用 `_write_pdf()` 转 PDF。
- 新增 `api/templates/report.html.j2`：A4 页面样式，`font-family` 按
  "Noto Sans CJK SC -> WenQuanYi Zen Hei -> Microsoft YaHei -> SimHei"声明
  （应对部署到 Linux 服务器的中文字体问题）；图表区域为占位（展示
  `chart_spec.title` + 原始 JSON），ECharts SSR 渲染待 `api/render/` 实现后接入。
- `api/core/paths.py` 新增 `report_pdf_path(session_id)`；`api/core/state.py`
  新增 `report_path` 字段。
- `api/core/graph.py`：图扩展为 `... -> node4_analysis -> node5_report -> END`。
- `api/routes/analyze.py`：`_initial_state` 写入 `report_path`；`/confirm` SSE
  新增 `report/done` 事件（携带各模块置信度摘要 + `pdf_url`）；新增
  `GET /api/report/{session_id}/pdf` 下载报告，文件不存在时返回404。
- **WeasyPrint Windows 阻塞问题**：本地 Windows venv 安装 `weasyprint==62.3`
  后，`from weasyprint import HTML` 因缺少系统级 Pango/Cairo/GDK-Pixbuf（GTK）
  报 `OSError: cannot load library 'gobject-2.0-0'`。处理为将该 import 延迟到
  `_write_pdf()` 内部并捕获 `OSError`：`report_html` 正常生成，
  `pdf_generated=False`，PDF 文件不写入，不阻断 Node1-5 主流程。详见
  `DEBT.md`（含部署到腾讯云 Linux 所需的 apt 依赖 + 中文字体包
  `fonts-noto-cjk`/`fonts-wqy-zenhei`）。
- 冒烟测试（沿用Node4的30行模拟数据，`amount`列人为制造3行空值）：
  - 置信度计算正确（30行 < 200 -> 样本量维度"低"，整体置信度取最低值"低"，
    `reasons` 文案正确）；
  - `_generate_narrative` 在当前测试脚本未加载 `DASHSCOPE_API_KEY`
    （`load_dotenv` 未执行）时正确降级为通用文案，`llm_available=False`；
  - `run_report()` 正常生成 `report_html`（含中文、置信度徽标、图表占位
    JSON），`pdf_generated=False`（符合预期，Windows 无 GTK）；
  - `api/main.py`/`api/core/graph.py` 均可正常导入，路由列表含
    `/api/report/{session_id}/pdf`。测试产物已清理。

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

## 2026-06-15（续8）

**Node4 分析模块：SegmentationModule + AttributionModule**
- 新增 `api/modules/segmentation.py`：`SegmentationModule`（用户/人群）。
  - `validate`：存在ID列（列名包含 id/user/customer/用户/客户/编号/会员/账号等
    关键词，或为高基数列：唯一值占比>50%）且存在数值列。
  - `run`：按ID列对数值列求和得到每个实体的指标值，按 rank + qcut 分为最多4个
    分群（低/中低/中高/高，实体数不足4时自动减少分群数），输出各群体的实体数/
    占比、指标总和/占比、人均值。
  - `get_chart_spec`：标准 ECharts pie option（各分群实体数占比）。
- 新增 `api/modules/attribution.py`：`AttributionModule`（贡献/驱动因素）。
  - `validate`：数值列数量≥2 且行数≥3。
  - `run`：选定因变量与候选自变量（最多5个，过滤零方差列），标准化（z-score）
    后做 OLS 回归（`statsmodels`），用标准化系数绝对值占比表示各自变量的相对
    贡献占比，输出 R² 与按贡献占比降序排列的 factors。预留接口注释：未来可替换
    为复用 empirical-agent 的 OLS/DID 基础设施。
  - `get_chart_spec`：标准 ECharts bar option（各自变量贡献占比，降序）。
- `requirements.txt` 中 `statsmodels==0.14.2`/`scipy==1.13.0` 补充安装到
  `api/venv`（此前未安装）。
- 手动冒烟测试通过：构造20个用户的消费数据验证 SegmentationModule（4分群正确、
  占比计算正确、chart_spec 为合法 pie option）；构造100行含明确线性关系
  （revenue = 2*ad_spend - 1.5*price + noise）的数据验证 AttributionModule
  （R²=0.995，ad_spend/price 贡献占比约52.6%/47.4%与系数符号符合预期，
  chart_spec 为合法 bar option）。测试脚本已清理。

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

## 2026-06-15（续7）

**Node4 分析模块：TrendInsightModule + ComparisonModule**
- 确认 `api/modules/base.py`（`BaseAnalysisModule`）与 `api/modules/registry.py`
  （`AnalysisRegistry`）已在此前会话完成，与 `docs/ARCHITECTURE.md` 第5节接口
  一致，无需改动。
- 新增 `api/modules/trend.py`：`TrendInsightModule`（趋势/时序）。
  - `validate`：存在可解析为日期的列（datetime dtype 或字符串列解析成功率
    ≥80%）且存在数值列。
  - `run`：自动选择日期列/数值列，按数据时间跨度自动判定聚合粒度
    （≤60天按天/≤730天按周/否则按月），按周期聚合求和，基于 z-score（|z|>2）
    检测异常点，用线性回归斜率 + 首尾变化率判断趋势方向（上升/下降/平稳）。
  - `get_chart_spec`：标准 ECharts line option，异常点通过 `series.markPoint`
    标注。
- 新增 `api/modules/comparison.py`：`ComparisonModule`（对比/分组）。
  - `validate`：存在分类列（唯一值数量 2~50）且存在数值列。
  - `run`：按分类列聚合（默认 sum）并按值降序排序，计算各分组占比，输出
    TOP5/BOTTOM3。
  - `get_chart_spec`：标准 ECharts bar option（按值降序）。
- 手动冒烟测试通过：构造含人为异常点的30天时序数据验证 TrendInsightModule
  （正确识别日期/数值列、按天聚合、检出异常点、chart_spec 为合法 line
  option）；构造4分组对比数据验证 ComparisonModule（分组排序、占比计算、
  chart_spec 为合法 bar option）。测试脚本已清理。

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

## 2026-06-15（续6）

**Node3 确定性清洗引擎**
- `docs/ARCHITECTURE.md` 第3.3节：设计并确认 Node3 plan 操作类型枚举
  （9类：rename_column/drop_columns/cast_type/strip_whitespace/
  standardize_categories/unit_convert/fillna/drop_rows_with_null/
  drop_duplicates），明确「确定性部分（由 confirmed_schema 推导）+
  LLM补充部分（仅5类，基于 business_meaning/resolved_table_issues）」
  两段式 plan 生成方式，以及与数组顺序无关的固定执行顺序。
- 新增 `api/nodes/node3_transform.py`：实现上述9个 `op_*` 固定函数
  （分发执行，无 eval/exec），`run_transform()` 读取 `raw_data_path`，
  执行 plan，写入 `cleaned_data_path`（parquet）。`cast_type` 转换失败
  统一走 `errors="coerce"` 转为 NaN/NaT，不中止流程；未识别的 op 直接
  报错中止。
- `api/core/paths.py` 新增 `cleaned_data_path(session_id)`。
- `api/core/graph.py`：图扩展为
  `node1_diagnosis -> node2_confirmation -> node3_transform -> END`。
- `api/routes/analyze.py`：`_initial_state` 改为按 `session_id` 生成
  `raw_data_path`/`cleaned_data_path`；`/confirm` 的 SSE 流新增
  `transform/done` 事件（携带最终 plan 与清洗后数据行列信息）。
- `requirements.txt` 新增 `pyarrow==16.1.0`（parquet 读写依赖）。
- 手动冒烟测试通过：构造含重命名/分类不统一写法/缺失值/重复行的测试CSV，
  `run_transform` 正确生成并按固定顺序执行 plan（rename → standardize_categories
  → fillna → drop_duplicates），输出 parquet 数据正确；`cast_type` 单独测试
  验证 int/datetime 转换失败正确转为 `NaN`/`NaT`，未知 op 正确报错中止。

---

## 2026-06-17

- 新增会话摘要机制：`scripts/_TEMPLATE.md`（模板）、`scripts/generate_summary.py`（生成脚本）、`sessions/`（输出目录）
- `AGENTS.md` 新增"会话摘要规则"章节，约定 `/summary` 触发指令，格式与 Claude Code 摘要统一（`YYYY-MM-DD_HHMM.md` + YAML frontmatter）

## 2026-06-15（续5）

**Node2 Human Confirmation（中断/恢复）**
- 新增 `api/core/schema.py`：定义 `ColumnConfirmation`/`ConfirmedSchema`
  （Node2 -> Node3 契约的 TypedDict）以及对应的 Pydantic 请求模型
  `ColumnConfirmationRequest`/`ConfirmedSchemaRequest`，覆盖字段重命名、
  是否纳入分析、缺失值处理策略（none/fill/drop_rows）+ 已解决的表级问题列表。
- 新增 `api/core/graph.py`：用 LangGraph `StateGraph` 装配
  `node1_diagnosis -> node2_confirmation -> END`，`node2_confirmation` 内
  调用 `interrupt({"diagnosis": ...})` 暂停流程；用 `MemorySaver` 作
  checkpointer，`thread_id = session_id` 隔离每个上传会话。
- 重写 `api/routes/analyze.py`：
  - `/api/analyze/{session_id}/stream` 改为驱动 `graph.stream(...)`，
    依次推送 `diagnosis/running` -> `diagnosis/done`（诊断结果） ->
    `confirmation/waiting_confirmation`（携带诊断数据供前端展示确认表单）
    后结束本次 SSE；
  - 新增 `POST /api/analyze/{session_id}/confirm`：校验
    `graph.get_state(config)` 是否处于中断状态，用
    `Command(resume=confirmed_schema)` 恢复流程，推送
    `confirmation/confirmed`（回显 `confirmed_schema`）。
- `requirements.txt`：`pydantic==2.7.1` 改为 `pydantic>=2.9`，解决与
  `langgraph==0.2.74`/`langchain-core==0.3.31` 的依赖解析冲突；新建本项目
  专属 `api/venv`（与 empirical-agent 的共享 venv 分离）并安装全部依赖。
- `docs/ARCHITECTURE.md`：Node2 章节改写为"中断点，已实现"，新增
  "3.2 confirmed_schema 结构（Node2 ↔ Node3 契约）"小节；`CLAUDE.md`
  文件结构树补充 `api/core/schema.py`/`api/core/graph.py`，更新
  `graph.py` 描述为"Node1→Node2中断，Node3-5待接入"。
- 端到端冒烟测试：本地起 `uvicorn`，完整跑通
  upload -> stream（running -> done -> waiting_confirmation） ->
  confirm（9 列，include/drop/fill/drop_rows 混合策略 +
  resolved_table_issues） -> confirmed 事件正确回显 `confirmed_schema`；
  额外验证两种错误路径（非中断状态下调用 confirm、对不存在 session 调用
  confirm）均正确返回 `confirmation/error`。测试产物（`api/data/`、
  uvicorn 进程、临时日志）已清理。
- `DEBT.md`：将 `MemorySaver` 的限制从"待验证风险"更新为已通过冒烟测试
  确认的事实——纯内存 checkpoint，进程重启会丢失处于 Node2 中断等待状态
  的会话，单 worker 部署可接受，后续如需持久化建议用 `SqliteSaver`。

## 2026-06-15（续4）

**Node1 冒烟测试**
- `api/main.py` 新增 `load_dotenv()`（依赖 `python-dotenv`，已在 requirements
  中），本地开发通过 `api/.env` 加载 `DASHSCOPE_API_KEY`；`api/.env` 已写入真实
  key（从腾讯云服务器 `/www/empirical-agent/api/.env` 取得，与 empirical-agent
  共用同一 DashScope key），文件已被 `.gitignore` 覆盖不会提交。
- 本地起 `uvicorn api.main:app --port 8001`，构造一份9列测试CSV（含空值、命名
  不规范的"Order Date"列、与`amount`完全一致的`amount_usd`重复列），完整跑通
  `/api/upload` → `/api/analyze/{session_id}/stream`：
  - SSE 两段事件（`running`/`done`）格式均为 `{"node","status","data"}`；
  - `null_rate`/字段级 `issues`/表级 `table_issues` 均正确输出（如"notes 空值率
    过高（90%）""amount 与 amount_usd 数据完全一致，疑似重复字段"）；
  - LLM 字段推断返回真实结构化结果（`llm_available: true`），包括对
    "Order Date" 命名风格不一致、`amount`/`amount_usd` 疑似冗余等口径问题的
    推断，质量符合预期。
- 测试用临时文件（`api/data/`）已清理。

## 2026-06-15（续3）

**Node1 数据诊断 + FastAPI 最小入口**
- 新增 `api/services/llm.py`：`chat_json()` 封装 DashScope `compatible-mode` 接口
  （模型 `deepseek-v4-flash`，`response_format: json_object`），未配置
  `DASHSCOPE_API_KEY` 或请求/解析失败时返回 `None`，调用方降级处理。
- 新增 `api/nodes/node1_diagnosis.py`：`run_diagnosis(raw_data_path)`：
  - Pandas 统计每列 `dtype`/`null_rate`/`unique_count`/`sample_values`，
    空值率 > 50% 标记为字段级 issue；
  - 表级检测：数据完全一致的列标记"疑似重复字段"，列名规范化后相同标记
    "疑似命名冲突"；
  - 将字段统计摘要发给 LLM，要求结构化输出 `inferred_meaning` + `issues` +
    `table_issues`；LLM 不可用时 `inferred_meaning` 标记为"AI推断暂不可用"，
    流程不中断。
- 新增 `api/core/paths.py`：`session_dir`/`raw_data_path`，按 `session_id` 隔离
  `api/data/` 下的文件。
- 新增最小 FastAPI 入口 `api/main.py` + 路由：
  - `POST /api/upload`：保存上传文件到 `api/data/<session_id>/raw.csv`，返回
    `session_id`；
  - `GET /api/analyze/{session_id}/stream`：SSE 推送诊断结果，事件统一格式
    `{"node": "diagnosis", "status": "running"/"done"/"error", "data": {...}}`；
  - `GET /health`：健康检查。
- 已用 empirical-agent 的 venv 验证 `api.main:app` 可正常导入、路由注册无误。
  尚未接入 LangGraph（当前 analyze 路由直接调用 Node1 函数，graph 装配与
  Node2-5 留待后续）。

## 2026-06-15（续2）

**代码骨架**
- 新增 `api/core/state.py`：`AnalysisState`（TypedDict，控制流/数据流分离，数据流
  字段只存路径）。
- 新增 `api/modules/base.py`：`BaseAnalysisModule` 抽象基类（`validate`/`run`/
  `get_chart_spec`）。
- 新增 `api/modules/registry.py`：`AnalysisRegistry`（`register`/
  `get_runnable_modules`），用于 Node4 自动判断可运行模块。
- 补充 `api/__init__.py`/`api/core/__init__.py`/`api/modules/__init__.py` 使其
  成为可导入的 Python 包。尚未实现任何具体分析模块。

## 2026-06-15（续）

**架构决策**
- 确认 Node5 图表渲染方案：ECharts 服务端渲染（SVG renderer + SSR）生成 SVG 字符串，
  嵌入 Jinja2 报告模板，WeasyPrint 转 PDF；`chart_spec` 直接采用标准 ECharts option
  格式，前端 `echarts-for-react` 与后端 SSR 复用同一份配置（`docs/ARCHITECTURE.md`
  第4/7节）。新增 `api/render/`（Node.js 子进程渲染器）规划。
- 确认后端服务端口为 8001（避开 empirical-agent 的 8000），写入 `api/.env.example`。

## 2026-06-15

**项目初始化**
- 新建 `business-analysis-agent` 项目（独立代码库，复用 empirical-agent 的项目文件结构规范）
- 完成文档初始化：`CLAUDE.md`（项目背景/技术栈/架构决策/五条核心约束/与 empirical-agent
  关系）、`CHANGELOG.md`、`STATUS.md`、`DEBT.md`、`docs/PRD.md`、`docs/ARCHITECTURE.md`
- 生成后端 `api/requirements.txt`（FastAPI、LangGraph、Pandas、statsmodels、WeasyPrint、
  Jinja2 等）与前端 `package.json`（Next.js 14 + ECharts）骨架
- 尚未编写任何业务代码，等待用户确认后开始第一阶段实现（`AnalysisState`/
  `BaseAnalysisModule`/`AnalysisRegistry`）

