"""临时验证脚本：跑通 Minerva 全流程，核对本次3个修复点（验证后可删除）。
完全照搬 pages/minerva.js 的接口调用顺序：GET /stream -> POST /resume(...) 循环。
"""
import json
import uuid

import requests

BASE = "http://127.0.0.1:8001"
SESSION_ID = f"mnv{uuid.uuid4().hex[:10]}"
PROXIES = {"http": None, "https": None}
CSV_PATH = "test_output/minerva_test_data.csv"

CSV_CONTENT = """event_name,user_id,event_time,credit_limit
click,1,2026-04-01,20000
click_event,2,2026-04-01,21000
tap,3,2026-04-02,19000
touch_click,4,2026-04-02,22000
click,5,2026-04-03,20500
apply,6,2026-04-03,23000
apply,7,2026-04-04,24000
click,8,2026-04-04,20100
"""

with open(CSV_PATH, "w", encoding="utf-8") as f:
    f.write(CSV_CONTENT)


def read_sse(resp):
    last = None
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        last = json.loads(line[len("data: "):])
    return last


def resume(value):
    r = requests.post(
        f"{BASE}/api/analyze/{SESSION_ID}/resume",
        json={"value": value},
        proxies=PROXIES,
    )
    r.raise_for_status()
    return r.json()


def classify(payload):
    if not payload:
        return None
    if payload.get("type") == "problem_definition":
        return "clarify", payload
    if payload.get("type") == "awaiting_data":
        return "awaiting_data", payload
    if payload.get("type") == "hypothesis_tree":
        return "hypothesis_tree", payload
    if payload.get("diagnosis"):
        return "confirmation", payload
    if payload.get("join_plan"):
        return "join_plan", payload
    if "transform_plan" in payload:
        return "transform", payload
    return "unknown", payload


# ---- 启动流程 ----
r = requests.get(f"{BASE}/api/analyze/{SESSION_ID}/stream", stream=True, proxies=PROXIES)
last_evt = read_sse(r)
phase, payload = classify(last_evt["data"])
print("== phase:", phase)
assert phase == "clarify", payload

# ---- 澄清对话直到收敛到 awaiting_data ----
msg = "钱包页贷款产品转化率低，重点关注点击到申请环节的流失，没有历史转化率基准"
for _ in range(5):
    data = resume(msg)
    if data.get("status") == "done":
        break
    phase, payload = classify(data["interrupt"])
    print("== phase:", phase, "| keys:", list(payload.keys()))
    if phase == "awaiting_data":
        break
    msg = "请直接基于现有数据分析，不需要更多背景信息"

assert phase == "awaiting_data", payload

# ---- 上传数据 ----
with open(CSV_PATH, "rb") as f:
    up = requests.post(
        f"{BASE}/api/upload",
        files={"files": ("test.csv", f, "text/csv")},
        data={"session_id": SESSION_ID},
        proxies=PROXIES,
    )
up.raise_for_status()
print("upload:", up.json())

data = resume(True)
phase, payload = classify(data["interrupt"])
print("== phase:", phase)
assert phase == "confirmation", payload
diagnosis = payload["diagnosis"]
print("table_issues:", diagnosis.get("table_issues"))

# ---- 问题1验证：勾选"让AI自动处理"该表级问题 ----
# node1诊断对table_issues的语义检测本身是既有逻辑、非本次改动范围，且LLM对小样本数据
# 判断有随机性；这里直接模拟截图里的真实场景（手动构造一条同义问题描述），专门测试本次
# 改动的部分：_llm_supplementary_ops 拿到该描述后能否真正生成standardize_categories。
table_issues = diagnosis.get("table_issues") or []
event_issue = next((i for i in table_issues if "event_name" in i or "click" in i), None)
print("node1实际检测到的表级问题:", table_issues)
if not event_issue:
    event_issue = "event_name 列存在同义不同名：'click'与'click_event'可能表示同一事件，'tap'与'touch_click'可能重复，需统一事件命名规范"
print("用于测试的表级问题描述:", event_issue)

columns_payload = []
for col in diagnosis["columns"]:
    columns_payload.append({
        "original_name": col["name"],
        "final_name": col["name"],
        "business_meaning": col.get("inferred_meaning") or "",
        "include": True,
        "missing_value_strategy": "fill" if col.get("null_rate", 0) > 0 else "none",
        "fill_value": "" if col.get("null_rate", 0) > 0 else None,
    })

confirmed_schema = {
    "columns": columns_payload,
    "resolved_table_issues": [event_issue] if event_issue else [],
}
data = resume(confirmed_schema)
phase, payload = classify(data["interrupt"])
print("== phase:", phase)
assert phase == "transform", payload
plan = payload["transform_plan"]
print("transform_plan:")
for step in plan:
    print(" ", step)

std_ops = [s for s in plan if s.get("op") == "standardize_categories"]
print("\n[问题1检查] standardize_categories ops:", std_ops)
if event_issue:
    print("[问题1结果]", "PASS - 生成了standardize_categories" if std_ops else "FAIL - 未生成standardize_categories")

# ---- 确认清洗计划，进入假设树 ----
data = resume({"action": "confirm", "plan": plan})
phase, payload = classify(data["interrupt"])
print("== phase:", phase)
assert phase == "hypothesis_tree", payload
tree = payload["tree"]
print(f"假设树共 {len(tree)} 条假设")
for n in tree[:5]:
    print(" -", n["id"], n["group"], n["label"][:40])

# ---- 问题2/3验证：找一个明显数据不相关的假设，调用 /verification/recommend ----
target = None
for n in tree:
    if "加载速度" in n["label"] or "UI" in n["label"] or "UX" in n["label"]:
        target = n
        break
if not target:
    target = tree[0]
print("\n选定验证目标:", target["id"], target["label"])

rec = requests.post(
    f"{BASE}/api/analyze/{SESSION_ID}/verification/recommend",
    json={"node_id": target["id"]},
    proxies=PROXIES,
)
rec.raise_for_status()
recommendation = rec.json()
print("[问题2/3] 推荐结果:", json.dumps(recommendation, ensure_ascii=False, indent=2))

if "加载速度" in target["label"] or "UI" in target["label"] or "UX" in target["label"]:
    ok = recommendation.get("data_sufficient") is False
    print("[问题3结果]", "PASS - data_sufficient=False" if ok else f"FAIL - data_sufficient={recommendation.get('data_sufficient')}")
else:
    print("[问题2结果] 推荐模块:", recommendation.get("module"), "| reason:", recommendation.get("reason"))

# ---- 用 skip 标记该假设为数据不足（验证 node_verification 的 skip 分支） ----
data = resume({"action": "verify", "node_id": target["id"], "module": "__skip__"})
phase, payload = classify(data["interrupt"])
print("== phase after skip:", phase)
updated_node = next(n for n in payload["tree"] if n["id"] == target["id"])
print("[skip分支结果]", updated_node["status"], "|", updated_node["verification_summary"])
assert updated_node["status"] == "partial"
assert "无法验证" in (updated_node["verification_summary"] or "")
print("[skip分支] PASS")

# ---- 正常验证一个有支撑数据的假设，确认主流程未被破坏 ----
normal_target = next((n for n in tree if n["id"] != target["id"]), None)
if normal_target:
    rec2 = requests.post(
        f"{BASE}/api/analyze/{SESSION_ID}/verification/recommend",
        json={"node_id": normal_target["id"]},
        proxies=PROXIES,
    )
    rec2.raise_for_status()
    rec2_data = rec2.json()
    print("\n正常假设推荐:", normal_target["label"][:40], "->", rec2_data)
    module = rec2_data.get("module") or "trend_insight"
    data = resume({"action": "verify", "node_id": normal_target["id"], "module": module})
    phase, payload = classify(data["interrupt"])
    print("== phase after normal verify:", phase)
    updated2 = next(n for n in payload["tree"] if n["id"] == normal_target["id"])
    print("[正常验证结果]", updated2["status"], "|", (updated2["verification_summary"] or "")[:80])
    print("[正常验证] PASS - 流程未破坏" if updated2["status"] != "pending" else "[正常验证] FAIL")

print("\n=== 全部检查完成 ===")
