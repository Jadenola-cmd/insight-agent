# 开发状态

> 本文件只保留"当前待办"视图，历史改动的详细过程记录在 CHANGELOG.md（按日期追加，
> 不重复整理在这里）。2026-06-20 起按此规则精简维护。

## 进行中

- （无）

## 待开始（按优先级）

1. **Minerva综合结论report.html是否需要嵌入图表**（需先确认是否要做，未排期）：
   `api/templates/minerva_conclusion.html.j2`目前只有文字+置信度徽标，不含任何
   图表；右侧实时面板的ECharts图表不会进入落盘的`report.html`。旧版`api/render/`
   ECharts SSR渲染器是为已废弃的旧线性流程`report.html.j2`设计的，目标已经过时，
   如果要做应该是"给Minerva综合结论加图表"这个新问题，不是简单捡回旧渲染器。
2. **WeasyPrint PDF导出**：已决策维持现状（HTML直出），除非明确要重新做PDF导出，
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
