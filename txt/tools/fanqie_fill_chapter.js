const CDP = require('chrome-remote-interface');
const fs = require('fs');
const path = require('path');

const file = process.argv[2];
if (!file) {
  console.error('Usage: node tools/fanqie_fill_chapter.js <chapter.md>');
  process.exit(2);
}

function parseChapter(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8').replace(/\r\n/g, '\n');
  const base = path.basename(filePath, '.md');
  const m = base.match(/^第(\d+)章_(.+)$/);
  if (!m) throw new Error(`Unexpected chapter filename: ${base}`);
  const no = String(Number(m[1]));
  const title = m[2];
  const body = raw.replace(/^#\s*第\d+章\s+.+\n+/, '').trim() + '\n';
  return { no, title, body };
}

(async () => {
  const chapter = parseChapter(file);
  const client = await CDP({ port: 9223 });
  const { Runtime, Input, Page } = client;
  await Page.enable();

  const targets = await Runtime.evaluate({
    expression: `(() => {
      const inputs = [...document.querySelectorAll('input')];
      const editor = document.querySelector('.ProseMirror');
      return {
        number: inputs.findIndex(i => !i.placeholder && i.getBoundingClientRect().width > 40 && i.getBoundingClientRect().width < 120),
        title: inputs.findIndex(i => i.placeholder === '请输入标题'),
        editor: !!editor
      };
    })()`,
    returnByValue: true
  });
  const t = targets.result.value;
  if (t.number < 0 || t.title < 0 || !t.editor) throw new Error(`Editor targets not found: ${JSON.stringify(t)}`);

  await Runtime.evaluate({
    expression: `(() => {
      const setInput = (el, value) => {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        setter.call(el, value);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      };
      const inputs = [...document.querySelectorAll('input')];
      setInput(inputs[${t.number}], ${JSON.stringify(chapter.no)});
      setInput(inputs[${t.title}], ${JSON.stringify(chapter.title)});
      const editor = document.querySelector('.ProseMirror');
      editor.focus();
      editor.innerHTML = '<p><br></p>';
    })()`
  });

  const rect = await Runtime.evaluate({
    expression: `(() => { const r=document.querySelector('.ProseMirror').getBoundingClientRect(); return {x:r.left+20,y:r.top+20}; })()`,
    returnByValue: true
  });
  await Input.dispatchMouseEvent({ type: 'mouseMoved', x: rect.result.value.x, y: rect.result.value.y });
  await Input.dispatchMouseEvent({ type: 'mousePressed', x: rect.result.value.x, y: rect.result.value.y, button: 'left', clickCount: 1 });
  await Input.dispatchMouseEvent({ type: 'mouseReleased', x: rect.result.value.x, y: rect.result.value.y, button: 'left', clickCount: 1 });
  await Input.insertText({ text: chapter.body });
  await new Promise(r => setTimeout(r, 5000));

  const state = await Runtime.evaluate({
    expression: `({
      url: location.href,
      text: document.body.innerText.slice(0, 2000),
      number: document.querySelectorAll('input')[${t.number}]?.value,
      title: document.querySelectorAll('input')[${t.title}]?.value,
      editorText: document.querySelector('.ProseMirror')?.innerText.slice(0, 300),
      editorChars: document.querySelector('.ProseMirror')?.innerText.length
    })`,
    returnByValue: true
  });
  const png = await Page.captureScreenshot({ format: 'png', captureBeyondViewport: true });
  fs.writeFileSync('output/fanqie-upload/chapter-filled.png', Buffer.from(png.data, 'base64'));
  console.log(JSON.stringify({ chapter: { no: chapter.no, title: chapter.title, bodyChars: chapter.body.length }, state: state.result.value }, null, 2));
  await client.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
