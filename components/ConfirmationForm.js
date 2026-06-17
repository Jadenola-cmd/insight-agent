import { useState } from "react";

function getOperationHint(col) {
  if (!col.include) return "此列将被排除，不参与分析";
  const hints = [];
  if (col.final_name !== col.original_name) hints.push(`重命名为"${col.final_name}"`);
  if (col.missing_value_strategy === "fill") {
    hints.push(`空值填充为"${col.fill_value !== "" ? col.fill_value : "(空字符串)"}"`);
  } else if (col.missing_value_strategy === "drop_rows") {
    hints.push("含空值的行将被删除");
  }
  if (hints.length === 0) return "";
  return "预计操作：" + hints.join("；");
}

const MISSING_VALUE_OPTIONS = [
  { value: "none", label: "不处理" },
  { value: "fill", label: "填充默认值" },
  { value: "drop_rows", label: "删除该行" },
];

function buildInitialColumns(diagnosis) {
  return diagnosis.columns.map((col) => ({
    original_name: col.name,
    final_name: col.name,
    business_meaning: col.inferred_meaning || "",
    include: true,
    missing_value_strategy: col.null_rate > 0 ? "fill" : "none",
    fill_value: "",
    // 仅用于UI展示，不提交
    _diagnosis: col,
  }));
}

export default function ConfirmationForm({ diagnosis, onSubmit, submitting }) {
  const [columns, setColumns] = useState(() => buildInitialColumns(diagnosis));
  const [resolvedIssues, setResolvedIssues] = useState(() => new Set());

  const updateColumn = (idx, patch) => {
    setColumns((prev) => prev.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  };

  const toggleResolvedIssue = (issue) => {
    setResolvedIssues((prev) => {
      const next = new Set(prev);
      if (next.has(issue)) next.delete(issue);
      else next.add(issue);
      return next;
    });
  };

  const handleSubmit = () => {
    const payload = {
      columns: columns.map(({ _diagnosis, ...rest }) => rest),
      resolved_table_issues: Array.from(resolvedIssues),
    };
    onSubmit(payload);
  };

  return (
    <div className="ia-card">
      <h2 style={styles.sectionTitle}>口径确认</h2>
      <p style={styles.subtitle}>
        共 {diagnosis.row_count} 行数据，请确认每个字段的含义与处理方式（疑似问题字段已高亮）。
      </p>

      {diagnosis.table_issues?.length > 0 && (
        <div style={styles.tableIssues}>
          <strong>表级口径问题：</strong>
          <ul style={styles.issueList}>
            {diagnosis.table_issues.map((issue) => (
              <li key={issue} style={styles.tableIssueRow}>
                <span style={styles.tableIssueText}>{issue}</span>
                <label style={styles.tableIssueCheckbox}>
                  <input
                    type="checkbox"
                    checked={resolvedIssues.has(issue)}
                    onChange={() => toggleResolvedIssue(issue)}
                  />{" "}
                  我已了解，忽略此问题继续分析
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}

      {columns.map((col, idx) => {
        const hasIssue = col._diagnosis.issues?.length > 0;
        return (
          <div key={col.original_name} style={hasIssue ? styles.columnRowIssue : styles.columnRow}>
            <div style={styles.columnHeader}>
              <span style={styles.columnName}>{col.original_name}</span>
              <span style={styles.columnMeta}>
                {col._diagnosis.dtype} · 空值率 {(col._diagnosis.null_rate * 100).toFixed(1)}% ·
                唯一值 {col._diagnosis.unique_count}
              </span>
            </div>

            {hasIssue && (
              <ul style={styles.issueListInline}>
                {col._diagnosis.issues.map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            )}

            <div style={styles.fieldRow}>
              <label style={styles.fieldLabel}>
                字段名
                <input
                  type="text"
                  value={col.final_name}
                  onChange={(e) => updateColumn(idx, { final_name: e.target.value })}
                  style={styles.input}
                />
              </label>
              <label style={styles.fieldLabel}>
                业务含义
                <input
                  type="text"
                  value={col.business_meaning}
                  onChange={(e) => updateColumn(idx, { business_meaning: e.target.value })}
                  style={styles.input}
                />
              </label>
              <label style={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={col.include}
                  onChange={(e) => updateColumn(idx, { include: e.target.checked })}
                />
                纳入分析
              </label>
            </div>

            {getOperationHint(col) && (
              <p style={col.include ? styles.operationHint : styles.operationHintExclude}>
                {getOperationHint(col)}
              </p>
            )}

            <div style={styles.fieldRow}>
              <label style={styles.fieldLabel}>
                缺失值处理
                <select
                  value={col.missing_value_strategy}
                  onChange={(e) => updateColumn(idx, { missing_value_strategy: e.target.value })}
                  style={styles.input}
                >
                  {MISSING_VALUE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
              {col.missing_value_strategy === "fill" && (
                <label style={styles.fieldLabel}>
                  填充值
                  <input
                    type="text"
                    value={col.fill_value}
                    onChange={(e) => updateColumn(idx, { fill_value: e.target.value })}
                    style={styles.input}
                  />
                </label>
              )}
            </div>
          </div>
        );
      })}

      <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting} style={{ marginTop: "1rem" }}>
        {submitting ? "提交中..." : "确认并开始清洗"}
      </button>
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
  tableIssues: {
    backgroundColor: "#fdf6ec",
    border: "1px solid #f5dab1",
    borderRadius: "0.4rem",
    padding: "0.6rem 1rem",
    marginBottom: "1rem",
    color: "#b88230",
  },
  issueList: {
    margin: "0.3rem 0 0",
    paddingLeft: "1.2rem",
  },
  issueListInline: {
    margin: "0.3rem 0 0.6rem",
    paddingLeft: "1.2rem",
    color: "#e6a23c",
    fontSize: "0.85rem",
  },
  columnRow: {
    borderTop: "1px solid #f2f3f5",
    padding: "0.8rem 0",
  },
  columnRowIssue: {
    borderTop: "1px solid #f2f3f5",
    borderLeft: "3px solid #e6a23c",
    backgroundColor: "#fdf6ec",
    padding: "0.8rem 0.8rem",
    marginLeft: "-0.8rem",
    marginRight: "-0.8rem",
  },
  columnHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    flexWrap: "wrap",
    gap: "0.5rem",
  },
  columnName: {
    fontWeight: "bold",
    fontFamily: "monospace",
  },
  columnMeta: {
    fontSize: "0.8rem",
    color: "#909399",
  },
  fieldRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: "1rem",
    marginTop: "0.5rem",
    alignItems: "center",
  },
  fieldLabel: {
    display: "flex",
    flexDirection: "column",
    fontSize: "0.8rem",
    color: "#606266",
    gap: "0.2rem",
    minWidth: "180px",
  },
  checkboxLabel: {
    display: "flex",
    alignItems: "center",
    gap: "0.3rem",
    fontSize: "0.85rem",
    color: "#606266",
  },
  input: {
    padding: "0.3rem 0.5rem",
    borderRadius: "0.3rem",
    border: "1px solid #dcdfe6",
    fontSize: "0.9rem",
  },
  tableIssueRow: {
    marginBottom: "0.4rem",
  },
  tableIssueText: {
    display: "block",
    marginBottom: "0.2rem",
  },
  tableIssueCheckbox: {
    fontSize: "0.85rem",
    color: "#b88230",
    cursor: "pointer",
  },
  operationHint: {
    margin: "0.3rem 0 0.2rem",
    fontSize: "0.8rem",
    color: "#5470c6",
  },
  operationHintExclude: {
    margin: "0.3rem 0 0.2rem",
    fontSize: "0.8rem",
    color: "#909399",
  },
};
