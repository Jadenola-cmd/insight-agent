import { useState } from "react";

const STAGES = ["问题定义", "假设树构建", "验证执行"];

const INITIAL_HYPOTHESES = [
  { id: "1-1", group: "供给侧", label: "授信策略收紧，客群需求本身更低", status: "pending", priority: false },
  { id: "1-2", group: "供给侧", label: "产品体验某环节出现问题导致流失", status: "pending", priority: false },
  { id: "2-1", group: "需求侧", label: "季节性需求波动（节假日/发薪日规律）", status: "pending", priority: true },
  { id: "2-2", group: "需求侧", label: "竞品分流（同期其他平台低息活动）", status: "pending", priority: false },
  { id: "2-3", group: "需求侧", label: "宏观消费意愿整体收缩", status: "pending", priority: false },
  { id: "3-1", group: "数据侧", label: "授信到支用时间间隔拉长（未支用≠不想支用）", status: "pending", priority: true },
];

const STATUS_CONFIG = {
  pending: { icon: "○", color: "#4A5568", label: "待验证" },
  active:  { icon: "◎", color: "#F0A500", label: "验证中" },
  partial: { icon: "◑", color: "#F0A500", label: "部分验证" },
  confirmed: { icon: "●", color: "#48BB78", label: "已验证" },
  rejected: { icon: "✕", color: "#FC8181", label: "已排除" },
};

const DEMO_CONVERSATION = [
  {
    stage: 0,
    messages: [
      { role: "user", text: "最近几个月信贷产品支用率持续下滑，应该从哪些维度去拆解分析？" },
      { role: "ai", text: "在开始拆解之前，我需要先理解几个背景。\n\n这个产品是纯线上还是有线下场景？获客主要是自有流量还是外部渠道导流？\n\n我问这个是因为支用率下滑的原因在不同场景下差异很大——自有流量下滑更可能是产品或定价问题，外部渠道导流下滑更可能是客群质量变化。" },
      { role: "user", text: "纯线上，外部渠道导流为主。从11%一直降到5%，持续了大概三个月。" },
      { role: "ai", text: "明白了。再问一个关键问题：\n\n11%这个基准是怎么来的？是行业水平、历史均值、还是内部目标？\n\n另外，下滑开始前你们有没有做过任何产品或运营上的调整？比如授信策略、定价、渠道结构？\n\n这个问题的原因我后面说。" },
      { role: "user", text: "11%是过去半年的历史均值。下滑前没有明显的产品调整，渠道结构也基本稳定。" },
      { role: "ai", isCard: true, text: "问题陈述已确认", card: {
        problem: "信贷产品支用率从历史均值11%持续下滑至5%，历时约3个月",
        metric: "支用率 = 实际借款用户 / 获得授信额度用户，基准11%（近半年历史均值）",
        meaning: "支用率下滑可能代表：①真实借款意愿下降 ②授信客群结构变化 ③产品体验阻断 ④竞品分流 ⸺需要区分",
        goal: "找出支用率持续下滑的主因，输出可被业务侧采取行动的建议"
      }},
    ]
  },
  {
    stage: 1,
    messages: [
      { role: "ai", text: "基于你的情况，我梳理出6个候选假设。\n\n有两个值得优先验证，因为验证成本低且解释力强——我已在地图中标注⭐。\n\n你之前提到支用率会「莫名整体变高」，这个细节很重要，我把它转化成了假设2.1（季节性规律）。你当时没有深查它，这次可以验证一下。" },
      { role: "user", text: "我之前拆过渠道、风险评分、定价额度分层，每个维度下各客群都在同步下滑，没有明显区分度。" },
      { role: "ai", text: "全维度同步下滑是一个重要发现，它排除了「结构性变化」的解释——如果是某个渠道或客群出问题，不会全体同步。\n\n这反而支持两个方向：\n① 有一个「共同原因」同时影响所有人（季节/宏观/竞品）\n② 是统计口径问题（时间间隔变化导致的假性下滑）\n\n我建议先验证假设3.1——授信到支用的时间间隔有没有拉长。这个数据你应该有，五分钟能查。" },
    ]
  },
  {
    stage: 2,
    messages: [
      { role: "user", text: "好，我们先验证假设3.1，看看授信到支用的时间间隔变化。" },
      { role: "ai", isVerify: true, text: "正在执行验证：假设3.1", verify: {
        hypothesis: "授信到支用时间间隔拉长（未支用≠不想支用）",
        query: "按月统计：授信日期到首次支用日期的中位数间隔天数",
        result: [
          { month: "1月", days: 4.2 },
          { month: "2月", days: 4.8 },
          { month: "3月", days: 5.1 },
          { month: "4月", days: 6.9 },
          { month: "5月", days: 8.3 },
          { month: "6月", days: 9.7 },
        ]
      }},
      { role: "ai", text: "验证结果：假设3.1 部分成立。\n\n授信到支用的中位数间隔从4.2天拉长到9.7天，增幅131%，与支用率下滑时间吻合。\n\n**这意味着**：部分「未支用」用户可能只是「还没支用」，不是不想借。当前支用率指标存在统计偏差。\n\n**但这不是全部原因**：即使校正时间窗口，支用率仍有下滑，需要继续验证假设2.1（季节性规律）。\n\n要继续验证吗？", partialVerify: "3-1" },
    ]
  }
];

function HypothesisTree({ hypotheses, stage }) {
  const groups = [...new Set(hypotheses.map(h => h.group))];
  return (
    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
      {groups.map(group => (
        <div key={group} style={{ marginBottom: 12 }}>
          <div style={{ color: "#4A5568", fontSize: 10, letterSpacing: 1, marginBottom: 6, textTransform: "uppercase" }}>
            {group}
          </div>
          {hypotheses.filter(h => h.group === group).map(h => {
            const cfg = STATUS_CONFIG[h.status];
            return (
              <div key={h.id} style={{
                display: "flex", alignItems: "flex-start", gap: 6,
                marginBottom: 6, opacity: stage < 1 ? 0.3 : 1,
                transition: "opacity 0.4s"
              }}>
                <span style={{ color: cfg.color, fontSize: 13, marginTop: 1, flexShrink: 0 }}>{cfg.icon}</span>
                <span style={{ color: h.status === "pending" ? "#718096" : "#E8EDF2", lineHeight: 1.4 }}>
                  {h.label}
                  {h.priority && stage >= 1 && (
                    <span style={{ color: "#F0A500", marginLeft: 4 }}>⭐</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function VerifyChart({ data }) {
  const max = Math.max(...data.map(d => d.days));
  return (
    <div style={{ marginTop: 8 }}>
      {data.map((d, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ color: "#718096", fontSize: 10, width: 24, fontFamily: "monospace" }}>{d.month}</span>
          <div style={{ flex: 1, background: "#1A2535", borderRadius: 2, height: 14, overflow: "hidden" }}>
            <div style={{
              width: `${(d.days / max) * 100}%`,
              height: "100%",
              background: d.days > 6 ? "#FC8181" : "#F0A500",
              transition: "width 0.6s ease",
              borderRadius: 2,
            }} />
          </div>
          <span style={{ color: "#E8EDF2", fontSize: 10, fontFamily: "monospace", width: 32 }}>{d.days}天</span>
        </div>
      ))}
    </div>
  );
}

function ProblemCard({ card }) {
  return (
    <div style={{
      background: "#0D1F2D", border: "1px solid #F0A500",
      borderRadius: 6, padding: 14, marginTop: 6
    }}>
      <div style={{ color: "#F0A500", fontSize: 10, letterSpacing: 1, marginBottom: 10, textTransform: "uppercase" }}>
        ✦ 问题陈述已确认
      </div>
      {[
        ["问题", card.problem],
        ["指标基准", card.metric],
        ["业务含义", card.meaning],
        ["分析目标", card.goal],
      ].map(([label, value]) => (
        <div key={label} style={{ marginBottom: 8 }}>
          <div style={{ color: "#4A5568", fontSize: 10, marginBottom: 2 }}>{label}</div>
          <div style={{ color: "#E8EDF2", fontSize: 12, lineHeight: 1.5 }}>{value}</div>
        </div>
      ))}
    </div>
  );
}

function Message({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div style={{
      display: "flex", justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom: 14,
    }}>
      {!isUser && (
        <div style={{
          width: 26, height: 26, borderRadius: "50%",
          background: "#F0A500", color: "#0F1923",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, fontWeight: 700, marginRight: 8, flexShrink: 0, marginTop: 2,
          fontFamily: "'Space Grotesk', sans-serif"
        }}>M</div>
      )}
      <div style={{ maxWidth: "80%" }}>
        {msg.isCard ? (
          <ProblemCard card={msg.card} />
        ) : msg.isVerify ? (
          <div style={{
            background: "#0D1F2D", border: "1px solid #2D3748",
            borderRadius: 6, padding: 14
          }}>
            <div style={{ color: "#718096", fontSize: 10, marginBottom: 4 }}>验证执行中</div>
            <div style={{ color: "#E8EDF2", fontSize: 12, marginBottom: 8 }}>{msg.verify.hypothesis}</div>
            <div style={{ color: "#4A5568", fontSize: 10, marginBottom: 6 }}>查询：{msg.verify.query}</div>
            <VerifyChart data={msg.verify.result} />
          </div>
        ) : (
          <div style={{
            background: isUser ? "#1A3A5C" : "#141E2B",
            border: `1px solid ${isUser ? "#2D5A8C" : "#1E2D3D"}`,
            borderRadius: isUser ? "12px 12px 2px 12px" : "2px 12px 12px 12px",
            padding: "10px 14px",
            color: "#E8EDF2", fontSize: 13, lineHeight: 1.7,
            whiteSpace: "pre-line"
          }}>
            {msg.text}
          </div>
        )}
      </div>
    </div>
  );
}

export default function MinervaPrototype() {
  const [stage, setStage] = useState(0);
  const [hypotheses, setHypotheses] = useState(INITIAL_HYPOTHESES);
  const [input, setInput] = useState("");

  const visibleMessages = DEMO_CONVERSATION
    .filter(s => s.stage <= stage)
    .flatMap(s => s.messages);

  const stageHypotheses = stage >= 2
    ? hypotheses.map(h =>
        h.id === "3-1" ? { ...h, status: "partial" } : h
      )
    : hypotheses;

  const problemDefined = stage >= 0;
  const treeBuilt = stage >= 1;
  const verifying = stage >= 2;

  return (
    <div style={{
      fontFamily: "'Inter', sans-serif",
      background: "#0F1923", color: "#E8EDF2",
      minHeight: "100vh", display: "flex", flexDirection: "column"
    }}>
      {/* Header */}
      <div style={{
        borderBottom: "1px solid #1E2D3D", padding: "12px 24px",
        display: "flex", alignItems: "center", gap: 16
      }}>
        <div style={{
          fontFamily: "'Space Grotesk', sans-serif",
          fontSize: 18, fontWeight: 700, letterSpacing: -0.5,
          color: "#F0A500"
        }}>Minerva</div>
        <div style={{ color: "#4A5568", fontSize: 12 }}>分析思维的对话伙伴</div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {STAGES.map((s, i) => (
            <button key={i} onClick={() => setStage(i)} style={{
              padding: "4px 12px", borderRadius: 4, fontSize: 11,
              border: `1px solid ${stage === i ? "#F0A500" : "#1E2D3D"}`,
              background: stage === i ? "#F0A500" : "transparent",
              color: stage === i ? "#0F1923" : "#4A5568",
              cursor: "pointer", fontFamily: "'Space Grotesk', sans-serif",
              fontWeight: 600, transition: "all 0.2s"
            }}>
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Body: 3-column */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Left: Analysis Map */}
        <div style={{
          width: 240, borderRight: "1px solid #1E2D3D",
          padding: 16, overflowY: "auto", flexShrink: 0
        }}>
          <div style={{
            fontSize: 10, color: "#4A5568", letterSpacing: 1,
            textTransform: "uppercase", marginBottom: 16
          }}>分析地图</div>

          {/* Stage 0: Problem */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <div style={{
                width: 6, height: 6, borderRadius: "50%",
                background: problemDefined ? "#48BB78" : "#4A5568"
              }} />
              <span style={{
                fontSize: 11, fontWeight: 600,
                color: problemDefined ? "#48BB78" : "#4A5568",
                fontFamily: "'Space Grotesk', sans-serif"
              }}>问题定义</span>
              {problemDefined && <span style={{ color: "#48BB78", fontSize: 10 }}>✓</span>}
            </div>
            {problemDefined && (
              <div style={{
                fontSize: 11, color: "#718096", lineHeight: 1.5,
                paddingLeft: 14, borderLeft: "1px solid #1E2D3D"
              }}>
                支用率下滑：11% → 5%<br />持续约3个月
              </div>
            )}
          </div>

          {/* Stage 1: Hypothesis Tree */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <div style={{
                width: 6, height: 6, borderRadius: "50%",
                background: treeBuilt ? "#F0A500" : "#4A5568"
              }} />
              <span style={{
                fontSize: 11, fontWeight: 600,
                color: treeBuilt ? "#F0A500" : "#4A5568",
                fontFamily: "'Space Grotesk', sans-serif"
              }}>假设树</span>
              {treeBuilt && <span style={{ color: "#718096", fontSize: 10 }}>
                {verifying ? "1/6 验证中" : "6个假设"}
              </span>}
            </div>
            <div style={{ paddingLeft: 14, borderLeft: "1px solid #1E2D3D" }}>
              <HypothesisTree hypotheses={stageHypotheses} stage={stage} />
            </div>
          </div>

          {/* Stage 2: Conclusion */}
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <div style={{
                width: 6, height: 6, borderRadius: "50%",
                background: "#4A5568"
              }} />
              <span style={{ fontSize: 11, fontWeight: 600, color: "#4A5568", fontFamily: "'Space Grotesk', sans-serif" }}>
                综合结论
              </span>
            </div>
            <div style={{ fontSize: 11, color: "#2D3748", paddingLeft: 14 }}>
              待验证完成后生成
            </div>
          </div>
        </div>

        {/* Center: Conversation */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
            {visibleMessages.map((msg, i) => (
              <Message key={i} msg={msg} />
            ))}
          </div>

          {/* Input */}
          <div style={{
            borderTop: "1px solid #1E2D3D", padding: "12px 24px",
            display: "flex", gap: 10, alignItems: "center"
          }}>
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder={
                stage === 0 ? "描述你观察到的业务问题..." :
                stage === 1 ? "补充背景信息，或确认开始验证某个假设..." :
                "继续讨论验证结果，或选择下一个假设..."
              }
              style={{
                flex: 1, background: "#141E2B",
                border: "1px solid #1E2D3D", borderRadius: 6,
                padding: "10px 14px", color: "#E8EDF2", fontSize: 13,
                outline: "none", fontFamily: "'Inter', sans-serif"
              }}
            />
            <button style={{
              background: "#F0A500", color: "#0F1923",
              border: "none", borderRadius: 6,
              padding: "10px 18px", fontSize: 13, fontWeight: 600,
              cursor: "pointer", fontFamily: "'Space Grotesk', sans-serif",
              letterSpacing: 0.3
            }}>发送</button>
          </div>
        </div>

        {/* Right: Data Panel */}
        <div style={{
          width: 220, borderLeft: "1px solid #1E2D3D",
          padding: 16, overflowY: "auto", flexShrink: 0
        }}>
          <div style={{
            fontSize: 10, color: "#4A5568", letterSpacing: 1,
            textTransform: "uppercase", marginBottom: 16
          }}>数据结果</div>

          {stage < 2 ? (
            <div style={{ color: "#2D3748", fontSize: 12, lineHeight: 1.6 }}>
              确认验证假设后，<br />数据结果将在此展示
            </div>
          ) : (
            <div>
              <div style={{
                background: "#141E2B", border: "1px solid #1E2D3D",
                borderRadius: 6, padding: 12, marginBottom: 12
              }}>
                <div style={{ fontSize: 10, color: "#F0A500", marginBottom: 8 }}>假设3.1 验证结果</div>
                <div style={{ fontSize: 10, color: "#718096", marginBottom: 4 }}>授信→支用中位数间隔</div>
                <div style={{ fontSize: 22, fontWeight: 700, color: "#FC8181", fontFamily: "'Space Grotesk', sans-serif" }}>
                  +131%
                </div>
                <div style={{ fontSize: 10, color: "#718096" }}>4.2天 → 9.7天</div>
              </div>

              <div style={{
                background: "#141E2B", border: "1px solid #1E2D3D",
                borderRadius: 6, padding: 12, marginBottom: 12
              }}>
                <div style={{ fontSize: 10, color: "#4A5568", marginBottom: 6 }}>置信度</div>
                <div style={{ display: "flex", gap: 4 }}>
                  {["样本量", "数据质量", "方法"].map((d, i) => (
                    <div key={i} style={{
                      flex: 1, textAlign: "center",
                      background: i === 0 ? "#1A3A1A" : "#1A2535",
                      borderRadius: 4, padding: "4px 0"
                    }}>
                      <div style={{ fontSize: 9, color: "#4A5568" }}>{d}</div>
                      <div style={{ fontSize: 11, color: i === 0 ? "#48BB78" : "#F0A500", fontWeight: 600 }}>
                        {i === 0 ? "高" : "中"}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{
                background: "#0D1F10", border: "1px solid #1A3A1A",
                borderRadius: 6, padding: 12
              }}>
                <div style={{ fontSize: 10, color: "#48BB78", marginBottom: 6 }}>下一步建议</div>
                <div style={{ fontSize: 11, color: "#718096", lineHeight: 1.6 }}>
                  校正统计窗口后继续验证假设2.1（季节性规律）
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
