const CDP = require('chrome-remote-interface');
const fs = require('fs');

(async () => {
  const client = await CDP({ port: 9223 });
  const { Page, Runtime } = client;
  await Page.enable();
  await Runtime.evaluate({
    expression: `
      [...document.querySelectorAll('button,a,div,span')]
        .find(el => (el.innerText || el.textContent || '').trim() === '立即登录')
        ?.click();
    `
  });
  await new Promise(r => setTimeout(r, 3000));
  const png = await Page.captureScreenshot({ format: 'png', captureBeyondViewport: true });
  fs.writeFileSync('output/fanqie-upload/login-dialog.png', Buffer.from(png.data, 'base64'));
  const result = await Runtime.evaluate({
    expression: `({
      title: document.title,
      url: location.href,
      text: document.body.innerText.slice(0, 2000)
    })`,
    returnByValue: true
  });
  console.log(JSON.stringify(result.result.value, null, 2));
  await client.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
