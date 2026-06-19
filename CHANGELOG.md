# CHANGELOG

只追加，不删旧内容。回溯历史时手动提供给 Claude。

---

## 2026-06-19续6（Minerva假设验证体验修复：表级问题处理路径+验证前推荐方法+数据不足判断）

用户实跑后反馈3个问题，均已修复并跑通端到端验证（`test_output/verify_fixes.py`，
驱动真实LLM调用走完整Minerva流程）：

1. **口径确认页表级问题无法真正处理**：`ConfirmationForm.js` 的勾选框语义反转——
   不勾选=忽略，勾选="让AI自动处理此问题"（原文案"我已了解，忽略此问题、不做任何
   处理"和实际想要的效果正好相反）；`node3_transform.py` 的 `_llm_supplementary_ops`
   prompt 补充强制指令：遇到同义不同名/疑似重复类别问题时必须识别具体列名和同义值，
   输出对应 `standardize_categories` 操作+完整mapping。验证脚本确认：勾选后清洗
   计划页正确生成了 `click_event→click`、`tap→touch_click` 的合并操作。
2. **验证假设时用户无依据瞎选分析模块**：新增 `recommend_verification()`
   （`api/nodes/hypothesis_tree.py`）+ `POST /api/analyze/{id}/verification/recommend`
   （`api/routes/verification.py`，REST方案，不经过LangGraph，参考
   `api/routes/data_append.py` 的"REST预览+graph resume确认"先例）：点击"验证此假设"
   先调该接口拿到LLM推荐的模块+列配置+一句话依据，`pages/minerva.js` 展示推荐卡片，
   用户可直接确认或切换模块，不再是对着5个选项盲猜。
3. **数据与假设不相关时仍强行给结论**：`recommend_verification()` 的prompt明确要求
   "现有列中没有一列在语义上真正支撑该假设描述的因果机制时必须返回
   `data_sufficient: false` 并说明缺什么数据，不允许为了凑答案选不相关的列/模块"；
   `node_verification`（`api/core/graph.py`）新增 `SKIP_VERIFICATION_MODULE`
   哨兵值分支（复用已有 `verifying_module` 字段，未新增state key），用户在推荐
   卡片选择"标记为数据不足，跳过验证"时直接把假设标记 `partial`+"无法验证"摘要，
   不再用不相关字段（如本次截图里的授信额度）硬跑出一个貌似严谨实则无意义的结论。
   验证脚本对"产品介绍页信息不透明"等数据侧确实缺失支撑字段的假设实测
   `data_sufficient=false` 判断正确；另选一个假设走正常 `attribution` 模块验证，
   确认原有 `module.run`+置信度判定+verdict 叙事逻辑未被破坏。

## 2026-06-19续5（严重事故复盘：部署流程从未真正commit + 服务器LLM key缺失）

### 事故描述

用户线上实测反馈"之前报告的问题都没改"+"假设树/综合结论AI解读暂不可用"。排查发现
两个独立问题叠加：

1. **本次会话（及更早若干次会话）的所有代码改动从未`git commit`**，一直停留在
   working tree。`scripts/deploy.sh`用`git push HEAD:refs/heads/deploy`部署，
   push的是**已提交的commit**，不包含working tree里的改动，所以本次会话的P0-1
   改动、以及更早会话里组A/B/C体验修复、LLM切Ark等全部从未真正发布到生产环境——
   `bash scripts/deploy.sh`跑出的"部署成功"+健康检查通过只证明了服务正常重启，
   没有证明部署内容是新代码。**教训：deploy.sh注释里写了"部署前请先commit"，
   但脚本本身不做检查，必须养成习惯先`git status`确认无未commit改动再部署；
   验证部署是否生效不能只看健康检查，要对比服务器`git rev-parse HEAD`和本地一致，
   且最好实际触发一次行为验证（如本次靠Playwright访问真实生产URL）。**
   修复：把所有积压的working tree改动整理成一个commit（`7411c7d`），重新跑
   `scripts/deploy.sh`，确认服务器HEAD与本地一致。
2. **服务器`api/.env`只配置了`DASHSCOPE_API_KEY`，且该key免费额度已耗尽**
   （DashScope返回403 `AllocationQuota.FreeTierOnly`），`ARK_API_KEY`从未同步到
   服务器（`.env`本身gitignored，部署流程不会同步它）。两条LLM路径全部失败，
   `chat_json()`返回`None`，各调用方触发"AI解读暂不可用"fallback文案——表面是
   产品文案问题，根因是账户/密钥配置问题。修复：经用户确认后，把本地
   `ARK_API_KEY`通过SSH管道直接append到服务器`.env`（全程未落盘到本地临时文件，
   避免明文密钥落地），`pm2 restart insight-api`后验证`chat_json()`真实调通。

### 验证

- 修复commit部署后用`test_output/minerva_scenario.js`场景1直接对生产环境
  `http://175.178.91.42:3001`跑一次完整端到端（问题定义→上传→诊断→口径确认→
  清洗→假设树生成15条假设→验证假设1→生成综合结论），全部通过、无控制台报错；
  抓取`/api/report/{id}/html`确认不再出现"AI解读暂不可用"，执行摘要是基于
  真实假设验证结果的LLM生成内容。
- 教训沉淀进memory：`feedback_deploy_verification`（部署后必须验证HEAD一致+
  实际行为，不能只看健康检查）。

---

## 2026-06-19续4（P1 部署改造：服务器裸仓库 + post-receive hook）

- 根因/动机：此前部署用`git archive HEAD | ssh ... tar -x`整包传输，服务器端
  目录不是git repo，丢失历史，不便回滚/diff；改造目标是保留服务器端git历史，
  同时仍不要求服务器直连GitHub（已知会因GFW间歇性干扰超时）。
- 服务器一次性初始化（SSH操作，执行前已与用户二次确认）：`/www`目录root拥有，
  用`sudo git init --bare /www/insight-agent.git`创建裸仓库后
  `sudo chown -R ubuntu:ubuntu`，使后续`ubuntu`用户push不需要sudo。
- `post-receive` hook（`/www/insight-agent.git/hooks/post-receive`）：从stdin
  读取推送的ref，只对`deploy`分支执行
  `git --work-tree=/www/insight-agent --git-dir=/www/insight-agent.git
  checkout -f deploy`，避免误推其他分支影响线上工作区。
- `scripts/deploy.sh`：把`git archive | ssh ... tar -x`换成
  `GIT_SSH_COMMAND="ssh -F $SSH_CONFIG" git push "${REMOTE}:${REMOTE_BARE_REPO}"
  "${REF}:refs/heads/deploy" --force`，其余装后端/前端依赖、`pnpm build`、
  `pm2 restart`、健康检查逻辑不变。
- 验证：先手动`git push`确认服务器`git rev-parse HEAD`与本地一致、工作区只剩
  历史遗留的未跟踪文件（如`api/nodes/upload.py`旧文件，与本次改动无关）；再跑
  完整`bash scripts/deploy.sh`走通构建+PM2重启+健康检查，顺带把本次会话P0-1
  的改动发布到生产环境（`http://175.178.91.42:3001`），`/health`与`/minerva`
  均返回200。
- 同步更新memory `reference_deploy_script.md`里的部署方式说明。

---

## 2026-06-19续3（P0-1 结论报告持久化 + 结构化重写）

- 根因：`node_conclusion`生成的`report_html`只写进LangGraph内存state从未落盘，
  进程重启/checkpoint丢失后报告拿不到；`generate_conclusion_narrative`让LLM直接
  吐裸HTML，没有"结论-数据支撑-建议+置信度"结构，且无法复用统一样式。
- `api/core/schema.py`：`HypothesisNode`新增`confidence_level`字段，
  `HypothesisTreeOp`的`update_summary`新增`confidence_level`可选字段。
- `api/core/graph.py` `node_verification`：`update_summary` op同时写回
  `confidence["level"]`到假设树节点（之前置信度只存在`last_verification`里，
  不会持久化到树上）。
- `api/nodes/hypothesis_tree.py` `generate_conclusion_narrative`：改为输出
  结构化JSON（`executive_summary`/`recommendation`/`caveats`），不再让LLM
  直吐HTML；fallback降级也从"AI解读暂不可用"升级为基于各分组验证状态
  （已验证/部分验证/已排除/待验证数量及标签）统计的详细默认文案。
- 新建`api/templates/minerva_conclusion.html.j2`：问题陈述卡片 + 按group列出
  每条假设的状态/置信度徽标/验证摘要 + 执行摘要/建议/注意事项三段文字，
  CSS统一加`.minerva-report`前缀避免污染全局样式。
- `api/core/paths.py`新增`report_html_path(session_id)`，`node_conclusion`
  渲染后写入`session_dir/report.html`磁盘文件（同时仍写`state.report_html`
  保持兼容）。
- `api/routes/analyze.py` `/api/report/{session_id}/html`：优先读磁盘文件，
  没有才回退读LangGraph state（旧版线性流程报告仍只在state中）。
- 本地起服务+Playwright跑通单表场景（s1，验证1个假设）与多表关联+追问场景
  （s3，关联4表后验证2次同一假设、追问深挖均通过），report.html磁盘文件
  正确生成，置信度徽标/verdict判定的rejected状态/结构化执行摘要均渲染正常，
  人工核查内容与实际验证结果一致（详见`test_output/minerva_scenario.js`，
  复用已有脚本，未新建）。

### P2 文档清理

- `STATUS.md`删除"待开始 > 后端"区块中重复过时的
  "Node0/Node3预览/Node6 接入`api/core/graph.py`"未完成项（与2026-06-16已完成
  的同名条目重复，是过时残留）。
- `DEBT.md`将WeasyPrint PDF验证标注为"已废弃，除非以后明确要做PDF导出否则
  不再保留为TODO"（产品方向已改为HTML报告直出，原TODO与现状矛盾）。

---

## 2026-06-19续（Minerva体验反馈组C：假设验证脱节 + 假设树MECE）

### #6/#7/#9 验证假设时模块不知道在验证哪个假设

- 根因：`node_verification`（`api/core/graph.py`）此前调用`module.run(df, {})`，
  config永远是空字典，各模块的列选择逻辑（如`trend_insight`的`select_numeric_metric`）
  只能"自动挑第一个非维度型数值列"，与假设文本完全无关；`_generate_narrative`
  （`api/nodes/node5_report.py`）也只喂metrics，不知道在验证什么假设，因此写不出
  "数据是否支持该假设"的论证，不同假设容易跑出同一份盲选列产生的雷同结论。
- 新增`suggest_verification_config`（`api/nodes/hypothesis_tree.py`）：验证前让LLM
  从该模块允许的config key（`MODULE_CONFIG_KEYS`，按模块区分如
  `trend_insight`→`date_column`/`value_column`，`attribution`→`dependent_column`/
  `independent_columns`）里选最贴合假设文本的列，列名校验只接受df中真实存在的列，
  LLM不可用/选不出来时返回空dict退回各模块原有自动检测，不阻断。
- `_generate_narrative`新增可选`hypothesis_label`/`problem_card`参数：传入假设文本时
  prompt要求明确写出数据对该假设是支持/不支持/部分支持，并额外输出
  `verdict`(support/refute/inconclusive)字段；不传时（`run_report`/`node6_followup`
  两个旧调用点）行为完全不变。
- `node_verification`：状态从"只看置信度高低判定verified/partial"改为优先按
  LLM给出的`verdict`映射（support→verified，refute→rejected，inconclusive→partial），
  LLM不可用时才退回旧的置信度规则。`rejected`状态前端`pages/minerva.js`此前已支持
  渲染（✕红色），未改前端。

### #8 假设树不满足MECE

- `generate_initial_ops`系统prompt新增MECE约束（不同分组假设不能是同一因果机制换个
  说法）。
- 新增`generate_dedupe_ops`（`api/nodes/hypothesis_tree.py`）：初始树生成后追加一次
  LLM自检，识别本质重叠（同因果机制、表述不同）的假设节点并输出`merge_node`操作合并，
  没有重叠时返回空列表。`node_hypothesis_init`（`api/core/graph.py`）依次调用
  `generate_initial_ops`→`generate_dedupe_ops`，仍是普通return提交，不在新拆出的
  interrupt前节点里做非幂等调用（沿用`[[project_langgraph_interrupt_rerun_gotcha]]`
  的教训）。

验证：`suggest_verification_config`/`generate_dedupe_ops`/`_generate_narrative`
（带hypothesis_label）三个函数本地脚本调用，确认真实LLM返回结构正确
（config列名校验通过、dedupe无重叠时返回空、verdict正确返回inconclusive），
均未跑Playwright端到端（下次会话建议补一轮真实假设验证场景回归）。

---

## 2026-06-19（Minerva体验反馈组A+组B落地：前端小改 + 清洗计划缓存/数据预览）

### 组A：前端体验小改（`pages/minerva.js`）

- **#1** 上传文件支持多次累加选择 + 单文件删除按钮，上传中显示"上传中..."文案+spinner
- **#4** 点击"开始验证"后该假设节点显示"正在验证..."spinner，替代选择器（此前点击后
  只是disable按钮，无可见反馈）
- **#5** 右侧数据结果面板宽度280→420px，图表高度220→340px

### 组B：流程语义修复（前后端，#2/#3）

- **#2** `ConfirmationForm.js` 表级问题确认勾选框文案改为"我已了解，忽略此问题、不做
  任何处理"，明确告知该勾选不会触发任何清洗操作（之前文案"忽略此问题继续分析"仍可能
  让人以为会被处理）
- **#3 核心bug**：`node3_preview`（`api/core/graph.py`）退回重新确认口径后，即使字段
  口径选项完全没变，清洗计划也会变——根因是LLM调用写在`interrupt()`之前，而LangGraph
  恢复interrupt时会把节点函数从头重跑一遍，等于每次"确认/拒绝/重新生成"操作都隐式触发
  一次新的LLM采样，**用户最终确认执行的plan和预览时看到的plan可能不是同一份**（与
  续19修复的假设树resume重跑bug同根因，见`[[project_langgraph_state_gotcha]]`）。
  - 拆出`node3_plan_init`（无interrupt，只在图真正路由进入时执行一次）与
    `node3_preview`（只剩interrupt本身，读已提交的`transform_plan_pending`），
    彻底消除"确认时重新生成"的可能性（已用脚本验证：连续3次resume后`shown plan ==
    executed plan`）
  - 按`confirmed_schema`内容算SHA256指纹缓存生成结果（`schema_fingerprint`，
    `api/nodes/node3_preview.py`），指纹不变时复用缓存不重新调LLM；新增
    `transform_plan_cache_key`/`transform_plan_cache`两个state字段
  - 新增"让AI重新生成"按钮（resume协议`{"action":"regenerate"}`），强制丢弃缓存
    重新生成一版，再次进入预览中断
  - 清洗计划预览新增**真实数据预览**：`build_data_preview()`在raw数据上真的跑一遍
    plan（不写入最终`cleaned_data_path`），返回清洗前后行列数对比+前5行样例数据；
    `TransformPreview.js`渲染为表格+行数变化提示（含异常减少行数的红色警示），
    取代此前只有操作文字描述的预览
  - `node3_transform.py`抽出`_apply_plan()`公共函数，`run_transform`与预览复用同一份
    执行逻辑，避免出现第二处op分发实现
  - 旧版线性流程（`pages/index.js`/`api/routes/v03.py`）同步获得真实数据预览展示与
    "让AI重新生成"按钮（同一套后端接口，前端`TransformConfirmRequest`新增`action`字段）

### 待续

组C（#6/#7/#8/#9，验证假设时模块不知道在验证哪个假设的核心架构缺口）按计划单独排期，
本轮未做。

---

## 2026-06-18 续19（Minerva自动化测试修复Loop第1轮，修复假设树resume重跑bug）

### 测试方式

Playwright驱动 `http://175.178.91.42:3001/minerva`，4个场景（单表/多表/假设验证
追问/模糊输入边界）全流程测试，脚本见 `test_output/minerva_scenario.js`。

### 发现并修复：假设树初次resume时被静默重新生成，验证结果错配到不同内容的节点

`api/core/graph.py` 的 `node_hypothesis_tree` 原先在 `interrupt()` 暂停前直接生成
初始假设树（`if not tree: tree = apply_ops(tree, generate_initial_ops(...))`）。
LangGraph 恢复 interrupt 时会把所在节点函数从头重新执行，而这次生成从未通过
`return` 提交到 checkpoint，于是第一次 resume（无论是verify还是chat）都会重新
调用一次LLM生成一棵内容完全不同的新树（用 Playwright 网络拦截实测复现：
12节点的初始树在首次verify后变成完全不同措辞的15节点新树）。用户在前端选择
验证的是旧树某个id（如"1.1"），但因为新树同id语义完全不同，验证结果被错配到
错的假设节点上。

修复：拆出独立节点 `node_hypothesis_init`（普通 `return` 提交生成结果，不在
其内部调用 `interrupt()`），插入到 `node3_transform → node_hypothesis_tree`
之间；`node_hypothesis_tree` 不再做懒初始化，进入时 tree 必须已非空。

`_route_after_transform` 的 Minerva 分支改为路由到 `node_hypothesis_init`。
修复前后对照实测：4次 resume（初始生成→verify→chat→verify）原本树id从
`1.1...3.4`（12节点）跳到`1,1.1...3,3.4`（15节点）再保持不变；修复后4次
resume全部保持同一棵12节点树，仅对应节点的status/summary被正确更新。

四个测试场景（单表/多表/验证追问/模糊输入边界）修复后全部通过，报告质量
人工评分均≥70/100。详见 `test_output/loop_log.md`。

---

## 2026-06-18 续18（LLM调用切换至火山方舟 Coding Plan，DashScope降级保留）

### `api/services/llm.py` 重写

`chat_json()` 优先调用火山方舟 Coding Plan（`ARK_API_KEY`，模型
`ark-code-latest`，`https://ark.cn-beijing.volces.com/api/coding/v3`），
失败或未配置时自动降级到原有 DashScope（`DASHSCOPE_API_KEY`，
`deepseek-v4-flash`），调用方（Node0/1/2/3/5/6 及 hypothesis_tree/data_append）
无需改动。

- Ark 的 `ark-code-latest` **不支持** `response_format: json_object` 参数
  （实测返回 400 `InvalidParameter`），改为去掉该参数，靠在 system prompt
  末尾追加"只输出合法JSON，不要markdown代码块"的约束；新增 `_parse_json_content`
  容错解析，剥除模型可能输出的 ```json 代码块包裹。
- `api/.env`/`.env.example` 新增 `ARK_API_KEY`。
- 已用 trace 实测确认：Ark 优先被调用且返回有效 JSON；DashScope 仍保留作为
  降级路径（未重新跑真实降级场景，逻辑未变）。

---

## 2026-06-18 续15（Minerva重构 Step5，增量上传支持）

### 新增 `api/nodes/data_append.py` + `api/routes/data_append.py`

假设验证阶段中途发现缺字段时，支持追加上传一个文件并合并进当前 session 的
已清洗数据，不打断 `node_hypothesis_tree` 的 interrupt（不经过 LangGraph
resume，只读写 `cleaned_data_path`/`merged_data_path` 指向的文件）：

- `generate_append_plan`：LLM 提议新文件与已有数据的合并 key（on/how），
  不可用时降级为同名列匹配，prompt 风格与 `node2_confirmation._generate_join_plan`
  一致。
- `POST /api/analyze/{session_id}/data/append/preview`（multipart file）：
  保存新文件、生成合并方案，暂存进 `session_state.json` 的 `pending_append`。
- `POST /api/analyze/{session_id}/data/append/confirm`（`{approved, plan?}`）：
  执行 `pd.merge`，**同时覆盖** `cleaned_data_path` 与（若存在）
  `merged_data_path`，避免要判断当前 session 实际生效的是哪个路径。
  `approved=false` 取消，清空 `pending_append`。
- `api/main.py` 注册新路由 `data_append.router`。
- 手动 curl 全链路验证通过：单表场景跑通 Node1-6 后追加上传含 `channel` 列的
  新文件，LLM 正确识别 `user_id` 为 join key，合并后 `cleaned.parquet` 正确
  新增 `channel` 列；cancel 路径与"未 preview 直接 confirm"的 404 保护均验证通过。

---

## 2026-06-18 续16（Minerva重构 Step6，前端三栏对话界面）

### 新增 `pages/minerva.js`（新路由，不改动 `pages/index.js` 旧线性流程）

完整三栏闭环：左侧分析地图（问题定义/假设树/综合结论三阶段状态 + 假设树节点
列表+验证按钮）、中间对话区（问题澄清聊天 + 各 interrupt 对应表单/上传区，
按需嵌入复用 `ConfirmationForm`/`JoinPlanForm`/`TransformPreview` 三个既有组件，
未重写）、右侧数据结果面板（最近一次假设验证的图表+置信度+三段式叙事）。
全流程接真实后端接口，无 mock 数据：

- 入口用 `GET /api/analyze/{id}/stream` 拿首个 interrupt；之后统一走
  `POST /api/analyze/{id}/resume`（`api/routes/analyze.py` 已有的通用 resume
  入口）推进问题澄清自循环 / `node_awaiting_data` / 假设树 chat|verify|conclude
  三个 action，按 interrupt payload 的特征字段（`type`/`diagnosis`/`join_plan`/
  `transform_plan`）区分阶段。
- 后端配合新增：`api/core/state.py` 新增 `last_verification` 字段；
  `api/core/graph.py` 的 `node_verification` 写入
  `{module, category, chart(VisualizationModule转换), confidence, narrative}`，
  `node_hypothesis_tree`/`node_awaiting_data` 的 interrupt payload 补充
  `last_verification`/`problem_card`，供右侧面板和左侧地图渲染。
- 修复一个 LangGraph 调用细节：`Command(resume=None)` 会被 LangGraph 当作
  "未提供resume值"抛 `EmptyInputError`，`node_awaiting_data`/`node6_followup`
  这类"resume 值本身不使用"的 interrupt，前端必须传任意真值（如 `true`），
  不能传 `null`。
- Playwright 全链路验证通过（`test_output/minerva_e2e.js`）：问题澄清对话
  （3轮收敛）→ 上传CSV → 字段口径确认 → 清洗计划确认 → 假设树生成 → 选择
  假设+模块验证（图表+置信度正确渲染）→ 生成综合结论（HTML正确渲染），
  全程无 console error，截图见 `test_output/minerva_final.png`。

---

## 2026-06-18（Minerva重构 Step1，假设树数据结构设计）

### 新增 ProblemCard / HypothesisNode / HypothesisTreeOp 类型定义

`api/core/schema.py` 新增：

- `ProblemCard`：阶段一"问题陈述卡片"输出（question/baseline/business_meaning/
  analysis_goal），对应`Minerva_PRD_v1.0.md`第三节。
- `HypothesisNode`：假设树单节点（id/parent/group/label/priority/status/
  verification_summary），`group`是叙述性分组名（如"需求侧"）不是节点id，
  根分组节点`parent`为`None`。`status`枚举
  `pending|verifying|verified|rejected|partial`对应PRD的待验证/验证中/已验证/
  已排除/部分验证。
- `HypothesisTreeOp`：假设树增量更新操作（`add_node`/`update_status`/
  `update_summary`/`merge_node`/`remove_node`），LLM每轮只允许输出这组操作，
  禁止直接吐自由文本或整棵树重写，应用逻辑留给Step2/3的固定函数实现。

`api/core/state.py`新增`stage`/`problem_card`/`hypothesis_tree`三个TypedDict
字段（⚠️ AnalysisState未声明的key会被LangGraph静默丢弃，本次已按
[[project_langgraph_state_gotcha]]提前声明，避免重演Join方案那次的bug）。
state内仍按现有风格存dict/list，详细结构在schema.py。

本次只做数据结构设计，未接入graph.py/node代码，下一步Step2路由骨架改造。

---

## 2026-06-18（续，Minerva重构 Step2+3+4，路由骨架+Stage1/2/3 Node骨架+上传时机迁移）

### graph.py 改为路由型：旧版线性流程与Minerva对话式流程共用一张图

核心思路：用"raw_data_path对应文件是否已存在"和"problem_card是否已写入"两个
信号区分旧版/Minerva入口，不新建并行图，同一张图按入口分流，旧版完全不受影响
（已用独立冒烟脚本回归验证，过程见下）。

- `api/core/graph.py`：
  - `node0_clarification` 改为双模式：raw.csv已存在（旧版，upload先于/stream）
    纯透传直入node1；不存在时（Minerva）自循环`interrupt()`等用户消息，调用
    `run_clarification`推进对话，收敛后写`problem_card`，`stage`切到
    `awaiting_data`。
  - 新增`node_awaiting_data`：阶段一结束、阶段二开始前的等待点，`interrupt()`
    等前端调用`POST /api/upload`（带session_id）写入数据后再恢复。
  - `node3_transform`之后新增条件边`_route_after_transform`：`problem_card`
    非空（Minerva）转`node_hypothesis_tree`，否则（旧版）走原`node4_analysis`。
    Node1/2/3本身代码未改一行，验证了"原样复用"。
  - 新增`node_hypothesis_tree`/`node_verification`/`node_conclusion`三个节点
    实现PRD阶段二/三：首次进入LLM一次性生成初始假设树（`hypothesis_tree.py`的
    `generate_initial_ops`+`apply_ops`），`interrupt()`等用户action
    （chat/verify/conclude）；verify时复用`registry.get_module(name)`+
    `node5_report.py`的`_compute_confidence`/`_generate_narrative`在全量清洗
    数据上跑一次模块，按置信度等级判定verified/partial写回树；conclude时
    生成综合结论写入`report_html`（复用现有`/api/report/{id}/html`展示）。
- `api/nodes/hypothesis_tree.py`（新建）：假设树固定操作函数
  `apply_ops`（add_node/update_status/update_summary/merge_node/remove_node，
  LLM不允许直接吐整棵树）+ 三个LLM增量生成函数（初始树/对话增量/综合结论），
  均有LLM不可用时的降级（占位节点/空操作/规则拼接的结论文本），不阻断流程。
- `api/nodes/node0_clarification.py`：`run_clarification`输出新增
  `question`/`baseline`/`business_meaning`三个字段（对应PRD"问题陈述卡片"），
  向后兼容——`api/routes/v03.py`旧版只读`analysis_goal`/`done`等字段，不受影响。
- `api/routes/analyze.py`：
  - `_initial_state()`补充Step1新增字段的默认值（`stage`/`problem_card`/
    `hypothesis_tree`/`clarification_history`/`clarification_round`/
    `verifying_node_id`/`verifying_module`）。
  - 删除`/stream`里"raw.csv不存在就报错"的前置guard——Minerva入口本来就要在
    上传前启动图；旧版因为upload已先发生，该guard本来就是恒真，删除不影响旧版。
  - 新增通用`POST /api/analyze/{session_id}/resume`（body `{"value": ...}`），
    服务Minerva新增的三个interrupt点；node2/node3_preview/node6仍用各自专属
    确认接口，未迁移。⚠️ LangGraph的`Command(resume=None)`会被当成"空输入"报
    `EmptyInputError`，`node_awaiting_data`这类无需携带数据的interrupt，resume
    必须传`true`等非空值，不能传`null`。
- `api/routes/upload.py`：`/api/upload`新增可选`session_id` Form字段，传入时
  复用该session目录而不是新建（Minerva流程问题定义阶段已占用session_id，
  上传时要写入同一个session）。
- `api/core/state.py`：补充`clarification_history`/`clarification_round`/
  `verifying_node_id`/`verifying_module`四个字段（Step1只声明了
  `stage`/`problem_card`/`hypothesis_tree`，实现阶段发现还需要这四个，属于正常
  的设计细化）。

### 验证

两条独立冒烟脚本（直接驱动graph对象，不经HTTP，验证后已删除）：
- Minerva全链路：问题定义3轮对话收敛 -> 上传数据 -> node1诊断/node2口径确认/
  node3清洗预览确认（全部复用现有节点不变）-> 假设树LLM生成11个分组假设节点 ->
  对1.1假设跑comparison模块验证（置信度判定为verified，结果写回树节点）->
  conclude生成综合结论HTML。全部用真实DashScope LLM调用，未降级。
- 旧版回归：raw.csv预先写好直接调`_initial_state`+`graph.stream`，确认
  `node0_clarification`不进入interrupt直接到node2诊断确认，跑完整条
  Node1-5+followup_ready，`stage`/`problem_card`全程保持初始空值，证明本次
  改造对旧版完全透明。

本批未做：Step5（增量上传支持）、Step6（前端三栏对话界面，需整体重做现有
step-based组件），按计划延后到下次会话。

---

## 2026-06-17（续5，清洗计划可编辑+拒绝回退，修复单表分析读取merged_data_path的bug）

### Node3清洗计划预览改为可编辑，拒绝不再终止会话

此前确认流程只有"往下走"一条路：`TransformPreview.js`只有确认/取消两个按钮，取消
直接走`_route_after_preview`到`END`，整个LangGraph会话结束，用户只能重新上传文件
（已记录在DEBT.md）。本次改造：

- `TransformPreview.js`：每条清洗操作加删除按钮；`fillna`填充值/`cast_type`目标
  类型/`unit_convert`换算系数支持inline编辑；提交时把编辑后的plan回传，不再是
  纯只读展示
- `node3_preview`（`api/core/graph.py`）：interrupt的resume约定从`bool`改为
  `{"action": "confirm"|"reject", "plan": [...]}`；`confirm`时用前端回传的
  （可能编辑过的）plan，`reject`时通过`_route_after_preview`路由回
  `node2_confirmation`重新触发口径确认interrupt，而不是走`END`
- `run_transform`（`api/nodes/node3_transform.py`）新增`final_plan`参数：给定时
  直接按此plan执行（仍经`_order_plan`重新排序+校验op类型，不跳过固定函数集合的
  约束），不再重新调用LLM生成补充操作，确保"预览看到的"与"实际执行的"是同一份
  plan（修复了此前preview展示的plan和confirm后实际执行的plan可能因LLM非确定性
  而不一致的潜在问题）
- `ConfirmationForm.js`新增`initialSchema`prop：退回到口径确认时沿用用户上一轮
  的编辑结果（重命名/排除字段/缺失值策略），而不是重新从诊断结果生成默认值
- `api/routes/v03.py`的`/transform/confirm`：`approved=false`时不再返回
  `transform/cancelled`后挂起，而是继续推进图执行到下一个interrupt（即
  node2_confirmation的Phase1），推送`confirmation/waiting_confirmation`事件，
  `pages/index.js`据此重新展示`ConfirmationForm`并清理本轮已失效的
  `join_plan`/`transform`时间线状态

### 顺带修复：单表分析场景读取了不存在的merged_data_path文件

回归验证时发现`node4_analysis`/`node5_report`/`node6_followup`三处都用
`state.get("merged_data_path") or state["cleaned_data_path"]`选数据源，但
`merged_data_path`在`_initial_state`里始终是非空路径字符串（即使没有任何join发
生），导致单表场景永远走到这个分支去读一个从未被写入的`merged.parquet`，
Node4直接抛`FileNotFoundError`，单表全流程此前实际无法跑通Node4之后的步骤。
`api/core/graph.py`新增`_data_path(state)`helper，按`confirmed_join_plan`是否
真的有`joins`来决定用哪个路径，三处统一改为调用该helper。

curl端到端验证：上传单表CSV→口径确认→清洗预览拒绝（验证回退到口径确认而非
END）→重新确认（验证`initialSchema`生效，编辑值被保留）→清洗预览确认（编辑后
删除`drop_duplicates`步骤、修改`fillna`填充值，验证实际执行的plan与编辑结果
一致）→分析→报告→追问就绪，全流程正常完成。

## 2026-06-17（续4）

### 新增转化漏斗分析模块（FunnelModule），补齐DEBT.md记录的漏斗覆盖缺口

新增 `api/modules/funnel.py`（category=转化/留存）：按实体（user_id）启发式识别
"曝光→申请→授信→放款"等业务漏斗阶段——按列名关键词+该列是否非空自动判定，不依赖
用户在口径确认界面手动标注；输出各阶段人数、环比转化率、总转化率，图表用ECharts
原生funnel类型。按"新增分析模块步骤"四步走：实现`BaseAnalysisModule`子类→
`registry.py`注册→`VisualizationModule`无需改动（已有defaults补全通用）→未改动
Node4主流程代码。`node5_report.py`同步补充"转化/留存"类别的置信度固定等级与相关
字段空值率映射。

### 接入回归中发现并修复3个bug

1. **漏斗阶段判定列误选维度表同名字段**：多表join时不同表可能有同名字段（如
   `dim_user_profile_risk`和`dwd_credit_apply`都有`credit_limit`列），`pd.merge`
   对冲突列加表名后缀，原列名被先join的表占用。原实现按关键词只取第一个匹配列，
   曾错误选中风险维度表的`credit_limit`（几乎对所有人非空），统计出"授信"阶段
   3460人超过"申请"阶段1008人，违反漏斗单调递减的业务逻辑。修复：候选列改为收集
   所有匹配列，结合"该列非空人数不能超过上一阶段人数"的业务约束筛选，满足约束的
   候选里选人数最大（最贴近真实转化）的那一列。
2. **叙事生成多环节比较数值推理错误**：转化漏斗的LLM叙事曾把"申请至授信环节"
   误判为流失最严重环节（实际曝光→申请的28%转化率才是三段中最低的）。给
   `_generate_narrative`的system prompt补充通用规则：涉及多阶段/环比/占比比较时
   必须严格按数据给出的比例字段判断，不要凭直觉估算，该规则对其余4个模块同样适用。
3. **`drop_duplicates`无保护阈值，曾致99.5%数据被误删**（较严重）：QA回归中发现
   一次清洗后所有模块样本量从16237骤降到84行，且整条流程不报错、不中断，所有
   下游分析在错误的84行小样本上跑完，没有任何提示。根因：`drop_duplicates`是
   LLM自由生成的"补充清洗操作"之一，不像`fillna`/`drop_rows_with_null`来自
   confirmed_schema里用户对每个字段的明确选择；LLM给的subset如果选了几个低基数
   字段组合（如event_name+platform+app_version），事件日志表里大量"看起来相同
   但实际是独立事件"的行会被误判为重复。`api/nodes/node3_transform.py`的
   `op_drop_duplicates`新增保护：执行后删除比例超过50%时判定为疑似subset误判，
   跳过该操作保留原数据并打印日志。本地验证：低基数subset（会删98.8%数据）被
   正确拦截，高基数subset正常生效。

同时改进`test_output/qa_loop.js`本身的稳定性：ECharts是`next/dynamic`懒加载，
固定`sleep(2000)`检查图表数偶发不稳定（出现过误判"无图表"），改为等待第一个
canvas出现再继续检查。

修复后连续2轮全流程回归（样本量16237行、漏斗3600→1008→811→384单调递减、
Path A-F全pass、报告质量3-4/4维度合格）确认稳定，详见`test_output/loop_log.md`。

---

## 2026-06-17（续3）

### 自动化QA Loop（Playwright，5表Join场景）发现并修复4个bug

用真实5张钱包业务表（事实表+维度表）跑通 Path A-F 全流程（澄清→上传→诊断→口径确认→
Join方案确认→清洗预览→分析→报告→追问），Playwright脚本见 `test_output/qa_loop.js`，
连续2轮全部通过（A-F pass）后收尾，记录于 `test_output/loop_log.md`。

发现并修复：

1. **`api/routes/upload.py` 多表上传错误纵向拼接**（最严重）：原逻辑对任意多文件都做
   `pd.concat(axis=0)`，对5张列名完全不同的表（事实表+维度表）拼接后产生49列错位宽表，
   Node1/Node2诊断的几乎所有列空值率被虚假推高到40%~99%，完全掩盖真实口径问题。
   改为：列名完全一致才纵向合并（同口径多文件场景），否则诊断只读行数最多的表（如
   `ods_wallet_events`），其余表仍各自存入 `tables/` 供 Join 方案使用。修复后诊断
   正确检出 `event_name`命名混乱、`material_id`空值率55%等真实问题。
2. **`pages/index.js` Step0问题澄清渲染丢失**：Join方案确认功能合入（`8fa9e7f`）时
   误删了 `<ClarificationChat>` 的渲染分支，上传区直接显示，澄清流程不可达。已恢复。
3. **多表join后维度静态属性被误当事件指标sum累加**：`credit_score`等用户维度属性
   join进事件表后按用户重复到每条事件行，Trend/Comparison模块默认对数值列做sum，
   导致"总额"随事件数虚假放大（Segmentation曾产出"平均信用评分5168.38"这种明显
   超出真实量级300-850的结论）。新增 `api/modules/_metrics.py` 共享启发式，按
   user_id/apply_id/loan_id分组识别"重复不变"的维度列，优先选事件级列+sum，否则
   退化为维度列+mean；Segmentation对维度列改用first而非sum。顺带修复一个独立的
   `pd.qcut` NaN分组导致 `labels[NaN]` 抛 TypeError 的潜伏bug。
4. **多表场景"口径确认"时间线状态永远卡在等待确认**：`node2_confirmation` 函数体
   内两个 `interrupt()`，只有两阶段都resume后节点才算返回；多表场景下该节点在
   `/confirm`接口里卡在Phase2 interrupt上从未返回，`confirmation/confirmed`事件
   从未发出。已在 `/confirm/join` 节点真正完成时补发该事件。

修复后报告质量人工抽查：结论具体（带百分比/具体数值）、置信度三维度标注齐全、
建议可执行（如"对debt_ratio超40%的客户提高审批门槛"），且不再含统计学上荒谬的
结论（trend从虚假的"9.73%下降"纠正为真实的"-0.8%基本平稳"）。

### 已知限制（记录于DEBT.md，本次未修复）

- 分析模块覆盖的是"维度属性的趋势/对比/分群"，尚未覆盖转化漏斗
  （曝光→申请→授信→放款）各环节的转化率/留存类分析，需要新增按
  user_id/apply_id/loan_id统计各阶段计数与转化率的逻辑，工作量较大，留作后续迭代。

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

