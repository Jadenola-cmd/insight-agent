Loop | 2026-06-17T10:35:46.452Z
A: pass
B: pass
C: pass
D: pass
E: fail
F: fail
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理）
---
Loop | 2026-06-17T10:40:00.491Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: fail
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=true 可操作性=true
---
Loop | 2026-06-17T10:42:06.393Z
A: pass
B: pass
C: pass
D: fail
E: fail
F: fail
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理）
---
Loop | 2026-06-17T10:45:37.808Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=false 可操作性=true
---
Loop | 2026-06-17T10:48:32.727Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=true 可操作性=true
---
Loop | 2026-06-17T11:37:44.920Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=true 可操作性=true
---
Loop | 2026-06-17T11:41:48.076Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=false 可操作性=true
---
Loop | 2026-06-17T11:46:49.430Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=false 可操作性=true
---
Loop | 2026-06-17T11:49:59.967Z
A: pass
B: pass
C: pass
D: pass
E: fail
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=false 可操作性=true
---
Loop | 2026-06-17T11:58:32.900Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=false 可操作性=true
---
Loop | 2026-06-17T12:01:59.367Z
A: pass
B: pass
C: pass
D: pass
E: pass
F: pass
备注: Path A 检出口径问题(页面文本扫描): event_name命名混乱 / Path C join方案: primary_table=ods_wallet_events（预期ods_wallet_events，合理） / Path F维度: 严谨性=true 完整性(漏斗覆盖)=true 具体性=false 可操作性=true
---

## Minerva Loop | 2026-06-18 第1轮

测试目标：单表/多表/假设验证追问/模糊输入边界 4场景，服务地址
http://175.178.91.42:3001/minerva，脚本 `minerva_scenario.js`

| 场景 | 结果(修复前) | 结果(修复后) | 报告质量评分 |
|---|---|---|---|
| 1 单表 | PASS（隐性受影响，见下） | PASS | ~72/100 |
| 2 多表+Join | PASS（隐性受影响） | PASS | ~83/100 |
| 3 验证追问 | 技术PASS，但发现严重bug | PASS | ~87/100 |
| 4 模糊输入边界 | PASS | PASS | N/A（追问质量定性合格） |

### 发现并修复（阻断核心产品逻辑，已修复）

**假设树首次resume被静默重新生成，验证结果错配**：`node_hypothesis_tree`在
`interrupt()`暂停前做懒初始化生成树，LangGraph恢复时节点函数从头重跑，该生成
从未提交checkpoint，导致首次resume（verify/chat）重新调LLM生成一棵完全不同
内容的新树，用户选择验证的node_id被错配到新树同id但语义不同的节点。用
Playwright拦截网络response实测复现（场景3：12节点初始树→首次verify后变成
15节点完全不同措辞的树）。修复：拆出`node_hypothesis_init`独立节点用普通
return提交生成结果。修复后4次resume验证tree内容稳定不变，仅目标节点
status/summary被正确更新。详见CHANGELOG.md 2026-06-18续19。

### 复核：已知问题（STATUS.md组A/B/C），未重复记录

- 组C(#6/#7/#9 验证假设无推荐方案/结论假设脱节/雷同结论)：本轮验证模块仍是
  config={}盲选，场景1/2报告确认存在"结论与验证数据关联性偏弱"的现象，与
  已知问题一致，未新增记录。注：本轮修复的resume重跑bug是这组症状的一个
  更深层助因（验证错配会进一步放大"结论脱节"的表现），但并非唯一原因，
  组C盲选问题本身仍需后续单独处理。
- 组A(#1/#4/#5 前端loading态/图表区域大小)、组B(#2/#3 表级问题文案/清洗计划
  缓存)：本轮未涉及，未触发。

### 终止条件判定

4个场景全部PASS，报告质量评分全部≥60。终止条件满足，本轮（第1轮）结束。
