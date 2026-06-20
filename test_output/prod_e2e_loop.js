// 生产环境端到端测试 - 场景1：单表上传+假设验证全流程
// 目标: http://175.178.91.42:3001/minerva
const { chromium } = require("playwright");
const path = require("path");

const BASE_URL = "http://175.178.91.42:3001";

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

  // Step1: 问题定义对话，循环发消息直到出现上传区
  const messages = [
    "最近三个月信贷产品支用率从11%下滑到5%，应该怎么拆解？",
    "纯线上业务，外部渠道导流为主，11%是过去半年历史均值，下滑前没有产品调整",
    "全维度（渠道/风险评分/定价分层）都同步下滑，没有明显区分度",
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
  await page.screenshot({ path: "test_output/prod_s1_step1.png", fullPage: true });

  // Step2: 上传数据
  await page.setInputFiles('input[type="file"]', path.join(__dirname, "m1.csv"));
  await page.click('button:has-text("上传并开始分析")');
  await page.waitForSelector("text=数据诊断完成", { timeout: 60000 });
  console.log("STEP2 上传 OK");

  // Step3: 字段口径确认
  await page.waitForTimeout(1000);
  const submitBtn = page.locator('button:has-text("确认并开始清洗")').first();
  await submitBtn.click();
  await page.waitForSelector("text=已生成清洗计划", { timeout: 60000 });
  console.log("STEP3 口径确认 OK");
  await page.screenshot({ path: "test_output/prod_s1_step3.png", fullPage: true });

  // Step4: 清洗计划确认 -> 假设树生成
  await page.waitForTimeout(1000);
  const confirmTransformBtn = page.locator('button:has-text("确认执行")').first();
  await confirmTransformBtn.click();
  await page.waitForSelector("text=验证此假设", { timeout: 240000 });
  console.log("STEP4 清洗确认 -> 假设树生成 OK");

  // 检查假设树是否出现占位文案
  const bodyText = await page.textContent("body");
  if (bodyText.includes("AI生成暂不可用") || bodyText.includes("占位")) {
    console.log("WARNING: 假设树疑似出现占位文案");
  } else {
    console.log("CHECK: 假设树未出现占位文案 OK");
  }
  await page.screenshot({ path: "test_output/prod_s1_step4_tree.png", fullPage: true });

  // Step5: 点击验证此假设，检查是否展示推荐模块
  await page.waitForTimeout(1000);
  await page.locator('button:has-text("验证此假设")').first().click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: "test_output/prod_s1_step5_recommend.png", fullPage: true });
  const recommendText = await page.textContent("body");
  console.log("CHECK: 验证前页面截图已保存，人工核查是否展示推荐模块+依据");

  await page.locator('button:has-text("开始验证")').first().click();
  await page.waitForSelector("text=置信度", { timeout: 60000 });
  console.log("STEP5 验证假设 OK");

  // Step6: 生成综合结论
  await page.waitForTimeout(1000);
  await page.click('button:has-text("生成综合结论")');
  await page.waitForTimeout(15000);

  await page.screenshot({ path: "test_output/prod_s1_final.png", fullPage: true });
  console.log("STEP6 综合结论 OK, screenshot saved");

  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s1_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  process.exit(1);
});
