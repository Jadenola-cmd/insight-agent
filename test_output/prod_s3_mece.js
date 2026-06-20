// 生产环境端到端测试 - 场景3：假设树MECE检查
// 思路：直连resume接口的JSON响应（非SSE，见api/routes/analyze.py），
// 拿到结构化hypothesis_tree（含group/label），程序化检查不同group间是否有
// 文本高度相似/本质重叠的假设，而不是只靠人工读截图。
const { chromium } = require("playwright");
const path = require("path");

const BASE_URL = "http://175.178.91.42:3001";

let page;
let capturedTree = null;

(async () => {
  const browser = await chromium.launch();
  page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("BROWSER ERROR:", msg.text());
  });
  page.on("response", async (res) => {
    if (res.status() >= 400) console.log("HTTP ERROR:", res.status(), res.url());
    if (res.url().includes("/resume") && res.request().method() === "POST") {
      try {
        const json = await res.json();
        const interrupt = json.interrupt;
        if (interrupt && interrupt.type === "hypothesis_tree" && interrupt.tree) {
          capturedTree = interrupt.tree;
        }
      } catch (e) {
        console.log("RESUME RESPONSE PARSE ERROR:", e.message);
      }
    }
  });

  await page.goto(`${BASE_URL}/minerva`);
  await page.waitForTimeout(2000);

  const messages = [
    "近一个月新户首笔放款后7天内的逾期率明显升高，想拆解原因",
    "纯线上消费贷，新户指首次放款客户，对比口径是上月同期新户",
    "渠道/风险评分/定价分层/放款金额段都看了，没有单一维度能完全解释升高",
  ];
  for (const msg of messages) {
    const uploadVisible = await page.locator('input[type="file"]').isVisible().catch(() => false);
    if (uploadVisible) break;
    await page.fill('input[placeholder*="描述你观察到的业务问题"]', msg);
    await page.click('button:has-text("发送")');
    await page.waitForTimeout(8000);
  }
  await page.waitForSelector('input[type="file"]', { timeout: 60000 });
  console.log("STEP1 问题定义 OK");

  await page.setInputFiles('input[type="file"]', path.join(__dirname, "m1.csv"));
  await page.click('button:has-text("上传并开始分析")');
  await page.waitForSelector("text=数据诊断完成", { timeout: 60000 });
  console.log("STEP2 上传 OK");

  await page.waitForTimeout(1000);
  await page.locator('button:has-text("确认并开始清洗")').first().click();
  await page.waitForSelector('h2:has-text("清洗计划预览")', { timeout: 60000 });
  console.log("STEP3 口径确认 -> 清洗计划 OK");

  await page.waitForTimeout(1000);
  await page.locator('button:has-text("确认执行")').first().click();
  console.log("STEP4 已确认执行清洗，等待假设树生成...");
  await page.waitForSelector("text=验证此假设", { timeout: 240000 });
  console.log("STEP4 假设树生成 OK");
  await page.screenshot({ path: "test_output/prod_s3_tree.png", fullPage: true });

  if (!capturedTree) {
    console.log("WARNING: 未捕获到resume响应中的hypothesis_tree JSON，改从页面DOM兜底提取分组/假设文本");
    const groups = await page.locator(".ia-card, [class*=group]").allTextContents();
    console.log(JSON.stringify(groups, null, 2));
  } else {
    console.log(`CHECK: 捕获到假设树，共 ${capturedTree.length} 个节点`);
    const byGroup = {};
    for (const node of capturedTree) {
      byGroup[node.group] = byGroup[node.group] || [];
      byGroup[node.group].push({ id: node.id, label: node.label });
    }
    console.log("=== 按分组列出假设 ===");
    for (const [group, nodes] of Object.entries(byGroup)) {
      console.log(`\n[${group}]`);
      nodes.forEach((n) => console.log(`  - (${n.id}) ${n.label}`));
    }

    // 简单MECE启发式检查：跨组两两比较label的字符级Jaccard相似度，超过阈值的标记出来人工复核
    function jaccard(a, b) {
      const setA = new Set(a);
      const setB = new Set(b);
      const inter = [...setA].filter((c) => setB.has(c)).length;
      const union = new Set([...setA, ...setB]).size;
      return inter / union;
    }
    console.log("\n=== 跨组相似度检查（字符级Jaccard > 0.6 标记需人工复核） ===");
    const allNodes = capturedTree;
    let flagged = 0;
    for (let i = 0; i < allNodes.length; i++) {
      for (let j = i + 1; j < allNodes.length; j++) {
        if (allNodes[i].group === allNodes[j].group) continue; // 只看跨组
        const sim = jaccard(allNodes[i].label, allNodes[j].label);
        if (sim > 0.6) {
          flagged++;
          console.log(
            `  [${allNodes[i].group}] "${allNodes[i].label}"  <->  [${allNodes[j].group}] "${allNodes[j].label}"  相似度=${sim.toFixed(2)}`
          );
        }
      }
    }
    if (flagged === 0) {
      console.log("CHECK: 未发现跨组高相似度假设，MECE检查通过 OK");
    } else {
      console.log(`WARNING: 发现 ${flagged} 对跨组高相似度假设，需人工核查是否本质重叠`);
    }
  }

  console.log("=== 场景3 MECE测试完成 ===");
  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s3_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  process.exit(1);
});
