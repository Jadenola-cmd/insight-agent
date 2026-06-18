import { useRef, useState } from "react";
import ConfirmationForm from "../components/ConfirmationForm";
import JoinPlanForm from "../components/JoinPlanForm";
import AnalysisReport from "../components/AnalysisReport";
import ClarificationChat from "../components/ClarificationChat";
import TransformPreview from "../components/TransformPreview";
import FollowupChat from "../components/FollowupChat";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

const NODE_LABELS = {
  clarification: "问题澄清",
  diagnosis: "数据诊断",
  confirmation: "口径确认",
  join_plan: "多表关联",
  transform: "数据清洗",
  analysis: "智能分析",
  report: "报告生成",
  followup: "追问对话",
};

const STATUS_LABELS = {
  running: "进行中",
  done: "完成",
  error: "失败",
  waiting_confirmation: "等待确认",
  waiting_preview: "等待预览确认",
  waiting: "等待中",
  confirmed: "已确认",
  ready: "已就绪",
  cancelled: "已取消",
};

// 各节点预估耗时（进行中时展示）
const STEP_ETA = {
  diagnosis: "约 10 秒",
  transform: "约 15 秒",
  analysis: "约 30 秒",
  report: "约 20 秒",
};

// 渲染时按此顺序过滤已收到事件的节点
const STEP_ORDER = [
  "clarification", "diagnosis", "confirmation",
  "join_plan", "transform", "analysis", "report", "followup",
];

function getStepState(status) {
  if (["done", "confirmed", "ready"].includes(status)) return "done";
  if (status === "running") return "running";
  if (["waiting_confirmation", "waiting_preview", "waiting"].includes(status)) return "waiting";
  if (status === "error") return "error";
  return "other";
}

const buildClarifySessionId = () =>
  `clarify-${Math.random().toString(36).slice(2, 10)}`;

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

const TERMINAL_EVENTS = new Set([
  "confirmation/waiting_confirmation",
  "confirmation/error",
  "diagnosis/error",
  "clarification/waiting",
]);

export default function Home() {
  const [files, setFiles] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [status, setStatus] = useState("idle");
  const [events, setEvents] = useState([]);
  const [diagnosis, setDiagnosis] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [reportResult, setReportResult] = useState(null);
  const eventSourceRef = useRef(null);

  const [clarificationDone, setClarificationDone] = useState(false);
  const [clarifySessionId] = useState(buildClarifySessionId);
  const [analysisGoal, setAnalysisGoal] = useState("");

  const [pendingSchema, setPendingSchema] = useState(null);
  const [transformPlan, setTransformPlan] = useState([]);
  const [confirmPhase, setConfirmPhase] = useState(null);

  // Join 方案确认
  const [joinPlan, setJoinPlan] = useState(null);
  const [tableColumns, setTableColumns] = useState({});

  const reset = () => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setFiles([]);
    setSessionId(null);
    setStatus("idle");
    setEvents([]);
    setDiagnosis(null);
    setErrorMessage(null);
    setAnalysisResult(null);
    setReportResult(null);
    setPendingSchema(null);
    setTransformPlan([]);
    setConfirmPhase(null);
    setJoinPlan(null);
    setTableColumns({});
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    reset();
    setStatus("uploading");
    try {
      const formData = new FormData();
      for (const f of files) formData.append("files", f);
      if (analysisGoal) formData.append("analysis_goal", analysisGoal);
      const res = await fetch(`${API_URL}/api/upload`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(`上传失败：HTTP ${res.status}`);
      const { session_id } = await res.json();
      setSessionId(session_id);
      startStream(session_id);
    } catch (err) {
      setStatus("error");
      setErrorMessage(err.message);
    }
  };

  const startStream = (id) => {
    setStatus("streaming");
    const es = new EventSource(`${API_URL}/api/analyze/${id}/stream`);
    eventSourceRef.current = es;
    es.onmessage = (e) => {
      const payload = JSON.parse(e.data);
      const key = `${payload.node}/${payload.status}`;
      setEvents((prev) => [...prev, payload]);
      if (payload.node === "confirmation" && payload.status === "waiting_confirmation") {
        setDiagnosis(payload.data);
        setStatus("waiting_confirmation");
      } else if (payload.status === "error") {
        setStatus("error");
        setErrorMessage(payload.data?.message || "未知错误");
      }
      if (TERMINAL_EVENTS.has(key)) es.close();
    };
    es.onerror = () => {
      es.close();
      if (status !== "waiting_confirmation" && status !== "error") {
        setStatus("error");
        setErrorMessage("SSE 连接中断");
      }
    };
  };

  const handlePrepareTransform = async (confirmedSchema) => {
    setPendingSchema(confirmedSchema);
    setStatus("confirming");
    setConfirmPhase("schema");

    try {
      const res = await fetch(`${API_URL}/api/analyze/${sessionId}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirmedSchema),
      });
      if (!res.ok) throw new Error(`确认失败：HTTP ${res.status}`);

      await readSseStream(res, (payload) => {
        const key = `${payload.node}/${payload.status}`;
        setEvents((prev) => [...prev, payload]);

        if (payload.node === "confirmation" && payload.status === "confirmed") {
          // 口径已确认，等待 join 方案
        } else if (payload.node === "join_plan" && payload.status === "waiting_confirmation") {
          setJoinPlan(payload.data.join_plan);
          setTableColumns(payload.data.table_columns || {});
          setStatus("waiting_join_confirm");
          setConfirmPhase(null);
        } else if (payload.node === "transform" && payload.status === "waiting_preview") {
          setTransformPlan(payload.data.transform_plan);
          setStatus("waiting_transform_confirm");
          setConfirmPhase(null);
        } else if (payload.status === "error") {
          setStatus("error");
          setErrorMessage(payload.data?.message || "未知错误");
        }
      });
    } catch (err) {
      setStatus("error");
      setErrorMessage(err.message);
    }
  };

  const handleConfirmJoin = async (confirmedJoinPlan) => {
    setStatus("confirming");
    setConfirmPhase("join");

    try {
      const res = await fetch(`${API_URL}/api/analyze/${sessionId}/confirm/join`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(confirmedJoinPlan),
      });
      if (!res.ok) throw new Error(`确认失败：HTTP ${res.status}`);

      await readSseStream(res, (payload) => {
        const key = `${payload.node}/${payload.status}`;
        setEvents((prev) => [...prev, payload]);

        if (payload.node === "join_plan" && payload.status === "confirmed") {
          // join 方案已确认
        } else if (payload.node === "transform" && payload.status === "waiting_preview") {
          setTransformPlan(payload.data.transform_plan);
          setStatus("waiting_transform_confirm");
          setConfirmPhase(null);
        } else if (payload.status === "error") {
          setStatus("error");
          setErrorMessage(payload.data?.message || "未知错误");
        }
      });
    } catch (err) {
      setStatus("error");
      setErrorMessage(err.message);
    }
  };

  const handleRunPipeline = async (plan) => {
    setStatus("confirming");
    setConfirmPhase("pipeline");

    try {
      const res = await fetch(`${API_URL}/api/analyze/${sessionId}/transform/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: true, plan }),
      });
      if (!res.ok) throw new Error(`确认失败：HTTP ${res.status}`);

      await readSseStream(res, (payload) => {
        setEvents((prev) => [...prev, payload]);

        if (payload.node === "transform" && payload.status === "done") {
          // 清洗完成
        } else if (payload.node === "analysis" && payload.status === "done") {
          setAnalysisResult({ results: payload.data.results, charts: payload.data.charts });
        } else if (payload.node === "report" && payload.status === "done") {
          setReportResult(payload.data);
        } else if (payload.node === "followup" && payload.status === "ready") {
          setStatus("done");
          setConfirmPhase(null);
        } else if (payload.status === "error") {
          setStatus("error");
          setErrorMessage(payload.data?.message || "未知错误");
        }
      });
    } catch (err) {
      setStatus("error");
      setErrorMessage(err.message);
    }
  };

  // 退回清洗计划：不再终止会话，流程回退到口径确认，重新展示表单（沿用上一轮的编辑结果）
  const handleRejectTransform = async () => {
    setStatus("confirming");
    setConfirmPhase("reject_transform");

    try {
      const res = await fetch(`${API_URL}/api/analyze/${sessionId}/transform/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: false }),
      });
      if (!res.ok) throw new Error(`操作失败：HTTP ${res.status}`);

      await readSseStream(res, (payload) => {
        if (payload.node === "confirmation" && payload.status === "waiting_confirmation") {
          // 退回到口径确认：清掉本轮已失效的 join_plan/transform 时间线状态，避免显示陈旧的"等待预览确认"
          setEvents((prev) => [
            ...prev.filter((e) => e.node !== "join_plan" && e.node !== "transform"),
            payload,
          ]);
          setDiagnosis(payload.data);
          setTransformPlan([]);
          setJoinPlan(null);
          setStatus("waiting_confirmation");
          setConfirmPhase(null);
        } else {
          setEvents((prev) => [...prev, payload]);
        }

        if (payload.status === "error") {
          setStatus("error");
          setErrorMessage(payload.data?.message || "未知错误");
        }
      });
    } catch (err) {
      setStatus("error");
      setErrorMessage(err.message);
    }
  };

  // ---- 构建时间线数据 ----
  const nodeStatusMap = {};
  for (const evt of events) {
    nodeStatusMap[evt.node] = evt.status;
  }

  const timelineNodes = [];
  for (const node of STEP_ORDER) {
    const st = nodeStatusMap[node];
    if (!st) continue;
    if (node === "join_plan" && st === "waiting_confirmation" && nodeStatusMap["confirmation"] === "confirmed") {
      timelineNodes.push({ node, status: st });
    } else if (node !== "join_plan") {
      timelineNodes.push({ node, status: st });
    }
  }

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div style={styles.headerInner}>
          <span style={styles.logo}>InsightAgent</span>
          <span style={styles.headerDesc}>商业分析智能体</span>
        </div>
      </header>

      <main style={styles.main}>
        {/* Step0 问题澄清 */}
        {!clarificationDone && (
          <ClarificationChat
            apiUrl={API_URL}
            sessionId={clarifySessionId}
            onComplete={(goal) => { setAnalysisGoal(goal || ""); setClarificationDone(true); }}
          />
        )}

        {/* 上传区 */}
        {clarificationDone && status === "idle" && (
          <div className="ia-card">
            <h2 style={styles.sectionTitle}>上传数据</h2>
            <div style={styles.uploadRow}>
              <input
                type="file"
                accept=".csv"
                multiple
                onChange={(e) => setFiles(Array.from(e.target.files))}
                style={styles.fileInput}
              />
              <button className="btn btn-primary" onClick={handleUpload} disabled={files.length === 0}>
                开始分析
              </button>
            </div>
            {files.length > 0 && (
              <p style={styles.fileCount}>
                已选 {files.length} 个文件
                {files.length > 1 ? "，将纵向合并" : ""}
              </p>
            )}
          </div>
        )}

        {/* 错误提示 */}
        {status === "error" && errorMessage && (
          <div className="ia-card" style={styles.error}>
            <strong>错误：</strong>{errorMessage}
            <div style={{ marginTop: "0.5rem" }}>
              <button className="btn btn-outline" onClick={reset}>重新开始</button>
            </div>
          </div>
        )}

        {/* 时间线进度 */}
        {timelineNodes.length > 0 && (
          <div className="ia-card">
            <h2 style={styles.sectionTitle}>分析进度</h2>
            <div style={styles.timeline}>
              {timelineNodes.map(({ node, status: st }) => {
                const state = getStepState(st);
                return (
                  <div key={node} style={styles.timelineRow}>
                    <div style={styles.timelineIconWrap}>
                      {state === "done" ? (
                        <span style={styles.iconDone}>✓</span>
                      ) : state === "running" ? (
                        <span className="ia-spinner" style={{ width: 16, height: 16 }} />
                      ) : state === "waiting" ? (
                        <span style={styles.iconWaiting}>⏳</span>
                      ) : state === "error" ? (
                        <span style={styles.iconError}>✗</span>
                      ) : (
                        <span style={styles.iconDot}>·</span>
                      )}
                    </div>
                    <div style={styles.timelineContent}>
                      <span style={state === "running" ? {...styles.timelineLabel, color: "#5470c6"} : styles.timelineLabel}>
                        {NODE_LABELS[node] || node}
                      </span>
                      <span style={state === "error" ? {...styles.timelineStatus, color: "#f56c6c"} : styles.timelineStatus}>
                        {STATUS_LABELS[st] || st}
                        {state === "running" && STEP_ETA[node] && (
                          <span style={styles.eta}>· {STEP_ETA[node]}</span>
                        )}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {status === "waiting_confirmation" && diagnosis && (
          <ConfirmationForm
            diagnosis={diagnosis}
            initialSchema={pendingSchema}
            onSubmit={handlePrepareTransform}
            submitting={false}
          />
        )}

        {status === "waiting_join_confirm" && joinPlan && (
          <JoinPlanForm
            joinPlan={joinPlan}
            tableColumns={tableColumns}
            onSubmit={handleConfirmJoin}
            submitting={false}
          />
        )}

        {status === "waiting_transform_confirm" && (
          <TransformPreview
            transformPlan={transformPlan}
            onConfirm={handleRunPipeline}
            onReject={handleRejectTransform}
          />
        )}

        {status === "confirming" && (
          <div className="ia-card" style={styles.waitingCard}>
            <span className="ia-spinner" />
            <span style={styles.waitingText}>
              {confirmPhase === "schema"
                ? "口径已确认，正在准备清洗计划..."
                : confirmPhase === "join"
                ? "关联方案已确认，正在准备清洗计划..."
                : confirmPhase === "reject_transform"
                ? "正在退回口径确认..."
                : "正在清洗数据并执行分析，请稍候..."}
            </span>
          </div>
        )}

        <AnalysisReport
          analysisResult={analysisResult}
          reportResult={reportResult}
          apiUrl={API_URL}
          sessionId={sessionId}
        />

        {status === "done" && (
          <FollowupChat apiUrl={API_URL} sessionId={sessionId} onNeedMoreData={reset} />
        )}
      </main>
    </div>
  );
}

const styles = {
  page: {
    minHeight: "100vh",
  },
  header: {
    background: "#fff",
    borderBottom: "1px solid #e4e7ed",
    padding: "0 1rem",
    position: "sticky",
    top: 0,
    zIndex: 100,
    boxShadow: "0 1px 8px rgba(0,0,0,0.06)",
  },
  headerInner: {
    maxWidth: 720,
    margin: "0 auto",
    height: 56,
    display: "flex",
    alignItems: "center",
    gap: "0.8rem",
  },
  logo: {
    fontSize: "1.15rem",
    fontWeight: 700,
    color: "#5470c6",
    letterSpacing: "-0.01em",
  },
  headerDesc: {
    fontSize: "0.85rem",
    color: "#909399",
  },
  main: {
    maxWidth: 720,
    margin: "0 auto",
    padding: "1.5rem 1rem 3rem",
  },
  sectionTitle: {
    margin: "0 0 1rem",
    fontSize: "1rem",
    fontWeight: 600,
    color: "#303133",
  },
  uploadRow: {
    display: "flex",
    alignItems: "center",
    gap: "0.8rem",
    flexWrap: "wrap",
  },
  fileInput: {
    fontSize: "0.9rem",
  },
  fileCount: {
    margin: "0.5rem 0 0",
    fontSize: "0.85rem",
    color: "#5470c6",
  },
  sessionId: {
    margin: "0.5rem 0 0",
    fontSize: "0.8rem",
    color: "#c0c4cc",
  },
  error: {
    marginTop: "1rem",
    padding: "0.8rem 1rem",
    borderRadius: "8px",
    backgroundColor: "#fef0f0",
    color: "#f56c6c",
    fontSize: "0.9rem",
  },
  // 时间线
  timeline: {
    display: "flex",
    flexDirection: "column",
    gap: "0.6rem",
  },
  timelineRow: {
    display: "flex",
    alignItems: "center",
    gap: "0.75rem",
  },
  timelineIconWrap: {
    width: 22,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  iconDone: {
    color: "#67c23a",
    fontWeight: 700,
    fontSize: "0.95rem",
  },
  iconWaiting: {
    color: "#e6a23c",
    fontSize: "1rem",
  },
  iconError: {
    color: "#f56c6c",
    fontWeight: 700,
  },
  iconDot: {
    color: "#c0c4cc",
    fontSize: "1.2rem",
    lineHeight: 1,
  },
  timelineContent: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    flex: 1,
    flexWrap: "wrap",
  },
  timelineLabel: {
    fontSize: "0.9rem",
    fontWeight: 500,
    color: "#303133",
    minWidth: "5em",
  },
  timelineStatus: {
    fontSize: "0.85rem",
    color: "#909399",
    display: "flex",
    alignItems: "center",
    gap: "0.3rem",
  },
  eta: {
    fontSize: "0.8rem",
    color: "#c0c4cc",
    marginLeft: "0.2rem",
  },
  // 过渡等待卡片
  waitingCard: {
    display: "flex",
    alignItems: "center",
    gap: "0.8rem",
  },
  waitingText: {
    color: "#606266",
    fontSize: "0.9rem",
  },
};
