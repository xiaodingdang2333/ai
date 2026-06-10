const CDP = require('chrome-remote-interface');
const fs = require('fs');

const url = process.argv[2] || 'https://fanqienovel.com/writer/zone';
const out = process.argv[3] || 'output/fanqie-upload/page.png';

(async () => {
  const client = await CDP({ port: 9223 });
  const { Page, Runtime } = client;
  await Page.enable();
  await Page.navigate({ url });
  await new Promise(r => setTimeout(r, 8000));
  const png = await Page.captureScreenshot({ format: 'png', captureBeyondViewport: true });
  fs.writeFileSync(out, Buffer.from(png.data, 'base64'));
  const result = await Runtime.evaluate({
    expression: `({
      title: document.title,
      url: location.href,
      text: document.body.innerText.slice(0, 3000)
    })`,
    returnByValue: true
  });
  console.log(JSON.stringify(result.result.value, null, 2));
  await client.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
