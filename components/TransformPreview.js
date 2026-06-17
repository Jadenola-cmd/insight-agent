import { useState } from "react";

const OP_LABELS = {
  rename_column: "重命名",
  drop_columns: "删除列",
  cast_type: "类型转换",
  strip_whitespace: "去除空白",
  standardize_categories: "规范分类",
  unit_convert: "单位换算",
  fillna: "填充空值",
  drop_rows_with_null: "删除空值行",
  drop_duplicates: "去重",
};

const TYPE_LABELS = { int: "整数", float: "小数", string: "文本", datetime: "日期时间", bool: "布尔值" };

function describeOp(step) {
  switch (step.op) {
    case "rename_column":
      return `"${step.from}" → "${step.to}"`;
    case "drop_columns":
      return (step.columns || []).join("、");
    case "cast_type":
      return `"${step.column}" 转为${TYPE_LABELS[step.to] || step.to}`;
    case "strip_whitespace":
      return (step.columns || []).join("、");
    case "standardize_categories": {
      const entries = Object.entries(step.mapping || {});
      const preview = entries.slice(0, 2).map(([k, v]) => `"${k}"→"${v}"`).join("、");
      return `"${step.column}"：${preview}${entries.length > 2 ? `等${entries.length}项` : ""}`;
    }
    case "unit_convert":
      return `"${step.column}" × ${step.factor}${step.new_name ? ` → "${step.new_name}"` : ""}`;
    case "fillna":
      return `"${step.column}" 空值填充为 ${JSON.stringify(step.value)}`;
    case "drop_rows_with_null":
      return `${(step.columns || []).join("、")} 有空值时删除该行`;
    case "drop_duplicates":
      return step.subset?.length ? `按 ${step.subset.join("、")} 去重` : "全列去重";
    default:
      return JSON.stringify(step);
  }
}

// Step4 清洗计划预览确认：展示Node3生成的transform_plan，用户确认后调用 onConfirm 处理后续流程
export default function TransformPreview({ apiUrl, sessionId, transformPlan, onConfirm, onCancel }) {
  const [submitting, setSubmitting] = useState(false);

  const handleConfirm = () => {
    setSubmitting(true);
    onConfirm?.();
  };

  const handleCancel = () => {
    onCancel?.();
  };

  return (
    <div className="ia-card">
      <h2 style={styles.sectionTitle}>清洗计划预览</h2>
      <p style={styles.subtitle}>请确认以下清洗操作后再执行，确认后将按此计划清洗数据。</p>

      {(!transformPlan || transformPlan.length === 0) && (
        <p style={styles.empty}>暂无清洗操作，可直接确认进入分析。</p>
      )}

      {transformPlan?.length > 0 && (
        <ul style={styles.planList}>
          {transformPlan.map((step, idx) => (
            <li key={idx} style={styles.planRow}>
              <span style={styles.opTag}>{OP_LABELS[step.op] || step.op}</span>
              <span style={styles.desc}>{describeOp(step)}</span>
            </li>
          ))}
        </ul>
      )}

      <div style={styles.buttonRow}>
        <button className="btn btn-primary" onClick={handleConfirm} disabled={submitting}>
          {submitting ? "提交中..." : "确认执行"}
        </button>
        <button className="btn btn-ghost" onClick={handleCancel} disabled={submitting}>
          取消
        </button>
      </div>
    </div>
  );
}

const styles = {
  sectionTitle: {
    margin: "0 0 0.5rem",
    fontSize: "1rem",
    fontWeight: 600,
    color: "#303133",
  },
  subtitle: {
    color: "#606266",
  },
  empty: {
    color: "#909399",
    fontSize: "0.9rem",
  },
  planList: {
    listStyle: "none",
    padding: 0,
    marginTop: "0.5rem",
  },
  planRow: {
    display: "flex",
    gap: "0.8rem",
    alignItems: "center",
    padding: "0.5rem 0",
    borderBottom: "1px solid #f2f3f5",
    fontSize: "0.9rem",
  },
  opTag: {
    backgroundColor: "#ecf5ff",
    color: "#5470c6",
    borderRadius: "0.3rem",
    padding: "0.1rem 0.6rem",
    fontSize: "0.85rem",
    whiteSpace: "nowrap",
    flexShrink: 0,
  },
  desc: {
    color: "#2f3542",
    fontSize: "0.9rem",
  },
  buttonRow: {
    display: "flex",
    gap: "0.8rem",
    marginTop: "1rem",
  },
};
