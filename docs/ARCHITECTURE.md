# 技术架构文档 — Business Analysis Agent

> 本文档描述系统的整体架构、LangGraph 状态机设计、模块接口约定与部署方案。
> 实现时若与本文档冲突，以 `CLAUDE.md` 中的五条核心约束为最高优先级。
> 标注"设计阶段，待实现"的内容对应 `docs/PRD.md` v0.3 新增需求（Node0 问题澄清、
> Node3 清洗计划预览确认、Node5 置信度标注、Node6 追问对话），尚未编码，不影响
> 已实现的 Node1-5 主流程。

---

## 1. 总体架构

```
┌─────────────┐      上传CSV       ┌──────────────────────────────────────┐
│  Next.js     │ ─────────────────▶ │  FastAPI                              │
│  前端        │                    │                                        │
│              │ ◀───── SSE ─────── │  ┌──────────────────────────────────┐ │
│  - 上传      │   流程状态推送      │  │   LangGraph StateGraph            │ │
│  - 进度展示  │                    │  │                                    │ │
│  - 口径确认  │ ── confirmed_schema│  │  Node1 → Node2(中断) → Node3       │ │
│  - 报告预览  │ ──────────────────▶│  │   → Node4 → Node5                 │ │
│  - PDF下载   │ ◀──── 报告/PDF ─── │  └──────────────────────────────────┘ │
└─────────────┘                    │                                        │
                                    │  api/data/<session_id>/               │
                                    │    raw.csv / cleaned.parquet / report.pdf │
                                    └──────────────────────────────────────┘
```

- 单用户、无登录：每次上传生成一个 `session_id`（UUID），所有中间文件与状态以
  `session_id` 为命名空间隔离，存放在 `api/data/<session_id>/` 下。
- 前后端通过以下接口交互（已实现部分见 `api/routes/`）：
  - `POST /api/upload`：上传文件，创建 session（`api/data/<session_id>/raw.csv`），
    返回 `session_id`
  - `GET /api/analyze/{session_id}/stream`：启动 LangGraph 流程（SSE），
    依次推送 Node1 诊断结果与 Node2 中断事件，推送
    `confirmation/waiting_confirmation` 后本次 SSE 连接结束
  - `POST /api/analyze/{session_id}/confirm`：提交 `confirmed_schema`
    （见第3.2节），用 `Command(resume=...)` 恢复被 Node2 中断的流程（SSE），
    推送 `confirmation/confirmed` 后结束（后续 Node3-5 接入后，此连接将继续
    推送对应事件）
  - `GET /api/report/<session_id>.pdf`：下载报告（Node5 实现后接入）

**v0.3 新增（设计阶段，待实现，详见 `docs/PRD.md` Step0/Step4/Step7）：**
  - `POST /api/clarify/start` + `POST /api/clarify/{session_id}/reply`：Step0
    对话式问题澄清（不超过3轮），最终输出 `analysis_goal`（分析目标 + 所需数据清单 +
    将运行的分析模块），确认后才进入 `/api/upload`
  - `POST /api/analyze/{session_id}/transform/confirm`：Node3 生成清洗 plan 后
    中断等待，前端展示「待执行操作」逐条预览，用户确认后提交本接口恢复执行
  - `POST /api/analyze/{session_id}/followup`：Step7 追问对话，基于
    `cleaned_data_path` 增量分析，结论追加进 `report_html` 对应章节

---

## 2. State 设计

```python
class AnalysisState(TypedDict):
    # 控制流
    current_node: str                 # 当前执行节点名，供 SSE 推送展示
    analysis_type: str                # 预留：用户可指定关注的分析类型（MVP 可不暴露）
    user_confirmations: dict          # Node2 产出的 confirmed_schema

    # 数据流（路径引用，不存实际DataFrame）
    raw_data_path: str                # 上传的原始 CSV 路径
    cleaned_data_path: str            # Node3 清洗后数据路径（parquet）
    analysis_results: dict            # Node4 输出：{module_name: {chart_spec, insight, ...}}
    charts_data: dict                 # VisualizationModule 转换后的 ECharts options
    report_html: str                  # Node5 组装的报告 HTML（PDF 生成前的中间产物）

    # v0.3 新增（设计阶段，待实现）
    analysis_goal: dict               # Node0 输出：{question, decision_context, required_data, modules}
    clarification_history: list       # Node0 对话轮次记录（问题澄清的多轮QA）
    transform_plan: dict              # Node3 生成的清洗plan（预览确认前，中断时写入）
    confidence_notes: dict            # Node5 按 {module_name: {level, reasons}} 记录置信度标注
    followup_history: list            # Node6 追问对话记录，每条含追加到report的结论引用
```

**约束（对应 CLAUDE.md 第4条）**：`raw_data_path`/`cleaned_data_path` 是字符串路径，
任何 Node 需要数据时自行 `pd.read_csv`/`pd.read_parquet`，处理完成后写回新文件并更新
路径字段。State 本身只在 Node 之间传递元数据和路径，不持有 DataFrame 对象，
保证 LangGraph checkpoint 序列化轻量。

---

## 3. LangGraph 节点设计

### Node0 — Question Clarification（设计阶段，待实现）
- **对应**：PRD Step0，流程入口，**在上传数据之前执行**。
- **输入**：用户的初始自然语言描述（如"看看最近的转化情况"）。
- **处理**：LLM 以选择题/简短追问形式与用户对话，**不超过3轮**，逐步把模糊需求收敛为
  结构化的 `analysis_goal`：
  - `question`：明确后的业务问题描述
  - `decision_context`：分析结果用于支持什么决定
  - `required_data`：所需数据清单（表/字段层级的粗粒度描述，供用户参考上传）
  - `modules`：预计将运行的分析模块名单（对应 `AnalysisRegistry` 中的模块，仅作展示，
    Node4 仍按 `validate()` 实际判断是否运行）
- **输出**：`analysis_goal` 写入 state，SSE 推送澄清结果供用户确认；确认后流程进入
  上传环节（`POST /api/upload`），`raw_data_path` 写入后续才触发 Node1。
- **与 Node1-5 的关系**：`analysis_goal.question`/`decision_context` 作为上下文传给
  Node5（叙事生成时回应 Step0 定义的问题）；`analysis_goal.modules` 不强制约束 Node4，
  仅用于前端展示"预计分析方向"。

### Node1 — Data Diagnosis
- **输入**：`raw_data_path`
- **处理**：
  1. `pandas.read_csv` 读取数据，计算每列的：dtype、空值率、唯一值数量、
     数值列的分布统计（min/max/mean/quantile）、字符串列的高频取值样例。
  2. 将列的统计摘要（不含原始数据）发给 LLM，请求结构化 JSON：每列的业务含义
     推断、建议的标准列名、可能的口径问题（如"列A和列B疑似重复""列C空值率
     过高""日期格式不统一"等）。
  3. 合并 Pandas 统计结果与 LLM 推断，输出诊断报告 JSON。
- **输出**：诊断报告 JSON 通过 SSE 推送给前端；同时写入 state 供 Node2 使用。
- **失败降级**：LLM 调用失败时，仍返回 Pandas 统计结果，业务含义字段标记为
  "AI推断暂不可用"，不阻断流程（用户仍可在 Node2 手动确认）。

### Node2 — Human Confirmation（中断点，已实现）
- **机制**：`api/core/graph.py` 中 `node2_confirmation` 调用 LangGraph
  `interrupt({"diagnosis": diagnosis})`：
  - 首次执行时抛出中断，`graph.stream(...)` 产出
    `{"__interrupt__": (Interrupt(value={"diagnosis": ...}), ...)}`，
    路由层据此推送 `confirmation/waiting_confirmation` SSE 事件并结束本次连接。
  - 前端 `POST /api/analyze/{session_id}/confirm` 提交 `confirmed_schema` 后，
    路由层用 `graph.stream(Command(resume=confirmed_schema_dict), config)` 恢复
    执行，`interrupt()` 直接返回该 `confirmed_schema_dict`，写入
    `state.user_confirmations`，推送 `confirmation/confirmed` 事件。
- **会话隔离 / 恢复**：`MemorySaver` 按 `thread_id = session_id` 隔离各会话的
  checkpoint（`api/core/graph.py: graph_config`）。`POST .../confirm` 前会调用
  `graph.get_state(config)` 检查该 session 是否确实处于中断等待状态
  （`any(t.interrupts for t in state.tasks)`），否则返回
  `confirmation/error`。
- **前端交互**：用户基于 Node1 诊断报告，对每个字段确认/修改最终列名、业务含义、
  是否参与后续分析，并为口径问题给出处理意见，组装成 `confirmed_schema`
  （见 3.2 节）后提交。
- **超时/未确认**：MVP 阶段不做自动超时清理；`MemorySaver` 为纯内存
  checkpoint，**进程重启会丢失所有处于中断等待状态的会话**（记录到
  `DEBT.md`，后续如需跨进程持久化可替换为
  `SqliteSaver`/`PostgresSaver`）。
- **PRD v0.3 对齐说明**："字段含义可编辑"（PRD Step3）已由现有
  `ColumnConfirmation.business_meaning` 字段满足——该字段本身即为"用户确认/修改后的
  业务含义"，前端展示时需将其渲染为可编辑输入框（而非只读文本），无需新增字段或
  后端改动。

### 3.2 confirmed_schema 结构（Node2 ↔ Node3 契约）

`api/core/schema.py` 中定义：

```python
class ColumnConfirmation(TypedDict):
    original_name: str        # Node1 诊断报告中的原始列名
    final_name: str           # 用户确认/修改后的列名
    business_meaning: str     # 用户确认/修改后的业务含义
    include: bool             # 是否参与后续清洗与分析
    missing_value_strategy: Literal["none", "fill", "drop_rows"]
    fill_value: str | float | None  # strategy == "fill" 时使用

class ConfirmedSchema(TypedDict):
    columns: list[ColumnConfirmation]
    resolved_table_issues: list[str]  # 用户对 table_issues 的处理说明（自由文本）
```

- `/api/analyze/{session_id}/confirm` 的请求体用对应的 Pydantic 模型
  `ConfirmedSchemaRequest`/`ColumnConfirmationRequest` 做校验（同一字段集合）。
- Node3 生成清洗 plan 时，直接遍历 `confirmed_schema.columns`：
  - `include=False` 的列 → 生成 `drop_columns` 操作；
  - `final_name != original_name` → 生成 `rename_column` 操作；
  - `missing_value_strategy="fill"` → 生成 `fillna` 操作（值取 `fill_value`）；
  - `missing_value_strategy="drop_rows"` → 该列纳入 `drop_duplicates`/行级
    缺失值删除的列集合；
  - `resolved_table_issues` 作为自由文本一并发给 LLM，供其在生成 plan 时参考
    （如"amount_usd 与 amount 重复，丢弃 amount_usd"直接对应一条
    `drop_columns` 操作，与 `include=False` 互相印证）。

### Node3 — Deterministic Transform Engine
- **输入**：`raw_data_path` + `user_confirmations`（即 `confirmed_schema`）
- **处理**：
  1. **确定性部分**（不经 LLM，由 `confirmed_schema` 直接推导）：
     - `include=False` 的列 → 一条 `drop_columns` 操作
     - `final_name != original_name` 的列 → 一条 `rename_column` 操作
     - `missing_value_strategy="fill"` 的列 → 一条 `fillna` 操作
     - `missing_value_strategy="drop_rows"` 的列 → 汇总进一条 `drop_rows_with_null` 操作
  2. **LLM 补充部分**：将 `confirmed_schema`（含 `business_meaning`、确定性部分生成的
     操作列表）+ `resolved_table_issues` 发给 LLM，请求输出补充操作列表（仅允许
     `cast_type`/`strip_whitespace`/`standardize_categories`/`unit_convert`/
     `drop_duplicates` 这五类，见 3.3 节），列引用均使用**重命名后的 `final_name`**。
  3. 合并两部分操作为最终 plan，**按 3.3 节规定的固定执行顺序**（而非数组中的
     原始顺序）依次调用对应的 `op_*` 函数执行，**不存在任何 `eval`/`exec`/
     动态代码路径**。plan 中出现未识别的 `op` 直接报错并中止（不静默忽略）。
  4. 清洗后数据写入 `cleaned_data_path`（parquet，保留 dtype）。
- **对应 CLAUDE.md 第3条**：完整的操作类型枚举见 3.3 节，后续新增操作类型需
  同时更新 3.3 节表格与对应 `op_*` 执行函数。

### 3.3 Node3 清洗操作类型枚举（plan op schema）

**固定执行顺序**（与 plan 数组中的原始顺序无关，Node3 按以下顺序分组执行，
保证「重命名先于引用」「类型转换先于填充」「行级删除/去重最后执行」）：

| 顺序 | op | 来源 | 参数 | 说明 |
|----|----|------|------|------|
| 1 | `rename_column` | 确定性（`final_name != original_name`） | `from`, `to` | 重命名列 |
| 2 | `drop_columns` | 确定性（`include=False`）+ LLM（重复字段等） | `columns: list[str]` | 删除列；两个来源的结果合并去重 |
| 3 | `cast_type` | LLM（基于 `business_meaning`/口径问题推断） | `column`, `to`, `format?` | 类型转换，`to` ∈ `int`/`float`/`string`/`datetime`/`bool`；数值/日期转换失败的值统一转为 `NaN`（`errors="coerce"`），不中止流程；`to="datetime"` 时 `format` 为可选的 `pandas` 日期格式串 |
| 4 | `strip_whitespace` | LLM | `columns: list[str]` | 对字符串列做 `.str.strip()`，处理"前后空格不一致"类口径问题 |
| 5 | `standardize_categories` | LLM | `column`, `mapping: dict[str,str]` | 按 `mapping` 统一同一分类的不同写法（如 `"美国"/"USA"` → `"美国"`），未在 `mapping` 中的取值保持不变 |
| 6 | `unit_convert` | LLM（基于 `resolved_table_issues` 中的单位换算说明） | `column`, `factor: float`, `new_name?` | 数值列乘以 `factor` 做单位换算（如"分→元"传 `0.01`）；`new_name` 可选，提供时同时重命名该列 |
| 7 | `fillna` | 确定性（`missing_value_strategy="fill"`） | `column`, `value: str \| float` | 用 `fill_value` 填充缺失值；`value` 为字面量，不支持 `mean`/`median` 等统计关键字（MVP 范围外） |
| 8 | `drop_rows_with_null` | 确定性（`missing_value_strategy="drop_rows"`） | `columns: list[str]` | 删除指定列集合中**任一列**为空的行；多个列汇总进同一条操作 |
| 9 | `drop_duplicates` | LLM（基于 `resolved_table_issues` 中的行重复说明） | `subset: list[str] \| null` | 删除重复行；`subset=null` 表示整行完全一致才视为重复 |

**示例 plan**（合并后，未按执行顺序排列，由 Node3 重排）：
```json
[
  {"op": "rename_column", "from": "amt", "to": "amount_cents"},
  {"op": "drop_columns", "columns": ["dup_col"]},
  {"op": "unit_convert", "column": "amount_cents", "factor": 0.01, "new_name": "amount"},
  {"op": "cast_type", "column": "order_date", "to": "datetime", "format": "%Y/%m/%d"},
  {"op": "standardize_categories", "column": "region", "mapping": {"美国": "美国", "USA": "美国"}},
  {"op": "fillna", "column": "channel", "value": "未知"},
  {"op": "drop_duplicates", "subset": ["order_id"]}
]
```

**执行函数映射**（`api/nodes/node3_transform.py`，均为固定 Python 函数，按 `op`
分发，禁止动态代码路径）：

| op | 函数 |
|----|------|
| `rename_column` | `op_rename_column` |
| `drop_columns` | `op_drop_columns` |
| `cast_type` | `op_cast_type` |
| `strip_whitespace` | `op_strip_whitespace` |
| `standardize_categories` | `op_standardize_categories` |
| `unit_convert` | `op_unit_convert` |
| `fillna` | `op_fillna` |
| `drop_rows_with_null` | `op_drop_rows_with_null` |
| `drop_duplicates` | `op_drop_duplicates` |

**未来扩展**（暂不实现，需要时按本节流程补充枚举+函数+表格）：
- `fillna` 的统计关键字填充（`mean`/`median`/`mode`）
- 拆分/合并列（如"姓名"拆分为"姓"+"名"）

### 3.4 清洗计划预览确认（设计阶段，待实现）

- **对应**：PRD Step4，"执行前预览确认"。
- **机制**：在 Node3 现有流程中插入第二个中断点——LLM 生成并与确定性操作合并、按
  3.3 节排序后的最终 plan，**先不执行**，调用 `interrupt({"transform_plan": plan})`
  写入 `state.transform_plan`，路由层推送 `node3_transform`/`status: "interrupted"`
  SSE 事件，前端逐条展示「待执行操作」（含每条操作的人类可读描述，如"删除列：
  amount_usd（与amount数值完全一致）"、"填充缺失值：risk_tier空值→'未知'（预计影响
  1,024行）"，预计影响行数需在生成 plan 时一并计算并附在每条操作上）。
- **前端交互**：用户可对单条操作勾选/取消（MVP 范围内是否支持编辑单条操作参数待定，
  默认仅支持整体确认或取消重新进入 Node2）；确认后调用
  `POST /api/analyze/{session_id}/transform/confirm`，用
  `Command(resume=...)` 恢复执行 `op_*` 函数链。
- **不违反 CLAUDE.md 第3条**：预览的是已生成的固定 plan（JSON），不引入新的代码执行
  路径；用户确认只是"是否执行"的开关，不改变 Node3 的执行函数集合。

### Node4 — Modular Analysis Engine
- **输入**：`cleaned_data_path`
- **处理**：
  1. `AnalysisRegistry` 遍历已注册模块，对每个模块调用 `validate(df) -> bool`，
     判断该模块是否可在当前数据上运行（如 `ComparisonModule` 需要至少一个分类列
     + 一个数值列；`TrendInsightModule` 需要至少一个时间列）。
  2. 对可运行的模块依次调用 `run(df, config) -> dict`，得到标准化结果
     `{"metrics": ..., "insight_data": ...}`。
  3. 对每个模块结果调用 `get_chart_spec(results) -> dict`，得到标准化 `chart_spec`
     （见第4节）。
  4. 汇总所有模块的 `{chart_spec, metrics, insight_data}` 写入
     `state.analysis_results`。
- **VisualizationModule**：独立于分析模块之后运行，遍历 `analysis_results` 中所有
  `chart_spec`，转换为 ECharts option，写入 `state.charts_data`。**不修改**
  `analysis_results` 中的分析结果本身。

### Node5 — Narrative + PDF Generator
- **输入**：`analysis_results` + `charts_data`（+ `analysis_goal`，若 Node0 已执行）
- **处理**：
  1. 对每个分析模块的 `insight_data`，调用 LLM 生成"结论 - 数据支撑 - 运营建议"
     三段式文字（结构化输出，每段独立字段，便于模板渲染）。若 `analysis_goal` 存在，
     报告首部追加"分析目标回顾"段落，直接回应 Step0 定义的问题（PRD Step6）。
  2. 按 5.1 节规则为每个模块结果计算 `confidence_notes[module_name]`。
  3. Jinja2 模板（`api/templates/report.html.j2`）组装完整报告 HTML：标题、
     各模块的三段式洞察 + 对应图表（图表在 PDF 中以静态图片或 ECharts 服务端
     渲染方式呈现，具体方案见第5节）+ 每个结论块的置信度标注。
  4. WeasyPrint 将 HTML 转换为 PDF，写入 `api/data/<session_id>/report.pdf`。
- **输出**：`report_html` 写入 state；PDF 文件路径通过最终 SSE 事件通知前端，
  前端展示下载链接。

#### 5.1 置信度标注规则（设计阶段，待实现；确定性规则，不经过 LLM）

对应 PRD 第四节。每个分析模块结果按以下三个维度分别评级，**取三者最低值**作为该
结论块的最终置信度，评级依据对用户可见（展示在报告中）：

| 维度 | 高 | 中 | 低（加警示） |
|------|----|----|------------|
| 样本量（`len(df)`） | >1000 | 200-1000 | <200 |
| 相关字段空值率 | <5% | 5-20% | >20% |
| 分析方法 | 描述性统计/漏斗（Trend/Comparison/Segmentation） | 回归归因（Attribution，附R²） | 预测模型（Prediction） |

- 计算位置：Node5 在调用 LLM 生成三段式文字之前，先用 `analysis_results` 中各模块的
  `metrics`（样本量、相关字段空值率）+ 模块 `category` 算出
  `confidence_notes[module_name] = {"level": "高|中|低", "reasons": [...]}`。
  `reasons` 记录每个维度的具体取值与对应评级，供模板渲染"为什么是这个置信度"。
- 模板渲染：每个三段式结论块旁附 `level` 徽标；`level == "低"` 时额外渲染警示样式。

### Node6 — Follow-up Dialogue（设计阶段，待实现）

- **对应**：PRD Step7，报告生成后的追问对话；流程图中位于 Node5 之后，可被多次
  触发（用户每次追问视为一次 Node6 执行，结果累积进 `followup_history`）。
- **输入**：用户追问文本 + `cleaned_data_path` + `analysis_results`（已有结论，
  避免重复分析）+ `followup_history`。
- **处理（现有数据可回答）**：
  1. LLM 判断该问题能否基于 `cleaned_data_path` 现有列回答；若能，确定需要运行的
     分析模块（复用 `AnalysisRegistry`，可能是已运行模块的不同 `config` 切片，
     如"高意向未转化用户的风险等级分布"对应 `SegmentationModule` 的子集分析）。
  2. 调用对应模块 `run()`/`get_chart_spec()`，按 5.1 节规则计算置信度，生成三段式
     结论文字。
  3. 结果以"补充分析（追问）"的形式追加到 `report_html` 中对应模块章节下（不替换
     主分析结论），并写入 `followup_history`。
- **处理（需要新数据）**：
  1. LLM 判断现有数据无法回答，输出需补充的数据说明（表名/字段建议，参考 PRD
     Step7 示例）。
  2. SSE 推送提示信息，前端展示"建议补充字段"并提供新文件上传入口。
  3. 用户补传后走短路径：新表走 Node1 诊断 → 关联现有 `cleaned_data_path`（关联键
     由 LLM 推断，用户确认）→ 针对性运行 Node4 相关模块 → 回到本节步骤3追加报告。
- **输出**：更新后的 `report_html`；若已生成过 PDF，需重新调用 WeasyPrint 生成新
  `report.pdf`（覆盖或加版本号，待实现时确定）。
- **不违反 CLAUDE.md 约束**：Node6 复用 Node4 的 `AnalysisRegistry`/模块接口与
  Node5 的三段式生成+置信度逻辑，不引入新的分析方法分类或渲染路径。

---

## 4. chart_spec 标准格式（分析模块 ↔ VisualizationModule 契约）

**chart_spec 直接采用标准 ECharts option 格式**（`title`/`xAxis`/`yAxis`/`series`/
`tooltip`/`legend` 等 ECharts 原生字段），前端浏览器与后端 PDF 渲染复用同一份配置，
不再设计独立的抽象 schema 与转换层。

```json
{
  "title": { "text": "图表标题" },
  "tooltip": {},
  "xAxis": { "type": "category", "data": ["..."] },
  "yAxis": { "type": "value" },
  "series": [
    { "name": "...", "type": "line", "data": [1, 2, 3] }
  ]
}
```

- 各分析模块的 `get_chart_spec()` 直接返回一个合法的 ECharts option 对象。
- `VisualizationModule` 的职责收窄为：对 chart_spec 做轻量校验/默认值补全
  （如统一主题色、默认 `tooltip`/`legend`），**不修改 `series` 中的数据内容，
  不引入任何分析逻辑**——仍满足 `CLAUDE.md` 约束5（VisualizationModule 只做
  chart_spec 到渲染配置的转换/补全，不做理解）。
- 前端 `echarts-for-react` 直接将 `charts_data` 中的 option 传给 `<ReactEcharts option={...} />`；
  后端 Node5 用同一份 option 做服务端渲染（见第7节）。

---

## 5. 分析模块接口（BaseAnalysisModule）

```python
class BaseAnalysisModule(ABC):
    name: str               # 模块标识，注册到 AnalysisRegistry 的 key
    category: str           # 业务问题类别（趋势/对比/分群/归因/预测）

    @abstractmethod
    def validate(self, df: pd.DataFrame) -> bool:
        """判断该模块是否可在当前数据上运行"""

    @abstractmethod
    def run(self, df: pd.DataFrame, config: dict) -> dict:
        """执行分析，返回标准化结果（metrics + insight_data）"""

    @abstractmethod
    def get_chart_spec(self, results: dict) -> dict:
        """将 run() 的结果转换为标准 chart_spec（见第4节）"""
```

### 初期五个模块

| 模块 | 业务问题类别 | validate 条件（初步） | 说明 |
|------|------|------|------|
| `TrendInsightModule` | 趋势/时序 | 存在可解析为日期/时间的列 | 分布、趋势、异常检测 |
| `ComparisonModule` | 对比/分组 | 存在分类列 + 数值列 | 同比环比、A/B、TOP/BOTTOM |
| `SegmentationModule` | 用户/人群 | 存在用户/实体ID列 | 分群、留存、Cohort、行为路径 |
| `AttributionModule` | 贡献/驱动因素 | 存在因变量 + 多个候选自变量 | 漏斗、贡献度分解；预留 OLS/DID 接口（复用 empirical-agent） |
| `PredictionModule` | 预测 | （初期 `validate` 返回 `False`） | 后期扩展，初期空壳 |

`AnalysisRegistry` 维护模块实例列表，提供：
```python
class AnalysisRegistry:
    def register(self, module: BaseAnalysisModule): ...
    def get_runnable_modules(self, df: pd.DataFrame) -> list[BaseAnalysisModule]: ...
```

---

## 6. SSE 事件协议（初步设计）

后端通过 SSE 向前端推送的事件统一为：

```json
{
  "node": "node1_diagnosis",
  "status": "running | done | error | interrupted",
  "payload": { ... }   // 该节点的输出，结构因 node 而异
}
```

- `node2_confirmation` 的 `status: "interrupted"` 事件携带 Node1 的诊断报告，前端
  据此渲染确认界面，并停止等待后续 SSE 事件，直到用户提交 `confirmed_schema`。
- `node5_report` 的 `status: "done"` 事件携带 PDF 下载链接。

**v0.3 新增节点对应的 `node` 取值（设计阶段，待实现）：**
- `node0_clarification`：`status: "interrupted"` 携带当前澄清问题/选项，
  `status: "done"` 携带最终 `analysis_goal`
- `node3_transform`：在原有 `done` 事件之前新增一次 `status: "interrupted"`，
  携带 `transform_plan`（见 3.4 节），用户确认后才推送原有的 `transform/done`
- `node6_followup`：每次追问对应一组 `running → done` 事件，`done` 的 `payload`
  携带本次追加的 `chart_spec`/三段式结论/`confidence_notes`，前端据此局部更新
  报告预览

---

## 7. PDF 报告图表渲染方案（已确认）

**方案：ECharts 服务端渲染（SSR，SVG renderer）→ 嵌入报告 HTML → WeasyPrint 转 PDF**

- `chart_spec` 即标准 ECharts option（见第4节），前端浏览器与 PDF 渲染复用同一份配置，
  保证两端视觉一致。
- FastAPI（Python）本身不具备 ECharts 渲染能力，引入一个轻量 Node.js 子进程渲染器：
  - 目录：`api/render/`
    - `api/render/package.json`：独立于前端 `package.json`，仅依赖 `echarts`
      （及其 SSR 所需的 `zrender`，随 `echarts` 安装）
    - `api/render/render_chart.js`：从 stdin 读取一个 chart_spec（ECharts option）
      JSON，调用：
      ```js
      const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width, height });
      chart.setOption(option);
      const svg = chart.renderToSVGString();
      ```
      将 SVG 字符串输出到 stdout。
  - Node5 通过 `subprocess` 对 `charts_data` 中每个 chart_spec 调用一次
    `render_chart.js`，得到 SVG 字符串，作为 Jinja2 模板变量内嵌到报告 HTML
    （`<div class="chart">{{ svg|safe }}</div>`）。WeasyPrint 原生支持内联 SVG，
    无需再转 PNG。
- **失败降级**：Node 子进程不可用或单个图表渲染报错时，该图表位置替换为
  "图表渲染失败"占位文字，不阻断整份报告生成（其余模块的洞察文字与图表正常输出）。
- **部署要求**：服务器需安装 Node.js 运行时（供 `api/render/` 子进程使用），
  与前端 Next.js 共享 Node 环境即可；记录到 `STATUS.md` 部署待办。

---

## 8. 部署架构

- **后端**：腾讯云轻量服务器，FastAPI + Uvicorn，PM2 管理进程（如
  `business-analysis-api`），端口与 empirical-agent 的 8000 区分（建议 8001，
  实现时在 `STATUS.md`/`.env.example` 中明确）。
- **前端**：Next.js `next build` 静态导出或 PM2 管理的 Node 进程，Nginx 反向代理
  `/api/*` → 后端端口，`/*` → 前端端口（沿用 empirical-agent 的 Nginx 分流模式）。
- **文件存储**：`api/data/<session_id>/` 为临时文件，无持久化数据库；定期清理策略
  待实现（记录到 `DEBT.md`）。
- **仅国内线路**：不部署到 Vercel/Railway，与 empirical-agent 的双环境部署模式不同。
