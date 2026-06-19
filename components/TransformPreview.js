import { useEffect, useState } from "react";

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
export default function TransformPreview({ transformPlan, dataPreview, onConfirm, onReject, onRegenerate }) {
  const [steps, setSteps] = useState(() => transformPlan || []);
  const [submitting, setSubmitting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  // regenerate 后父组件传入新的 transformPlan（同一组件实例不会重新挂载），
  // 需要同步刷新本地可编辑副本，否则界面会停留在重新生成前的旧版方案
  useEffect(() => {
    setSteps(transformPlan || []);
    setRegenerating(false);
    setSubmitting(false);
  }, [transformPlan]);

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

  const handleRegenerate = () => {
    setRegenerating(true);
    onRegenerate?.();
  };

  const rowDelta = dataPreview ? dataPreview.after_rows - dataPreview.before_rows : null;

  return (
    <div className="ia-card">
      <h2 style={styles.sectionTitle}>清洗计划预览</h2>
      <p style={styles.subtitle}>
        可删除不需要的操作、调整填充值/类型/换算系数；如果问题源于字段口径本身，可退回上一步重新确认；
        对生成的方案不满意也可让AI重新生成一版。
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

      {dataPreview && (
        <div style={styles.previewBlock}>
          <div style={styles.previewSummary}>
            清洗前 {dataPreview.before_rows} 行 / {dataPreview.before_columns} 列 → 清洗后{" "}
            {dataPreview.after_rows} 行 / {dataPreview.after_columns.length} 列
            {rowDelta !== null && rowDelta !== 0 && (
              <span style={rowDelta < 0 ? styles.rowDeltaWarn : styles.rowDeltaInfo}>
                {" "}（{rowDelta < 0 ? `减少${-rowDelta}行` : `增加${rowDelta}行`}）
              </span>
            )}
          </div>
          {dataPreview.sample_rows?.length > 0 && (
            <div style={styles.tableWrap}>
              <table style={styles.previewTable}>
                <thead>
                  <tr>
                    {dataPreview.after_columns.map((c) => (
                      <th key={c} style={styles.previewTh}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {dataPreview.sample_rows.map((row, i) => (
                    <tr key={i}>
                      {dataPreview.after_columns.map((c) => (
                        <td key={c} style={styles.previewTd}>{row[c] === null || row[c] === undefined ? "" : String(row[c])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <div style={styles.buttonRow}>
        <button className="btn btn-primary" onClick={handleConfirm} disabled={submitting || regenerating}>
          {submitting ? "提交中..." : "确认执行"}
        </button>
        {onRegenerate && (
          <button className="btn btn-outline" onClick={handleRegenerate} disabled={submitting || regenerating}>
            {regenerating ? "生成中..." : "让AI重新生成"}
          </button>
        )}
        <button className="btn btn-ghost" onClick={handleReject} disabled={submitting || regenerating}>
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
  previewBlock: {
    marginTop: "1rem",
    paddingTop: "0.8rem",
    borderTop: "1px solid #f2f3f5",
  },
  previewSummary: {
    fontSize: "0.85rem",
    color: "#606266",
    marginBottom: "0.5rem",
  },
  rowDeltaWarn: { color: "#f56c6c", fontWeight: 600 },
  rowDeltaInfo: { color: "#909399" },
  tableWrap: {
    overflowX: "auto",
    border: "1px solid #f2f3f5",
    borderRadius: "0.4rem",
  },
  previewTable: {
    borderCollapse: "collapse",
    width: "100%",
    fontSize: "0.78rem",
  },
  previewTh: {
    textAlign: "left",
    padding: "0.4rem 0.6rem",
    background: "#fafbfc",
    borderBottom: "1px solid #e4e7ed",
    whiteSpace: "nowrap",
  },
  previewTd: {
    padding: "0.35rem 0.6rem",
    borderBottom: "1px solid #f2f3f5",
    whiteSpace: "nowrap",
  },
};
