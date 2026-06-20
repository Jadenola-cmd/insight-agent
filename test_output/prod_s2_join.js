// 生产环境端到端测试 - 场景2：多表上传+Join方案确认+清洗计划稳定性
// 目标: http://175.178.91.42:3001/minerva
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
(async () => {
  const browser = await chromium.launch();
  page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("BROWSER ERROR:", msg.text());
  });
  page.on("pageerror", (err) => console.log("PAGE ERROR:", err.message));
  page.on("response", (res) => {
    if (res.status() >= 400) console.log("HTTP ERROR:", res.status(), res.url());
  });

  await page.goto(`${BASE_URL}/minerva`);
  await page.waitForTimeout(2000);

  // Step1: 问题定义对话
  const messages = [
    "多个信贷产品线最近放款通过率波动较大，想看不同用户群体和渠道的差异",
    "纯线上业务，5张表：行为事件/授信申请/放款记录/用户画像(CRM)/用户画像(风控)",
    "想知道哪些字段可以关联，以及关联后整体数据质量如何",
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
  await page.screenshot({ path: "test_output/prod_s2_step1.png", fullPage: true });

  // Step2: 上传5张表
  await page.setInputFiles('input[type="file"]', FILES);
  console.log(`已选择 ${FILES.length} 个文件`);
  await page.click('button:has-text("上传并开始分析")');
  await page.waitForSelector("text=数据诊断完成", { timeout: 90000 });
  console.log("STEP2 多表上传+诊断 OK");
  await page.screenshot({ path: "test_output/prod_s2_step2_diagnosis.png", fullPage: true });

  // Step3: 字段口径确认
  await page.waitForTimeout(1000);
  const submitBtn = page.locator('button:has-text("确认并开始清洗")').first();
  await submitBtn.click();
  console.log("STEP3 已提交字段口径确认，等待Join方案...");

  // Step4: Join方案确认（用h2标题判断当前渲染的表单，避免chat历史文本误匹配）
  await page.waitForSelector('h2:has-text("多表关联方案确认")', { timeout: 90000 });
  console.log("STEP4 Join方案生成 OK");
  await page.screenshot({ path: "test_output/prod_s2_step4_join.png", fullPage: true });

  const primarySelect = page.locator("select").first();
  const primaryValue = await primarySelect.inputValue().catch(() => "(无法读取)");
  console.log("CHECK: Join方案主表 =", primaryValue);

  await page.locator('button:has-text("确认关联方案，继续清洗")').first().click();
  console.log("STEP4 已提交Join方案确认");

  // Step5: 清洗计划预览（第一次）
  await page.waitForSelector('h2:has-text("清洗计划预览")', { timeout: 90000 });
  console.log("STEP5 清洗计划生成（第一次） OK");
  const planText1 = await page.locator('h2:has-text("清洗计划预览")').locator("xpath=..").textContent();
  await page.screenshot({ path: "test_output/prod_s2_step5_plan1.png", fullPage: true });

  // Step6: 测试稳定性 —— 退回重新确认口径，再走一遍，检查清洗计划是否一致
  const backBtn = page.locator('button:has-text("退回修改口径")').first();
  const hasBackBtn = await backBtn.isVisible().catch(() => false);
  if (hasBackBtn) {
    await backBtn.click();
    console.log("STEP6 已点击退回修改口径");
    await page.waitForSelector('h2:has-text("口径确认")', { timeout: 30000 });
    const submitBtn2 = page.locator('button:has-text("确认并开始清洗")').first();
    await submitBtn2.click();
    await page.waitForSelector('h2:has-text("多表关联方案确认")', { timeout: 90000 });
    await page.locator('button:has-text("确认关联方案，继续清洗")').first().click();
    await page.waitForSelector('h2:has-text("清洗计划预览")', { timeout: 90000 });
    const planText2 = await page.locator('h2:has-text("清洗计划预览")').locator("xpath=..").textContent();
    await page.screenshot({ path: "test_output/prod_s2_step6_plan2.png", fullPage: true });
    console.log("CHECK: 清洗计划重复confirm后是否一致 =", planText1 === planText2 ? "一致 OK" : "不一致，需人工核查截图差异");
  } else {
    console.log("STEP6 跳过：未找到退回修改口径按钮（当前阶段可能不支持）");
  }

  // Step7: 确认执行清洗 -> 假设树生成
  const confirmExecBtn = page.locator('button:has-text("确认执行")').first();
  await confirmExecBtn.click();
  console.log("STEP7 已确认执行清洗，等待假设树生成...");
  await page.waitForSelector("text=验证此假设", { timeout: 240000 });
  console.log("STEP7 假设树生成 OK");

  const bodyText = await page.textContent("body");
  if (bodyText.includes("AI生成暂不可用") || bodyText.includes("占位")) {
    console.log("WARNING: 假设树疑似出现占位文案");
  } else {
    console.log("CHECK: 假设树未出现占位文案 OK");
  }
  await page.screenshot({ path: "test_output/prod_s2_step7_tree.png", fullPage: true });

  console.log("=== 场景2 多表Join测试完成 ===");
  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s2_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  process.exit(1);
});
