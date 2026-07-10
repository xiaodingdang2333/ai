#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

function loadCdp() {
  try {
    return require('chrome-remote-interface');
  } catch (_) {
    return require(path.join('F:', 'ai', 'txt', 'node_modules', 'chrome-remote-interface'));
  }
}

let CDP;
function getCdp() {
  if (!CDP) CDP = loadCdp();
  return CDP;
}
const DEFAULT_ROOT = fs.existsSync('/home/admin/ai/txt') ? '/home/admin/ai/txt' : path.join('F:', 'ai', 'txt');
const DEFAULT_PORT = 9223;
const API_PUBLISH_SCRIPT = '/home/admin/ai/scripts/fanqie-api-publish.js';
const PORT_ACCOUNT_MAP = {
  9223: { account: 'account-a', expected: '\u897f\u5927\u6c34\u602a' },
  9224: { account: 'account-b', expected: '\u6843\u679d\u9192\u9192' },
  9225: { account: 'account-c', expected: '\u6ce1\u8299\u8f6f\u547c\u547c' }
};
const U = {
  newDraft: '\\u65b0\\u5efa\\u8349\\u7a3f',
  saveDraft: '\\u5b58\\u8349\\u7a3f',
  saved: '\\u5df2\\u4fdd\\u5b58',
  next: '\\u4e0b\\u4e00\\u6b65',
  submit: '\\u63d0\\u4ea4',
  basic: '\\u4ec5\\u57fa\\u7840\\u68c0\\u6d4b',
  yes: '\\u662f',
  no: '\\u5426',
  confirmPublish: '\\u786e\\u8ba4\\u53d1\\u5e03',
  continueEditing: '\\u7ee7\\u7eed\\u7f16\\u8f91',
  dailyLimit: '\\u63d0\\u4ea4\\u5b57\\u6570\\u8d85\\u51fa\\u6bcf\\u65e5\\u4e0a\\u9650',
  published: '\\u5df2\\u53d1\\u5e03',
  auditing: '\\u5ba1\\u6838\\u4e2d'
};
const SAVE_DRAFT_LABELS = [U.saveDraft, '\\u5b58\\u8349\\u7a3f'];

function usage() {
  console.log(`Usage:
  node fanqie-upload.js scan --book <book-dir-or-name> [--root F:\\ai\\txt] [--from N] [--to N]
  node fanqie-upload.js drafts --book <book-dir-or-name> --book-id <id> [--port 9223] [--expected-account NAME] [--from N] [--to N]
  node fanqie-upload.js verify --book <book-dir-or-name> --book-id <id> [--port 9223] [--expected-account NAME] [--from N] [--to N]
  node fanqie-upload.js repair --book <book-dir-or-name> --book-id <id> [--port 9223] [--from N] [--to N]
  node fanqie-upload.js repair-href --book <book-dir-or-name> --book-id <id> --href <edit-url> [--port 9223] [--from N] [--to N]
  node fanqie-upload.js publish --book <book-dir-or-name> --book-id <id> [--account account-a] [--expected-account 西大水怪] [--port 9223] [--from N] [--to N]
  node fanqie-upload.js all --book <book-dir-or-name> --book-id <id> [--port 9223] [--from N] [--to N]
`);
}

function argValue(args, name, fallback = undefined) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (!args[index + 1]) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function normalize(text) {
  return text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

function resolveBookDir(book, root) {
  if (!book) throw new Error('--book is required');
  const direct = path.resolve(book);
  if (fs.existsSync(direct)) return direct;
  const underRoot = path.resolve(root, book);
  if (fs.existsSync(underRoot)) return underRoot;
  throw new Error(`Book directory not found: ${book}`);
}

function parseChapter(file) {
  const raw = normalize(fs.readFileSync(file, 'utf8'));
  const lines = raw.split('\n');
  const firstIndex = lines.findIndex(line => line.trim());
  const firstLine = firstIndex >= 0 ? lines[firstIndex].trim() : '';
  const heading = firstLine.match(/^#{1,6}\s+(.+?)\s*$/);
  const title = (heading ? heading[1] : path.basename(file, '.md')).trim();
  const noMatch = title.match(/第\s*0*(\d+)\s*章/) || path.basename(file).match(/第\s*0*(\d+)\s*章/) || path.basename(file).match(/^0*(\d+)[\s._-]/);
  if (!noMatch) throw new Error(`Cannot find chapter number: ${file}`);
  const bodyLines = lines.filter((_, index) => !(heading && index === firstIndex));
  const body = bodyLines.join('\n').trim() + '\n';
  const no = Number(noMatch[1]);
  return {
    no,
    padded: String(no).padStart(3, '0'),
    title,
    shortTitle: title.replace(/^(?:第\s*0*\d+\s*章[\s._-]*)+/, '').trim(),
    body,
    bodyChars: body.trim().length,
    file
  };
}

function loadChapters(bookDir, from = 1, to = Number.MAX_SAFE_INTEGER) {
  const chapterDir = path.join(bookDir, '正文');
  if (!fs.existsSync(chapterDir)) throw new Error(`Chapter directory not found: ${chapterDir}`);
  return fs.readdirSync(chapterDir)
    .filter(name => name.toLowerCase().endsWith('.md'))
    .map(name => parseChapter(path.join(chapterDir, name)))
    .filter(chapter => chapter.no >= from && chapter.no <= to)
    .sort((a, b) => a.no - b.no);
}

function fullChapterTitle(chapter) {
  return `第${chapter.padded}章 ${chapter.shortTitle}`;
}

function chapterNumber(title) {
  const match = String(title || '').match(/第\s*0*(\d+)\s*章/);
  return match ? Number(match[1]) : 0;
}

function sourceParagraphCount(chapter) {
  return normalize(chapter.body).trim().split(/\n\s*\n+/).filter(Boolean).length;
}

function compactText(text) {
  return normalize(String(text || '')).replace(/\s+/g, '');
}

function validateLocalChapters(chapters) {
  const byNumber = new Map();
  const byTitle = new Map();
  for (const chapter of chapters) {
    if (byNumber.has(chapter.no)) {
      throw new Error(`Duplicate local chapter number ${chapter.padded}: ${byNumber.get(chapter.no)} and ${chapter.file}`);
    }
    const title = fullChapterTitle(chapter);
    if (byTitle.has(title)) throw new Error(`Duplicate local chapter title: ${title}`);
    if (!chapter.shortTitle) throw new Error(`Empty local chapter title: ${chapter.file}`);
    if (!chapter.body.trim()) throw new Error(`Empty local chapter body: ${chapter.file}`);
    byNumber.set(chapter.no, chapter.file);
    byTitle.set(title, chapter.file);
  }
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function bodyToHtml(body) {
  return normalize(body)
    .trim()
    .split(/\n\s*\n+/)
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => `<p>${escapeHtml(part).replace(/\n/g, '<br>')}</p>`)
    .join('');
}

function draftBoxUrl(bookId, bookDir, type = 2) {
  return `https://fanqienovel.com/main/writer/chapter-manage/${bookId}&${encodeURIComponent(path.basename(bookDir))}?type=${type}`;
}

async function connect(port) {
  const cdp = getCdp();
  const targets = await cdp.List({ port });
  const target = targets.find(item => item.type === 'page' && item.url.includes('fanqienovel.com')) || targets.find(item => item.type === 'page');
  if (!target) throw new Error(`No Chrome page found on CDP port ${port}`);
  const client = await cdp({ port, target });
  client.Page.javascriptDialogOpening(async () => {
    try {
      await client.Page.handleJavaScriptDialog({ accept: true });
    } catch (_) {}
  });
  await client.Runtime.enable();
  await client.Page.enable();
  try {
    await client.Emulation.enable();
    await client.Emulation.setDeviceMetricsOverride({
      width: 1600,
      height: 1200,
      deviceScaleFactor: 1,
      mobile: false,
      screenWidth: 1600,
      screenHeight: 1200
    });
  } catch (_) {}
  return client;
}

async function evalv(Runtime, expression) {
  const result = await Runtime.evaluate({ expression, returnByValue: true, awaitPromise: true });
  return result.result.value;
}

async function acceptLeaveDialog(Page) {
  try {
    await Page.handleJavaScriptDialog({ accept: true });
    return true;
  } catch (_) {
    if (process.platform !== 'win32') return false;
    try {
      const script = [
        'Add-Type -AssemblyName UIAutomationClient',
        '$root=[System.Windows.Automation.AutomationElement]::RootElement',
        '$name=[string]([char]0x79bb)+[char]0x5f00',
        '$cond=[System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::NameProperty,$name)',
        '$el=$root.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$cond)',
        'if($el){$el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke();"CLICKED"}'
      ].join(';');
      return execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
        encoding: 'utf8',
        windowsHide: true,
        timeout: 2500
      }).includes('CLICKED');
    } catch (_) {
      return false;
    }
  }
}

async function navigate(Page, url, waitMs = 4500) {
  let active = true;
  const dialogGuard = (async () => {
    while (active) {
      await acceptLeaveDialog(Page);
      await sleep(900);
    }
  })();
  try {
    await Page.navigate({ url });
    await sleep(waitMs);
  } finally {
    active = false;
    await dialogGuard;
  }
}

async function fetchDraftList(Runtime, bookId) {
  const result = await evalv(Runtime, `(
    async () => {
      const all = [];
      for (let pageIndex = 0; pageIndex < 10; pageIndex++) {
        const url = '/api/author/chapter/draft_list/v1?book_id=${bookId}&page_index=' + pageIndex + '&page_count=80';
        const res = await fetch(url, { credentials: 'include' });
        const json = await res.json();
        if (!json || json.code !== 0) return { code: json && json.code, message: json && json.message, draft_list: all };
        const rows = (json.data && json.data.draft_list) || [];
        all.push(...rows);
        const total = Number(json.data && json.data.total_count || 0);
        if (!rows.length || all.length >= total) break;
      }
      return { code: 0, draft_list: all };
    }
  )()`);
  if (!result || result.code !== 0) {
    throw new Error(`Draft list API failed: ${JSON.stringify(result)}`);
  }
  return result;
}

async function fetchPublishedList(Runtime, bookId) {
  const result = await evalv(Runtime, `(
    async () => {
      const all = [];
      for (let pageIndex = 0; pageIndex < 50; pageIndex++) {
        const url = '/api/author/chapter/chapter_list/v1?book_id=${bookId}&page_index=' + pageIndex + '&page_count=80';
        const res = await fetch(url, { credentials: 'include' });
        const json = await res.json();
        if (!json || json.code !== 0) return { code: json && json.code, message: json && json.message, item_list: all };
        const rows = (json.data && json.data.item_list) || [];
        all.push(...rows);
        const total = Number(json.data && json.data.total_count || 0);
        if (!rows.length || all.length >= total) break;
      }
      return { code: 0, item_list: all };
    }
  )()`);
  if (!result || result.code !== 0) {
    throw new Error(`Published chapter list API failed: ${JSON.stringify(result)}`);
  }
  return result;
}

async function verifyAccount(Runtime, expectedAccount) {
  if (!expectedAccount) throw new Error('Expected account name is required for draft upload');
  const result = await evalv(Runtime, `(async () => {
    const res = await fetch('/api/user/info/v2', { credentials: 'include' });
    return await res.json();
  })()`);
  const actual = result && result.data && result.data.name;
  if (!result || result.code !== 0 || actual !== expectedAccount) {
    throw new Error(`Account mismatch or invalid login: expected=${expectedAccount}, actual=${actual || (result && result.message) || 'UNKNOWN'}`);
  }
  console.log(`ACCOUNT ${actual}`);
  return actual;
}

async function fetchDraftArticle(Runtime, bookId, itemId) {
  const result = await evalv(Runtime, `(async () => {
    const url = '/api/author/edit_article/v0/?book_id=${bookId}&item_id=${itemId}&from_source=0';
    const res = await fetch(url, { credentials: 'include' });
    const json = await res.json();
    if (!json || json.code !== 0) return { code: json && json.code, message: json && json.message };
    const data = json.data || {};
    const doc = new DOMParser().parseFromString(data.content || '', 'text/html');
    const paragraphs = [...doc.querySelectorAll('p')];
    return {
      code: 0,
      title: data.title || '',
      text: doc.body.innerText || doc.body.textContent || '',
      htmlChars: (data.content || '').length,
      paragraphs: paragraphs.length,
      nonEmptyParagraphs: paragraphs.filter(p => (p.innerText || p.textContent || '').trim()).length
    };
  })()`);
  if (!result || result.code !== 0) {
    throw new Error(`Draft article API failed for item ${itemId}: ${JSON.stringify(result)}`);
  }
  return result;
}

async function verifySavedArticle(Runtime, bookId, row, chapter) {
  const expectedTitle = fullChapterTitle(chapter);
  const stats = await fetchDraftArticle(Runtime, bookId, row.item_id);
  if (stats.title !== expectedTitle) {
    throw new Error(`Saved title mismatch: expected=${expectedTitle}, actual=${stats.title}`);
  }
  const minimumParagraphs = Math.max(2, Math.floor(sourceParagraphCount(chapter) * 0.8));
  if (stats.nonEmptyParagraphs < minimumParagraphs) {
    throw new Error(`Saved paragraph mismatch for ${expectedTitle}: expected>=${minimumParagraphs}, actual=${stats.nonEmptyParagraphs}`);
  }
  if (compactText(stats.text) !== compactText(chapter.body)) {
    throw new Error(`Saved body mismatch for ${expectedTitle}: platform content differs from local manuscript`);
  }
  const words = Number(row.word_number || row.word_count || row.words || 0);
  if (!words) throw new Error(`Saved draft has zero words: ${expectedTitle}`);
  return stats;
}

async function repairUnexpectedBlankDraft(Runtime, bookId, row, chapter) {
  const before = await fetchDraftArticle(Runtime, bookId, row.item_id);
  if (before.title || compactText(before.text) || before.nonEmptyParagraphs) {
    throw new Error(`Unexpected new draft is not blank and cannot be repaired safely: item=${row.item_id}`);
  }
  const expectedTitle = fullChapterTitle(chapter);
  const payload = await evalv(Runtime, `(async () => {
    const editUrl = '/api/author/edit_article/v0/?book_id=${bookId}&item_id=${row.item_id}&from_source=0';
    const editRes = await fetch(editUrl, { credentials: 'include' });
    const editJson = await editRes.json();
    if (!editJson || editJson.code !== 0) return { code: editJson && editJson.code, message: editJson && editJson.message, stage: 'edit_article' };
    const article = editJson.data || {};
    const volumeRes = await fetch('/app/book/volume_list/v0/?book_id=${bookId}&order=1', { credentials: 'include' });
    const volumeJson = await volumeRes.json();
    const volume = (volumeJson && volumeJson.data && volumeJson.data.volume_list || [])[0] || {};
    const form = new URLSearchParams();
    const fields = {
      book_id: ${JSON.stringify(String(bookId))},
      item_id: ${JSON.stringify(String(row.item_id))},
      title: ${JSON.stringify(expectedTitle)},
      content: ${JSON.stringify(bodyToHtml(chapter.body))},
      volume_id: String(article.volume_id || volume.volume_id || ''),
      volume_name: String(article.volume_name || volume.volume_name || ''),
      device_platform: 'pc',
      item_version: String(article.latest_version || article.item_version || '')
    };
    for (const [key, value] of Object.entries(fields)) form.set(key, value);
    const saveRes = await fetch('/app/book/cover_article/v0/', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: form.toString()
    });
    const text = await saveRes.text();
    let json;
    try { json = JSON.parse(text); } catch (_) { json = { code: -99999, body: text.slice(0, 1000) }; }
    return { ...json, stage: 'cover_article', volume_id: fields.volume_id };
  })()`);
  if (!payload || payload.code !== 0) {
    throw new Error(`Blank-draft repair failed for item=${row.item_id}: ${JSON.stringify(payload)}`);
  }
  const after = await fetchDraftList(Runtime, bookId);
  const saved = (after.draft_list || []).find(item => String(item.item_id) === String(row.item_id));
  if (!saved) throw new Error(`Blank-draft repair removed item unexpectedly: ${row.item_id}`);
  await verifySavedArticle(Runtime, bookId, saved, chapter);
  return saved;
}

async function collectDraftTitles(Runtime, bookId) {
  const result = await fetchDraftList(Runtime, bookId);
  const titles = new Set();
  for (const row of result.draft_list || []) {
    const title = row.title || row.chapter_title || '';
    if (title) titles.add(title);
  }
  return titles;
}

async function hasText(Runtime, escaped) {
  return !!await evalv(Runtime, `document.body && document.body.innerText.includes('${escaped}')`);
}

async function waitFor(Runtime, expression, timeoutMs, label) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const value = await evalv(Runtime, expression);
    if (value) return value;
    await sleep(600);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function clickText(Runtime, Input, escaped, options = {}) {
  const selector = options.label ? 'label' : 'button,[role="button"],a';
  const maxX = options.maxX ? `&& item.x < ${options.maxX}` : '';
  const point = await evalv(Runtime, `(() => {
    const needle = '${escaped}';
    const items = [...document.querySelectorAll('${selector}')]
      .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
      .map(el => {
        const r = el.getBoundingClientRect();
        return { text: (el.innerText || el.textContent || '').trim(), disabled: !!el.disabled, x: r.left + r.width / 2, y: r.top + r.height / 2 };
      })
      .filter(item => item.text && !item.disabled ${maxX});
    const item = items.find(item => item.text === needle || item.text.includes(needle));
    return item ? { x: item.x, y: item.y, text: item.text } : null;
  })()`);
  if (!point) return false;
  await Input.dispatchMouseEvent({ type: 'mouseMoved', x: point.x, y: point.y });
  await Input.dispatchMouseEvent({ type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await Input.dispatchMouseEvent({ type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await sleep(options.wait || 1200);
  return true;
}

async function clickDialogButton(Runtime, text) {
  const result = await Runtime.evaluate({ returnByValue: true, awaitPromise: true, userGesture: true, expression: `(() => {
    const needle = ${JSON.stringify(text)};
    const roots = [...document.querySelectorAll('.arco-modal,[role="dialog"],.arco-drawer')]
      .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length));
    for (const root of roots) {
      const buttons = [...root.querySelectorAll('button,[role="button"],label')]
        .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && !el.disabled)
        .map(el => ({ el, value: (el.innerText || el.textContent || '').trim() }))
        .filter(item => item.value);
      const exact = buttons.find(item => item.value === needle);
      const partial = buttons.find(item => item.value.includes(needle));
      const button = (exact || partial)?.el;
      if (button) {
        button.focus();
        const events = ['pointerover', 'pointerenter', 'mouseover', 'mouseenter', 'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
        for (const type of events) {
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
          button.dispatchEvent(event);
        }
        button.click();
        return true;
      }
    }
    return false;
  })()` });
  return result.result.value;
}

async function clickSaveDraft(Runtime, Input, wait = 3500) {
  for (const label of SAVE_DRAFT_LABELS) {
    if (await clickText(Runtime, Input, label, { wait })) return true;
  }
  return false;
}

async function pageText(Runtime, limit = 8000) {
  return await evalv(Runtime, `document.body ? document.body.innerText.slice(0, ${limit}) : ''`);
}

async function visibleDialogText(Runtime, limit = 2500) {
  return await evalv(Runtime, `([...document.querySelectorAll('.arco-modal,[role="dialog"],.arco-message,.arco-notification')]
    .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
    .map(el => (el.innerText || '').trim())
    .filter(Boolean)
    .join('\\n---\\n') || (document.body ? document.body.innerText : '')).slice(0, ${limit})`);
}

async function advancePublishStep(Runtime, aiUse) {
  const result = await Runtime.evaluate({ returnByValue: true, awaitPromise: true, userGesture: true, expression: `(() => {
    const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const dialogRoots = [...document.querySelectorAll('.arco-modal,[role="dialog"],.arco-drawer,.arco-message,.arco-notification')]
      .filter(visible);
    const dialogText = dialogRoots.map(el => (el.innerText || '').trim()).filter(Boolean).join('\\n---\\n');
    const bodyText = document.body ? document.body.innerText : '';
    const text = dialogText || bodyText;
    const allText = [dialogText, bodyText].filter(Boolean).join('\\n---\\n');
    const clickInDialogs = needle => {
      const roots = dialogRoots.length ? dialogRoots : [];
      roots.push(document);
      const robustClick = el => {
        el.focus?.();
        for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
          const event = typeof PointerEvent !== 'undefined' && type.startsWith('pointer')
            ? new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse', isPrimary: true, button: 0, buttons: type.endsWith('down') ? 1 : 0 })
            : new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, buttons: type.endsWith('down') ? 1 : 0 });
          el.dispatchEvent(event);
        }
        el.click?.();
      };
      for (const root of roots) {
        const items = [...root.querySelectorAll('button,[role="button"],label,span,div')]
          .filter(el => visible(el) && !el.disabled)
          .map(el => ({ el, value: (el.innerText || el.textContent || '').trim() }))
          .filter(item => item.value);
        const exact = items.find(item => item.value === needle);
        const partial = items.find(item => item.value.includes(needle));
        const item = exact || partial;
        if (item) {
          robustClick(item.el);
          return item.value;
        }
      }
      return '';
    };
    const clickLabel = needle => {
      const items = [...document.querySelectorAll('label,button,[role="button"]')]
        .filter(el => visible(el) && !el.disabled)
        .map(el => ({ el, value: (el.innerText || el.textContent || '').trim() }))
        .filter(item => item.value);
      const item = items.find(item => item.value === needle) || items.find(item => item.value.includes(needle));
      if (!item) return '';
      item.el.focus?.();
      item.el.click?.();
      return item.value;
    };
    if (allText.includes(${JSON.stringify(U.dailyLimit)})) return { status: 'daily-limit', text: text.slice(0, 300) };
    if (location.href.includes('chapter-manage')) return { status: 'submitted', text: text.slice(0, 300) };
    if (allText.includes('这里可以设置分卷') || document.querySelector('.publish-tour-guide,.reactour__helper')) {
      for (const el of [...document.querySelectorAll('.reactour__helper,.reactour__mask,.publish-tour-guide,.publish-guide,[class*=reactour]')]) el.remove();
      const next = [...document.querySelectorAll('button.publish-button,button')]
        .find(el => visible(el) && !el.disabled && ((el.innerText || el.textContent || '').trim()) === ${JSON.stringify(U.next)});
      if (next) {
        next.click();
        return { status: 'tour-next-clicked', clicked: ${JSON.stringify(U.next)}, text: text.slice(0, 500) };
      }
      return { status: 'tour-visible', text: text.slice(0, 500) };
    }
    if (allText.includes(${JSON.stringify(U.confirmPublish)})) {
      const ai = ${JSON.stringify(aiUse === 'no' ? U.no : U.yes)};
      const label = clickLabel(ai);
      const clicked = clickInDialogs(${JSON.stringify(U.confirmPublish)});
      return { status: clicked ? 'confirm-clicked' : 'confirm-visible', clicked, label, text: text.slice(0, 500) };
    }
    if (allText.includes('是否进行内容风险检测')) {
      const clicked = clickInDialogs('确定');
      return { status: clicked ? 'risk-confirm-clicked' : 'risk-confirm-visible', clicked, text: text.slice(0, 500) };
    }
    if (allText.includes('错别字未修改')) {
      const clicked = clickInDialogs(${JSON.stringify(U.submit)});
      const buttons = [...document.querySelectorAll('button,[role="button"],label')]
        .filter(el => visible(el) && !el.disabled)
        .map(el => (el.innerText || el.textContent || '').trim())
        .filter(Boolean)
        .slice(-12);
      return { status: clicked ? 'typo-clicked' : 'typo-visible', clicked, buttons, text: text.slice(0, 500) };
    }
    if (allText.includes(${JSON.stringify(U.basic)})) {
      const clicked = clickInDialogs(${JSON.stringify(U.basic)});
      return { status: clicked ? 'basic-clicked' : 'basic-visible', clicked, text: text.slice(0, 500) };
    }
    if (allText.includes(${JSON.stringify(U.submit)})) {
      const clicked = clickInDialogs(${JSON.stringify(U.submit)});
      return { status: clicked ? 'submit-clicked' : 'submit-visible', clicked, text: text.slice(0, 500) };
    }
    return { status: 'waiting', text: text.slice(0, 500) };
  })()` });
  return result.result.value;
}

async function getVisibleChapterState(Runtime) {
  const text = await pageText(Runtime, 12000);
  return text;
}

async function fillChapterMeta(Runtime, Input, chapter) {
  const rects = await evalv(Runtime, `(() => [...document.querySelectorAll('input,textarea')]
    .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
    .slice(0, 2)
    .map(el => {
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, value: el.value || '', placeholder: el.placeholder || '' };
    }))()`);
  if (!rects || rects.length < 2) throw new Error('Cannot locate chapter number/title inputs');
  await replaceAt(Input, rects[0], chapter.padded);
  await replaceAt(Input, rects[1], chapter.shortTitle);
  await evalv(Runtime, `(() => {
    const inputs = [...document.querySelectorAll('input,textarea')]
      .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
      .slice(0, 2);
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    set.call(inputs[0], ${JSON.stringify(chapter.padded)});
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
    inputs[0].dispatchEvent(new Event('change', { bubbles: true }));
    set.call(inputs[1], ${JSON.stringify(chapter.shortTitle)});
    inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
    inputs[1].dispatchEvent(new Event('change', { bubbles: true }));
    inputs[1].blur();
  })()`);
  const values = await evalv(Runtime, `(() => [...document.querySelectorAll('input,textarea')]
    .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
    .slice(0, 2)
    .map(el => el.value))()`);
  if (values[0] !== chapter.padded || values[1] !== chapter.shortTitle) {
    throw new Error(`Input verification failed: ${JSON.stringify(values)}`);
  }
}

async function fillChapterBody(Runtime, Input, chapter) {
  const sourceParagraphs = normalize(chapter.body).trim().split(/\n\s*\n+/).filter(Boolean).length;
  const point = await evalv(Runtime, `(() => {
    const editor = [...document.querySelectorAll('.ProseMirror,[contenteditable="true"]')]
      .find(el => el.getBoundingClientRect().width > 500) || document.querySelector('.ProseMirror,[contenteditable="true"]');
    if (!editor) return null;
    const r = editor.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + Math.min(40, r.height / 2) };
  })()`);
  if (!point) throw new Error('Cannot locate chapter editor');
  await evalv(Runtime, `(() => {
    const editor = [...document.querySelectorAll('.ProseMirror,[contenteditable="true"]')]
      .find(el => el.getBoundingClientRect().width > 500) || document.querySelector('.ProseMirror,[contenteditable="true"]');
    if (!editor) return false;
    editor.focus();
    return document.activeElement === editor;
  })()`);
  for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
    await Input.dispatchMouseEvent({ type, x: point.x, y: point.y, button: 'left', clickCount: 1 });
  }
  await sleep(300);
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'Control', code: 'ControlLeft' });
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8 });
  await sleep(300);
  // Insert explicit paragraph HTML in one editor transaction. Simulated Enter
  // keys are lost when ProseMirror re-renders, and plain insertText may flatten
  // or truncate paragraphs while modifying an existing draft.
  const insertedHtml = await evalv(Runtime, `(() => {
    const editor = [...document.querySelectorAll('.ProseMirror,[contenteditable="true"]')]
      .find(el => el.getBoundingClientRect().width > 500) || document.querySelector('.ProseMirror,[contenteditable="true"]');
    if (!editor) return false;
    editor.focus();
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor);
    selection.removeAllRanges();
    selection.addRange(range);
    const ok = document.execCommand('insertHTML', false, ${JSON.stringify(bodyToHtml(chapter.body))});
    editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste' }));
    return ok;
  })()`);
  if (!insertedHtml) throw new Error('Body HTML insertion failed');
  await evalv(Runtime, `(() => {
    const editor = [...document.querySelectorAll('.ProseMirror,[contenteditable="true"]')]
      .find(el => el.getBoundingClientRect().width > 500) || document.querySelector('.ProseMirror,[contenteditable="true"]');
    if (editor) editor.blur();
    return true;
  })()`);
  await sleep(500);
  const inserted = await evalv(Runtime, `(() => {
    const editor = [...document.querySelectorAll('.ProseMirror,[contenteditable="true"]')]
      .find(el => el.getBoundingClientRect().width > 500) || document.querySelector('.ProseMirror,[contenteditable="true"]');
    const paragraphs = [...editor.querySelectorAll('p')];
    return {
      chars: editor.innerText.trim().length,
      paragraphs: paragraphs.length,
      nonEmptyParagraphs: paragraphs.filter(p => p.innerText.trim()).length,
      text: editor.innerText.slice(0, 500)
    };
  })()`);
  if (!inserted || inserted.chars < Math.min(500, chapter.bodyChars / 2)) {
    throw new Error(`Body paste failed: ${JSON.stringify(inserted)}`);
  }
  const minimumParagraphs = Math.max(2, Math.floor(sourceParagraphs * 0.8));
  if (sourceParagraphs > 1 && inserted.nonEmptyParagraphs < minimumParagraphs) {
    throw new Error(`Body paragraph verification failed: source=${sourceParagraphs}, inserted=${JSON.stringify(inserted)}`);
  }
  return inserted.chars;
}

async function createDraft(client, chapter) {
  const { Runtime, Input } = client;
  await waitFor(Runtime, `document.body && document.body.innerText.includes('${U.next}')`, 30000, 'draft editor');
  await fillChapterMeta(Runtime, Input, chapter);
  await fillChapterBody(Runtime, Input, chapter);
  await evalv(Runtime, `(() => {
    const el = [...document.querySelectorAll('textarea')]
      .find(e => e.placeholder && e.placeholder.includes('请描述你希望设定的人物'));
    if (!el) return false;
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    const value = '本章人物沿用作品既有设定，行为、关系与剧情承接前文。';
    set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.blur();
    return true;
  })()`);
  await waitFor(Runtime, `([...document.querySelectorAll('button,[role="button"],a')]
    .some(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      && !el.disabled
      && /\\u4e0b\\u4e00\\u6b65/.test((el.innerText || el.textContent || '').trim())))`, 30000, 'next button');
  await clickText(Runtime, Input, U.next, { wait: 1500 });
  await waitFor(Runtime, `([...document.querySelectorAll('button,[role="button"],a')]
    .some(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      && !el.disabled
      && /\\u5b58\\u8349\\u7a3f|\\u4fdd\\u5b58\\u8349\\u7a3f/.test((el.innerText || el.textContent || '').trim())))`, 30000, 'save draft button');
  if (!await clickSaveDraft(Runtime, Input, 2500)) throw new Error('Save draft button not found');
  await waitFor(Runtime, `document.body.innerText.includes('${U.saved}')`, 30000, 'saved status');
}

async function waitForDraftSaved(Runtime, bookId, chapter) {
  const expected = fullChapterTitle(chapter);
  const deadline = Date.now() + 45000;
  let lastCount = 0;
  while (Date.now() < deadline) {
    const result = await fetchDraftList(Runtime, bookId);
    const rows = result.draft_list || [];
    lastCount = rows.length;
    const row = rows.find(item => (item.title || item.chapter_title || '') === expected);
    if (row && Number(row.word_number || row.word_count || row.words || 0) > 0) return row;
    await sleep(2000);
  }
  throw new Error(`Saved draft not found via API after timeout: ${expected} (last_count=${lastCount})`);
}

function requestedDraftState(rows, chapters) {
  const wanted = new Set(chapters.map(chapter => chapter.no));
  const grouped = new Map();
  for (const row of rows) {
    const title = row.title || row.chapter_title || '';
    const no = chapterNumber(title);
    if (!wanted.has(no)) continue;
    if (!grouped.has(no)) grouped.set(no, []);
    grouped.get(no).push({ ...row, title, no });
  }
  return grouped;
}

async function verifyRequestedDrafts(Runtime, bookId, chapters, options = {}) {
  const [draftResult, publishedResult] = await Promise.all([
    fetchDraftList(Runtime, bookId),
    fetchPublishedList(Runtime, bookId)
  ]);
  const drafts = (draftResult.draft_list || []).map(row => ({ ...row, platformState: 'draft' }));
  const published = (publishedResult.item_list || []).map(row => ({ ...row, platformState: 'published' }));
  const grouped = requestedDraftState([...drafts, ...published], chapters);
  const missing = [];
  for (const chapter of chapters) {
    const expected = fullChapterTitle(chapter);
    const matches = grouped.get(chapter.no) || [];
    if (!matches.length) {
      missing.push(expected);
      continue;
    }
    if (matches.length !== 1) {
      throw new Error(`Duplicate platform drafts for chapter ${chapter.padded}: ${matches.map(row => row.title).join(' | ')}`);
    }
    const row = matches[0];
    if (row.title !== expected) {
      throw new Error(`Platform title conflict for chapter ${chapter.padded}: expected=${expected}, actual=${row.title}`);
    }
    await verifySavedArticle(Runtime, bookId, row, chapter);
    if (!options.quiet) console.log(`VERIFIED_${row.platformState.toUpperCase()} ${expected}`);
  }
  if (missing.length && !options.allowMissing) {
    throw new Error(`Missing platform drafts: ${missing.join(', ')}`);
  }
  return { draftRows: drafts, publishedRows: published, grouped, missing };
}

async function createDraftWithRecovery(client, bookId, bookDir, chapter, attempts = 3) {
  const { Runtime, Page } = client;
  const expected = fullChapterTitle(chapter);
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const before = await fetchDraftList(Runtime, bookId);
    const beforeIds = new Set((before.draft_list || []).map(row => String(row.item_id)));
    try {
      await navigate(Page, draftBoxUrl(bookId, bookDir, 2));
      let href = '';
      for (let i = 0; i < 25 && !href; i++) {
        href = await evalv(Runtime, `(() => {
          const el = [...document.querySelectorAll('a,button,[role="button"]')]
            .find(a => (a.innerText || a.textContent || '').trim().includes('${U.newDraft}'));
          return el && el.href ? el.href : '';
        })()`);
        if (!href) await sleep(1000);
      }
      if (!href) throw new Error('Cannot locate new draft button');
      await navigate(Page, href);
      await sleep(2500);
      await createDraft(client, chapter);
      const row = await waitForDraftSaved(Runtime, bookId, chapter);
      await verifySavedArticle(Runtime, bookId, row, chapter);
      console.log(`DRAFT ${expected}`);
      return row;
    } catch (error) {
      lastError = error;
      let after;
      try {
        after = await fetchDraftList(Runtime, bookId);
      } catch (listError) {
        throw new Error(`${expected} failed and draft state cannot be checked safely: ${error.message}; ${listError.message}`);
      }
      const exact = (after.draft_list || []).filter(row => (row.title || row.chapter_title || '') === expected);
      if (exact.length === 1) {
        await verifySavedArticle(Runtime, bookId, exact[0], chapter);
        console.log(`RECOVERED ${expected}`);
        return exact[0];
      }
      if (exact.length > 1) throw new Error(`Retry blocked: duplicate drafts already exist for ${expected}`);
      const newRows = (after.draft_list || []).filter(row => !beforeIds.has(String(row.item_id)));
      if (newRows.length) {
        if (newRows.length === 1) {
          const repaired = await repairUnexpectedBlankDraft(Runtime, bookId, newRows[0], chapter);
          console.log(`RECOVERED_PARTIAL ${expected}`);
          return repaired;
        }
        throw new Error(`Retry blocked after partial save for ${expected}; new unexpected drafts: ${newRows.map(row => `${row.item_id}:${row.title || '未命名草稿'}`).join(', ')}`);
      }
      if (attempt < attempts) {
        console.warn(`RETRY ${expected} attempt=${attempt + 1} reason=${error.message}`);
        await sleep(1500 * attempt);
      }
    }
  }
  throw lastError || new Error(`Failed to create ${expected}`);
}

async function replaceAt(Input, point, text) {
  await Input.dispatchMouseEvent({ type: 'mouseMoved', x: point.x, y: point.y });
  await Input.dispatchMouseEvent({ type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await Input.dispatchMouseEvent({ type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await sleep(150);
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17 });
  await Input.insertText({ text });
  await sleep(200);
}

async function commandScan(chapters) {
  let total = 0;
  for (const chapter of chapters) {
    total += chapter.bodyChars;
    console.log(`${chapter.padded} ${String(chapter.bodyChars).padStart(5)} ${chapter.shortTitle}`);
  }
  console.log(`TOTAL ${chapters.length} chapters, ${total} chars`);
}

async function commandDrafts(bookDir, bookId, chapters, port, options = {}) {
  const client = await connect(port);
  const { Runtime, Page } = client;
  try {
    await navigate(Page, draftBoxUrl(bookId, bookDir, 2));
    await verifyAccount(Runtime, options.expectedAccount);
    const initial = await verifyRequestedDrafts(Runtime, bookId, chapters, { allowMissing: true, quiet: true });
    for (const chapter of chapters) {
      const expected = fullChapterTitle(chapter);
      const matches = initial.grouped.get(chapter.no) || [];
      if (matches.length === 1) {
        console.log(`SKIP_${matches[0].platformState.toUpperCase()} ${expected}`);
      } else {
        await createDraftWithRecovery(client, bookId, bookDir, chapter, options.attempts || 3);
      }
      console.log(JSON.stringify({ event: 'chapter_verified', chapter_no: chapter.no }));
    }
    await verifyRequestedDrafts(Runtime, bookId, chapters);
    console.log(`UPLOAD_OK ${chapters.length} chapters`);
  } finally {
    await client.close();
  }
}

async function commandVerify(bookId, chapters, port, options = {}) {
  const client = await connect(port);
  try {
    // A fresh leased browser can expose about:blank before its startup URL has
    // committed.  Verify uses relative backend APIs, so establish the Fanqie
    // origin explicitly instead of depending on CDP's initial target choice.
    await navigate(client.Page, 'https://fanqienovel.com/writer/zone');
    await verifyAccount(client.Runtime, options.expectedAccount);
    await verifyRequestedDrafts(client.Runtime, bookId, chapters);
    console.log(`VERIFY_OK ${chapters.length} chapters`);
  } finally {
    await client.close();
  }
}

async function verifyVisibleDraftSaved(Runtime, chapter) {
  let row = null;
  for (let i = 0; i < 15; i++) {
    row = await evalv(Runtime, `(() => {
      const expected = ${JSON.stringify(fullChapterTitle(chapter))};
      const row = [...document.querySelectorAll('tr, [class*="table"] [class*="row"], div')]
        .find(item => (item.innerText || '').includes(expected));
      if (!row) return null;
      const cells = [...row.querySelectorAll('td')].map(td => td.innerText.trim());
      const text = row.innerText || '';
      const wordMatch = text.match(/\\n\\s*(\\d+)\\s*\\n/) || text.match(/\\t\\s*(\\d+)\\s*\\t/);
      return { title: cells[0] || expected, words: Number(cells[1] || wordMatch?.[1] || 0), text: text.slice(0, 300) };
    })()`);
    if (row) break;
    await sleep(2000);
  }
  if (!row) {
    console.warn(`WARN Saved draft verification skipped: ${fullChapterTitle(chapter)} not visible yet`);
    return;
  }
  if (!row.words) throw new Error(`Saved draft verification failed: ${fullChapterTitle(chapter)} has 0 words`);
  if (row.words > Math.max(chapter.bodyChars * 1.7, chapter.bodyChars + 1200)) {
    throw new Error(`Saved draft verification failed: ${fullChapterTitle(chapter)} suspicious word count ${row.words}`);
  }
}

async function collectDraftRows(Runtime, Page, bookId, bookDir) {
  await navigate(Page, draftBoxUrl(bookId, bookDir, 2));
  const rows = [];
  for (let page = 1; page <= 10; page++) {
    const current = await evalv(Runtime, `(() => [...document.querySelectorAll('tr')]
      .map(row => {
        const title = row.querySelector('.table-title a')?.innerText?.trim();
        const cells = [...row.querySelectorAll('td')].map(td => td.innerText.trim());
        const href = row.querySelector('a[href*="/publish/"]')?.href || '';
        const match = title && title.match(/第\\s*0*(\\d+)\\s*章/);
        return title && match && href ? { no: Number(match[1]), title, words: Number(cells[1] || 0), href } : null;
      })
      .filter(Boolean))()`);
    const linkRows = await evalv(Runtime, `(() => {
      const anchors = [...document.querySelectorAll('a')].map(a => ({
        text: (a.innerText || a.textContent || '').trim(),
        href: a.href || ''
      }));
      const out = [];
      for (let i = 0; i < anchors.length; i++) {
        const match = anchors[i].text.match(/第\\s*0*(\\d+)\\s*章[^\\n\\t]*/);
        if (!match) continue;
        const edit = anchors.slice(i + 1, i + 5)
          .find(item => item.href.includes('/publish/') && item.href.includes('modifydraft'));
        if (!edit) continue;
        out.push({
          no: Number(match[1]),
          title: anchors[i].text,
          words: 0,
          href: edit.href
        });
      }
      return out;
    })()`);
    const divRows = await evalv(Runtime, `(() => {
      const out = [];
      for (const row of [...document.querySelectorAll('tr, [class*="table"] [class*="row"], div')]) {
        const text = (row.innerText || '').trim();
        const match = text.match(/第\\s*0*(\\d+)\\s*章[^\\n\\t]*/);
        if (!match) continue;
        const href = [...row.querySelectorAll('a[href*="/publish/"]')]
          .map(a => a.href)
          .find(h => h.includes('modifydraft')) || '';
        if (!href) continue;
        const words = Number((text.match(/\\n\\s*(\\d{3,5})\\s*\\n/) || text.match(/\\t\\s*(\\d{3,5})\\s*\\t/) || [])[1] || 0);
        out.push({ no: Number(match[1]), title: match[0].trim(), words, href });
      }
      return out;
    })()`);
    rows.push(...current, ...linkRows, ...divRows);
    const clicked = await evalv(Runtime, `(() => {
      const next = [...document.querySelectorAll('li')]
        .find(el => el.getAttribute('aria-label') === '下一页' && !String(el.className).includes('disabled'));
      if (!next) return false;
      next.click();
      return true;
    })()`);
    if (!clicked) break;
    await sleep(1400);
  }
  const seen = new Map();
  for (const row of rows) seen.set(String(row.no).padStart(3, '0'), row);
  return seen;
}

async function saveDraft(Runtime, Input) {
  await waitFor(Runtime, `([...document.querySelectorAll('button,[role="button"],a')]
    .some(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      && !el.disabled
      && /\\u5b58\\u8349\\u7a3f|\\u4fdd\\u5b58\\u8349\\u7a3f/.test((el.innerText || el.textContent || '').trim())))`, 30000, 'save draft button');
  if (!await clickSaveDraft(Runtime, Input, 3500)) throw new Error('Save draft button not found');
  await waitFor(Runtime, `document.body.innerText.includes('${U.saved}')`, 30000, 'saved status');
}

async function repairDraft(client, href, chapter) {
  const { Runtime, Input, Page } = client;
  await navigate(Page, href);
  // The recovery prompt can appear after the page first renders. Dismiss it
  // before editing so it cannot replace the repaired body later.
  for (let i = 0; i < 5; i++) {
    if (await clickText(Runtime, Input, U.continueEditing, { wait: 700 })) break;
    await sleep(700);
  }
  await waitFor(Runtime, `!!document.querySelector('.ProseMirror,[contenteditable="true"]')`, 30000, 'chapter editor');
  await fillChapterMeta(Runtime, Input, chapter);
  const chars = await fillChapterBody(Runtime, Input, chapter);
  await waitFor(Runtime, `([...document.querySelectorAll('button,[role="button"],a')]
    .some(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      && !el.disabled
      && /\\u4e0b\\u4e00\\u6b65/.test((el.innerText || el.textContent || '').trim())))`, 30000, 'next button');
  if (!await clickText(Runtime, Input, U.next, { wait: 1500 })) throw new Error('Next button not found while repairing draft');
  await saveDraft(Runtime, Input);
  console.log(`REPAIR ${fullChapterTitle(chapter)} ${chars}`);
}

async function commandRepair(bookDir, bookId, chapters, port) {
  const client = await connect(port);
  const { Runtime, Page } = client;
  try {
    const rows = await collectDraftRows(Runtime, Page, bookId, bookDir);
    for (const chapter of chapters) {
      const row = rows.get(chapter.padded);
      if (!row) {
        console.log(`MISSING_DRAFT ${fullChapterTitle(chapter)}`);
        continue;
      }
      await repairDraft(client, row.href, chapter);
    }
  } finally {
    await client.close();
  }
}

async function commandRepairHref(chapters, port, href) {
  if (!href) throw new Error('--href is required for repair-href');
  if (chapters.length !== 1) throw new Error('repair-href requires exactly one chapter; set --from and --to to the same number');
  const client = await connect(port);
  try {
    await repairDraft(client, href, chapters[0]);
  } finally {
    await client.close();
  }
}

async function draftLinks(Runtime) {
  return await evalv(Runtime, `(() => {
    const rows = [...document.querySelectorAll('tr, .byte-table-tr, [class*="table"] [class*="row"], div')]
      .map(row => ({ text: (row.innerText || '').trim(), hrefs: [...row.querySelectorAll('a')].map(a => a.href).filter(Boolean) }))
      .filter(row => /第\\d{3}章/.test(row.text) && row.hrefs.some(h => h.includes('/publish/')));
    const map = new Map();
    for (const row of rows) {
      const match = row.text.match(/第(\\d{3})章\\s*([^\\n\\t]+)/);
      const href = row.hrefs.find(h => h.includes('/publish/'));
      if (match && href) map.set(match[1], { no: Number(match[1]), title: match[0], href });
    }
    return [...map.values()].sort((a, b) => a.no - b.no);
  })()`);
}

async function publishOne(client, href, chapter, options = {}) {
  const { Runtime, Input, Page } = client;
  console.log(`TRY ${fullChapterTitle(chapter)}`);
  await navigate(Page, href);
  console.log(`OPEN ${fullChapterTitle(chapter)}`);
  await clickText(Runtime, Input, U.continueEditing, { wait: 1000 });
  await waitFor(Runtime, `([...document.querySelectorAll('button,[role="button"],a')]
    .some(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      && !el.disabled
      && String(el.className).includes('publish-button')
      && ((el.innerText || el.textContent || '').trim()).includes('${U.next}')))`, 30000, 'next button');
  const nextClicked = await evalv(Runtime, `(() => {
    const el = [...document.querySelectorAll('button,[role="button"],a')]
      .find(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
        && !el.disabled
        && String(el.className).includes('publish-button')
        && ((el.innerText || el.textContent || '').trim()).includes('${U.next}'));
    if (!el) return false;
    el.click();
    return true;
  })()`);
  if (!nextClicked && !await clickText(Runtime, Input, U.next, { wait: 2500 })) throw new Error(`Cannot click next for ${fullChapterTitle(chapter)}`);
  console.log(`NEXT ${fullChapterTitle(chapter)}`);
  const checkDeadline = Date.now() + 180000;
  let lastStep = null;
  while (Date.now() < checkDeadline) {
    const step = await advancePublishStep(Runtime, options.aiUse);
    lastStep = step;
    if (step.status !== 'waiting') console.log(`STEP ${chapter.padded} ${step.status}${step.clicked ? ` ${step.clicked}` : ''}`);
    if (step.status === 'daily-limit') return { status: 'daily-limit' };
    if (step.status === 'submitted') return { status: 'submitted' };
    await sleep(step.status === 'confirm-clicked' ? 5000 : 2500);
  }
  throw new Error(`Publish confirmation did not complete for ${fullChapterTitle(chapter)}. Last step: ${JSON.stringify(lastStep)}`);
}

async function commandPublish(bookDir, bookId, chapters, port, options = {}) {
  console.log('PUBLISH_SCRIPT_VERSION 20260616-2344');
  const wanted = new Map(chapters.map(chapter => [chapter.padded, chapter]));
  const client = await connect(port);
  const { Runtime, Page } = client;
  let publishedCount = 0;
  try {
    const rows = await collectDraftRows(Runtime, Page, bookId, bookDir);
    const links = chapters
      .map(chapter => {
        const row = rows.get(chapter.padded);
        return row ? { no: chapter.no, title: row.title, href: row.href } : null;
      })
      .filter(Boolean);
    if (!links.length) {
      console.log('No matching drafts found.');
      return;
    }
    console.log(`DRAFT_ROWS ${links.map(link => String(link.no).padStart(3, '0')).join(',')}`);
    for (const link of links) {
      const chapter = wanted.get(String(link.no).padStart(3, '0'));
      const result = await publishOne(client, link.href, chapter, options);
      if (result.status === 'daily-limit') {
        console.log(`DAILY_LIMIT at ${fullChapterTitle(chapter)}`);
        const remaining = links.filter(item => item.no >= link.no).map(item => String(item.no).padStart(3, '0')).join(', ');
        console.log(`REMAINING ${remaining}`);
        return;
      }
      console.log(`PUBLISH ${fullChapterTitle(chapter)}`);
      publishedCount++;
      if (options.limit && publishedCount >= options.limit) return;
    }
  } finally {
    await client.close();
  }
}

function commandPublishApi(bookDir, bookId, from, to, port, options = {}) {
  if (!fs.existsSync(API_PUBLISH_SCRIPT)) {
    throw new Error(`API publish script not found: ${API_PUBLISH_SCRIPT}`);
  }
  const mapped = PORT_ACCOUNT_MAP[port] || {};
  const account = options.account || mapped.account;
  const expectedAccount = options.expectedAccount || mapped.expected;
  if (!account || !expectedAccount) {
    throw new Error('--account and --expected-account are required when --port is not 9223/9224/9225');
  }
  const args = [
    API_PUBLISH_SCRIPT,
    '--account', account,
    '--expected-account', expectedAccount,
    '--book', path.basename(bookDir),
    '--book-id', bookId,
    '--ai-use', options.aiUse || 'yes',
    '--from', String(from),
    '--to', String(to)
  ];
  console.log(`PUBLISH_API ${account} ${expectedAccount} ${path.basename(bookDir)}`);
  execFileSync('node', args, { stdio: 'inherit' });
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (!command || command === '-h' || command === '--help') {
    usage();
    return;
  }
  const root = path.resolve(argValue(args, '--root', DEFAULT_ROOT));
  const bookDir = resolveBookDir(argValue(args, '--book'), root);
  const from = Number(argValue(args, '--from', '1'));
  const to = Number(argValue(args, '--to', String(Number.MAX_SAFE_INTEGER)));
  const port = Number(argValue(args, '--port', String(DEFAULT_PORT)));
  const bookId = argValue(args, '--book-id', '');
  const aiUse = argValue(args, '--ai-use', 'yes');
  const limit = Number(argValue(args, '--limit', '0'));
  const account = argValue(args, '--account', '');
  const expectedAccount = argValue(args, '--expected-account', (PORT_ACCOUNT_MAP[port] || {}).expected || '');
  const attempts = Number(argValue(args, '--attempts', '3'));
  const href = argValue(args, '--href', '');
  const chapters = loadChapters(bookDir, from, to);
  if (!chapters.length) throw new Error(`No chapters found in ${bookDir}`);
  validateLocalChapters(chapters);

  if (command === 'scan') return commandScan(chapters);
  if (!bookId) throw new Error('--book-id is required for drafts/publish/all');
  if (command === 'drafts') return commandDrafts(bookDir, bookId, chapters, port, { expectedAccount, attempts });
  if (command === 'verify') return commandVerify(bookId, chapters, port, { expectedAccount });
  if (command === 'repair') return commandRepair(bookDir, bookId, chapters, port);
  if (command === 'repair-href') return commandRepairHref(chapters, port, href);
  if (command === 'publish') return commandPublishApi(bookDir, bookId, from, to, port, { aiUse, account, expectedAccount, limit });
  if (command === 'publish-cdp') return commandPublish(bookDir, bookId, chapters, port, { aiUse, limit });
  if (command === 'all') {
    await commandDrafts(bookDir, bookId, chapters, port, { expectedAccount, attempts });
    commandPublishApi(bookDir, bookId, from, to, port, { aiUse, account, expectedAccount });
    return;
  }
  throw new Error(`Unknown command: ${command}`);
}

main().catch(error => {
  console.error(error.message || error);
  process.exit(1);
});
