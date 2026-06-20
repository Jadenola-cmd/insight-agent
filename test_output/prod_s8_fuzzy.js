// 生产环境端到端测试 - 场景8：模糊/边界输入
// 用极度模糊的问题描述开场，看Step0澄清对话能否在合理轮次内（不超过设计上限3轮+1轮
// 收敛确认）收敛到具体的analysis_goal并进入上传区，而不是无限循环追问或直接卡死
const { chromium } = require("playwright");

const BASE_URL = "http://175.178.91.42:3001";

let page;

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

  // 故意用极度模糊、几乎没有信息量的问题开场，并在后续回答里继续含糊其辞，
  // 测试澄清对话是否真的能收敛而不是死循环
  const fuzzyMessages = [
    "业务最近不太好，帮我看看",
    "就是感觉数据不太对，说不清楚具体是哪里",
    "嗯都看看吧，哪里有问题就说哪里",
    "行，那就随便看看趋势好了",
    "好的",
  ];

  let uploadAppeared = false;
  let turnsUsed = 0;
  for (const msg of fuzzyMessages) {
    const uploadVisible = await page.locator('input[type="file"]').isVisible().catch(() => false);
    if (uploadVisible) { uploadAppeared = true; break; }
    const input = page.locator('input[placeholder*="描述你观察到的业务问题"]');
    const inputVisible = await input.isVisible().catch(() => false);
    if (!inputVisible) break;
    await input.waitFor({ state: "visible", timeout: 20000 });
    await page.waitForFunction((el) => !el.disabled, await input.elementHandle(), { timeout: 20000 }).catch(() => {});
    await input.fill(msg);
    await page.click('button:has-text("发送")');
    turnsUsed++;
    await page.waitForTimeout(9000);
    console.log(`第${turnsUsed}轮已发送: "${msg}"`);
    const bodyText = await page.textContent("body");
    console.log(`  当前AI最新回复片段: ${bodyText.slice(-300).replace(/\s+/g, " ")}`);
  }

  if (!uploadAppeared) {
    uploadAppeared = await page.locator('input[type="file"]').isVisible().catch(() => false);
  }

  await page.screenshot({ path: "test_output/prod_s8_clarify.png", fullPage: true });

  console.log(`\nCHECK: 共用了 ${turnsUsed} 轮模糊回答`);
  if (uploadAppeared) {
    console.log("CHECK: 澄清对话最终收敛，进入上传区 OK");
  } else {
    console.log("WARNING: 5轮模糊回答后仍未进入上传区，疑似澄清对话无法收敛/死循环");
  }

  if (uploadAppeared) {
    // 继续走完整流程，确认收敛后的analysis_goal是否合理（不应该是空泛的"看看趋势"）
    const path = require("path");
    await page.setInputFiles('input[type="file"]', path.join(__dirname, "m1.csv"));
    await page.click('button:has-text("上传并开始分析")');
    await page.waitForSelector("text=数据诊断完成", { timeout: 60000 });
    console.log("STEP2 上传 OK");
    const bodyText = await page.textContent("body");
    const goalMatch = bodyText.match(/已确认分析目标[:：]([^]*?)请上传/);
    console.log("CHECK: 收敛后的analysis_goal =", goalMatch ? goalMatch[1].trim().slice(0, 200) : "(未提取到，见截图)");
  }

  console.log("=== 场景8 模糊/边界输入测试完成 ===");
  await browser.close();
})().catch(async (err) => {
  console.error("TEST FAILED:", err);
  try {
    await page.screenshot({ path: "test_output/prod_s8_failure.png", fullPage: true });
    console.log("FAILURE SCREENSHOT SAVED");
  } catch (e) {}
  process.exit(1);
});
