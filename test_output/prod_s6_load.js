// 生产环境端到端测试 - 场景6：高频连续LLM调用
// 单表流程跑通后，连续验证多个假设（每个假设都会触发 recommend + verify 两次LLM调用），
// 模拟真实session节奏下的连续LLM调用压力，专测续7"假设树/验证偶发失败"场景的
// 重试机制+失败日志是否生效（不模拟LLM全挂，只看自然概率下是否有失败被正确处理）
const { chromium } = require("playwright");
const path = require("path");

const BASE_URL = "http://175.178.91.42:3001";

let page;
const verifyLog = [];

(async () => {
  const browser = await chromium.launch();
  page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("BROWSER ERROR:", msg.text());
  });
  page.on("response", (res) => {
    if (res.status() >= 400) console.log("HTTP ERROR:", res.status(), res.url());
  });

  await page.goto(`${BASE_URL}/minerva`);
  await page.waitForTimeout(2000);

  const messages = [
    "最近三个月信用卡分期业务的逾期率持续上升，需要找到主要驱动因素",
    "纯线上业务，对比口径是去年同期，各渠道都有不同程度上升",
    "渠道/额度段/还款方式都看了一遍，没有单一维度能完全解释",
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

  const count = await page.locator('button:has-text("验证此假设")').count();
  console.log(`CHECK: 共 ${count} 个假设节点，将连续验证前4个（每个间隔仅3秒，制造连续LLM调用压力）`);

  const VERIFY_TARGET = Math.min(4, count);
  for (let i = 0; i < VERIFY_TARGET; i++) {
    const t0 = Date.now();
    const btn = page.locator('button:has-text("验证此假设")').first();
    const visible = await btn.isVisible().catch(() => false);
    if (!visible) {
      console.log(`  [${i}] 跳过：未找到可验证按钮`);
      break;
    }
    await btn.click();
    await page.waitForTimeout(3000); // 不等推荐结果渲染完成就尽快点开始验证，制造连续压力

    // 等推荐结果出现（最多20秒），拿到推荐模块就直接点"开始验证"
    let dataInsufficient = false;
    for (let t = 0; t < 7; t++) {
      const warnVisible = await page.locator('button:has-text("标记为数据不足，跳过验证")').isVisible().catch(() => false);
      const startVisible = await page.locator('button:has-text("开始验证")').isVisible().catch(() => false);
      if (warnVisible) { dataInsufficient = true; break; }
      if (startVisible) break;
      await page.waitForTimeout(3000);
    }

    if (dataInsufficient) {
      await page.locator('button:has-text("标记为数据不足，跳过验证")').first().click();
    } else {
      const startBtn = page.locator('button:has-text("开始验证")').first();
      const ok = await startBtn.isVisible().catch(() => false);
      if (ok) {
        await startBtn.click();
      } else {
        console.log(`  [${i}] WARNING: 未出现'开始验证'按钮也未出现数据不足提示，可能推荐接口失败`);
        await page.locator('button:has-text("取消")').first().click().catch(() => {});
        continue;
      }
    }

    // 等待这个节点验证完成（状态从pending变为其他，或出现置信度文案）—最多90秒，立刻进入下一个不额外等待冷却
    try {
      await page.waitForFunction(
        () => !document.body.innerText.includes("正在验证..."),
        { timeout: 90000 }
      );
    } catch (e) {
      console.log(`  [${i}] WARNING: 90秒内验证未完成`);
    }
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`  [${i}] 验证完成，耗时 ${elapsed}s`);
    verifyLog.push({ i, elapsed });
  }

  await page.screenshot({ path: "test_output/prod_s6_after_verify.png", fullPage: true });
  const bodyText = await page.textContent("body");
  const placeholderHit = bodyText.includes("AI生成暂不可用") || bodyText.includes("占位");
  console.log(placeholderHit ? "WARNING: 出现占位/AI不可用文案" : "CHECK: 未出现占位文案 OK");
  console.log("耗时记录:", JSON.stringify(verifyLog));

  console.log("=== 场景6 高频连续LLM调用测试完成（结果汇总见pm2日志[llm._call]记录，需配合SSH人工核对） ===");
  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s6_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  process.exit(1);
});
