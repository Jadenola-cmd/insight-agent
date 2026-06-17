import { useState } from "react";

const JOIN_HOW_OPTIONS = [
  { value: "left", label: "LEFT JOIN" },
  { value: "inner", label: "INNER JOIN" },
  { value: "right", label: "RIGHT JOIN" },
  { value: "outer", label: "FULL OUTER JOIN" },
];

export default function JoinPlanForm({ joinPlan, tableColumns, onSubmit, submitting }) {
  const [primaryTable, setPrimaryTable] = useState(joinPlan?.primary_table || "");
  const [joins, setJoins] = useState(
    (joinPlan?.joins || []).map((j) => ({
      table: j.table || "",
      left_col: j.on?.left_col || "",
      right_col: j.on?.right_col || "",
      how: j.how || "left",
      purpose: j.purpose || "",
    }))
  );

  const tableNames = Object.keys(tableColumns || {});

  const updateJoin = (idx, patch) => {
    setJoins((prev) => prev.map((j, i) => (i === idx ? { ...j, ...patch } : j)));
  };

  const addJoin = () => {
    setJoins((prev) => [
      ...prev,
      { table: "", left_col: "", right_col: "", how: "left", purpose: "" },
    ]);
  };

  const removeJoin = (idx) => {
    setJoins((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = () => {
    const payload = {
      primary_table: primaryTable,
      joins: joins
        .filter((j) => j.table)
        .map((j) => ({
          table: j.table,
          on: { left_col: j.left_col, right_col: j.right_col },
          how: j.how,
          purpose: j.purpose,
        })),
    };
    onSubmit(payload);
  };

  const getColumnsForTable = (tableName) => tableColumns?.[tableName] || [];

  return (
    <div className="ia-card">
      <h2 style={styles.sectionTitle}>多表关联方案确认</h2>
      <p style={styles.subtitle}>
        系统已根据表结构自动推荐关联方案，您可以修改主表、关联键和JOIN方式后确认。
      </p>

      {/* 主表选择 */}
      <div style={styles.fieldGroup}>
        <label style={styles.fieldLabel}>
          主表（primary_table）
          <select
            value={primaryTable}
            onChange={(e) => setPrimaryTable(e.target.value)}
            style={styles.select}
          >
            <option value="">-- 请选择主表 --</option>
            {tableNames.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>
        {primaryTable && (
          <div style={styles.columnHint}>
            可用字段：{getColumnsForTable(primaryTable).join("、")}
          </div>
        )}
      </div>

      {/* JOIN 列表 */}
      {joins.length === 0 && (
        <p style={styles.emptyHint}>单表分析，无需关联。如需关联其他表，请点击下方按钮添加。</p>
      )}

      {joins.map((join, idx) => (
        <div key={idx} style={styles.joinRow}>
          <div style={styles.joinHeader}>
            <span style={styles.joinIndex}>关联 #{idx + 1}</span>
            <button className="btn btn-ghost" onClick={() => removeJoin(idx)} style={styles.removeBtn}>
              删除
            </button>
          </div>

          <div style={styles.joinFields}>
            <label style={styles.fieldLabel}>
              右表
              <select
                value={join.table}
                onChange={(e) => updateJoin(idx, { table: e.target.value })}
                style={styles.select}
              >
                <option value="">-- 选择表 --</option>
                {tableNames.filter((t) => t !== primaryTable).map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>

            <label style={styles.fieldLabel}>
              JOIN 方式
              <select
                value={join.how}
                onChange={(e) => updateJoin(idx, { how: e.target.value })}
                style={styles.select}
              >
                {JOIN_HOW_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </label>
          </div>

          <div style={styles.joinFields}>
            <label style={styles.fieldLabel}>
              左表关联键
              <input
                type="text"
                value={join.left_col}
                onChange={(e) => updateJoin(idx, { left_col: e.target.value })}
                style={styles.input}
                placeholder="如 user_id"
              />
            </label>
            <label style={styles.fieldLabel}>
              右表关联键
              <input
                type="text"
                value={join.right_col}
                onChange={(e) => updateJoin(idx, { right_col: e.target.value })}
                style={styles.input}
                placeholder="如 user_id"
              />
            </label>
          </div>

          {/* 左表可用字段 */}
          <div style={styles.columnHint}>
            主表({primaryTable || "未选"})可用字段：{getColumnsForTable(primaryTable).join("、") || "无"}
          </div>

          {/* 右表可用字段 */}
          {join.table && (
            <div style={styles.columnHint}>
              {join.table} 可用字段：{getColumnsForTable(join.table).join("、") || "无"}
            </div>
          )}

          <label style={styles.fieldLabelFull}>
            关联目的说明
            <input
              type="text"
              value={join.purpose}
              onChange={(e) => updateJoin(idx, { purpose: e.target.value })}
              style={styles.input}
              placeholder="如：补充用户属性信息"
            />
          </label>
        </div>
      ))}

      <div style={styles.actions}>
        <button className="btn btn-outline" onClick={addJoin}>
          + 新增关联
        </button>
        <button
          className="btn btn-primary"
          onClick={handleSubmit}
          disabled={submitting || !primaryTable}
          style={{ marginLeft: "0.5rem" }}
        >
          {submitting ? "提交中..." : "确认关联方案，继续清洗"}
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
    marginBottom: "1rem",
  },
  fieldGroup: {
    marginBottom: "1rem",
  },
  fieldLabel: {
    display: "flex",
    flexDirection: "column",
    fontSize: "0.8rem",
    color: "#606266",
    gap: "0.2rem",
    minWidth: "180px",
    flex: 1,
  },
  fieldLabelFull: {
    display: "flex",
    flexDirection: "column",
    fontSize: "0.8rem",
    color: "#606266",
    gap: "0.2rem",
    marginTop: "0.5rem",
  },
  select: {
    padding: "0.3rem 0.5rem",
    borderRadius: "0.3rem",
    border: "1px solid #dcdfe6",
    fontSize: "0.9rem",
    backgroundColor: "#fff",
  },
  input: {
    padding: "0.3rem 0.5rem",
    borderRadius: "0.3rem",
    border: "1px solid #dcdfe6",
    fontSize: "0.9rem",
  },
  columnHint: {
    fontSize: "0.75rem",
    color: "#909399",
    marginTop: "0.3rem",
    lineHeight: 1.4,
  },
  emptyHint: {
    color: "#909399",
    fontSize: "0.9rem",
    marginBottom: "1rem",
  },
  joinRow: {
    border: "1px solid #e4e7ed",
    borderRadius: "0.5rem",
    padding: "0.8rem",
    marginBottom: "0.8rem",
    backgroundColor: "#fafafa",
  },
  joinHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "0.5rem",
  },
  joinIndex: {
    fontWeight: 600,
    fontSize: "0.85rem",
    color: "#5470c6",
  },
  removeBtn: {
    fontSize: "0.8rem",
    padding: "0.2rem 0.5rem",
  },
  joinFields: {
    display: "flex",
    flexWrap: "wrap",
    gap: "0.8rem",
    marginBottom: "0.5rem",
  },
  actions: {
    display: "flex",
    alignItems: "center",
    marginTop: "1rem",
  },
};
