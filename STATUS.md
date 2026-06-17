# 开发状态

## 已完成

- [x] 项目文档初始化：`CLAUDE.md`、`CHANGELOG.md`、`STATUS.md`、`DEBT.md`、
      `docs/PRD.md`、`docs/ARCHITECTURE.md`（2026-06-15）
- [x] 后端 `requirements.txt`、前端 `package.json` 骨架（2026-06-15）
- [x] 确认 Node5 图表渲染方案：ECharts 服务端渲染（SVG）→ 嵌入 HTML → WeasyPrint
      转 PDF，chart_spec 采用标准 ECharts option 格式（2026-06-15，详见
      `docs/ARCHITECTURE.md` 第4/7节）
- [x] 确认后端端口 8001，写入 `api/.env.example`（2026-06-15）
- [x] `api/core/state.py`：`AnalysisState` TypedDict（2026-06-15）
- [x] `api/modules/base.py`：`BaseAnalysisModule` 抽象基类（2026-06-15）
- [x] `api/modules/registry.py`：`AnalysisRegistry`（2026-06-15）
- [x] Node1 数据诊断（`api/nodes/node1_diagnosis.py`）：Pandas 字段统计 + LLM 字段
      语义推断（`api/services/llm.py`，DashScope `deepseek-v4-flash`）+ 表级口径
      问题检测（疑似重复字段/命名冲突），LLM 不可用时降级但不阻断（2026-06-15）
- [x] FastAPI 最小入口（`api/main.py`）+ `/api/upload`（session 隔离）+
      `/api/analyze/{session_id}/stream`（SSE，事件格式
      `{"node","status","data"}`）+ `/health`（2026-06-15）
- [x] Node1 冒烟测试通过（2026-06-15）：本地起服务，上传9列含空值/命名不规范/
      重复字段的测试CSV，SSE两段事件格式正确，`null_rate`/`issues`/`table_issues`
      均正确标记，LLM字段推断（DashScope `deepseek-v4-flash`）返回真实结构化结果
      （`llm_available: true`）。`api/main.py` 新增 `load_dotenv()`，本地通过
      `api/.env` 加载 `DASHSCOPE_API_KEY`（已写入，`.gitignore` 已覆盖不会提交）
- [x] `api/core/graph.py`：LangGraph 图装配（Node1 -> Node2），使用 `MemorySaver`
      + `thread_id = session_id` 隔离会话；`api/core/schema.py` 定义
      `ConfirmedSchema`/`ColumnConfirmation`（Node2 -> Node3 契约，覆盖
      重命名/排除字段/缺失值填充或删除行/已解决的表级问题）（2026-06-15）
- [x] Node2 Human Confirmation：`interrupt()` 在诊断完成后暂停流程，
      `POST /api/analyze/{session_id}/confirm` 用 `Command(resume=...)` 恢复；
      SSE 推送 `confirmation`/`waiting_confirmation`（携带诊断数据供前端展示）
      与 `confirmation`/`confirmed`（回显 `confirmed_schema`）（2026-06-15）
- [x] Node1+Node2 端到端冒烟测试通过（2026-06-15）：upload -> stream
      （running -> diagnosis done -> waiting_confirmation） -> confirm（9 列，
      含 include/drop/fill/drop_rows 混合策略 + resolved_table_issues） ->
      confirmed 事件正确回显；未处于中断状态时调用 `/confirm` 与对不存在的
      session 调用均正确返回 `confirmation/error`。新建专属 `api/venv`
      （与 empirical-agent 的 venv 分离），`requirements.txt` 中 `pydantic`
      约束放宽为 `>=2.9`（解决与 `langgraph`/`langchain-core` 的依赖冲突）

- [x] Node3 确定性清洗引擎（2026-06-15）：`docs/ARCHITECTURE.md` 第3.3节确认
      9类操作枚举（确定性4类 + LLM补充5类，固定执行顺序），
      `api/nodes/node3_transform.py` 实现固定 `op_*` 函数集合，
      `api/core/graph.py` 接入为 `node1 -> node2 -> node3 -> END`，
      `api/routes/analyze.py` 的 `/confirm` SSE 新增 `transform/done` 事件。
      手动冒烟测试通过（rename/standardize_categories/fillna/drop_duplicates
      端到端跑通，cast_type 的 coerce 降级与未知op报错单独验证）
- [x] Node4 分析模块（第一批，2026-06-15）：`api/modules/base.py`/
      `registry.py` 确认与架构文档一致；新增 `api/modules/trend.py`
      （`TrendInsightModule`，趋势/时序）与 `api/modules/comparison.py`
      （`ComparisonModule`，对比/分组），均通过单模块冒烟测试，
      `chart_spec` 输出为合法 ECharts line/bar option
- [x] Node4 分析模块（第二批，2026-06-15）：新增 `api/modules/segmentation.py`
      （`SegmentationModule`，用户/人群，按数值指标分群+pie chart_spec）与
      `api/modules/attribution.py`（`AttributionModule`，贡献/驱动因素，
      标准化OLS回归贡献占比+bar chart_spec），均通过单模块冒烟测试；
      `statsmodels`/`scipy` 已安装到 `api/venv`
- [x] Node4 主流程 + VisualizationModule（2026-06-15）：`api/modules/registry.py`
      新增 `default_registry`（注册 Trend/Comparison/Segmentation/Attribution/
      Prediction）；新增 `api/modules/prediction.py`（空壳）与
      `api/modules/visualization.py`（chart_spec 默认值补全）；新增
      `api/nodes/node4_analysis.py`，`api/core/graph.py` 接入为
      `node3 -> node4 -> END`，`/confirm` SSE 新增 `analysis/done` 事件
- [x] Node5 叙事 + 置信度 + PDF（2026-06-15）：新增 `api/nodes/node5_report.py`
      （置信度三维度规则计算 + LLM三段式洞察生成，LLM不可用时降级）与
      `api/templates/report.html.j2`（含置信度徽标、中文字体声明、图表占位）；
      `api/core/paths.py`/`state.py` 新增 `report_path`；`api/core/graph.py`
      接入为 `node4 -> node5 -> END`；新增 `GET /api/report/{session_id}/pdf`。
      WeasyPrint 在本地 Windows 因缺 GTK 系统库无法加载，已做成延迟导入+降级
      （`pdf_generated=False`，不阻断流程），详见 `DEBT.md`（含部署到Linux所需
      apt依赖与中文字体包）
- [x] 前端 Step①：项目初始化 + 上传 + SSE 流程进度骨架（2026-06-15）：
      `pnpm install`（与 empirical-agent 保持一致），新增 `next.config.js`/
      `.env.local`/`.env.example`/`pages/_app.js`/`pages/index.js`；浏览器
      （Playwright + 系统 Chrome）验证上传 30 行测试 CSV 后流程进度列表与
      "等待口径确认"区块均正常渲染，无控制台报错
- [x] 前端 Step②③④（2026-06-15）：新增 `components/ConfirmationForm.js`
      （Node2口径确认：字段含义可编辑、问题字段高亮、表级问题勾选确认）与
      `components/AnalysisReport.js`（Node4图表渲染 + 置信度徽标 +
      三段式洞察 + PDF下载区块）；`pages/index.js` 接入两个组件，新增
      基于 `fetch()`+`ReadableStream` 的 POST SSE 解析处理
      `/api/analyze/{session_id}/confirm` 的完整事件流；后端
      `node5_report.py`/`graph.py`/`routes/analyze.py` 同步补充
      `narrative`/`pdf_generated` 字段。Playwright 端到端验证通过：
      上传->确认表单->清洗/分析/报告全流程SSE事件、4个模块ECharts图表
      （4个canvas）、置信度徽标、三段式文字、PDF"暂未生成"提示均正常渲染
- [x] 报告输出由 PDF 改为 HTML 直出（2026-06-15）：新增
      `GET /api/report/{session_id}/html`（从LangGraph state读取
      `report_html`），`AnalysisReport.js`"下载PDF"按钮改为"查看完整报告"
      （`window.open`新标签页）；`node5_report.py` 的 `_write_pdf()`
      调用整段注释、`pdf_generated`固定`False`，PDF路由保留但不产出文件。
      Playwright验证：新标签页正确展示报告HTML（置信度徽标/三段式文字/
      图表占位）
- [x] 前端 Step0/Step4/Step7 占位界面（2026-06-15续13）：新增
      `components/ClarificationChat.js`/`TransformPreview.js`/
      `FollowupChat.js`，`pages/index.js` 接入完整流程（澄清->上传->
      口径确认->清洗预览->分析报告->追问），接口地址写死、调用失败不
      阻断。`pnpm dev` 验证编译通过、无控制台报错。后续接入真实接口时
      需替换为后端实际的事件名/路径
- [x] 后端 Node0/Node3预览确认/Node6（设计阶段实现，未接入
      `api/core/graph.py`，2026-06-15续14）：新增
      `api/nodes/node0_clarification.py`（`run_clarification`，对话式
      澄清≤3轮，输出 `analysis_goal`）、`api/nodes/node3_preview.py`
      （`generate_transform_plan`/`run_preview`，复用 `node3_transform`
      内部函数生成清洗plan但不执行；`node3_preview(state)`含`interrupt()`
      仅为未来图接入预留）、`api/nodes/node6_followup.py`
      （`run_followup`，LLM判断追问可否用现有数据回答，可回答时复用
      `default_registry`+Node5叙事逻辑追加报告章节）；`state.py`新增
      `analysis_goal`/`transform_plan`/`followup_history`；
      `registry.py`新增`get_module(name)`；新增
      `api/core/session_state.py`（JSON文件持久化新增字段）与
      `api/routes/v03.py`（`/api/clarify/*`、
      `/api/analyze/{session_id}/transform/preview|confirm`、
      `/api/analyze/{session_id}/followup*`），`main.py`注册新路由。
      curl端到端验证：澄清3轮收敛、清洗plan预览/确认（含取消/空plan/
      未预览即确认404）、追问可回答/不可回答两条路径均正常

## 进行中

- （无，等待用户确认下一步）

## 最近完成（2026-06-17 续3，自动化QA Loop）

- [x] Playwright自动化QA Loop（`test_output/qa_loop.js`）跑通5表Join场景全流程
      Path A-F，发现并修复4个bug（详见CHANGELOG.md）：多表上传错误纵向拼接致诊断
      错位、Step0澄清渲染丢失、join后维度属性被误sum累加致结论失真（含一个独立的
      qcut NaN分组潜伏bug）、口径确认时间线状态卡死。连续2轮全部Path pass后收尾，
      已部署验证（`bash scripts/deploy.sh`）。报告质量人工抽查4/4维度合格。

## 最近完成（2026-06-17 续）

- [x] 部署脚本 `scripts/deploy.sh`（2026-06-17）：`git archive` 经 SSH 直传服务器解压
  （绕开服务器访问 GitHub HTTPS 经常超时的问题）+ 远程装依赖/构建/PM2重启/健康检查，
  已用于本次 Join 方案确认 bug 修复的实际部署并验证通过。后续代码改动部署只需
  `bash scripts/deploy.sh`

## 最近完成（2026-06-17）

- [x] Node2 Join 方案确认 bug 修复（2026-06-17）：审查 codex 新增的 Join 方案确认中断
  发现 `AnalysisState` 缺少 `session_id` 字段声明，LangGraph 静默丢弃 schema 外的 key
  导致多表 join 方案生成一直读错目录（功能实际未生效，已用最小复现脚本验证）；
  `api/core/state.py` 补字段修复。同时给单表上传场景跳过 Join Phase 2/3 的
  `interrupt()`，避免强制多走一轮无意义确认。

## 最近完成（2026-06-16）

- [x] 澄清流程发消息后直接跳上传的 bug 修复（2026-06-16）：`api/routes/v03.py`
  `clarify_stream` 改为按 `analysis_goal` 是否有值返回 `reply`/`done` 两种状态；
  `components/ClarificationChat.js` 增加 `analysis_goal` 非空才调 `onComplete` 的保护。
  服务器同步重新 build + pm2 restart。

- [x] 腾讯云部署完成（2026-06-16）：文件传输 → python3.10-venv + fonts-noto-cjk →
  `api/venv` + pip install → `api/.env`/`.env.local` → pnpm build → PM2 进程
  (`insight-api`:8001, `insight-web`:3002) → Nginx 监听 3001 代理 → 腾讯云安全组
  开放 3001 端口。**访问地址：`http://175.178.91.42:3001`**，health/前端均 200 验证通过。

- [x] Node0/Node3预览/Node6 接入 `api/core/graph.py`（2026-06-16）：
  图结构更新为 node0→node1→node2(interrupt)→node3_preview(interrupt)→
  node3_transform→node4→node5→node6(interrupt self-loop)→END；
  node0 读取 `analysis_goal` 透传；node6 单次 interrupt+self-loop 保证
  每轮追问后 state 正确写入 checkpoint；`/confirm` 推 `transform/waiting_preview`；
  `/transform/confirm` 改 StreamingResponse；`/followup` 走图 resume；
  `upload.py` 接收 `analysis_goal` FormData 字段；前端 `handlePrepareTransform`/
  `handleRunPipeline` 重写对接真实 SSE 流；curl 端到端验证全流程通过
- [x] Playwright E2E 全流程端到端验证通过（2026-06-16）：Step0澄清→上传→SSE进度
  →口径确认→清洗预览→分析报告（4 ECharts图表+置信度徽标+三段式叙事+完整报告HTML）
  →追问对话，7个步骤全部通过；同步修复 node0_clarification 改纯透传、
  node4 各模块异常隔离、v03.py clarify_stream node名修正、e2e_test.js waitForFunction
  参数错误等 4 项 bug

## 待开始

### 后端
- [ ] `api/render/`：Node.js 子进程 ECharts SVG 渲染器（`render_chart.js` +
      `package.json`），接入后替换 `report.html.j2` 中的图表占位区
- [ ] WeasyPrint PDF 生成的实际验证：本地 Windows 需安装 GTK3 Runtime，或
      直接在腾讯云 Linux 部署环境验证（含中文字体包）

### 后端（PRD v0.3 新增，docs/ARCHITECTURE.md 已补充设计）
- [x] Node0 问题澄清（`node0_clarification.py`，2026-06-15续14，设计阶段
      实现）：对话式澄清（≤3轮）输出 `analysis_goal`，
      `/api/clarify/*` 接口已实现（独立于graph）
- [x] Node3 清洗计划预览确认（3.4节，`node3_preview.py`，2026-06-15续14，
      设计阶段实现）：plan 生成后写入 `session_state.json`，
      `/api/analyze/{session_id}/transform/preview|confirm` 已实现
      （`node3_preview(state)`含`interrupt()`但未接入graph.py）
- [x] Node5 置信度标注（5.1节）：已在 `node5_report.py` 实现
      （三维度规则计算 `confidence`，写入报告模板）
- [x] Node6 追问对话（`node6_followup.py`，2026-06-15续14，设计阶段实现）：
      现有数据增量分析追加报告 / 需要新数据时引导补传，
      `/api/analyze/{session_id}/followup*` 已实现


- [x] Node2 Join方案确认中断点（2026-06-17）：`api/core/schema.py` 新增 JoinPlan 相关

- [x] 会话摘要机制（2026-06-17）：`scripts/_TEMPLATE.md` + `scripts/generate_summary.py` + `sessions/` 目录，`AGENTS.md` 新增规则章节，`/summary` 指令触发，格式与 Claude Code 摘要统一
      TypedDict/Pydantic 模型；`api/core/state.py` 新增 `proposed_join_plan`/
      `confirmed_join_plan`/`merged_data_path`；`api/nodes/node2_confirmation.py`
      双阶段确认（字段口径 → join方案）；`POST /api/analyze/{session_id}/confirm/join`
      路由；`node3_transform.py` 固定 `pd.merge()` 执行 join；`node4_analysis.py`
      优先读 `merged_data_path`；`pages/index.js` 新增 join 确认状态与时间线节点；
      `components/JoinPlanForm.js` 新建 join 方案编辑组件

- [ ] Node0/Node3预览/Node6 接入 `api/core/graph.py`（当前为独立路由+
      `session_state.json`，需设计 `clarification_history`/
      `transform_plan`/`followup_history` 如何随主流程checkpoint流转，
      `node3_preview(state)`的`interrupt()`接入后需打通与
      `node2_confirmation`/`node3_transform`的衔接，approved=false时
      流程走向待与前端交互一起确定）

### 前端
- [x] 文件上传组件（2026-06-15，Step①）
- [x] SSE 流程进度展示（2026-06-15，Step①）
- [x] Node2 口径确认交互界面（含字段含义可编辑输入框）（2026-06-15，Step②）
- [x] Node4 结果展示（ECharts图表）（2026-06-15，Step③）
- [x] 报告预览 + PDF 下载（2026-06-15，Step④）

### 前端（PRD v0.3 新增）
- [x] Step0 问题澄清对话界面（2026-06-15续13，占位接口）
- [x] Step4 清洗计划预览确认界面（2026-06-15续13，占位接口）
- [x] 报告置信度徽标渲染（高/中/低 + 警示样式）（Step③已实现）
- [x] Step7 追问对话框（2026-06-15续13，占位接口；报告动态追加展示待接入真实接口）

### 部署
- [ ] 服务器安装 Node.js 运行时（供 `api/render/` SSR 子进程使用，与前端共享）
- [ ] 腾讯云 PM2 进程配置（端口 8001）+ Nginx 路由
- [ ] 前端 Nginx 静态托管配置

## 用户体验优化 Round 1（2026-06-16 已完成批次）

### P0 — 已修复
- [x] **#2 类型转换报错**：`op_cast_type` + `run_transform` 执行循环加 try/except，
      失败时跳过该列/操作不再 502
- [x] **#2 Nginx timeout**：`/etc/nginx/sites-available/insight-agent` 中
      `proxy_read_timeout 300s → 600s`，已热重载（2026-06-16）

### P1 — 核心体验（已完成小改同批）
- [x] **#3 流程进度中文化**：`pages/index.js` 新增 `NODE_LABELS`/`STATUS_LABELS` 映射
- [x] **#5 "已处理已知晓"改文案**：改为"我已了解，忽略此问题继续分析"
- [x] **#9 清洗预览可读性**：`TransformPreview.js` op → 中文标签 + 自然语言描述
- [x] **#7 提交后过渡反馈**：`confirmPhase` 区分两阶段，口径确认后显示"正在准备清洗计划..."
- [x] **#6 字段处理透明化**：`ConfirmationForm.js` 实时显示字段预计操作说明

### P1 — 大改（已完成）
- [x] **#1 多文件上传**：`upload.py` 改 `List[UploadFile]` + pd.concat 合并为单 raw.csv；
      前端 `<input multiple>` + 多文件提示；下游节点无需改动

### P2 — 体验增强（已完成，2026-06-16）
- [x] **#8 运行动效 + 预估时间**：进度时间线 spinner 动画 + 诊断约10s/清洗约15s/分析约30s/报告约20s
- [x] **#4 UI 整体美化**：`styles/globals.css` CSS变量 + `.ia-card`/`.btn-*`/`.ia-spinner`；
      粘性 Header 品牌栏；5个组件卡片阴影统一；按钮 hover 效果

