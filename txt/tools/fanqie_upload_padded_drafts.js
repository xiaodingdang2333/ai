const CDP = require('chrome-remote-interface');
const fs = require('fs');
const path = require('path');

const BOOK_ID = '7642178186335226942';
const BOOK_TITLE_ENCODED = '%E5%BF%AB%E7%A9%BF%EF%BC%9A%E6%81%B6%E6%AF%92%E5%A5%B3%E9%85%8D%E8%A7%89%E9%86%92%E5%90%8E%EF%BC%8C%E5%85%A8%E5%91%98%E8%B7%AA%E6%B1%82';

function argValue(args, name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (!args[index + 1]) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function loadChapters(jsonl, from, to) {
  return fs.readFileSync(jsonl, 'utf8')
    .trim()
    .split(/\r?\n/)
    .map(line => JSON.parse(line))
    .filter(chapter => chapter.no >= from && chapter.no <= to);
}

function chapterNo(no) {
  return String(no).padStart(3, '0');
}

function shortTitle(title) {
  const index = title.indexOf(' ');
  return index >= 0 ? title.slice(index + 1).trim() : title.trim();
}

async function waitFor(Runtime, expression, timeoutMs, label) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const result = await Runtime.evaluate({ expression, returnByValue: true });
    if (result.result.value) return result.result.value;
    await sleep(1000);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function clickAndReplace(Input, point, text) {
  await Input.dispatchMouseEvent({ type: 'mouseMoved', x: point.x, y: point.y });
  await Input.dispatchMouseEvent({ type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await Input.dispatchMouseEvent({ type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await sleep(200);
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'Control', code: 'ControlLeft', windowsVirtualKeyCode: 17, modifiers: 0 });
  await Input.insertText({ text });
  await sleep(300);
  await Input.dispatchKeyEvent({ type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
  await Input.dispatchKeyEvent({ type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
}

async function draftBox(Runtime, Page) {
  const url = `https://fanqienovel.com/main/writer/chapter-manage/${BOOK_ID}&${BOOK_TITLE_ENCODED}?type=2`;
  await Page.navigate({ url });
  await sleep(5000);
  return url;
}

async function getNewDraftHref(Runtime) {
  return waitFor(
    Runtime,
    `[...document.querySelectorAll('a')].find(a => (a.innerText || a.textContent || '').trim() === '\\u65b0\\u5efa\\u8349\\u7a3f')?.href`,
    15000,
    'new draft link'
  );
}

async function fillDraft(Runtime, Input, chapter) {
  const no = chapterNo(chapter.no);
  const title = shortTitle(chapter.title);
  const body = chapter.body.trim() + '\n';

  await waitFor(Runtime, `!!document.querySelector('.ProseMirror,[contenteditable="true"]')`, 30000, 'editor');
  await sleep(1000);

  const rects = await Runtime.evaluate({
    expression: `(() => [...document.querySelectorAll('input,textarea')]
      .filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length))
      .slice(0, 2)
      .map(e => {
        const r = e.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2, value: e.value, placeholder: e.placeholder };
      }))()`,
    returnByValue: true
  });
  const [numberPoint, titlePoint] = rects.result.value;
  if (!numberPoint || !titlePoint) throw new Error('Cannot find number/title inputs');

  await clickAndReplace(Input, numberPoint, no);
  await clickAndReplace(Input, titlePoint, title);

  const values = await Runtime.evaluate({
    expression: `(() => [...document.querySelectorAll('input,textarea')]
      .filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length))
      .slice(0, 2)
      .map(e => e.value))()`,
    returnByValue: true
  });
  if (values.result.value[0] !== no || values.result.value[1] !== title) {
    throw new Error(`Input verification failed: ${JSON.stringify(values.result.value)}`);
  }

  const insert = await Runtime.evaluate({
    expression: `(() => {
      const editor = document.querySelector('.ProseMirror,[contenteditable="true"]');
      editor.focus();
      document.execCommand('selectAll', false, null);
      const ok = document.execCommand('insertText', false, ${JSON.stringify(body)});
      editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '' }));
      editor.dispatchEvent(new Event('change', { bubbles: true }));
      return { ok, chars: editor.innerText.trim().length };
    })()`,
    returnByValue: true
  });
  if (!insert.result.value.ok || insert.result.value.chars < 1000) {
    throw new Error(`Body insert failed: ${JSON.stringify(insert.result.value)}`);
  }

  const clicked = await Runtime.evaluate({
    expression: `(() => {
      const button = [...document.querySelectorAll('button,[role="button"]')]
        .find(el => (el.innerText || el.textContent || '').includes('\\u5b58\\u8349\\u7a3f'));
      if (!button) return false;
      button.click();
      return true;
    })()`,
    returnByValue: true
  });
  if (!clicked.result.value) throw new Error('Save draft button not found');

  await waitFor(
    Runtime,
    `document.body.innerText.includes('\\u5df2\\u4fdd\\u5b58')`,
    30000,
    'saved status'
  );
  await sleep(3000);
  return { no, title };
}

async function verifyDraft(Runtime, expected) {
  const title = `第${expected.no}章 ${expected.title}`;
  const started = Date.now();
  while (Date.now() - started < 20000) {
    const text = await Runtime.evaluate({
      expression: `document.body ? document.body.innerText : ''`,
      returnByValue: true
    });
    const value = text.result.value || '';
    if (value.includes(title)) return;
    await sleep(1000);
  }
  throw new Error(`Draft title not found after save: ${title}`);
}

async function main() {
  const args = process.argv.slice(2);
  const port = Number(argValue(args, '--port', '9223'));
  const jsonl = path.resolve(argValue(args, '--jsonl', path.join(__dirname, '..', 'output', 'fanqie-upload', 'kuai-chapters.jsonl')));
  const from = Number(argValue(args, '--from', '20'));
  const to = Number(argValue(args, '--to', '30'));
  const chapters = loadChapters(jsonl, from, to);
  if (!chapters.length) throw new Error(`No chapters in ${jsonl} for ${from}-${to}`);

  const target = (await CDP.List({ port })).find(item => item.type === 'page' && /fanqienovel\.com/.test(item.url));
  if (!target) throw new Error(`Fanqie page not found on CDP port ${port}`);
  const client = await CDP({ port, target });
  const { Runtime, Page, Input } = client;
  await Page.enable();

  try {
    for (const chapter of chapters) {
      const expected = { no: chapterNo(chapter.no), title: shortTitle(chapter.title) };
      console.log(`\nCreating 第${expected.no}章 ${expected.title}`);
      await draftBox(Runtime, Page);
      const href = await getNewDraftHref(Runtime);
      await Page.navigate({ url: href });
      const filled = await fillDraft(Runtime, Input, chapter);
      await draftBox(Runtime, Page);
      await verifyDraft(Runtime, filled);
      console.log(`Saved 第${filled.no}章 ${filled.title}`);
    }

    await draftBox(Runtime, Page);
    const summary = await Runtime.evaluate({
      expression: `document.body.innerText.slice(0, 8000)`,
      returnByValue: true
    });
    console.log(`\nFINAL DRAFT BOX\n${summary.result.value}`);
  } finally {
    await client.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
