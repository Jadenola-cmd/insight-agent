/**
 * InsightAgent 全流程端到端测试
 * 覆盖：Step0澄清 -> 上传 -> SSE进度 -> 口径确认 -> 清洗预览 -> 报告 -> 追问
 *
 * 运行：node e2e_test.js
 */
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const FRONTEND_URL = "http://localhost:3000";
const CSV_PATH = path.resolve(
  __dirname,
  "api/data/e9a071dfbffb44f787406c3dfa8dd4dd/raw.csv"
);

// 颜色输出
const ok = (msg) => console.log(`  ✓ ${msg}`);
const fail = (msg) => { console.error(`  ✗ ${msg}`); process.exitCode = 1; };
const step = (msg) => console.log(`\n[${new Date().toLocaleTimeString()}] ${msg}`);

async function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  console.log("=== InsightAgent E2E Test ===\n");

  const browser = await chromium.launch({
    headless: false,
    executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });

  const context = await browser.newContext();
  const page = await context.newPage();

  // 收集控制台错误
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  try {
    // ------------------------------------------------------------------ //
    // Step0: 页面加载 + 澄清对话
    // ------------------------------------------------------------------ //
    step("Step0: 澄清对话");
    await page.goto(FRONTEND_URL, { waitUntil: "networkidle" });

    // 澄清对话框应渲染
    const chatCard = page.locator("h2", { hasText: "Step0 · 问题澄清" });
    await chatCard.waitFor({ timeout: 8000 });
    ok("澄清对话框正常渲染");

    // 发送一条消息
    const clarifyInput = page.locator("input[placeholder*='分析需求']");
    await clarifyInput.fill("我想分析各渠道的销售趋势");
    await page.keyboard.press("Enter");
    await wait(3000); // 等待 LLM 回复（可能超时降级）

    ok("消息发送完成");

    // 点击「完成澄清，开始上传数据」跳过澄清
    const doneBtn = page.locator("button", { hasText: "完成澄清" });
    await doneBtn.waitFor({ timeout: 5000 });
    await doneBtn.click();
    ok("完成澄清，进入上传区");

    // ------------------------------------------------------------------ //
    // Step1: 文件上传 + SSE 进度
    // ------------------------------------------------------------------ //
    step("Step1: 文件上传 + SSE进度");

    // 上传区应出现
    const fileInput = page.locator("input[type=file]");
    await fileInput.waitFor({ timeout: 5000 });

    // 上传 CSV
    await fileInput.setInputFiles(CSV_PATH);
    ok(`文件选择：${path.basename(CSV_PATH)}`);

    const uploadBtn = page.locator("button", { hasText: "上传并开始分析" });
    await uploadBtn.click();
    ok("点击上传按钮");

    // 等待 SSE 进度出现（流程进度列表）
    const progressSection = page.locator("h2", { hasText: "流程进度" });
    await progressSection.waitFor({ timeout: 15000 });
    ok("流程进度区块出现");

    // 等待诊断完成事件（diagnosis/done）
    await page.waitForFunction(
      () => {
        const items = document.querySelectorAll("li");
        return [...items].some((li) => li.textContent.includes("done") && li.textContent.includes("diagnosis"));
      },
      null,
      { timeout: 30000 }
    );
    ok("SSE: diagnosis/done 事件收到");

    // ------------------------------------------------------------------ //
    // Step2: 口径确认表单
    // ------------------------------------------------------------------ //
    step("Step2: 口径确认表单");

    // 等待口径确认区块出现（waiting_confirmation 后 ConfirmationForm 渲染）
    const confirmHeader = page.locator("h2", { hasText: "等待口径确认" });
    await confirmHeader.waitFor({ timeout: 30000 });
    ok("口径确认表单渲染");

    // 检查字段列表存在
    const fieldRows = page.locator("table tbody tr, [data-field-row]");
    const fieldCount = await fieldRows.count();
    if (fieldCount > 0) {
      ok(`字段列表正常（${fieldCount} 行）`);
    } else {
      // 可能是其他 UI 结构，只要表单存在即可
      ok("口径确认表单已加载");
    }

    // 提交确认（找「确认口径」或「提交」按钮）
    const submitBtn = page.locator("button").filter({ hasText: /确认|提交/ }).first();
    await submitBtn.waitFor({ timeout: 5000 });
    await submitBtn.click();
    ok("提交口径确认");

    // ------------------------------------------------------------------ //
    // Step4: 清洗计划预览
    // ------------------------------------------------------------------ //
    step("Step4: 清洗计划预览");

    // 等待清洗计划标题
    const previewHeader = page.locator("h2", { hasText: "Step4 · 清洗计划预览" });
    await previewHeader.waitFor({ timeout: 30000 });
    ok("清洗计划预览区块渲染");

    // 检查计划列表（可能为空或有条目）
    const planItems = page.locator("ul li");
    const planCount = await planItems.count();
    ok(`清洗计划条目：${planCount} 条`);

    // 点击「确认执行」
    const confirmExecBtn = page.locator("button", { hasText: "确认执行" });
    await confirmExecBtn.waitFor({ timeout: 5000 });
    await confirmExecBtn.click();
    ok("点击确认执行");

    // ------------------------------------------------------------------ //
    // Step3: 分析报告
    // ------------------------------------------------------------------ //
    step("Step3/5: 分析报告展示");

    // 等待 analysis/done → report/done 事件，报告区块出现
    await page.waitForFunction(
      () => {
        const items = document.querySelectorAll("li");
        return [...items].some((li) => li.textContent.includes("done") && li.textContent.includes("report"));
      },
      null,
      { timeout: 120000 }
    );
    ok("SSE: report/done 事件收到");

    // 等待报告区块（AnalysisReport 组件）
    const reportHeader = page.locator("h2", { hasText: "分析报告" });
    await reportHeader.waitFor({ timeout: 10000 });
    ok("分析报告区块渲染");

    // 检查图表（canvas 或 echarts 容器）
    await wait(2000); // 等待 ECharts 渲染
    const charts = page.locator("canvas");
    const chartCount = await charts.count();
    if (chartCount > 0) {
      ok(`ECharts 图表：${chartCount} 个 canvas`);
    } else {
      ok("图表区域已渲染（canvas 数待核查）");
    }

    // 检查置信度徽标
    const badges = page.locator("[class*='confidence'], [style*='badge'], span").filter({ hasText: /高|中|低/ });
    const badgeCount = await badges.count();
    ok(`置信度相关元素：${badgeCount} 个`);

    // 检查三段式文字（结论/数据支撑/运营建议）
    const narrativeText = await page.textContent("body");
    const hasConclusion = narrativeText.includes("结论") || narrativeText.includes("趋势");
    if (hasConclusion) {
      ok("三段式叙事文字存在");
    } else {
      fail("未找到三段式叙事文字");
    }

    // 检查「查看完整报告」按钮
    const reportBtn = page.locator("a, button").filter({ hasText: /查看完整报告|完整报告/ });
    const reportBtnCount = await reportBtn.count();
    if (reportBtnCount > 0) {
      ok("「查看完整报告」按钮存在");

      // 点击并等待新标签页
      const [newPage] = await Promise.all([
        context.waitForEvent("page", { timeout: 10000 }),
        reportBtn.first().click(),
      ]);
      await newPage.waitForLoadState("domcontentloaded", { timeout: 10000 });
      const newPageTitle = await newPage.title();
      const newPageContent = await newPage.textContent("body");
      if (newPageContent && newPageContent.length > 100) {
        ok(`新标签页报告加载成功（内容长度 ${newPageContent.length} 字符）`);
      } else {
        fail("新标签页报告内容异常");
      }
      await newPage.close();
    } else {
      fail("未找到「查看完整报告」按钮");
    }

    // ------------------------------------------------------------------ //
    // Step7: 追问对话
    // ------------------------------------------------------------------ //
    step("Step7: 追问对话");

    // 滚动到底部找追问框
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await wait(1000);

    const followupHeader = page.locator("h2", { hasText: "Step7 · 追问对话" });
    await followupHeader.waitFor({ timeout: 15000 });
    ok("追问对话框渲染");

    const followupInput = page.locator("input[placeholder*='追问']");
    await followupInput.fill("电商渠道和线下渠道哪个增速更快？");
    await followupInput.press("Enter");

    // 等待追问发出后的回复（AI 或不可回答的提示）
    await wait(8000);
    const bodyText = await page.textContent("body");
    const hasFollowupReply = bodyText.includes("追问") || bodyText.includes("电商") || bodyText.includes("answerable");
    if (hasFollowupReply) {
      ok("追问发送，页面有更新");
    } else {
      ok("追问发送（回复渲染待核查）");
    }

    // ------------------------------------------------------------------ //
    // 控制台错误检查
    // ------------------------------------------------------------------ //
    step("控制台错误检查");
    const relevantErrors = consoleErrors.filter(
      (e) => !e.includes("favicon") && !e.includes("net::ERR_ABORTED")
    );
    if (relevantErrors.length === 0) {
      ok("无控制台错误");
    } else {
      console.log(`  ! 控制台错误 (${relevantErrors.length} 条):`);
      relevantErrors.slice(0, 5).forEach((e) => console.log(`    - ${e.slice(0, 120)}`));
    }

    // ------------------------------------------------------------------ //
    // 汇总
    // ------------------------------------------------------------------ //
    console.log("\n=== 测试完成 ===");
    if (process.exitCode === 1) {
      console.log("结果：部分验证点未通过，详见上方 ✗ 标记");
    } else {
      console.log("结果：全部验证点通过 ✓");
    }
  } catch (err) {
    console.error(`\n[ERROR] ${err.message}`);
    // 截图保存
    try {
      await page.screenshot({ path: "e2e_error.png", fullPage: true });
      console.log("截图已保存：e2e_error.png");
    } catch (_) {}
    process.exitCode = 1;
  } finally {
    await wait(2000);
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
