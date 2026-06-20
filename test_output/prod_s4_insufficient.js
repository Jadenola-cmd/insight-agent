// 生产环境端到端测试 - 场景4：数据不相关场景
// 故意用与可用字段（m1.csv: user_id/amount/city/date）完全不相关的业务问题
// （APP页面加载速度导致用户流失），验证：
// ①推荐验证方法接口对不相关假设是否真的返回 data_sufficient:false
// ②点击"标记为数据不足，跳过验证"后是否真的跳过分析、不硬凑结论
const { chromium } = require("playwright");
const path = require("path");

const BASE_URL = "http://175.178.91.42:3001";

let page;
let lastRecommend = null;
let lastResumeAfterSkip = null;

(async () => {
  const browser = await chromium.launch();
  page = await browser.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("BROWSER ERROR:", msg.text());
  });
  page.on("response", async (res) => {
    if (res.status() >= 400) console.log("HTTP ERROR:", res.status(), res.url());
    if (res.url().includes("/verification/recommend") && res.request().method() === "POST") {
      try {
        lastRecommend = await res.json();
      } catch (e) {}
    }
  });

  await page.goto(`${BASE_URL}/minerva`);
  await page.waitForTimeout(2000);

  const messages = [
    "APP内信贷产品页面加载速度变慢，导致很多用户没等到页面加载完就关闭APP流失了，想分析怎么解决",
    "纯线上业务，问题集中在页面打开到展示额度信息这段时间，用户反馈明显感觉变慢",
    "怀疑是前端渲染或后端接口响应慢导致的，没有具体排查方向，想先看数据能定位到什么程度",
  ];
  for (const msg of messages) {
    const uploadVisible = await page.locator('input[type="file"]').isVisible().catch(() => false);
    if (uploadVisible) break;
    await page.fill('input[placeholder*="描述你观察到的业务问题"]', msg);
    await page.click('button:has-text("发送")');
    await page.waitForTimeout(8000);
  }
  await page.waitForSelector('input[type="file"]', { timeout: 60000 });
  console.log("STEP1 问题定义 OK（注意：故意用与m1.csv字段[user_id/amount/city/date]完全不相关的页面加载场景）");

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
  await page.screenshot({ path: "test_output/prod_s4_tree.png", fullPage: true });

  // Step5: 遍历假设节点点"验证此假设"，找到第一个 data_sufficient:false 的
  const verifyButtons = page.locator('button:has-text("验证此假设")');
  const count = await verifyButtons.count();
  console.log(`CHECK: 共 ${count} 个假设节点可验证`);

  let foundInsufficient = false;
  for (let i = 0; i < count; i++) {
    lastRecommend = null;
    const btn = page.locator('button:has-text("验证此假设")').nth(0); // 每次点第一个，已验证的不再显示该按钮
    const visible = await btn.isVisible().catch(() => false);
    if (!visible) break;
    await btn.click();
    await page.waitForTimeout(3000);
    // 等待推荐结果渲染（最多15秒）
    for (let t = 0; t < 5 && !lastRecommend; t++) await page.waitForTimeout(3000);
    console.log(`  节点${i}: recommend响应 =`, JSON.stringify(lastRecommend));

    if (lastRecommend && lastRecommend.data_sufficient === false) {
      foundInsufficient = true;
      await page.screenshot({ path: "test_output/prod_s4_insufficient_card.png", fullPage: true });
      console.log("CHECK: 命中 data_sufficient:false，reason =", lastRecommend.reason);

      const skipBtn = page.locator('button:has-text("标记为数据不足，跳过验证")').first();
      const skipVisible = await skipBtn.isVisible().catch(() => false);
      if (!skipVisible) {
        console.log("WARNING: data_sufficient=false 但前端未渲染'标记为数据不足，跳过验证'按钮");
        break;
      }

      page.once("response", async (res) => {
        if (res.url().includes("/resume") && res.request().method() === "POST") {
          try {
            lastResumeAfterSkip = await res.json();
          } catch (e) {}
        }
      });
      await skipBtn.click();
      await page.waitForTimeout(3000);
      console.log("CHECK: 跳过验证后resume响应 =", JSON.stringify(lastResumeAfterSkip).slice(0, 500));
      await page.screenshot({ path: "test_output/prod_s4_after_skip.png", fullPage: true });
      break;
    } else {
      // 取消这次验证，换下一个节点试
      const cancelBtn = page.locator('button:has-text("取消")').first();
      await cancelBtn.click().catch(() => {});
      await page.waitForTimeout(1000);
    }
  }

  if (!foundInsufficient) {
    console.log("WARNING: 所有假设节点的推荐接口都返回data_sufficient:true，未能验证'数据不足拦截'路径——");
    console.log("说明本次构造的不相关场景LLM仍判断数据可用，需要换一个更不相关的问题/数据组合重测");
  } else {
    // 检查假设树最终状态：被跳过的节点应该是 partial，summary 是固定的"无法验证"文案，而不是硬凑的支持/反驳结论
    const bodyText = await page.textContent("body");
    if (bodyText.includes("当前数据缺少支撑该假设所需的字段，无法验证")) {
      console.log("CHECK: 假设树正确显示'无法验证'摘要，未硬凑结论 OK");
    } else {
      console.log("WARNING: 未在页面找到预期的'无法验证'摘要文案，需人工核查截图");
    }
  }

  console.log("=== 场景4 数据不相关测试完成 ===");
  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s4_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  process.exit(1);
});
