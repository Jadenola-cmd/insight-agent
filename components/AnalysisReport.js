import dynamic from "next/dynamic";

// ECharts 依赖 window/document，需禁用 SSR
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

const CONFIDENCE_COLORS = {
  高: "#67c23a",
  中: "#e6a23c",
  低: "#f56c6c",
};

export default function AnalysisReport({ analysisResult, reportResult, apiUrl, sessionId }) {
  if (!analysisResult && !reportResult) return null;

  const charts = analysisResult?.charts || {};
  const modules = reportResult?.modules || [];

  return (
    <div style={styles.wrapper}>
      <h2>分析报告</h2>

      {modules.map((m) => (
        <div key={m.name} className="ia-card">
          <div style={styles.cardHeader}>
            <h3 style={styles.cardTitle}>{m.category}</h3>
            <span
              style={{
                ...styles.badge,
                backgroundColor: CONFIDENCE_COLORS[m.confidence?.level] || "#909399",
              }}
            >
              置信度：{m.confidence?.level || "未知"}
            </span>
          </div>

          {charts[m.name] && (
            <div style={styles.chartBox}>
              <ReactECharts option={charts[m.name]} style={{ height: "320px" }} />
            </div>
          )}

          {m.confidence?.reasons?.length > 0 && (
            <ul style={styles.reasonList}>
              {m.confidence.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}

          {m.narrative && (
            <div style={styles.narrative}>
              <p>
                <strong>结论：</strong>
                {m.narrative.conclusion}
              </p>
              <p>
                <strong>数据支撑：</strong>
                {m.narrative.data_support}
              </p>
              <p>
                <strong>运营建议：</strong>
                {m.narrative.recommendation}
              </p>
            </div>
          )}
        </div>
      ))}

      {reportResult && (
        <div className="ia-card">
          <h3 style={styles.cardTitle}>完整报告</h3>
          <button
            className="btn btn-primary"
            style={{ marginTop: "0.5rem" }}
            onClick={() => window.open(`${apiUrl}/api/report/${sessionId}/html`, "_blank")}
          >
            查看完整报告
          </button>
        </div>
      )}
    </div>
  );
}

const styles = {
  wrapper: {
    marginTop: "1.5rem",
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: "0.5rem",
  },
  cardTitle: {
    margin: 0,
  },
  badge: {
    color: "#fff",
    borderRadius: "1rem",
    padding: "0.2rem 0.8rem",
    fontSize: "0.85rem",
  },
  chartBox: {
    marginTop: "0.5rem",
  },
  reasonList: {
    marginTop: "0.5rem",
    paddingLeft: "1.2rem",
    fontSize: "0.8rem",
    color: "#909399",
  },
  narrative: {
    marginTop: "0.8rem",
    fontSize: "0.9rem",
    color: "#303133",
    lineHeight: 1.6,
  },
};
