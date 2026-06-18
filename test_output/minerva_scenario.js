// Minerva 场景化端到端测试脚本
// 用法: node minerva_scenario.js <scenario:1|2|3|4> [baseUrl]
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const DATA_DIR = "D:/00_Workspace/02_InsightAgent/AIOutput/Claude/20260615钱包测试数据/完整版";
const OUT_DIR = __dirname;

const SCENARIO = process.argv[2] || "1";
const BASE_URL = process.argv[3] || "http://175.178.91.42:3001";

const CONFUSION_MESSAGES = [
  "最近三个月信贷产品支用率从11%下滑到5%，应该怎么拆解？",
  "纯线上业务，外部渠道导流为主，11%是过去半年历史均值，下滑前没有产品调整",
  "全维度（渠道/风险评分/定价分层）都同步下滑，没有明显区分度",
];

const VAGUE_MESSAGES = ["我的数据有问题"];

function file(name) {
  return path.join(DATA_DIR, name);
}

async function waitNoError(page) {
  const errVisible = await page.locator("text=错误：").isVisible().catch(() => false);
  if (errVisible) {
    const txt = await page.locator("text=错误：").innerText().catch(() => "");
    throw new Error("页面进入错误态: " + txt);
  }
}

async function run() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push("PAGE ERROR: " + err.message));

  let sessionId = null;
  page.on("request", (req) => {
    const m = req.url().match(/\/api\/analyze\/([^/]+)\/(stream|resume)/);
    if (m) sessionId = m[1];
  });
  const resumeBodies = [];
  page.on("response", async (res) => {
    if (/\/api\/analyze\/[^/]+\/resume/.test(res.url())) {
      try {
        const body = await res.json();
        resumeBodies.push(body);
      } catch {}
    }
  });

  const log = [];
  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT_DIR, `s${SCENARIO}_${name}.png`), fullPage: true });
  };

  try {
    await page.goto(`${BASE_URL}/minerva`);
    await page.waitForTimeout(2000);

    if (SCENARIO === "4") {
      // 边界场景：模糊输入，验证AI追问而非直接放行到上传
      await page.fill('input[placeholder*="描述你观察到的业务问题"]', VAGUE_MESSAGES[0]);
      await page.click('button:has-text("发送")');
      await page.waitForTimeout(10000);
      const uploadVisible = await page.locator('input[type="file"]').isVisible().catch(() => false);
      const aiMsgs = await page.locator('div:has-text("")').allTextContents().catch(() => []);
      await shot("after_vague");
      if (uploadVisible) {
        log.push("FAIL: 模糊输入后直接进入上传阶段，未追问");
      } else {
        log.push("PASS: 模糊输入后未直接放行，AI应已追问");
      }
      // 打印最后一条AI消息辅助人工核查
      const lastBubble = await page.locator('div').filter({ hasText: /./ }).last().innerText().catch(() => "");
      log.push("最后页面文本片段: " + lastBubble.slice(-200));
      fs.writeFileSync(path.join(OUT_DIR, `s${SCENARIO}_log.txt`), log.join("\n"));
      console.log(log.join("\n"));
      await browser.close();
      return;
    }

    const messages = CONFUSION_MESSAGES;
    for (const msg of messages) {
      const uploadVisible = await page.locator('input[type="file"]').isVisible().catch(() => false);
      if (uploadVisible) break;
      await page.fill('input[placeholder*="描述你观察到的业务问题"]', msg);
      await page.click('button:has-text("发送")');
      await page.waitForTimeout(10000);
    }
    await page.waitForSelector('input[type="file"]', { timeout: 60000 });
    log.push("STEP1 问题定义 OK");
    await shot("step1_problem");

    const files = SCENARIO === "2" || SCENARIO === "3"
      ? ["dim_user_profile_crm.csv", "dim_user_profile_risk.csv", "dwd_credit_apply.csv", "dwd_loan_record.csv", "ods_wallet_events.csv"].map(file)
      : [file("dwd_loan_record.csv")];

    await page.setInputFiles('input[type="file"]', files);
    await page.click('button:has-text("上传并开始分析")');
    await page.waitForSelector('button:has-text("确认并开始清洗"), button:has-text("确认关联方案，继续清洗")', { timeout: 120000 });
    await waitNoError(page);
    log.push("STEP2 上传+诊断 OK");
    await shot("step2_diagnosis");

    if (await page.locator('button:has-text("确认并开始清洗")').isVisible().catch(() => false)) {
      await page.click('button:has-text("确认并开始清洗")');
    }
    await page.waitForSelector('button:has-text("确认关联方案，继续清洗"), button:has-text("确认执行")', { timeout: 120000 });
    await waitNoError(page);
    if (await page.locator('button:has-text("确认关联方案，继续清洗")').isVisible().catch(() => false)) {
      log.push("检测到多表关联方案确认阶段");
      await shot("step3_join");
      await page.click('button:has-text("确认关联方案，继续清洗")');
      await page.waitForSelector('button:has-text("确认执行")', { timeout: 120000 });
    }
    await waitNoError(page);
    log.push("STEP3 口径/关联确认 OK");
    await shot("step3_transform_preview");

    await page.click('button:has-text("确认执行")');
    await page.waitForSelector('text=验证此假设', { timeout: 150000 });
    await waitNoError(page);
    log.push("STEP4 清洗确认 -> 假设树生成 OK");
    await shot("step4_hypothesis_tree");

    const hypoCount = await page.locator('button:has-text("验证此假设")').count();
    log.push(`假设数量: ${hypoCount}`);

    // 验证第一个假设
    await page.locator('button:has-text("验证此假设")').first().click();
    await page.locator('button:has-text("开始验证")').first().click();
    await page.waitForSelector("text=置信度", { timeout: 90000 });
    await waitNoError(page);
    log.push("STEP5 验证假设1 OK");
    await shot("step5_verify1");

    if (SCENARIO === "3") {
      // 场景3：追问深挖
      await page.fill('input[placeholder*="补充背景信息"]', "刚才验证的这个假设，能再细分到具体渠道层面看看吗？");
      await page.click('button:has-text("发送")');
      await page.waitForTimeout(15000);
      await waitNoError(page);
      log.push("STEP5b 追问深挖 OK");
      await shot("step5b_followup");

      // 再验证第二个假设（如果存在）
      const hypoCount2 = await page.locator('button:has-text("验证此假设")').count();
      if (hypoCount2 > 0) {
        await page.locator('button:has-text("验证此假设")').first().click();
        await page.locator('button:has-text("开始验证")').first().click();
        await page.waitForSelector("text=置信度", { timeout: 90000 });
        await waitNoError(page);
        log.push("STEP5c 验证假设2 OK");
        await shot("step5c_verify2");
      }
    }

    await page.click('button:has-text("生成综合结论")');
    await page.waitForTimeout(20000);
    await waitNoError(page);
    log.push("STEP6 综合结论 OK");
    await shot("step6_conclusion");

    log.push("sessionId: " + sessionId);
    log.push("consoleErrors: " + JSON.stringify(consoleErrors));

    fs.writeFileSync(path.join(OUT_DIR, `s${SCENARIO}_log.txt`), log.join("\n"));
    fs.writeFileSync(path.join(OUT_DIR, `s${SCENARIO}_session.txt`), sessionId || "");
    fs.writeFileSync(path.join(OUT_DIR, `s${SCENARIO}_resume_bodies.json`), JSON.stringify(resumeBodies, null, 2));
    console.log(log.join("\n"));
    console.log("RESULT: PASS");
  } catch (err) {
    log.push("ERROR: " + err.message);
    log.push("consoleErrors: " + JSON.stringify(consoleErrors));
    fs.writeFileSync(path.join(OUT_DIR, `s${SCENARIO}_log.txt`), log.join("\n"));
    console.log(log.join("\n"));
    console.log("RESULT: FAIL");
    await shot("error_state").catch(() => {});
  } finally {
    await browser.close();
  }
}

run();
