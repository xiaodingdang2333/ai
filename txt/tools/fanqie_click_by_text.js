const CDP = require('chrome-remote-interface');
const fs = require('fs');

const text = process.argv[2] || '立即登录';
const out = process.argv[3] || 'output/fanqie-upload/after-click.png';

(async () => {
  const client = await CDP({ port: 9223 });
  const { Page, Runtime, Input } = client;
  await Page.enable();
  const found = await Runtime.evaluate({
    expression: `(() => {
      const el = [...document.querySelectorAll('button,a,div,span')]
        .find(e => (e.innerText || e.textContent || '').trim() === ${JSON.stringify(text)});
      if (!el) return null;
      el.scrollIntoView({block:'center', inline:'center'});
      const r = el.getBoundingClientRect();
      return {x:r.left + r.width / 2, y:r.top + r.height / 2, text: el.innerText || el.textContent, tag: el.tagName};
    })()`,
    returnByValue: true
  });
  const v = found.result.value;
  if (!v) throw new Error(`Text not found: ${text}`);
  await Input.dispatchMouseEvent({ type: 'mouseMoved', x: v.x, y: v.y });
  await Input.dispatchMouseEvent({ type: 'mousePressed', x: v.x, y: v.y, button: 'left', clickCount: 1 });
  await Input.dispatchMouseEvent({ type: 'mouseReleased', x: v.x, y: v.y, button: 'left', clickCount: 1 });
  await new Promise(r => setTimeout(r, 5000));
  const png = await Page.captureScreenshot({ format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(out, Buffer.from(png.data, 'base64'));
  const result = await Runtime.evaluate({
    expression: `({title: document.title, url: location.href, text: document.body.innerText.slice(0, 2500)})`,
    returnByValue: true
  });
  console.log(JSON.stringify({ clicked: v, page: result.result.value }, null, 2));
  await client.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
