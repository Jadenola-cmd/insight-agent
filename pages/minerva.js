import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import ConfirmationForm from "../components/ConfirmationForm";
import JoinPlanForm from "../components/JoinPlanForm";
import TransformPreview from "../components/TransformPreview";

// ECharts 依赖 window/document，需禁用 SSR（同 components/AnalysisReport.js 的做法）
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// 验证假设时可选的分析模块（对应 api/modules/registry.py 的 default_registry，
// PredictionModule 为空壳故不列出）
const MODULE_OPTIONS = [
  { name: "trend_insight", label: "趋势/时序" },
  { name: "comparison", label: "对比/分组" },
  { name: "segmentation", label: "用户/人群" },
  { name: "attribution", label: "贡献/驱动因素" },
  { name: "funnel", label: "转化/留存" },
];

const STATUS_CONFIG = {
  pending: { icon: "○", color: "#909399" },
  verifying: { icon: "◎", color: "#e6a23c" },
  partial: { icon: "◑", color: "#e6a23c" },
  verified: { icon: "●", color: "#67c23a" },
  rejected: { icon: "✕", color: "#f56c6c" },
};

function genSessionId() {
  return `mnv${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
}

async function readSseStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      if (!part.startsWith("data: ")) continue;
      try {
        onEvent(JSON.parse(part.slice("data: ".length)));
      } catch {
        // 忽略格式错误的片段
      }
    }
  }
}

// 各 interrupt() payload 形状不同，靠特征字段区分对应阶段（与 api/core/graph.py 的
// 各节点 interrupt() 调用一一对应）
function classifyInterrupt(payload) {
  if (!payload) return null;
  if (payload.type === "problem_definition") {
    return { phase: "clarify", history: payload.history || [] };
  }
  if (payload.type === "awaiting_data") {
    return { phase: "awaiting_data", problemCard: payload.problem_card };
  }
  if (payload.type === "hypothesis_tree") {
    return {
      phase: "hypothesis_tree",
      tree: payload.tree || [],
      lastVerification: payload.last_verification || null,
      problemCard: payload.problem_card,
    };
  }
  if (payload.diagnosis) return { phase: "confirmation", diagnosis: payload.diagnosis };
  if (payload.join_plan) {
    return { phase: "join_plan", joinPlan: payload.join_plan, tableColumns: payload.table_columns || {} };
  }
  if (payload.transform_plan) return { phase: "transform", transformPlan: payload.transform_plan };
  return { phase: "unknown", raw: payload };
}

export default function Minerva() {
  const [sessionId] = useState(genSessionId);
  const [phase, setPhase] = useState("loading");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  const [problemCard, setProblemCard] = useState(null);
  const [diagnosis, setDiagnosis] = useState(null);
  const [joinPlan, setJoinPlan] = useState(null);
  const [tableColumns, setTableColumns] = useState({});
  const [transformPlan, setTransformPlan] = useState([]);
  const [tree, setTree] = useState([]);
  const [lastVerification, setLastVerification] = useState(null);
  const [conclusionHtml, setConclusionHtml] = useState("");

  const [files, setFiles] = useState([]);
  const [verifyTarget, setVerifyTarget] = useState(null);
  const [verifyModule, setVerifyModule] = useState(MODULE_OPTIONS[0].name);

  const startedRef = useRef(false);

  const addMessage = (role, text) => setMessages((prev) => [...prev, { role, text }]);

  const applyInterrupt = (classified) => {
    if (!classified) return;
    setPhase(classified.phase);
    if (classified.phase === "clarify") {
      setMessages(classified.history.map((m) => ({ role: m.role === "user" ? "user" : "ai", text: m.content })));
    } else if (classified.phase === "awaiting_data") {
      setProblemCard(classified.problemCard || null);
      if (classified.problemCard?.analysis_goal) {
        addMessage("ai", `已确认分析目标：${classified.problemCard.analysis_goal}\n\n请上传需要分析的数据文件（CSV）。`);
      } else {
        addMessage("ai", "请上传需要分析的数据文件（CSV）。");
      }
    } else if (classified.phase === "confirmation") {
      setDiagnosis(classified.diagnosis);
      addMessage("ai", "数据诊断完成，请确认字段口径。");
    } else if (classified.phase === "join_plan") {
      setJoinPlan(classified.joinPlan);
      setTableColumns(classified.tableColumns);
      addMessage("ai", "已生成多表关联方案，请确认。");
    } else if (classified.phase === "transform") {
      setTransformPlan(classified.transformPlan);
      addMessage("ai", "已生成清洗计划，请确认。");
    } else if (classified.phase === "hypothesis_tree") {
      setTree(classified.tree);
      setLastVerification(classified.lastVerification);
      if (classified.problemCard) setProblemCard(classified.problemCard);
    }
  };

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/analyze/${sessionId}/stream`);
        await readSseStream(res, (evt) => {
          if (evt.status === "error") {
            setErrorMessage(evt.data?.message || "未知错误");
            setPhase("error");
            return;
          }
          if (evt.node === "diagnosis" && evt.status === "running") return;
          applyInterrupt(classifyInterrupt(evt.data));
        });
      } catch (err) {
        setErrorMessage(err.message);
        setPhase("error");
      }
    })();
  }, [sessionId]);

  const resume = async (value) => {
    const res = await fetch(`${API_URL}/api/analyze/${sessionId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.status === "done") {
      setPhase("conclusion");
      const htmlRes = await fetch(`${API_URL}/api/report/${sessionId}/html`);
      if (htmlRes.ok) setConclusionHtml(await htmlRes.text());
      return;
    }
    applyInterrupt(classifyInterrupt(data.interrupt));
  };

  const withSending = async (fn) => {
    setSending(true);
    try {
      await fn();
    } catch (err) {
      setErrorMessage(err.message);
      setPhase("error");
    } finally {
      setSending(false);
    }
  };

  const handleSend = () => {
    if (!input.trim() || sending) return;
    const text = input.trim();
    setInput("");
    addMessage("user", text);
    withSending(async () => {
      if (phase === "clarify") await resume(text);
      else if (phase === "hypothesis_tree") await resume({ action: "chat", message: text });
    });
  };

  const handleUpload = () => {
    if (files.length === 0) return;
    withSending(async () => {
      const formData = new FormData();
      for (const f of files) formData.append("files", f);
      formData.append("session_id", sessionId);
      const res = await fetch(`${API_URL}/api/upload`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(`上传失败：HTTP ${res.status}`);
      addMessage("ai", "数据已上传，正在诊断...");
      // LangGraph 把 Command(resume=None) 当作"未提供resume值"而报错
      // （EmptyInputError），node_awaiting_data 本身不使用该值，传任意真值即可
      await resume(true);
    });
  };

  const handleConfirmSchema = (confirmedSchema) =>
    withSending(async () => {
      addMessage("user", "已确认字段口径");
      await resume(confirmedSchema);
    });

  const handleConfirmJoin = (confirmedJoinPlan) =>
    withSending(async () => {
      addMessage("user", "已确认关联方案");
      await resume(confirmedJoinPlan);
    });

  const handleConfirmTransform = (plan) =>
    withSending(async () => {
      addMessage("user", "已确认清洗计划");
      addMessage("ai", "正在清洗数据并生成初始假设树...");
      await resume({ action: "confirm", plan });
    });

  const handleRejectTransform = () =>
    withSending(async () => {
      addMessage("user", "退回，重新确认口径");
      await resume({ action: "reject" });
    });

  const handleVerify = (nodeId, moduleName) =>
    withSending(async () => {
      const label = MODULE_OPTIONS.find((m) => m.name === moduleName)?.label || moduleName;
      addMessage("user", `验证假设 ${nodeId}（${label}）`);
      setVerifyTarget(null);
      await resume({ action: "verify", node_id: nodeId, module: moduleName });
    });

  const handleConclude = () =>
    withSending(async () => {
      addMessage("user", "生成综合结论");
      await resume({ action: "conclude" });
    });

  const groups = [...new Set(tree.map((n) => n.group))];
  const hasVerified = tree.some((n) => n.status !== "pending");

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <span style={styles.logo}>Minerva</span>
        <span style={styles.headerDesc}>分析思维的对话伙伴</span>
      </header>

      <div style={styles.body}>
        {/* 左：分析地图 */}
        <div style={styles.left}>
          <div style={styles.panelTitle}>分析地图</div>

          <div style={styles.mapSection}>
            <div style={styles.mapSectionHead}>
              <span style={{ ...styles.dot, background: problemCard ? "#67c23a" : "#c0c4cc" }} />
              <span style={styles.mapSectionLabel}>问题定义</span>
            </div>
            {problemCard && (
              <div style={styles.mapSectionBody}>{problemCard.question || problemCard.analysis_goal}</div>
            )}
          </div>

          <div style={styles.mapSection}>
            <div style={styles.mapSectionHead}>
              <span style={{ ...styles.dot, background: tree.length ? "#e6a23c" : "#c0c4cc" }} />
              <span style={styles.mapSectionLabel}>假设树</span>
              {tree.length > 0 && <span style={styles.mapSectionMeta}>{tree.length} 个假设</span>}
            </div>
            <div style={styles.mapSectionBody}>
              {groups.map((g) => (
                <div key={g} style={{ marginBottom: 10 }}>
                  <div style={styles.groupLabel}>{g}</div>
                  {tree
                    .filter((n) => n.group === g)
                    .map((n) => {
                      const cfg = STATUS_CONFIG[n.status] || STATUS_CONFIG.pending;
                      return (
                        <div key={n.id} style={styles.treeNode}>
                          <div style={styles.treeNodeRow}>
                            <span style={{ color: cfg.color }}>{cfg.icon}</span>
                            <span style={styles.treeNodeLabel}>
                              {n.label}
                              {n.priority && <span style={{ color: "#e6a23c" }}> ⭐</span>}
                            </span>
                          </div>
                          {n.verification_summary && (
                            <div style={styles.treeNodeSummary}>{n.verification_summary}</div>
                          )}
                          {phase === "hypothesis_tree" &&
                            (verifyTarget === n.id ? (
                              <div style={styles.verifyPicker}>
                                <select
                                  value={verifyModule}
                                  onChange={(e) => setVerifyModule(e.target.value)}
                                  style={styles.select}
                                >
                                  {MODULE_OPTIONS.map((m) => (
                                    <option key={m.name} value={m.name}>
                                      {m.label}
                                    </option>
                                  ))}
                                </select>
                                <button
                                  className="btn btn-primary"
                                  style={styles.smallBtn}
                                  disabled={sending}
                                  onClick={() => handleVerify(n.id, verifyModule)}
                                >
                                  开始验证
                                </button>
                                <button className="btn btn-outline" style={styles.smallBtn} onClick={() => setVerifyTarget(null)}>
                                  取消
                                </button>
                              </div>
                            ) : (
                              <button
                                className="btn btn-outline"
                                style={styles.smallBtn}
                                disabled={sending}
                                onClick={() => setVerifyTarget(n.id)}
                              >
                                验证此假设
                              </button>
                            ))}
                        </div>
                      );
                    })}
                </div>
              ))}
            </div>
          </div>

          <div style={styles.mapSection}>
            <div style={styles.mapSectionHead}>
              <span style={{ ...styles.dot, background: phase === "conclusion" ? "#67c23a" : "#c0c4cc" }} />
              <span style={styles.mapSectionLabel}>综合结论</span>
            </div>
            {phase === "hypothesis_tree" && (
              <button className="btn btn-primary" style={{ marginTop: 8 }} disabled={!hasVerified || sending} onClick={handleConclude}>
                生成综合结论
              </button>
            )}
          </div>
        </div>

        {/* 中：对话 */}
        <div style={styles.center}>
          <div style={styles.messages}>
            {messages.map((m, i) => (
              <div
                key={i}
                style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start", marginBottom: 12 }}
              >
                <div style={m.role === "user" ? styles.bubbleUser : styles.bubbleAi}>{m.text}</div>
              </div>
            ))}
            {phase === "conclusion" && conclusionHtml && (
              <div className="ia-card" dangerouslySetInnerHTML={{ __html: conclusionHtml }} />
            )}
            {errorMessage && (
              <div className="ia-card" style={styles.error}>
                <strong>错误：</strong>
                {errorMessage}
              </div>
            )}
          </div>

          <div style={styles.actionArea}>
            {phase === "awaiting_data" && (
              <div style={styles.uploadRow}>
                <input type="file" accept=".csv" multiple onChange={(e) => setFiles(Array.from(e.target.files))} />
                <button className="btn btn-primary" onClick={handleUpload} disabled={files.length === 0 || sending}>
                  上传并开始分析
                </button>
              </div>
            )}

            {phase === "confirmation" && diagnosis && (
              <ConfirmationForm diagnosis={diagnosis} onSubmit={handleConfirmSchema} submitting={sending} />
            )}

            {phase === "join_plan" && joinPlan && (
              <JoinPlanForm joinPlan={joinPlan} tableColumns={tableColumns} onSubmit={handleConfirmJoin} submitting={sending} />
            )}

            {phase === "transform" && (
              <TransformPreview transformPlan={transformPlan} onConfirm={handleConfirmTransform} onReject={handleRejectTransform} />
            )}

            {(phase === "clarify" || phase === "hypothesis_tree") && (
              <div style={styles.inputRow}>
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleSend();
                  }}
                  placeholder={phase === "clarify" ? "描述你观察到的业务问题..." : "补充背景信息，或在左侧选择假设进行验证..."}
                  style={styles.input}
                  disabled={sending}
                />
                <button className="btn btn-primary" onClick={handleSend} disabled={sending || !input.trim()}>
                  发送
                </button>
              </div>
            )}

            {phase === "loading" && <span className="ia-spinner" />}
          </div>
        </div>

        {/* 右：数据结果 */}
        <div style={styles.right}>
          <div style={styles.panelTitle}>数据结果</div>
          {!lastVerification ? (
            <div style={styles.placeholder}>选择左侧假设进行验证后，数据结果将在此展示</div>
          ) : (
            <div>
              <div className="ia-card" style={styles.resultCard}>
                <div style={styles.resultLabel}>{lastVerification.category}</div>
                {lastVerification.chart && <ReactECharts option={lastVerification.chart} style={{ height: 220 }} />}
              </div>
              <div className="ia-card" style={styles.resultCard}>
                <div style={styles.resultLabel}>置信度：{lastVerification.confidence?.level}</div>
                <ul style={styles.reasonList}>
                  {(lastVerification.confidence?.reasons || []).map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
              <div className="ia-card" style={styles.resultCard}>
                <p>
                  <strong>结论：</strong>
                  {lastVerification.narrative?.conclusion}
                </p>
                <p>
                  <strong>数据支撑：</strong>
                  {lastVerification.narrative?.data_support}
                </p>
                <p>
                  <strong>建议：</strong>
                  {lastVerification.narrative?.recommendation}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: { minHeight: "100vh", display: "flex", flexDirection: "column" },
  header: {
    background: "#fff",
    borderBottom: "1px solid #e4e7ed",
    padding: "0.8rem 1.2rem",
    display: "flex",
    alignItems: "center",
    gap: "0.8rem",
    flexShrink: 0,
  },
  logo: { fontSize: "1.15rem", fontWeight: 700, color: "#5470c6" },
  headerDesc: { fontSize: "0.85rem", color: "#909399" },
  body: { flex: 1, display: "flex", overflow: "hidden" },
  left: { width: 280, borderRight: "1px solid #e4e7ed", padding: 16, overflowY: "auto", flexShrink: 0, background: "#fafbfc" },
  center: { flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 },
  right: { width: 280, borderLeft: "1px solid #e4e7ed", padding: 16, overflowY: "auto", flexShrink: 0, background: "#fafbfc" },
  panelTitle: { fontSize: "0.75rem", color: "#909399", letterSpacing: 1, textTransform: "uppercase", marginBottom: 14 },
  mapSection: { marginBottom: 20 },
  mapSectionHead: { display: "flex", alignItems: "center", gap: 6, marginBottom: 6 },
  dot: { width: 7, height: 7, borderRadius: "50%", flexShrink: 0 },
  mapSectionLabel: { fontSize: "0.85rem", fontWeight: 600, color: "#303133" },
  mapSectionMeta: { fontSize: "0.75rem", color: "#909399" },
  mapSectionBody: { fontSize: "0.8rem", color: "#606266", lineHeight: 1.6, paddingLeft: 13, borderLeft: "1px solid #e4e7ed" },
  groupLabel: { fontSize: "0.7rem", color: "#909399", letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 4 },
  treeNode: { marginBottom: 8 },
  treeNodeRow: { display: "flex", alignItems: "flex-start", gap: 6 },
  treeNodeLabel: { fontSize: "0.8rem", color: "#303133", lineHeight: 1.4 },
  treeNodeSummary: { fontSize: "0.72rem", color: "#909399", marginTop: 2, marginLeft: 14, lineHeight: 1.4 },
  verifyPicker: { display: "flex", gap: 4, alignItems: "center", marginTop: 4, marginLeft: 14, flexWrap: "wrap" },
  select: { fontSize: "0.75rem", padding: "2px 4px" },
  smallBtn: { fontSize: "0.72rem", padding: "2px 8px", marginTop: 4, marginLeft: 14 },
  messages: { flex: 1, overflowY: "auto", padding: "20px 24px" },
  bubbleUser: {
    maxWidth: "75%",
    background: "#5470c6",
    color: "#fff",
    borderRadius: "12px 12px 2px 12px",
    padding: "10px 14px",
    fontSize: "0.88rem",
    lineHeight: 1.6,
    whiteSpace: "pre-line",
  },
  bubbleAi: {
    maxWidth: "75%",
    background: "#fff",
    border: "1px solid #e4e7ed",
    color: "#303133",
    borderRadius: "2px 12px 12px 12px",
    padding: "10px 14px",
    fontSize: "0.88rem",
    lineHeight: 1.6,
    whiteSpace: "pre-line",
  },
  actionArea: { borderTop: "1px solid #e4e7ed", padding: "14px 24px", background: "#fff" },
  uploadRow: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" },
  inputRow: { display: "flex", gap: 10 },
  input: { flex: 1, border: "1px solid #e4e7ed", borderRadius: 6, padding: "10px 14px", fontSize: "0.88rem", outline: "none" },
  placeholder: { fontSize: "0.8rem", color: "#c0c4cc", lineHeight: 1.6 },
  resultCard: { marginBottom: 12, fontSize: "0.8rem" },
  resultLabel: { fontSize: "0.78rem", color: "#5470c6", fontWeight: 600, marginBottom: 6 },
  reasonList: { paddingLeft: 18, margin: 0, color: "#909399", fontSize: "0.75rem", lineHeight: 1.6 },
  error: { color: "#f56c6c", fontSize: "0.85rem" },
};
