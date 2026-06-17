# Business Analysis Agent — AGENTS.md

面向商业/经营分析师的AI协作提效工具（**不是业务侧自助分析平台**）作品集 Demo，同时作为
可长期演进的真实产品：流程以 Step0 对话式问题澄清开始（明确分析目标与所需数据），随后
用户上传业务数据 CSV，Agent（LangGraph 多节点流程）自动诊断数据口径、清洗（执行前预览
确认）、执行问题驱动的分析模块、生成图表与"结论-数据支撑-运营建议"三段式洞察文字并标注
置信度，支持追问对话将新结论动态追加进报告，最终输出 PDF 报告。无登录系统，单用户直接
访问。详见 `docs/PRD.md`（v0.3）。

@STATUS.md
@DEBT.md

---

## 与 empirical-agent 的关系

- 同一开发者的姊妹项目，**代码库完全独立**（不同 git 仓库、不同部署端口），但复用同一套
  项目文件结构规范（根目录 `AGENTS.md`/`CHANGELOG.md`/`STATUS.md`/`DEBT.md` + `docs/`）
  和文档维护流程。
- 技术栈同源：Next.js 14 前端 + FastAPI 后端 + 阿里云 DashScope（DeepSeek）LLM，部署在同一台
  腾讯云轻量服务器，但使用**新端口**，与 empirical-agent 的 PM2 进程（`empirical-api`:8000 /
  `empirical-web`:3000）互不冲突。
- `AttributionModule`（贡献度分解）预留接口，未来复用 empirical-agent 中已实现的
  OLS / DID 统计方法（`linearmodels`/`statsmodels`），避免重复实现面板回归基础设施。
- 两个项目定位不同：empirical-agent 面向论文实证分析（强统计严谨性、对齐 Stata），
  本项目面向业务分析场景（强调问题驱动的洞察输出与报告生成），**不要把两者的开发约束
  互相套用**。

---

## 技术栈

### 前端
- **框架**: Next.js 14（Pages Router，与 empirical-agent 一致）
- **图表**: ECharts（`echarts` + `echarts-for-react`），由 `VisualizationModule` 输出的
  `chart_spec` 直接映射为 ECharts option
- **实时进度**: SSE（`EventSource` 或 `fetch` + `ReadableStream`）订阅后端 LangGraph 各
  Node 执行状态

### 后端
- **框架**: FastAPI + Uvicorn，Python 3.12
- **流程编排**: LangGraph（多节点状态机，含 Human-in-the-loop 中断/恢复；Node0 问题澄清、
  Node3 清洗计划预览确认、Node6 追问对话为 v0.3 新增设计，详见
  `docs/ARCHITECTURE.md`）
- **数据处理**: `pandas`、`numpy`
- **统计方法**: `statsmodels`（`AttributionModule` 预留，复用 empirical-agent 的 OLS/DID 思路）
- **报告生成**: Jinja2（HTML 模板）+ WeasyPrint（HTML → PDF）；图表通过 ECharts
  服务端渲染（Node.js 子进程，`api/render/`）生成 SVG 后嵌入报告 HTML（详见
  `docs/ARCHITECTURE.md` 第7节）
- **AI 推断/解读**: 阿里云 DashScope API（DeepSeek 模型，沿用 empirical-agent 的
  `DASHSCOPE_API_KEY` 配置方式）

### 环境变量
| 变量 | 用途 |
|------|------|
| `NEXT_PUBLIC_API_URL` | 前端指向的后端地址 |
| `DASHSCOPE_API_KEY` | DashScope LLM 密钥 |
| `API_PORT` | 后端服务端口（需与 empirical-agent 的 8000 区分） |

---

## 文件结构

```
business-analysis-agent/
├── pages/                     # Next.js 前端（Pages Router）
│   ├── index.js               # 上传 + 流程进度（SSE） + 口径确认 + 报告预览/下载
│   └── _app.js
├── api/
│   ├── main.py                # FastAPI 入口，注册路由
│   ├── requirements.txt
│   ├── core/
│   │   ├── state.py           # AnalysisState（TypedDict，控制流/数据流分离）
│   │   ├── schema.py           # ConfirmedSchema（Node2↔Node3契约）+ 请求体校验模型
│   │   ├── paths.py            # session 路径helper
│   │   └── graph.py            # LangGraph 图装配（Node1→Node2中断，Node3-5待接入）
│   ├── nodes/
│   │   ├── node0_clarification.py # （待实现）Step0问题澄清对话，输出analysis_goal
│   │   ├── node1_diagnosis.py     # 数据诊断（Pandas统计 + LLM字段语义推断）
│   │   ├── node2_confirmation.py  # Human-in-loop 中断点
│   │   ├── node3_transform.py     # 确定性清洗引擎（LLM出plan + 执行前预览确认中断 + 固定函数执行）
│   │   ├── node4_analysis.py      # 模块化分析引擎（调用 AnalysisRegistry）
│   │   ├── node5_report.py        # 叙事生成（含置信度标注） + Jinja2 + WeasyPrint
│   │   └── node6_followup.py      # （待实现）Step7追问对话，结论追加进report_html
│   ├── modules/
│   │   ├── base.py             # BaseAnalysisModule 抽象基类
│   │   ├── registry.py         # AnalysisRegistry 注册与自动匹配
│   │   ├── trend.py             # TrendInsightModule
│   │   ├── comparison.py        # ComparisonModule
│   │   ├── segmentation.py      # SegmentationModule
│   │   ├── attribution.py       # AttributionModule（预留OLS/DID接口）
│   │   ├── prediction.py        # PredictionModule（壳）
│   │   └── visualization.py     # VisualizationModule（chart_spec -> ECharts配置）
│   ├── routes/
│   │   ├── upload.py            # 文件上传
│   │   ├── analyze.py           # 启动/恢复流程、SSE 推送
│   │   └── health.py            # 健康检查
│   ├── templates/
│   │   └── report.html.j2       # PDF 报告 Jinja2 模板
│   ├── render/                   # ECharts 服务端渲染（Node.js 子进程）
│   │   ├── package.json          # 独立于前端，仅依赖 echarts
│   │   └── render_chart.js       # stdin: chart_spec(JSON) -> stdout: SVG
│   ├── services/
│   │   └── llm.py                # DashScope 客户端封装
│   └── data/                     # 上传文件 / 清洗后数据（路径引用，按 session 隔离）
├── docs/
│   ├── PRD.md                    # 产品需求文档
│   └── ARCHITECTURE.md           # 完整技术架构文档
├── CHANGELOG.md                  # 迭代记录（只追加）
├── STATUS.md                     # 当前开发状态（已完成/进行中/待开始）
├── DEBT.md                       # 技术债务记录
├── package.json
└── next.config.js
```

---

## 核心约束（不得违反）

1. **问题驱动而非方法驱动**：所有分析模块对应的是业务问题类别（趋势/对比/人群/归因/预测），
   不是按统计方法分类。新增模块前先问"这是哪一类业务问题"，而不是"这是哪个统计方法"。

2. **标准化输出，禁止模块自渲染**：每个分析模块的 `run()` 必须输出结构化的
   `chart_spec`（图表配置描述）+ `insight`（结论性 JSON），**任何分析模块都不允许直接
   生成可视化内容**。渲染统一交给 `VisualizationModule`。

3. **Node3 严禁执行 LLM 生成的任意代码**：LLM 只负责根据 `confirmed_schema` 输出 JSON
   格式的清洗操作计划（plan）。Node3 的清洗逻辑必须是**固定的 Python 函数集合**，按 plan
   中的操作类型分发执行，绝不能 `eval`/`exec` LLM 输出的代码字符串。

4. **DataFrame 不进入 LangGraph state**：`AnalysisState` 中的数据字段（`raw_data_path`/
   `cleaned_data_path`）只存文件路径（如 parquet/csv 路径），各 Node 按需自行读取文件。
   State 中不出现 `pd.DataFrame` 对象，避免序列化/checkpoint 膨胀。

5. **VisualizationModule 是纯转换层**：只做"分析模块输出的 `chart_spec` → ECharts option"
   的格式转换，不包含任何统计/业务分析逻辑，也不反向影响分析结果。

---

## 开发规范

- **模块开发顺序**：先实现 `BaseAnalysisModule` + `AnalysisRegistry`，再逐个实现
  `TrendInsightModule`/`ComparisonModule`/`SegmentationModule`，`AttributionModule` 和
  `PredictionModule` 可后置。
- **新增分析模块步骤**：① 继承 `BaseAnalysisModule`，实现 `validate`/`run`/
  `get_chart_spec`；② 在 `AnalysisRegistry` 注册；③ `VisualizationModule` 按需补充对应
  `chart_spec` 类型到 ECharts option 的映射；④ 不修改 Node4 主流程代码。
- **Session/文件管理**：参考 empirical-agent 的 session 缓存思路，但本项目无登录系统，
  按上传请求生成的 `session_id` 隔离 `api/data/` 下的文件，避免单用户多次上传互相覆盖。
- **本地启动**：
  ```bash
  # 后端
  cd api && uvicorn main:app --reload --port <API_PORT>

  # 前端
  npm run dev
  ```

---

## 文档维护规则

每次会话结束前，若本次有代码改动，必须执行：
1. **`CHANGELOG.md`**：追加一条，格式 `## YYYY-MM-DD` + 改动要点
2. **`STATUS.md`**：更新"已完成/进行中/待开始"三个分区

DEBT.md 按需更新：引入新技术债时追加，偿还旧债时标注或删除。


---

## 会话摘要规则

用户输入 `/summary` 指令时，生成会话摘要到 `sessions/` 目录。

1. **触发方式**：用户输入 `/summary`（或 `/summary <任务描述>`）时立即执行。
2. **命名格式**：`YYYY-MM-DD_HHMM.md`（与 Claude Code 摘要统一格式）。
3. **格式**：YAML frontmatter（`date`/`project`/`tags`）+ 主要任务 / 完成内容 / 关键决策 /
   遗留事项，参考 `scripts/_TEMPLATE.md`。
4. **辅助脚本**：`python scripts/generate_summary.py "<任务描述>"` 先生成模板，再填入
   实际内容。
5. **合并到 Claude Code 目录**：生成后在终端执行：
   `copy sessions\*.md "D:\01_Knowledge\Projects\202606_InsightAgent\会话摘要\"`
   将 Codex 摘要合并到 Claude Code 摘要目录。
6. **与 CHANGELOG 的区别**：CHANGELOG 记录"做了什么"（面向产品迭代），会话摘要记录
   "怎么做的 + 为什么这么做 + 接下来做什么"（面向开发连续性）。

`DEBT.md` 按需更新：引入新技术债时追加，偿还旧债时标注或删除。
