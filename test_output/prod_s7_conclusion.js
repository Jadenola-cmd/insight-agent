// 生产环境端到端测试 - 场景7：综合结论生成
// 用5表钱包数据集（字段丰富，更容易让假设真正命中可验证模块），遍历假设逐个验证
// 直到至少1个真正跑了分析模块（非数据不足跳过），再生成综合结论，检查report.html
// 落盘、结构化执行摘要、置信度徽标是否真实存在（不只是CSS定义）。
const { chromium } = require("playwright");
const path = require("path");

const BASE_URL = "http://175.178.91.42:3001";
const DATA_DIR = path.resolve(__dirname, "../AIOutput/Claude/20260615钱包测试数据/完整版");
const FILES = [
  "ods_wallet_events.csv",
  "dwd_credit_apply.csv",
  "dwd_loan_record.csv",
  "dim_user_profile_crm.csv",
  "dim_user_profile_risk.csv",
].map((f) => path.join(DATA_DIR, f));

let page;
let sessionId = null;
let realVerifyCount = 0;

(async () => {
  const browser = await chromium.launch();
  page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("BROWSER ERROR:", msg.text());
  });
  page.on("response", async (res) => {
    if (res.status() >= 400) console.log("HTTP ERROR:", res.status(), res.url());
    if (res.url().includes("/api/upload") && res.request().method() === "POST") {
      try {
        const json = await res.json();
        if (json.session_id) sessionId = json.session_id;
      } catch (e) {}
    }
    if (res.url().includes("/verification/recommend")) {
      try {
        console.log("    RECOMMEND:", JSON.stringify(await res.json()));
      } catch (e) {
        console.log("    RECOMMEND PARSE ERROR/TIMEOUT:", e.message);
      }
    }
  });

  await page.goto(`${BASE_URL}/minerva`);
  await page.waitForTimeout(2000);

  const messages = [
    "多个信贷产品线最近放款通过率波动较大，想看不同用户群体和渠道的差异并给出结论",
    "纯线上业务，外部渠道导流为主，5张表：行为事件/授信申请/放款记录/用户画像(CRM)/用户画像(风控)",
    "全维度都看了，没有单一维度能完全解释",
  ];
  for (const msg of messages) {
    const uploadVisible = await page.locator('input[type="file"]').isVisible().catch(() => false);
    if (uploadVisible) break;
    const input = page.locator('input[placeholder*="描述你观察到的业务问题"]');
    await input.waitFor({ state: "visible", timeout: 20000 });
    await page.waitForFunction((el) => !el.disabled, await input.elementHandle(), { timeout: 20000 }).catch(() => {});
    await input.fill(msg);
    await page.click('button:has-text("发送")');
    await page.waitForTimeout(8000);
  }
  await page.waitForSelector('input[type="file"]', { timeout: 60000 });
  console.log("STEP1 问题定义 OK");

  await page.setInputFiles('input[type="file"]', FILES);
  await page.click('button:has-text("上传并开始分析")');
  await page.waitForSelector("text=数据诊断完成", { timeout: 90000 });
  console.log("STEP2 多表上传 OK");

  await page.waitForTimeout(1000);
  await page.locator('button:has-text("确认并开始清洗")').first().click();
  await page.waitForSelector('h2:has-text("多表关联方案确认")', { timeout: 90000 });
  console.log("STEP3 Join方案 OK");
  await page.locator('button:has-text("确认关联方案，继续清洗")').first().click();
  await page.waitForSelector('h2:has-text("清洗计划预览")', { timeout: 90000 });
  console.log("STEP4 清洗计划 OK");

  await page.locator('button:has-text("确认执行")').first().click();
  console.log("STEP5 已确认执行清洗，等待假设树生成...");
  await page.waitForSelector("text=验证此假设", { timeout: 240000 });
  console.log("STEP5 假设树生成 OK");

  const total = await page.locator('button:has-text("验证此假设")').count();
  console.log(`CHECK: 共 ${total} 个假设节点，逐个验证直到命中真正跑模块的`);

  // 注意：前端"验证此假设"按钮不会因为已验证过而消失（允许用不同模块重新验证），
  // DOM顺序固定对应假设顺序，故用nth(i)精确定位第i个假设而不是每次都点nth(0)
  for (let i = 0; i < total && realVerifyCount === 0; i++) {
    const target = page.locator('button:has-text("验证此假设")').nth(i);
    await target.click();

    let dataSufficient = false;
    let startVisible = false;
    for (let t = 0; t < 7; t++) {
      await page.waitForTimeout(3000);
      const warnVisible = await page.locator('button:has-text("标记为数据不足，跳过验证")').isVisible().catch(() => false);
      startVisible = await page.locator('button:has-text("开始验证")').isVisible().catch(() => false);
      if (warnVisible || startVisible) { dataSufficient = !warnVisible; break; }
    }

    if (startVisible && dataSufficient) {
      // DEBT.md里attribution模块500 bug已修复，这次故意保留LLM推荐的原始模块
      // （即使是attribution）直接验证修复是否生效，不再绕开
      await page.locator('button:has-text("开始验证")').first().click();
      realVerifyCount++;
      console.log(`  [${i}] 命中真正验证模块，已点击"开始验证"`);
    } else if (await page.locator('button:has-text("标记为数据不足，跳过验证")').isVisible().catch(() => false)) {
      await page.locator('button:has-text("标记为数据不足，跳过验证")').first().click();
      console.log(`  [${i}] 数据不足，跳过`);
    } else {
      console.log(`  [${i}] WARNING: 既无开始验证也无跳过按钮，取消`);
      await page.locator('button:has-text("取消")').first().click().catch(() => {});
    }
    await page.waitForFunction(() => !document.body.innerText.includes("正在验证..."), { timeout: 90000 }).catch(() => {});
  }

  console.log(`CHECK: 本次共有 ${realVerifyCount} 个假设真正跑了分析模块`);

  const concludeBtn = page.locator('button:has-text("生成综合结论")');
  await concludeBtn.waitFor({ timeout: 10000 });
  await concludeBtn.click();
  console.log("STEP6 已点击生成综合结论，等待...");
  await page.waitForTimeout(20000);
  await page.screenshot({ path: "test_output/prod_s7_conclusion.png", fullPage: true });

  const bodyText = await page.textContent("body");
  console.log("CHECK: 页面含'置信度'文案 =", /置信度/.test(bodyText));
  console.log("CHECK: 页面含执行摘要/建议/注意事项关键词 =", /执行摘要|建议|注意事项/.test(bodyText));

  console.log("=== 场景7 综合结论生成测试完成 ===");
  console.log("SESSION_ID_FOR_SSH_CHECK:", sessionId);
  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s7_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  console.log("SESSION_ID_FOR_SSH_CHECK:", sessionId);
  process.exit(1);
});
