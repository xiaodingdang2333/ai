const CDP = require('chrome-remote-interface');
const fs = require('fs');
const path = require('path');
const { loadChapters, resolveBookDir } = require('./fanqie_chapters');

function usage() {
  console.log(`Usage:
  node tools/fanqie_fill_from_export.js --chapter <no> [--book <book-dir-or-name>] [--jsonl output/fanqie-upload/chapters.jsonl] [--port 9223] [--save-draft]

This fills the currently open Fanqie chapter editor page.
By default it does not click save or publish.

If --book is provided, the chapter is read directly from <book-dir-or-name>/正文/*.md.
If --book is omitted, the script reads from --jsonl.
`);
}

function argValue(args, name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (!args[index + 1]) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

function hasFlag(args, name) {
  return args.includes(name);
}

function loadChapter(jsonlFile, no) {
  const rows = fs.readFileSync(jsonlFile, 'utf8')
    .split(/\r?\n/)
    .filter(Boolean)
    .map(line => JSON.parse(line));
  const chapter = rows.find(item => Number(item.no) === Number(no));
  if (!chapter) throw new Error(`Chapter ${no} not found in ${jsonlFile}`);
  return chapter;
}

function loadChapterFromBook(bookDir, no) {
  const rows = loadChapters(bookDir);
  const chapter = rows.find(item => Number(item.no) === Number(no));
  if (!chapter) throw new Error(`Chapter ${no} not found in ${bookDir}`);
  return chapter;
}

function shortTitle(title) {
  return title
    .replace(/^第\s*0*\d+\s*章\s*/, '')
    .trim();
}

async function clickSaveDraft(Runtime) {
  const result = await Runtime.evaluate({
    expression: `(() => {
      const candidates = [...document.querySelectorAll('button, [role="button"], a')]
        .filter(el => {
          const text = (el.innerText || el.textContent || '').trim();
          const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
          return visible && /保存|草稿/.test(text) && !/发布/.test(text);
        });
      const el = candidates[0];
      if (!el) return { clicked: false, reason: 'save draft button not found' };
      el.click();
      return { clicked: true, text: (el.innerText || el.textContent || '').trim() };
    })()`,
    returnByValue: true
  });
  return result.result.value;
}

async function waitForCloudSave(Runtime, timeoutMs = 20000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const result = await Runtime.evaluate({
      expression: `document.body.innerText.slice(0, 500)`,
      returnByValue: true
    });
    const text = result.result.value || '';
    if (text.includes('已保存到云端')) return { saved: true, text: '已保存到云端' };
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  return { saved: false, text: 'timed out waiting for cloud save' };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('-h') || args.includes('--help')) {
    usage();
    return;
  }

  const no = Number(argValue(args, '--chapter'));
  if (!no) throw new Error('--chapter is required');

  const bookArg = argValue(args, '--book', '');
  const jsonlFile = path.resolve(argValue(args, '--jsonl', path.join(__dirname, '..', 'output', 'fanqie-upload', 'chapters.jsonl')));
  const port = Number(argValue(args, '--port', '9223'));
  const saveDraft = hasFlag(args, '--save-draft');
  const chapter = bookArg
    ? loadChapterFromBook(resolveBookDir(bookArg), no)
    : loadChapter(jsonlFile, no);
  const chapterNo = String(chapter.no).padStart(3, '0');
  const chapterTitle = shortTitle(chapter.title);
  const body = chapter.body.trim() + '\n';

  const cdpTargets = await CDP.List({ port });
  const target = cdpTargets
    .filter(item => item.type === 'page')
    .sort((a, b) => Number(/\/publish\//.test(b.url)) - Number(/\/publish\//.test(a.url)))
    .find(item => /fanqienovel\.com/.test(item.url));
  if (!target) throw new Error(`Fanqie page not found on CDP port ${port}`);
  const client = await CDP({ port, target });
  const { Runtime, Input, Page } = client;
  await Page.enable();

  const targetsResult = await Runtime.evaluate({
    expression: `(() => {
      const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      const inputs = [...document.querySelectorAll('input, textarea')].filter(visible);
      const editor = document.querySelector('.ProseMirror,[contenteditable="true"]');
      const inputInfo = inputs.map((el, index) => ({
        index,
        tag: el.tagName,
        type: el.type || '',
        value: el.value || '',
        placeholder: el.placeholder || '',
        width: Math.round(el.getBoundingClientRect().width),
        top: Math.round(el.getBoundingClientRect().top)
      }));
      const numberIndex = inputInfo.find(item => item.width > 30 && item.width < 140 && !/标题|名称|title/i.test(item.placeholder))?.index ?? 0;
      const titleIndex = inputInfo.find(item => /标题|名称|title/i.test(item.placeholder))?.index
        ?? inputInfo.find(item => item.index !== numberIndex && item.width >= 140)?.index
        ?? 1;
      return {
        url: location.href,
        title: document.title,
        inputs: inputInfo,
        numberIndex,
        titleIndex,
        hasEditor: !!editor
      };
    })()`,
    returnByValue: true
  });
  const targets = targetsResult.result.value;
  if (!targets.hasEditor) throw new Error(`Editor not found on current page: ${JSON.stringify(targets, null, 2)}`);

  const fillResult = await Runtime.evaluate({
    expression: `(() => {
      const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      const inputs = [...document.querySelectorAll('input, textarea')].filter(visible);
      const setValue = (el, value) => {
        const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      };
      setValue(inputs[${targets.numberIndex}], ${JSON.stringify(chapterNo)});
      setValue(inputs[${targets.titleIndex}], ${JSON.stringify(chapterTitle)});
      const editor = document.querySelector('.ProseMirror,[contenteditable="true"]');
      editor.focus();
      return {
        number: inputs[${targets.numberIndex}]?.value,
        title: inputs[${targets.titleIndex}]?.value,
        activeEditor: document.activeElement === editor
      };
    })()`,
    returnByValue: true
  });

  const insertResult = await Runtime.evaluate({
    expression: `(() => {
      const editor = document.querySelector('.ProseMirror,[contenteditable="true"]');
      editor.focus();
      document.execCommand('selectAll', false, null);
      const ok = document.execCommand('insertText', false, ${JSON.stringify(body)});
      editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '' }));
      editor.dispatchEvent(new Event('change', { bubbles: true }));
      return {
        ok,
        activeEditor: document.activeElement === editor,
        editorPreview: editor.innerText.slice(0, 120),
        editorChars: editor.innerText.trim().length
      };
    })()`,
    returnByValue: true
  });
  await new Promise(resolve => setTimeout(resolve, 1000));

  const save = saveDraft ? await clickSaveDraft(Runtime) : { clicked: false, reason: 'save disabled by default' };
  const cloudSave = saveDraft ? await waitForCloudSave(Runtime) : { saved: false, text: 'save disabled by default' };
  await new Promise(resolve => setTimeout(resolve, 500));

  const stateResult = await Runtime.evaluate({
    expression: `(() => {
      const editor = document.querySelector('.ProseMirror,[contenteditable="true"]');
      return {
        url: location.href,
        bodyText: document.body.innerText.slice(0, 1000),
        editorPreview: editor?.innerText.slice(0, 120),
        editorChars: editor?.innerText.trim().length
      };
    })()`,
    returnByValue: true
  });

  fs.mkdirSync(path.join(__dirname, '..', 'output', 'fanqie-upload'), { recursive: true });
  const screenshot = await Page.captureScreenshot({ format: 'png', captureBeyondViewport: true });
  const screenshotFile = path.join(__dirname, '..', 'output', 'fanqie-upload', `filled-${String(chapter.no).padStart(3, '0')}.png`);
  fs.writeFileSync(screenshotFile, Buffer.from(screenshot.data, 'base64'));

  console.log(JSON.stringify({
    chapter: {
      no: chapter.no,
      title: chapterTitle,
      fullTitle: chapter.title,
      bodyChars: body.trim().length
    },
    targets,
    fill: fillResult.result.value,
    insert: insertResult.result.value,
    save,
    cloudSave,
    state: stateResult.result.value,
    screenshot: screenshotFile
  }, null, 2));

  await client.close();
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
