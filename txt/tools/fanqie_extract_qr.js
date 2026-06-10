const CDP = require('chrome-remote-interface');
const fs = require('fs');

(async () => {
  const client = await CDP({ port: 9223 });
  const { Runtime } = client;
  const result = await Runtime.evaluate({
    expression: `(() => {
      const imgs = [...document.images].map((img, i) => {
        const r = img.getBoundingClientRect();
        return { i, src: img.src, x:r.x, y:r.y, w:r.width, h:r.height, alt:img.alt || '' };
      });
      const canvases = [...document.querySelectorAll('canvas')].map((c, i) => {
        const r = c.getBoundingClientRect();
        let data = '';
        try { data = c.toDataURL('image/png'); } catch {}
        return { i, data, x:r.x, y:r.y, w:r.width, h:r.height };
      });
      return { imgs, canvases };
    })()`,
    returnByValue: true
  });
  const v = result.result.value;
  fs.writeFileSync('output/fanqie-upload/qr-dom.json', JSON.stringify(v, null, 2), 'utf8');
  const candidates = [
    ...v.imgs.filter(x => x.w >= 120 && x.h >= 120).map(x => ({ type: 'img', data: x.src, ...x })),
    ...v.canvases.filter(x => x.w >= 120 && x.h >= 120 && x.data).map(x => ({ type: 'canvas', src: x.data, ...x }))
  ];
  if (!candidates.length) {
    console.log(JSON.stringify(v, null, 2));
    throw new Error('No QR-sized image/canvas found');
  }
  const qr = candidates.sort((a,b) => (b.w*b.h) - (a.w*a.h))[0];
  let dataUrl = qr.src || qr.data;
  if (!dataUrl.startsWith('data:image/')) {
    console.log(JSON.stringify({ qr, note: 'QR is remote image URL' }, null, 2));
    await client.close();
    return;
  }
  const base64 = dataUrl.replace(/^data:image\/\w+;base64,/, '');
  fs.writeFileSync('output/fanqie-upload/qr-original.png', Buffer.from(base64, 'base64'));
  const html = `<!doctype html>
<meta charset="utf-8">
<title>番茄扫码登录</title>
<style>
  html,body{margin:0;height:100%;background:#fff;color:#111;font-family:sans-serif}
  body{display:grid;place-items:center}
  .wrap{text-align:center}
  img{width:min(88vmin,980px);height:min(88vmin,980px);image-rendering:pixelated}
  p{font-size:28px;margin:18px 0 0}
</style>
<div class="wrap">
  <img src="qr-original.png" alt="番茄扫码登录二维码">
  <p>打开番茄小说或番茄作家助手扫码登录</p>
</div>`;
  fs.writeFileSync('output/fanqie-upload/qr-login.html', html, 'utf8');
  console.log(JSON.stringify({ saved: 'output/fanqie-upload/qr-login.html', qr }, null, 2));
  await client.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
