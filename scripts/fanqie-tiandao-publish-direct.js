#!/usr/bin/env node
const CDP = require('/home/admin/ai/codex/skills/fanqie-upload/node_modules/chrome-remote-interface');
const fs = require('fs');
const path = require('path');

const port = Number(process.argv[2] || process.env.PORT || 9225);
const bookId = process.argv[3] || '7648515504381889560';
const bookName = process.argv[4] || '天道破产后，我在修真界开养老院';
const aiUse = process.argv[5] || 'no';
const debugDir = process.env.FANQIE_DEBUG_DIR || '/home/admin/ai/output/fanqie-upload/tiandao/debug';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function connect() {
  const targets = await CDP.List({ port });
  const target = targets.find(item => item.type === 'page' && item.url.includes('fanqienovel.com')) || targets.find(item => item.type === 'page');
  if (!target) throw new Error(`No Fanqie page on port ${port}`);
  const client = await CDP({ port, target });
  await client.Runtime.enable();
  await client.Page.enable();
  return client;
}

async function evalv(Runtime, expression, userGesture = false) {
  const result = await Runtime.evaluate({ expression, returnByValue: true, awaitPromise: true, userGesture });
  if (result.exceptionDetails) {
    const text = result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'Runtime.evaluate failed';
    throw new Error(text);
  }
  return result.result.value;
}

async function saveDebugSnapshot(client, row, reason, lastStep) {
  fs.mkdirSync(debugDir, { recursive: true });
  const safeNo = String(row.no).padStart(3, '0');
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '').replace('T', '-');
  const base = path.join(debugDir, `${stamp}-${safeNo}-${reason}`);
  const text = await evalv(client.Runtime, `(() => ({
    url: location.href,
    title: document.title,
    body: document.body ? document.body.innerText.slice(0, 12000) : ''
  }))()`).catch(error => ({ error: String(error && error.message || error) }));
  fs.writeFileSync(`${base}.json`, JSON.stringify({ row, reason, lastStep, text }, null, 2));
  const shot = await client.Page.captureScreenshot({ format: 'png', captureBeyondViewport: true }).catch(() => null);
  if (shot && shot.data) fs.writeFileSync(`${base}.png`, Buffer.from(shot.data, 'base64'));
  return base;
}

function draftBoxUrl(type = 2) {
  return `https://fanqienovel.com/main/writer/chapter-manage/${bookId}&${encodeURIComponent(bookName)}?type=${type}`;
}

async function navigate(Page, url, waitMs = 5000) {
  await Page.navigate({ url });
  await sleep(waitMs);
}

async function collectDraftRows(client) {
  const { Runtime, Page } = client;
  await navigate(Page, draftBoxUrl(2), 7000);
  const rows = [];
  for (let page = 1; page <= 10; page++) {
    const current = await evalv(Runtime, `(() => {
      const out = [];
      for (const row of [...document.querySelectorAll('tr, [class*="table"] [class*="row"], div')]) {
        const text = (row.innerText || '').trim();
        const match = text.match(/第\\s*0*(\\d+)\\s*章[^\\n\\t]*/);
        if (!match) continue;
        const href = [...row.querySelectorAll('a[href*="/publish/"]')]
          .map(a => a.href)
          .find(h => h.includes('modifydraft')) || '';
        if (!href) continue;
        out.push({ no: Number(match[1]), title: match[0].trim(), href });
      }
      return out;
    })()`);
    rows.push(...current);
    const clicked = await evalv(Runtime, `(() => {
      const next = [...document.querySelectorAll('li')]
        .find(el => el.getAttribute('aria-label') === '下一页' && !String(el.className).includes('disabled'));
      if (!next) return false;
      next.click();
      return true;
    })()`, true);
    if (!clicked) break;
    await sleep(1800);
  }
  const seen = new Map();
  for (const row of rows) seen.set(String(row.no).padStart(3, '0'), row);
  return [...seen.values()].sort((a, b) => a.no - b.no);
}

async function clickContinueEditing(Runtime) {
  await evalv(Runtime, `(() => {
    const item = [...document.querySelectorAll('button,[role="button"],a')]
      .find(el => (el.innerText || el.textContent || '').trim().includes('继续编辑'));
    if (!item) return false;
    item.click();
    return true;
  })()`, true).catch(() => false);
  await sleep(1000);
}

async function clickNext(Runtime) {
  for (let i = 0; i < 25; i++) {
    const clicked = await evalv(Runtime, `(() => {
      const item = [...document.querySelectorAll('button,[role="button"],a')]
        .find(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
          && !el.disabled
          && String(el.className).includes('publish-button')
          && (el.innerText || el.textContent || '').trim().includes('下一步'));
      if (!item) return false;
      item.click();
      return true;
    })()`, true);
    if (clicked) return true;
    await sleep(1000);
  }
  return false;
}

async function advancePublish(Runtime) {
  return await evalv(Runtime, `(() => {
    const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const roots = [...document.querySelectorAll('.arco-modal,[role="dialog"],.arco-drawer,.arco-message,.arco-notification')]
      .filter(visible);
    const rootText = roots.map(el => (el.innerText || '').trim()).filter(Boolean).join('\\n---\\n');
    const bodyText = document.body ? document.body.innerText : '';
    const text = rootText || bodyText;
    const clickText = needle => {
      const items = [...document.querySelectorAll('button,[role="button"],label')]
        .filter(el => visible(el) && !el.disabled)
        .map(el => ({ el, value: (el.innerText || el.textContent || '').trim() }))
        .filter(item => item.value);
      const item = items.find(item => item.value === needle) || items.find(item => item.value.includes(needle));
      if (!item) return '';
      item.el.focus();
      for (const type of ['pointerover', 'pointerenter', 'mouseover', 'mouseenter', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
        const event = type.startsWith('pointer')
          ? new PointerEvent(type, {
              bubbles: true,
              cancelable: true,
              pointerId: 1,
              pointerType: 'mouse',
              isPrimary: true,
              button: 0,
              buttons: type.endsWith('down') ? 1 : 0
            })
          : new MouseEvent(type, {
              bubbles: true,
              cancelable: true,
              button: 0,
              buttons: type.endsWith('down') ? 1 : 0
            });
        item.el.dispatchEvent(event);
      }
      item.el.click();
      return item.value;
    };
    if (
      bodyText.includes('提交字数超出每日上限') ||
      bodyText.includes('发布数量已达上限') ||
      bodyText.includes('今日发布数量') ||
      (bodyText.includes('今日') && bodyText.includes('上限')) ||
      (bodyText.includes('每日') && bodyText.includes('上限'))
    ) return { status: 'daily-limit', text: text.slice(0, 300) };
    if (location.href.includes('chapter-manage')) return { status: 'submitted', text: text.slice(0, 300) };
    if (text.includes('确认发布')) {
      const label = clickText(${JSON.stringify(aiUse === 'no' ? '否' : '是')});
      const clicked = clickText('确认发布');
      return { status: clicked ? 'confirm-clicked' : 'confirm-visible', clicked, label, text: text.slice(0, 300) };
    }
    if (text.includes('错别字未修改')) {
      const clicked = clickText('提交');
      return { status: clicked ? 'typo-clicked' : 'typo-visible', clicked, text: text.slice(0, 300) };
    }
    if (text.includes('仅基础检测')) {
      const clicked = clickText('仅基础检测');
      return { status: clicked ? 'basic-clicked' : 'basic-visible', clicked, text: text.slice(0, 300) };
    }
    if (text.includes('提交')) {
      const clicked = clickText('提交');
      return { status: clicked ? 'submit-clicked' : 'submit-visible', clicked, text: text.slice(0, 300) };
    }
    return { status: 'waiting', text: text.slice(0, 300) };
  })()`, true);
}

async function publishOne(client, row) {
  const { Runtime, Page } = client;
  console.log(`TRY ${row.title}`);
  await navigate(Page, row.href, 7000);
  await clickContinueEditing(Runtime);
  if (!await clickNext(Runtime)) throw new Error(`Cannot click next for ${row.title}`);
  console.log(`NEXT ${row.title}`);
  const deadline = Date.now() + 180000;
  let lastStep = null;
  let confirmClicks = 0;
  while (Date.now() < deadline) {
    const step = await advancePublish(Runtime);
    lastStep = step;
    if (step.status !== 'waiting') console.log(`STEP ${String(row.no).padStart(3, '0')} ${step.status}${step.clicked ? ` ${step.clicked}` : ''}`);
    if (step.status === 'daily-limit') return 'daily-limit';
    if (step.status === 'submitted') return 'submitted';
    if (step.status === 'confirm-clicked') {
      confirmClicks += 1;
      if (confirmClicks === 4 || confirmClicks === 10) {
        console.log(`DEBUG_CONFIRM_TEXT ${String(row.no).padStart(3, '0')} ${String(step.text || '').replace(/\\s+/g, ' ').slice(0, 500)}`);
      }
    }
    await sleep(step.status === 'confirm-clicked' ? 5000 : 2500);
  }
  const base = await saveDebugSnapshot(client, row, 'timeout', lastStep);
  console.log(`DEBUG_SNAPSHOT ${base}.json ${base}.png`);
  throw new Error(`Publish timed out for ${row.title}`);
}

(async () => {
  const client = await connect();
  try {
    const rows = await collectDraftRows(client);
    if (!rows.length) {
      console.log('No matching drafts found.');
      return;
    }
    console.log(`DRAFT_ROWS ${rows.map(row => String(row.no).padStart(3, '0')).join(',')}`);
    for (const row of rows) {
      const result = await publishOne(client, row);
      if (result === 'daily-limit') {
        console.log(`DAILY_LIMIT at ${row.title}`);
        const remaining = rows.filter(item => item.no >= row.no).map(item => String(item.no).padStart(3, '0')).join(', ');
        console.log(`REMAINING ${remaining}`);
        return;
      }
      console.log(`PUBLISH ${row.title}`);
    }
  } finally {
    await client.close();
  }
})().catch(error => {
  console.error(error.message || error);
  process.exit(1);
});
