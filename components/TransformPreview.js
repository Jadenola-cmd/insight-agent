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

// 支持内联编辑的字段：fillna的填充值、cast_type的目标类型、unit_convert的换算系数。
// 其余op（rename/drop_columns/standardize_categories等）只支持整条删除，避免过度设计。
const CAST_TYPE_OPTIONS = Object.keys(TYPE_LABELS);

function EditableValue({ step, onChange }) {
  switch (step.op) {
    case "fillna":
      return (
        <input
          type="text"
          value={step.value ?? ""}
          onChange={(e) => onChange({ value: e.target.value })}
          style={styles.inlineInput}
        />
      );
    case "cast_type":
      return (
        <select
          value={step.to}
          onChange={(e) => onChange({ to: e.target.value })}
          style={styles.inlineInput}
        >
          {CAST_TYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>{TYPE_LABELS[t]}</option>
          ))}
        </select>
      );
    case "unit_convert":
      return (
        <input
          type="number"
          value={step.factor ?? ""}
          onChange={(e) => onChange({ factor: Number(e.target.value) })}
          style={styles.inlineInput}
        />
      );
    default:
      return null;
  }
}

// Step4 清洗计划预览确认：展示Node3生成的transform_plan，支持删除/微调单条操作后
// 再确认执行；也可整体退回上一步重新做口径确认（不再是死路，回退后流程会
// 重新生成清洗计划）。
export default function TransformPreview({ transformPlan, onConfirm, onReject }) {
  const [steps, setSteps] = useState(() => transformPlan || []);
  const [submitting, setSubmitting] = useState(false);

  const updateStep = (idx, patch) => {
    setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const removeStep = (idx) => {
    setSteps((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleConfirm = () => {
    setSubmitting(true);
    onConfirm?.(steps);
  };

  const handleReject = () => {
    setSubmitting(true);
    onReject?.();
  };

  return (
    <div className="ia-card">
      <h2 style={styles.sectionTitle}>清洗计划预览</h2>
      <p style={styles.subtitle}>
        可删除不需要的操作、调整填充值/类型/换算系数；如果问题源于字段口径本身，可退回上一步重新确认。
      </p>

      {steps.length === 0 && (
        <p style={styles.empty}>暂无清洗操作，可直接确认进入分析。</p>
      )}

      {steps.length > 0 && (
        <ul style={styles.planList}>
          {steps.map((step, idx) => (
            <li key={idx} style={styles.planRow}>
              <span style={styles.opTag}>{OP_LABELS[step.op] || step.op}</span>
              <span style={styles.desc}>{describeOp(step)}</span>
              <EditableValue step={step} onChange={(patch) => updateStep(idx, patch)} />
              <button
                className="btn btn-ghost"
                onClick={() => removeStep(idx)}
                disabled={submitting}
                style={styles.removeBtn}
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      )}

      <div style={styles.buttonRow}>
        <button className="btn btn-primary" onClick={handleConfirm} disabled={submitting}>
          {submitting ? "提交中..." : "确认执行"}
        </button>
        <button className="btn btn-ghost" onClick={handleReject} disabled={submitting}>
          退回修改口径
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
  inlineInput: {
    padding: "0.15rem 0.4rem",
    borderRadius: "0.3rem",
    border: "1px solid #dcdfe6",
    fontSize: "0.85rem",
    width: "6rem",
  },
  removeBtn: {
    fontSize: "0.8rem",
    padding: "0.1rem 0.5rem",
    marginLeft: "auto",
  },
  buttonRow: {
    display: "flex",
    gap: "0.8rem",
    marginTop: "1rem",
  },
};
