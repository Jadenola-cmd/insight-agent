/**
 * InsightAgent 自动化QA Loop：Path A-F 全流程端到端测试（多表上传 + Join + 清洗 + 分析 + 报告 + 追问）
 * 运行：node test_output/qa_loop.js
 */
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const FRONTEND_URL = "http://175.178.91.42:3001";
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

const ok = (msg) => console.log(`  ✓ ${msg}`);
const fail = (msg) => { console.error(`  ✗ ${msg}`); process.exitCode = 1; };
const step = (msg) => console.log(`\n[${new Date().toLocaleTimeString()}] ${msg}`);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const result = { A: "fail", B: "fail", C: "fail", D: "fail", E: "fail", F: "fail", notes: [] };

async function main() {
  console.log("=== InsightAgent QA Loop (Path A-F) ===");

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

  try {
    await page.goto(FRONTEND_URL, { waitUntil: "networkidle", timeout: 30000 });

    // ---- Step0: 澄清对话（跳过） ----
    step("Step0: 澄清对话");
    const doneBtn = page.locator("button", { hasText: "完成澄清，开始上传数据" });
    await doneBtn.waitFor({ timeout: 10000 });
    await doneBtn.click();
    ok("跳过澄清，进入上传区");

    // ============================================================ //
    // Path A: 5张表上传 + 诊断
    // ============================================================ //
    step("Path A: 上传5张表 + 等待诊断");
    const fileInput = page.locator("input[type=file]");
    await fileInput.waitFor({ timeout: 10000 });
    await fileInput.setInputFiles(FILES);
    ok(`已选择 ${FILES.length} 个文件`);

    const uploadBtn = page.locator("button", { hasText: "开始分析" });
    await uploadBtn.click();
    ok("点击开始分析");

    const confirmHeader = page.locator("h2", { hasText: "口径确认" });
    try {
      await confirmHeader.waitFor({ timeout: 60000 });
      ok("诊断完成，口径确认表单渲染");
      result.A = "pass";
    } catch (e) {
      fail("60秒内未出现口径确认表单");
      throw new Error("Path A failed: " + e.message);
    }

    // 抓取诊断字段问题用于记录
    const bodyTextA = await page.textContent("body");
    const detected = [];
    if (bodyTextA.includes("event_name") && /同义|不一致|混乱/.test(bodyTextA)) detected.push("event_name命名混乱");
    if (bodyTextA.includes("kyc_status")) detected.push("kyc_status相关问题");
    if (bodyTextA.includes("interest_rate")) detected.push("interest_rate相关问题");
    result.notes.push(`Path A 检出口径问题(页面文本扫描): ${detected.join("、") || "(未在当前主表字段中扫描到，注意：风控/利率字段属于其他待join表，主表诊断阶段不可见，属设计预期)"}`);

    // ============================================================ //
    // Path B: 字段级口径确认
    // ============================================================ //
    step("Path B: 字段级口径确认");
    const columnRows = page.locator("input[type=text]").locator("xpath=../.."); // 字段名输入框所在容器，粗略定位
    // 按字段名文本定位每个字段块（columnRow），逐个设置策略
    const fieldBlocks = await page.locator("text=空值率").locator("xpath=ancestor::div[1]").all();
    ok(`定位到字段元信息行：${fieldBlocks.length} 个（用于读取null_rate）`);

    // 用更可靠的方式：读取所有 "字段名" label 对应的 input，逐一处理
    const nameInputs = page.locator("label", { hasText: "字段名" }).locator("input");
    const nameCount = await nameInputs.count();
    ok(`字段编辑行数：${nameCount}`);

    // 逐字段读取空值率文本并设置 include / 缺失值策略
    const allColumnMeta = page.locator("text=/空值率/");
    const metaCount = await allColumnMeta.count();
    let droppedCount = 0;
    for (let i = 0; i < metaCount; i++) {
      const metaText = await allColumnMeta.nth(i).textContent();
      const m = metaText.match(/空值率\s*([\d.]+)%/);
      const nullRate = m ? parseFloat(m[1]) : 0;
      // 找到该字段对应行的"纳入分析"复选框（按DOM顺序对应同一字段块）
      const includeCheckbox = page.locator("label", { hasText: "纳入分析" }).nth(i).locator("input[type=checkbox]");
      if (nullRate > 50) {
        await includeCheckbox.uncheck();
        droppedCount++;
      }
    }
    ok(`空值率>50%的字段已设为排除：${droppedCount} 个`);

    // 表级口径问题：全部勾选"我已了解"
    const issueCheckboxes = page.locator("label", { hasText: "我已了解" }).locator("input[type=checkbox]");
    const issueCount = await issueCheckboxes.count();
    for (let i = 0; i < issueCount; i++) {
      await issueCheckboxes.nth(i).check();
    }
    ok(`已勾选表级口径问题确认：${issueCount} 个`);

    const submitConfirmBtn = page.locator("button", { hasText: "确认并开始清洗" });
    await submitConfirmBtn.click();
    ok("提交口径确认");

    // ============================================================ //
    // Path C: join方案确认
    // ============================================================ //
    step("Path C: Join方案确认");
    const joinHeader = page.locator("h2", { hasText: "多表关联方案确认" });
    try {
      await joinHeader.waitFor({ timeout: 30000 });
      ok("Join方案表单渲染（说明Path B口径确认已被后端接受）");
      result.B = "pass";
    } catch (e) {
      fail("30秒内未出现Join方案表单");
      throw new Error("Path C failed: " + e.message);
    }

    const primarySelect = page.locator("select").first();
    const primaryValue = await primarySelect.inputValue();
    const reasonable = primaryValue === "ods_wallet_events";
    result.notes.push(`Path C join方案: primary_table=${primaryValue}（预期ods_wallet_events，${reasonable ? "合理" : "不合理，需人工核查"}）`);
    if (reasonable) {
      ok(`主表 ${primaryValue} 符合预期`);
      result.C = "pass";
    } else {
      fail(`主表 ${primaryValue} 与预期不符`);
    }

    const joinSubmitBtn = page.locator("button", { hasText: "确认关联方案，继续清洗" });
    await joinSubmitBtn.click();
    ok("提交join方案确认（采用LLM默认推荐方案）");

    // ============================================================ //
    // Path D: 清洗plan预览确认
    // ============================================================ //
    step("Path D: 清洗计划预览确认");
    const previewHeader = page.locator("h2", { hasText: "清洗计划预览" });
    try {
      await previewHeader.waitFor({ timeout: 90000 });
      ok("清洗计划预览渲染");
    } catch (e) {
      fail("30秒内未出现清洗计划预览");
      throw new Error("Path D failed: " + e.message);
    }
    const planItems = page.locator("ul li");
    const planCount = await planItems.count();
    ok(`清洗计划条目数：${planCount}`);
    result.D = "pass";

    const confirmExecBtn = page.locator("button", { hasText: "确认执行" });
    await confirmExecBtn.click();
    ok("点击确认执行");

    // ============================================================ //
    // Path E: 分析完成
    // ============================================================ //
    step("Path E: 等待分析完成");
    // h2"分析报告"在analysis/done后就先渲染（此时modules还是空），
    // 必须等到"查看完整报告"按钮出现（reportResult已就位，即report/done）才能检查模块/图表
    const reportBtnWait = page.locator("button", { hasText: "查看完整报告" });
    try {
      await reportBtnWait.waitFor({ timeout: 120000 });
      ok("分析+报告生成完成（查看完整报告按钮出现）");
    } catch (e) {
      fail("120秒内未完成分析+报告生成");
      throw new Error("Path E failed: " + e.message);
    }
    // canvas是next/dynamic({ssr:false})懒加载的echarts-for-react渲染出来的，
    // 固定sleep时间不稳定（之前出现过2秒不够导致误判"无图表"），改为等到出现
    // 第一个canvas再继续，超时也不阻断（后面会再检查一次数量）
    try {
      await page.locator("canvas").first().waitFor({ timeout: 15000 });
    } catch (_) {
      // 留给后面的chartCount检查报告真实结果
    }
    const moduleHeaders = await page.locator("h3").allTextContents();
    ok(`分析模块: ${moduleHeaders.join("、")}`);
    const hasTrend = moduleHeaders.some((t) => t.includes("趋势"));
    const hasComparison = moduleHeaders.some((t) => t.includes("对比"));
    if (hasTrend && hasComparison) {
      ok("Trend和Comparison模块均有输出");
      result.E = "pass";
    } else {
      fail(`缺少模块，Trend=${hasTrend} Comparison=${hasComparison}`);
    }
    const charts = page.locator("canvas");
    const chartCount = await charts.count();
    ok(`ECharts图表数：${chartCount}`);
    if (chartCount === 0) { fail("无图表渲染"); result.E = "fail"; }

    // ============================================================ //
    // Path F: 报告质量验证
    // ============================================================ //
    step("Path F: 报告质量验证");
    const sessionIdMatch = await page.evaluate(() => {
      const links = [...document.querySelectorAll("button")];
      return null; // sessionId 不直接暴露在DOM，下面用网络请求兜底
    });

    const reportBtn = page.locator("button", { hasText: "查看完整报告" });
    await reportBtn.waitFor({ timeout: 10000 });
    const [reportPage] = await Promise.all([
      context.waitForEvent("page", { timeout: 10000 }),
      reportBtn.click(),
    ]);
    await reportPage.waitForLoadState("domcontentloaded", { timeout: 10000 });
    const reportUrl = reportPage.url();
    const reportHtml = await reportPage.content();
    const reportLen = reportHtml.length;
    ok(`报告页面URL: ${reportUrl}，内容长度 ${reportLen}`);

    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const savePath = path.join(__dirname, `report_loop_${ts}.html`);
    fs.writeFileSync(savePath, reportHtml, "utf-8");
    ok(`报告已保存: ${savePath}`);

    if (reportLen < 5120) {
      fail(`报告内容过小（${reportLen} 字节 < 5KB），疑似生成失败或内容缺失`);
    } else {
      ok(`报告大小正常（${reportLen} 字节）`);
    }

    const reportText = await reportPage.textContent("body");
    const dim1 = /置信度|样本量|空值率/.test(reportText);
    const dim3 = /\d+\.\d+%|\d{3,}/.test(reportText) && !/(较高|较低)\s*(?!\d)/.test(reportText.replace(/\d/g, ""));
    const dim4 = /建议|阈值|优先|A\/B测试|审批/.test(reportText);
    const dim2 = /曝光|申请|授信|放款|转化/.test(reportText);
    result.notes.push(`Path F维度: 严谨性=${dim1} 完整性(漏斗覆盖)=${dim2} 具体性=${dim3} 可操作性=${dim4}`);
    const passCount = [dim1, dim2, dim3, dim4].filter(Boolean).length;
    if (passCount >= 3 && reportLen >= 5120) {
      result.F = "pass";
      ok(`报告质量 ${passCount}/4 维度合格，判定 pass`);
    } else {
      fail(`报告质量仅 ${passCount}/4 维度合格`);
    }
    await reportPage.close();

    // ============================================================ //
    // Step7 追问对话（附加验证）
    // ============================================================ //
    step("Step7: 追问对话");
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const followupInput = page.locator("input[placeholder*='追问']");
    await followupInput.waitFor({ timeout: 10000 });
    await followupInput.fill("信用评分下降最多的是哪类用户？");
    await followupInput.press("Enter");
    await wait(10000);
    ok("追问已发送");

    // 控制台错误
    const relevantErrors = consoleErrors.filter((e) => !e.includes("favicon"));
    if (relevantErrors.length > 0) {
      result.notes.push(`控制台错误 ${relevantErrors.length} 条: ${relevantErrors.slice(0, 3).join(" | ")}`);
    }
  } catch (err) {
    console.error(`\n[ERROR] ${err.message}`);
    const relevantErrors = consoleErrors.filter((e) => !e.includes("favicon"));
    if (relevantErrors.length > 0) {
      console.error(`控制台错误 (${relevantErrors.length}):`);
      relevantErrors.slice(0, 10).forEach((e) => console.error(`  - ${e}`));
    }
    try {
      await page.screenshot({ path: path.join(__dirname, "qa_loop_error.png"), fullPage: true });
      ok("截图已保存：qa_loop_error.png");
    } catch (_) {}
  } finally {
    await browser.close();
  }

  console.log("\n=== 汇总 ===");
  console.log(JSON.stringify(result, null, 2));

  const logLine = `Loop | ${new Date().toISOString()}
A: ${result.A}
B: ${result.B}
C: ${result.C}
D: ${result.D}
E: ${result.E}
F: ${result.F}
备注: ${result.notes.join(" / ")}
---
`;
  fs.appendFileSync(path.join(__dirname, "loop_log.md"), logLine, "utf-8");
}

main();
