# 开发状态

## 已完成

- [x] 生产环境LLM两条路径同时失效排查与修复（2026-06-19续8）：执行线上端到端测试
      场景1时发现假设树再次降级为占位文案，pm2日志（续7新加的`[llm._call]`日志，
      此时验证有效）显示Ark和DashScope同时失败。排查：①Ark
      `ark-code-latest`——用相同key+相近请求体分别从本地和生产服务器（IP
      175.178.91.42）直接curl对比，本地200成功、服务器侧网关层（istio-envoy）
      0.18s内直接拒绝返回纯文本`Bad Request`（非模型API的结构化错误），判定为
      火山方舟Coding Plan对该服务器出口IP的网关层限制/风控拦截，代码侧不可修复，
      需账号/控制台侧处理（未继续深挖，超出本次范围）；②DashScope
      `deepseek-v4-flash`——免费额度已耗尽（`AllocationQuota.FreeTierOnly`），
      经用户确认暂不切换付费。修复：`llm.py`的`DASHSCOPE_MODEL`改为`glm-5.1`
      （同一`DASHSCOPE_API_KEY`下不受免费层限制即可调用），且该模型同Ark一样
      不支持`response_format=json_object`，改为prompt约束输出JSON（与Ark
      处理方式一致）。已部署（commit`e04f024`）+ Playwright对生产环境重跑场景1
      验证：假设树生成5个具体假设（非占位），部署后pm2 error日志中`[llm._call]`
      零失败记录。Ark的IP限制问题仍未解决，但DashScope+glm-5.1作为主力路径已
      验证可用，不阻塞后续测试。详见CHANGELOG.md
- [x] 假设树生成偶发失败排查与修复（2026-06-19续7）：用户线上反馈假设树只生成1个
      占位假设，排查发现`llm.py`的`_call`异常处理静默吞掉所有异常不打日志，无法
      定位原因；SSH诊断脚本复现确认Ark/DashScope key均有效、Ark接口本身正常（拿
      同样的problem_card手动调用生成成功），判断为该session内连续多次LLM调用后的
      偶发限流/超时。修复：`llm.py`异常分支补充stderr日志（异常类型/HTTP状态码，
      不打印key）；`hypothesis_tree.py`的`generate_initial_ops`（单发关键步骤）
      失败后增加一次重试再降级为占位文案。已部署到生产环境（commit`5de58e9`，
      服务器HEAD一致，健康检查通过），下次会话按下方"线上端到端测试方案"验证
      实际效果。详见CHANGELOG.md
- [x] Minerva假设验证体验修复（2026-06-19续6）：用户实跑反馈3个问题——①口径确认页
      表级问题（如event_name同义不同名）只能勾选"忽略"没有实际处理路径；②验证假设
      时用户只能从5个模块里盲猜；③数据与假设不相关时仍强行选一个字段硬跑出结论（如
      用授信额度验证"页面加载慢导致流失"）。修复：①`ConfirmationForm.js`勾选语义
      反转为"让AI自动处理"+`node3_transform.py`prompt强制要求同义问题输出具体
      `standardize_categories`映射；②③新增`recommend_verification()`
      （`hypothesis_tree.py`）+ REST接口`/verification/recommend`
      （`routes/verification.py`，不经过LangGraph，参考`data_append.py`先例），
      点击验证前先展示LLM推荐模块+依据，数据不相关时返回`data_sufficient:false`，
      `node_verification`新增`SKIP_VERIFICATION_MODULE`哨兵分支支持"标记为数据
      不足，跳过验证"（未新增state字段）。`test_output/verify_fixes.py`驱动真实
      LLM跑通完整流程验证3点均生效，`pnpm exec next build`确认前端无编译错误。
      详见CHANGELOG.md
- [x] 严重事故修复：部署流程从未真正commit + 服务器LLM key缺失（2026-06-19续5）：
      用户线上实测发现"之前的修复都没生效"+"假设树/综合结论AI解读暂不可用"，排查
      发现本次及更早会话的所有改动一直停留在working tree从未`git commit`，
      `deploy.sh`的`git push HEAD`实际推送的是旧commit，此前所有"部署成功"都只是
      健康检查通过、没有真正发布新代码；同时服务器`api/.env`缺`ARK_API_KEY`且
      `DASHSCOPE_API_KEY`免费额度已耗尽，导致LLM两条路径全失败触发fallback文案。
      修复：积压改动整理成commit `7411c7d`后重新部署+确认服务器HEAD与本地一致；
      经用户确认后把`ARK_API_KEY`通过SSH管道同步到服务器（未落盘本地临时文件）。
      用Playwright直接对生产环境跑通完整场景验证，确认报告不再出现fallback文案。
      详见CHANGELOG.md，教训详见memory `feedback_deploy_verification`。

- [x] P1 部署改造为"服务器建裸仓库+本地push+post-receive hook自动checkout"
      （2026-06-19续4，已实际执行+发布）：服务器`/www`目录root拥有，初始化时
      `sudo git init --bare /www/insight-agent.git` + `sudo chown -R
      ubuntu:ubuntu`；`post-receive` hook只对`deploy`分支推送执行
      `git --work-tree=/www/insight-agent --git-dir=/www/insight-agent.git
      checkout -f deploy`，避免误推其他分支影响工作区；`scripts/deploy.sh`
      改为`GIT_SSH_COMMAND=... git push ... HEAD:refs/heads/deploy --force`
      触发hook，其余装依赖/构建/PM2重启/健康检查逻辑不变。手动push验证
      commit hash与服务器工作区一致后，跑完整`bash scripts/deploy.sh`
      端到端成功（构建+PM2重启+健康检查全部通过），同时把本次会话P0-1的
      改动发布到了生产环境（`http://175.178.91.42:3001`，`/health`与
      `/minerva`均200）。同步更新了memory `reference_deploy_script.md`。

- [x] P0-1 结论报告持久化 + 结构化重写（2026-06-19续3）：`HypothesisNode`新增
      `confidence_level`字段，`node_verification`验证后写回置信度到假设树节点；
      `generate_conclusion_narrative`改输出结构化JSON（执行摘要/建议/注意事项），
      不再让LLM直吐裸HTML，fallback降级也升级为基于各分组验证状态统计的详细
      文案；新建`api/templates/minerva_conclusion.html.j2`（问题陈述卡片+按group
      列假设状态/置信度徽标/验证摘要+三段式执行摘要，`.minerva-report`前缀CSS）；
      `node_conclusion`渲染后落盘`session_dir/report.html`，`/api/report/{id}/html`
      优先读磁盘文件不再依赖LangGraph内存state。P0-2：本地起服务+Playwright跑通
      单表（验证1个假设）与多表关联+追问（验证2次同假设）两个场景，report.html
      磁盘文件正确生成，置信度/verdict判定/结构化执行摘要内容均人工核查通过。
      P2文档清理同步完成（STATUS.md删除重复过时项，DEBT.md标注WeasyPrint已废弃）。
      详见CHANGELOG.md

- [x] Minerva自动化测试修复Loop第1轮（2026-06-18续19）：Playwright驱动4个场景
      （单表/多表/假设验证追问/模糊输入边界）全流程测试，发现并修复严重bug
      ——假设树首次resume时被静默重新生成、验证结果错配到不同内容的节点
      （根因：`node_hypothesis_tree`懒初始化代码跑在`interrupt()`暂停前，未
      提交checkpoint，LangGraph恢复时整段重跑）。拆出`node_hypothesis_init`
      独立节点修复，4场景修复后全部通过，报告质量人工评分均≥70/100。
      详见CHANGELOG.md、`test_output/loop_log.md`

- [x] LLM调用主路径切换至火山方舟Coding Plan（2026-06-18续18）：
      `api/services/llm.py` 的 `chat_json()` 优先调用 `ark-code-latest`
      （`ARK_API_KEY`），失败/未配置时降级到原有 DashScope，所有调用方
      （Node0/1/2/3/5/6、hypothesis_tree、data_append）无需改动。修复了
      Ark 不支持 `response_format:json_object` 的兼容问题（改prompt约束+
      容错解析），实测确认优先路径生效。详见CHANGELOG.md

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

- （无，下次会话优先项见下）

## 下次会话优先做

### 线上端到端测试方案（2026-06-19续7设计，下次会话开始执行）

目标：验证近期几轮修复（组A/B/C体验修复、假设树MECE去重、验证前推荐模块、结论报告
持久化、续7的LLM静默失败+重试）在生产环境（`http://175.178.91.42:3001/minerva`）
是否真实生效，而非只看健康检查。工具用Playwright（复用`test_output/minerva_e2e.js`
模式）新建`test_output/prod_e2e_loop.js`，目标URL写死为生产地址，真实LLM调用不mock；
测试期间用`Monitor`工具实时盯`ssh ... pm2 logs insight-api`，重点看续7新加的
`[llm._call]`异常日志是否在真实失败时出现。

场景矩阵（按顺序跑，每场景截图+日志落盘到`test_output/`）：
1. 单表上传+假设验证：全流程跑通，假设树不出现占位文案，验证前展示LLM推荐模块+依据
2. 多表上传+Join：Join方案确认、清洗计划稳定（同schema重复confirm不重新生成）
3. 假设树MECE：检查初始树不同分组间是否仍有本质重叠假设
4. 数据不相关场景：故意用不相关字段验证假设，确认返回`data_sufficient:false`而非
   硬凑结论
5. 表级口径问题：同义不同名字段，勾选"让AI自动处理"，检查清洗计划输出具体
   `standardize_categories`映射
6. 高频连续LLM调用：模拟真实session节奏连续触发多次LLM调用，专测续7"假设树偶发
   失败"场景，确认重试机制+失败日志均生效
7. 综合结论生成：`report.html`落盘、结构化执行摘要、置信度徽标
8. 模糊/边界输入：模糊问题描述，确认澄清对话能收敛

验收标准：全流程无500/502/控制台报错；假设树不出现"AI生成暂不可用"（除非主动模拟
LLM全挂）；场景4必须真正拦截不硬凑结论；报告内容人工抽查执行摘要/建议/置信度均有
实质内容、不同假设结论不雷同；场景6若有LLM失败，pm2日志必须能看到`[llm._call]`记录。

---

### 本次会话（2026-06-19续4）已完成P1部署改造，已实际发布到生产环境

**P3 明确延后，不在下次会话范围**：`api/render/` ECharts SSR图表渲染（用户已确认
不做）、P2旧债Join阶段循环式改口径（工作量大）、P1旧债JoinPlanForm"让AI重新生成"
按钮（模式同`TransformPreview`已有实现可抄，预计<30分钟，无需单独排期）。

---

### Minerva 重构（2026-06-18 讨论确定，Step1-6 已全部完成，闭环跑通）

产品方向：从"线性清洗→分析→报告流水线"转为"假设驱动的持续对话工具"
（`docs/Minerva_PRD_v1.0.md`/`docs/minerva-prototype.jsx`，不推翻现有后端，接入新对话前端）。
讨论结论：①假设树 = LLM一次性生成初始树 + 对话增量修改 + UI可编辑（三者都要，
参照Node3清洗计划可编辑模式）；②数据 = 单数据集会话级共享，问题定义阶段结束后
统一上传，假设树基于`confirmed_schema`生成；③原型改浅色主题。

`pages/minerva.js` 已是可端到端跑通的真实功能页面（问题澄清→上传→口径确认→
清洗确认→假设验证→综合结论），下次会话可从"用户体验打磨"和下方两个延后项
切入，而非继续搭骨架。

- [x] **Step1 假设树数据结构设计**（2026-06-18）：`api/core/schema.py`新增
      `ProblemCard`/`HypothesisNode`/`HypothesisTreeOp`（含增量操作枚举
      add_node/update_status/update_summary/merge_node/remove_node）；
      `api/core/state.py`新增`stage`/`problem_card`/`hypothesis_tree`字段
      （已按[[project_langgraph_state_gotcha]]提前显式声明）。仅数据结构，
      未接入graph.py，详见CHANGELOG.md
- [x] **Step2 graph.py路由骨架改造**（2026-06-18续）：同一张图按
      "raw.csv是否已存在"+"problem_card是否已写入"两个信号分流旧版/Minerva
      入口，未新建并行图。`node0_clarification`双模式（旧版透传/Minerva自循环
      对话）、`node3_transform`后条件边分流到`node4_analysis`（旧版）或
      `node_hypothesis_tree`（Minerva）。
- [x] **Step3 Stage1/2/3 Node骨架**（2026-06-18续）：新增`node_awaiting_data`/
      `node_hypothesis_tree`/`node_verification`/`node_conclusion`
      （`api/core/graph.py`）+ `api/nodes/hypothesis_tree.py`（固定操作函数
      `apply_ops` + 3个LLM增量生成函数，LLM均有降级）；验证分发复用
      `registry.get_module(name)` + `node5_report.py`的置信度/叙事函数，
      Node1-4模块代码未改一行。
- [x] **Step4 数据上传时机迁移**（2026-06-18续）：Node1诊断/Node2确认/Node3清洗
      原样复用；`/api/upload`新增可选`session_id`字段支持复用已占用的会话；
      `/api/analyze/{id}/stream`删除"raw.csv不存在即报错"的前置guard；新增
      通用`POST /api/analyze/{id}/resume`服务三个新interrupt点。两条独立冒烟
      脚本验证Minerva全链路与旧版回归均通过，详见CHANGELOG.md。
- [x] **Step5 增量上传支持**（2026-06-18续15）：新增`api/nodes/data_append.py`
      （LLM生成合并key，降级同名列匹配）+ `api/routes/data_append.py`
      （`/api/analyze/{id}/data/append/preview|confirm`，preview/confirm两步
      与Node3清洗计划同模式，但不经过LangGraph，不打断`node_hypothesis_tree`
      的interrupt，直接覆盖写`cleaned_data_path`/`merged_data_path`）。curl
      端到端验证通过（合并成功/cancel/未preview直接confirm的404保护）。
- [x] **Step6 前端三栏对话界面**（2026-06-18续16）：新增`pages/minerva.js`
      （新路由，不改动`pages/index.js`），分析地图（左）+对话区（中）+数据结果
      （右），浅色主题。复用`ConfirmationForm`/`JoinPlanForm`/`TransformPreview`
      三个既有组件嵌入对话流（未重写），全流程接真实后端（无mock），统一走
      `/api/analyze/{id}/resume`通用入口。配合后端补充`last_verification`状态
      字段（`api/core/state.py`/`graph.py`），`node_verification`写入图表/置信度/
      叙事供右侧面板渲染。Playwright端到端验证（`test_output/minerva_e2e.js`）
      问题澄清→上传→口径确认→清洗确认→假设验证→综合结论全链路通过，截图
      `test_output/minerva_final.png`。过程中发现并修复一个LangGraph细节：
      `Command(resume=None)`会被当作未提供resume值报错，纯信号型interrupt
      需传任意真值。

### Minerva 体验测试反馈（2026-06-18 续17，用户实际跑通一遍后提的9条，均未动代码）

按根因分三组，组C是关键发现：验证假设时模块从不知道在验证哪个假设，是#6/#7/#8/#9
共同的根因，建议单独排期不要和体验小修混在一起。

**组A：前端体验层（纯前端小改）—— 已完成（2026-06-19）**
- [x] **#1** 上传后反馈弱、文件选择无增删改：`pages/minerva.js`已加已选文件列表+
      单删按钮，上传中按钮文案"上传中..."+spinner
- [x] **#4** 验证假设时前端无提醒：点"开始验证"后该节点显示"正在验证..."spinner
- [x] **#5** 数据结果图表区域太小：右栏 280→420px，图表 220→340px

**组B：流程语义不清晰（前后端都要改，中等改动）—— 已完成（2026-06-19）**
- [x] **#2** 表级问题"我已知晓"指向不明：`ConfirmationForm.js`勾选框文案改为
      "我已了解，忽略此问题、不做任何处理"，明确不会触发任何清洗操作
- [x] **#3** 退回重新确认口径后清洗计划不稳定 + 缺真实数据预览：拆出
      `node3_plan_init`（无interrupt）与`node3_preview`（只剩interrupt），彻底
      消除"确认时LLM重新生成"的可能（根因与续19假设树resume重跑bug相同，
      `interrupt()`前的代码会在每次resume时重跑）；按`confirmed_schema`指纹
      缓存plan；新增"让AI重新生成"按钮（`action:"regenerate"`）；新增
      `build_data_preview()`真实跑一遍plan产出行列数对比+样例数据，
      `TransformPreview.js`渲染为表格。脚本验证：连续多次resume后
      shown plan == executed plan。详见CHANGELOG.md

**组C：核心架构缺口（同根因）—— 已完成（2026-06-19续）**
- [x] **#6/#7/#9** 验证假设时无推荐方案、结论和假设内容脱节、不同假设撞车出
      雷同结论：新增`suggest_verification_config`（`api/nodes/hypothesis_tree.py`），
      验证前让LLM按假设文本从该模块允许的config key中选列（替代`module.run(df, {})`
      空字典盲选）；`_generate_narrative`（`node5_report.py`）新增可选
      `hypothesis_label`/`problem_card`参数，要求明确写support/refute/inconclusive
      并输出`verdict`字段；`node_verification`状态判定改为优先按`verdict`映射
      （support→verified/refute→rejected/inconclusive→partial），LLM不可用时退回
      旧的置信度规则。详见CHANGELOG.md，本地脚本验证LLM返回结构正确，
      未跑Playwright端到端（建议下次会话补回归）。
- [x] **#8** 假设树不满足MECE（供给侧/需求侧出现本质重叠的假设）：
      `generate_initial_ops`prompt加MECE约束；新增`generate_dedupe_ops`，初始树
      生成后追加一次LLM自检识别本质重叠假设并合并（`merge_node`），无重叠时
      不动。详见CHANGELOG.md。

### 旧路线遗留（Minerva之外，不阻塞，延后）

- [ ] **P1**：`JoinPlanForm.js` 加"让AI重新生成"按钮，带用户反馈文本重新调用
      `_generate_join_plan`（`api/nodes/node2_confirmation.py`）。增量小。
- [ ] **P2**：Join阶段发现Node2字段口径本身错了时，支持"返回改口径"。需要把
      `run_node2_confirmation` 从线性两阶段改成可循环结构，工作量较大。
- 背景：确认流程"否认/修改"重新设计的P0（清洗计划可编辑+拒绝回退）已于
  2026-06-17续5完成，P1/P2是用户认可的后续方向（非否决），按优先级延后，
  详见 DEBT.md「Join方案确认点缺少否认/修改路径」。

## 最近完成（2026-06-17 续5，清洗计划可编辑+拒绝回退）

- [x] 解决"确认流程只能往下走，不能否认/修改"的问题（P0范围，详见CHANGELOG.md）：
      `TransformPreview.js`清洗计划支持删除单条操作+编辑fillna值/cast_type目标
      类型/unit_convert系数；拒绝时不再终止会话（`DEBT.md`已记录的债），改为路由
      回`node2_confirmation`重新确认口径，`ConfirmationForm.js`沿用上一轮编辑结果
      （新增`initialSchema`prop）。顺带修复单表场景`node4_analysis`等三处误读
      不存在的`merged_data_path`导致的`FileNotFoundError`（此前单表全流程实际
      无法跑通Node4之后的步骤）。curl端到端验证通过。
      P1（Join方案重新生成）/P2（Join阶段返回改口径）暂未做，待用户确认是否需要。

## 最近完成（2026-06-17 续4，新增转化漏斗分析模块）

- [x] `api/modules/funnel.py`：`FunnelModule`（category=转化/留存），启发式识别
      "曝光→申请→授信→放款"漏斗各阶段，输出阶段人数/环比转化率/总转化率，
      ECharts原生funnel图。已注册进`registry.py`默认列表，`node5_report.py`
      补充对应置信度配置。补齐DEBT.md记录的漏斗覆盖缺口（已标注解决）。
- [x] 接入回归中发现并修复3个bug（详见CHANGELOG.md）：①漏斗阶段判定列误选
      维度表同名字段致授信人数超过申请人数 ②叙事生成多环节比较数值推理错误
      ③`drop_duplicates`无保护阈值，曾致99.5%数据被误删且全流程不报错
      （较严重，已加保护阈值）。修复后连续2轮全流程回归确认稳定。

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

