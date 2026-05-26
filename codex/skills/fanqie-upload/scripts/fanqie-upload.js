#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

function loadCdp() {
  try {
    return require('chrome-remote-interface');
  } catch (_) {
    return require(path.join('F:', 'ai', 'txt', 'node_modules', 'chrome-remote-interface'));
  }
}

const CDP = loadCdp();
const DEFAULT_ROOT = path.join('F:', 'ai', 'txt');
const DEFAULT_PORT = 9223;
const U = {
  newDraft: '\\u65b0\\u5efa\\u8349\\u7a3f',
  saveDraft: '\\u5b58\\u8349\\u7a3f',
  saved: '\\u5df2\\u4fdd\\u5b58',
  next: '\\u4e0b\\u4e00\\u6b65',
  submit: '\\u63d0\\u4ea4',
  basic: '\\u4ec5\\u57fa\\u7840\\u68c0\\u6d4b',
  yes: '\\u662f',
  confirmPublish: '\\u786e\\u8ba4\\u53d1\\u5e03',
  dailyLimit: '\\u63d0\\u4ea4\\u5b57\\u6570\\u8d85\\u51fa\\u6bcf\\u65e5\\u4e0a\\u9650',
  published: '\\u5df2\\u53d1\\u5e03',
  auditing: '\\u5ba1\\u6838\\u4e2d'
};

function usage() {
  console.log(`Usage:
  node fanqie-upload.js scan --book <book-dir-or-name> [--root F:\\ai\\txt] [--from N] [--to N]
  node fanqie-upload.js drafts --book <book-dir-or-name> --book-id <id> [--port 9223] [--from N] [--to N]
  node fanqie-upload.js publish --book <book-dir-or-name> --book-id <id> [--port 9223] [--from N] [--to N]
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
    shortTitle: title.replace(/^第\s*0*\d+\s*章\s*/, '').trim(),
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

function draftBoxUrl(bookId, bookDir, type = 2) {
  return `https://fanqienovel.com/main/writer/chapter-manage/${bookId}&${encodeURIComponent(path.basename(bookDir))}?type=${type}`;
}

async function connect(port) {
  const targets = await CDP.List({ port });
  const target = targets.find(item => item.type === 'page' && item.url.includes('fanqienovel.com')) || targets.find(item => item.type === 'page');
  if (!target) throw new Error(`No Chrome page found on CDP port ${port}`);
  const client = await CDP({ port, target });
  await client.Runtime.enable();
  await client.Page.enable();
  return client;
}

async function evalv(Runtime, expression) {
  const result = await Runtime.evaluate({ expression, returnByValue: true, awaitPromise: true });
  return result.result.value;
}

async function navigate(Page, url, waitMs = 4500) {
  await Page.navigate({ url });
  await sleep(waitMs);
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

async function pageText(Runtime, limit = 8000) {
  return await evalv(Runtime, `document.body ? document.body.innerText.slice(0, ${limit}) : ''`);
}

async function getVisibleChapterState(Runtime) {
  const text = await pageText(Runtime, 12000);
  return text;
}

async function createDraft(client, chapter) {
  const { Runtime, Input } = client;
  await waitFor(Runtime, `!!document.querySelector('.ProseMirror,[contenteditable="true"]')`, 30000, 'chapter editor');
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
  const values = await evalv(Runtime, `(() => [...document.querySelectorAll('input,textarea')]
    .filter(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
    .slice(0, 2)
    .map(el => el.value))()`);
  if (values[0] !== chapter.padded || values[1] !== chapter.shortTitle) {
    throw new Error(`Input verification failed: ${JSON.stringify(values)}`);
  }
  const inserted = await evalv(Runtime, `(() => {
    const editor = document.querySelector('.ProseMirror,[contenteditable="true"]');
    editor.focus();
    document.execCommand('selectAll', false, null);
    const ok = document.execCommand('insertText', false, ${JSON.stringify(chapter.body.trim() + '\n')});
    editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '' }));
    editor.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok, chars: editor.innerText.trim().length };
  })()`);
  if (!inserted.ok || inserted.chars < Math.min(500, chapter.bodyChars)) {
    throw new Error(`Body insert failed: ${JSON.stringify(inserted)}`);
  }
  await waitFor(Runtime, `([...document.querySelectorAll('button,[role="button"],a')]
    .some(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
      && !el.disabled
      && ((el.innerText || el.textContent || '').trim()).includes('${U.saveDraft}')))`, 30000, 'save draft button');
  if (!await clickText(Runtime, Input, U.saveDraft, { wait: 2500 })) throw new Error('Save draft button not found');
  await waitFor(Runtime, `document.body.innerText.includes('${U.saved}')`, 30000, 'saved status');
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

async function commandDrafts(bookDir, bookId, chapters, port) {
  const client = await connect(port);
  const { Runtime, Page } = client;
  try {
    for (const chapter of chapters) {
      const expected = fullChapterTitle(chapter);
      await navigate(Page, draftBoxUrl(bookId, bookDir, 2));
      const draftText = await getVisibleChapterState(Runtime);
      await navigate(Page, draftBoxUrl(bookId, bookDir, 1));
      const publishedText = await getVisibleChapterState(Runtime);
      if (draftText.includes(expected) || publishedText.includes(expected)) {
        console.log(`SKIP ${expected}`);
        continue;
      }
      await navigate(Page, draftBoxUrl(bookId, bookDir, 2));
      const href = await waitFor(Runtime, `[...document.querySelectorAll('a')].find(a => (a.innerText || a.textContent || '').trim().includes('${U.newDraft}'))?.href`, 15000, 'new draft link');
      await navigate(Page, href);
      await createDraft(client, chapter);
      console.log(`DRAFT ${expected}`);
    }
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

async function publishOne(client, href, chapter) {
  const { Runtime, Input, Page } = client;
  await navigate(Page, href);
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
  await sleep(2500);
  for (let i = 0; i < 20; i++) {
    if (await hasText(Runtime, U.basic) || await hasText(Runtime, U.confirmPublish)) break;
    await clickText(Runtime, Input, U.submit, { wait: 2000 });
  }
  if (await hasText(Runtime, U.basic)) {
    if (!await clickText(Runtime, Input, U.basic, { wait: 3500 })) throw new Error(`Cannot click basic check for ${fullChapterTitle(chapter)}`);
  }
  await waitFor(Runtime, `document.body.innerText.includes('${U.confirmPublish}')`, 15000, 'confirm publish dialog');
  await clickText(Runtime, Input, U.yes, { label: true, maxX: 1000, wait: 700 });
  for (let i = 0; i < 5; i++) {
    await clickText(Runtime, Input, U.confirmPublish, { wait: 5000 });
    if (await hasText(Runtime, U.dailyLimit)) return { status: 'daily-limit' };
    const url = await evalv(Runtime, 'location.href');
    if (url.includes('chapter-manage')) return { status: 'submitted' };
  }
  if (await hasText(Runtime, U.dailyLimit)) return { status: 'daily-limit' };
  throw new Error(`Publish confirmation did not complete for ${fullChapterTitle(chapter)}`);
}

async function commandPublish(bookDir, bookId, chapters, port) {
  const wanted = new Map(chapters.map(chapter => [chapter.padded, chapter]));
  const client = await connect(port);
  const { Runtime, Page } = client;
  try {
    await navigate(Page, draftBoxUrl(bookId, bookDir, 2));
    const links = (await draftLinks(Runtime)).filter(item => wanted.has(String(item.no).padStart(3, '0')));
    if (!links.length) {
      console.log('No matching drafts found.');
      return;
    }
    for (const link of links) {
      const chapter = wanted.get(String(link.no).padStart(3, '0'));
      const result = await publishOne(client, link.href, chapter);
      if (result.status === 'daily-limit') {
        console.log(`DAILY_LIMIT at ${fullChapterTitle(chapter)}`);
        const remaining = links.filter(item => item.no >= link.no).map(item => String(item.no).padStart(3, '0')).join(', ');
        console.log(`REMAINING ${remaining}`);
        return;
      }
      console.log(`PUBLISH ${fullChapterTitle(chapter)}`);
    }
  } finally {
    await client.close();
  }
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
  const chapters = loadChapters(bookDir, from, to);
  if (!chapters.length) throw new Error(`No chapters found in ${bookDir}`);

  if (command === 'scan') return commandScan(chapters);
  if (!bookId) throw new Error('--book-id is required for drafts/publish/all');
  if (command === 'drafts') return commandDrafts(bookDir, bookId, chapters, port);
  if (command === 'publish') return commandPublish(bookDir, bookId, chapters, port);
  if (command === 'all') {
    await commandDrafts(bookDir, bookId, chapters, port);
    await commandPublish(bookDir, bookId, chapters, port);
    return;
  }
  throw new Error(`Unknown command: ${command}`);
}

main().catch(error => {
  console.error(error.message || error);
  process.exit(1);
});
