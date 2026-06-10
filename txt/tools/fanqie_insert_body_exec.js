const CDP = require('chrome-remote-interface');
const fs = require('fs');

const file = process.argv[2];
const raw = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
const body = raw.replace(/^#\s*第\d+章\s+.+\n+/, '').trim() + '\n';

(async () => {
  const c = await CDP({ port: 9223 });
  const { Runtime, Page } = c;
  await Page.enable();
  const r = await Runtime.evaluate({
    expression: `(() => {
      const editor = document.querySelector('.ProseMirror');
      editor.focus();
      document.execCommand('selectAll', false, null);
      const ok = document.execCommand('insertText', false, ${JSON.stringify(body)});
      editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: '' }));
      return { ok, text: editor.innerText.slice(0,300), len: editor.innerText.length, html: editor.innerHTML.slice(0,500), active: document.activeElement === editor };
    })()`,
    returnByValue: true
  });
  await new Promise(resolve => setTimeout(resolve, 5000));
  const state = await Runtime.evaluate({
    expression: `({
      text: document.body.innerText.slice(0, 1200),
      editorText: document.querySelector('.ProseMirror')?.innerText.slice(0,300),
      editorChars: document.querySelector('.ProseMirror')?.innerText.length
    })`,
    returnByValue: true
  });
  const png = await Page.captureScreenshot({ format: 'png', captureBeyondViewport: true });
  fs.writeFileSync('output/fanqie-upload/chapter-body-inserted.png', Buffer.from(png.data, 'base64'));
  console.log(JSON.stringify({ insert: r.result.value, state: state.result.value, sourceChars: body.length }, null, 2));
  await c.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
