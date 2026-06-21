# 开发状态

> 本文件只保留"当前待办"视图，历史改动的详细过程记录在 CHANGELOG.md（按日期追加，
> 不重复整理在这里）。2026-06-20 起按此规则精简维护。

## 进行中

- （无）

## 待开始（按优先级）

1. **WeasyPrint PDF导出**：已决策维持现状（HTML直出），除非明确要重新做PDF导出，
   否则不再保留为待办，详见 DEBT.md。

## 已完成（概括，详情见CHANGELOG.md）

- 2026-06-15 ~ 2026-06-19：完整Minerva重构（问题澄清→上传→口径确认→Join方案→
  清洗计划预览→假设树生成→验证→综合结论的对话式全流程）、9批用户体验反馈修复、
  部署改造为裸仓库push+post-receive自动checkout、LLM主路径切换Ark+DashScope
  glm-5.1双路径降级。旧版线性流程（`pages/index.js`）已被Minerva实际取代，
  相关P1/P2遗留项（JoinPlanForm重新生成按钮、Join阶段返回改口径）不再投入。
- 2026-06-20：线上端到端测试场景1-8全部执行完毕（单表/多表Join/假设树MECE/
  数据不相关拦截/表级口径处理/高频LLM调用/综合结论生成/模糊输入收敛），过程中
  排查并排除了用户反馈的"502"（实为历史日志噪音+真实499均已在更早修复中解决），
  发现并修复2个真实bug（AttributionModule分类自变量500崩溃、event_name等同义值
  清洗被静默跳过，均见DEBT.md「已解决」）。
- 2026-06-21：Minerva综合结论report.html嵌入图表（持久化单假设验证图表到假设树
  节点 + 新增KPI总览/状态分布图，前端ECharts JS渲染，vendor本地echarts.min.js，
  零新增系统依赖），报告结构按商业分析师交付惯例重排（执行摘要前置）。已部署
  线上（commit afcb3a8），用服务器真实测试数据（minerva_test_data.csv）跑通
  node_verification→node_conclusion 全流程，确认 chart_spec 正确持久化到假设树
  节点，且 `GET /api/report/{session_id}/html` 真实HTTP路由返回的report.html
  含两条假设的图表div+/static/echarts.min.js引用，`/static/echarts.min.js`
  本身200可访问。
