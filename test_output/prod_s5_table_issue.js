// 生产环境端到端测试 - 场景5：表级口径问题（同义不同名字段）
// 5表数据集里有event_name等命名混乱的表级问题，本场景勾选"让AI自动处理此问题"，
// 检查清洗计划是否真的输出具体的standardize_categories映射（而不是空操作或笼统文案）
const { chromium } = require("playwright");
const path = require("path");

const BASE_URL = "http://175.178.91.42:3001";
const DATA_DIR = path.resolve(
  __dirname,
  "../AIOutput/Claude/20260615钱包测试数据/完整版"
);
const FILES = [
  "ods_wallet_events.csv",
  "dwd_credit_apply.csv",
  "dwd_loan_record.csv",
  "dim_user_profile_crm.csv",
  "dim_user_profile_risk.csv",
].map((f) => path.join(DATA_DIR, f));

let page;
let capturedTransformPlan = null;

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
        if (interrupt && interrupt.transform_plan) {
          capturedTransformPlan = interrupt.transform_plan;
        }
      } catch (e) {}
    }
  });

  await page.goto(`${BASE_URL}/minerva`);
  await page.waitForTimeout(2000);

  const messages = [
    "多个信贷产品线最近放款通过率波动较大，想看不同用户群体和渠道的差异",
    "纯线上业务，外部渠道导流为主，5张表：行为事件/授信申请/放款记录/用户画像(CRM)/用户画像(风控)",
    "全维度都看了，没有单一维度能完全解释",
  ];
  for (const msg of messages) {
    const uploadVisible = await page.locator('input[type="file"]').isVisible().catch(() => false);
    if (uploadVisible) break;
    const input = page.locator('input[placeholder*="描述你观察到的业务问题"]');
    await input.waitFor({ state: "visible", timeout: 20000 });
    await page.waitForFunction(
      (el) => !el.disabled,
      await input.elementHandle(),
      { timeout: 20000 }
    ).catch(() => {});
    await input.fill(msg);
    await page.click('button:has-text("发送")');
    await page.waitForTimeout(8000);
  }
  await page.waitForSelector('input[type="file"]', { timeout: 60000 });
  console.log("STEP1 问题定义 OK");

  await page.setInputFiles('input[type="file"]', FILES);
  await page.click('button:has-text("上传并开始分析")');
  await page.waitForSelector("text=数据诊断完成", { timeout: 90000 });
  console.log("STEP2 多表上传+诊断 OK");

  // Step3: 检查表级口径问题，勾选"让AI自动处理此问题"
  await page.waitForTimeout(1000);
  const issueTexts = await page.locator("li", { has: page.locator('label:has-text("让AI自动处理此问题")') }).allTextContents();
  console.log(`CHECK: 检测到 ${issueTexts.length} 个表级口径问题：`);
  issueTexts.forEach((t) => console.log("  -", t.replace(/\s+/g, " ").trim()));

  const checkboxes = page.locator('label:has-text("让AI自动处理此问题") input[type="checkbox"]');
  const cbCount = await checkboxes.count();
  for (let i = 0; i < cbCount; i++) {
    await checkboxes.nth(i).check();
  }
  console.log(`STEP3 已勾选全部 ${cbCount} 个表级问题为"让AI自动处理"`);
  await page.screenshot({ path: "test_output/prod_s5_step3_issues.png", fullPage: true });

  await page.locator('button:has-text("确认并开始清洗")').first().click();
  console.log("STEP3 已提交字段口径确认，等待Join方案...");

  await page.waitForSelector('h2:has-text("多表关联方案确认")', { timeout: 90000 });
  console.log("STEP4 Join方案生成 OK");
  await page.locator('button:has-text("确认关联方案，继续清洗")').first().click();

  await page.waitForSelector('h2:has-text("清洗计划预览")', { timeout: 90000 });
  console.log("STEP5 清洗计划生成 OK");
  await page.screenshot({ path: "test_output/prod_s5_step5_plan.png", fullPage: true });

  if (!capturedTransformPlan) {
    console.log("WARNING: 未捕获到resume响应中的transform_plan，仅能凭截图人工核查");
  } else {
    console.log(`CHECK: 清洗计划共 ${capturedTransformPlan.length} 条操作`);
    console.log("完整plan:", JSON.stringify(capturedTransformPlan, null, 2));
    const standardizeOps = capturedTransformPlan.filter((op) => op.op === "standardize_categories");
    if (standardizeOps.length === 0) {
      console.log("WARNING: 清洗计划中未出现standardize_categories操作——表级问题可能未被转化为具体清洗动作，需人工核查截图");
    } else {
      console.log(`CHECK: 命中 ${standardizeOps.length} 条 standardize_categories 操作：`);
      standardizeOps.forEach((op) => {
        console.log(`  - 列=${op.column}  mapping=${JSON.stringify(op.mapping)}`);
        const mappingSize = op.mapping ? Object.keys(op.mapping).length : 0;
        if (mappingSize === 0) {
          console.log("    WARNING: mapping为空，未给出具体同义值映射");
        } else {
          console.log(`    OK: mapping包含 ${mappingSize} 组具体映射`);
        }
      });
    }
  }

  console.log("=== 场景5 表级口径问题测试完成 ===");
  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s5_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  process.exit(1);
});
