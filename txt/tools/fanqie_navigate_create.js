const CDP = require('chrome-remote-interface');
const fs = require('fs');

(async () => {
  const client = await CDP({ port: 9223 });
  const { Page, Runtime, Log } = client;
  await Page.enable();
  await Log.enable();
  const logs = [];
  Log.entryAdded(({ entry }) => logs.push(entry));
  const hrefResult = await Runtime.evaluate({
    expression: `document.querySelector('a[href*="/publish/"]')?.href`,
    returnByValue: true
  });
  const href = hrefResult.result.value;
  if (!href) throw new Error('publish href not found');
  await Runtime.evaluate({ expression: `location.href = ${JSON.stringify(href)}` });
  await new Promise(r => setTimeout(r, 15000));
  const png = await Page.captureScreenshot({ format: 'png', captureBeyondViewport: true });
  fs.writeFileSync('output/fanqie-upload/create-route.png', Buffer.from(png.data, 'base64'));
  const page = await Runtime.evaluate({
    expression: `({
      url: location.href,
      title: document.title,
      text: document.body.innerText.slice(0, 3000),
      html: document.body.innerHTML.slice(0, 1000),
      scripts: [...document.scripts].slice(-10).map(s => s.src || s.textContent.slice(0,80)),
      resources: performance.getEntriesByType('resource').slice(-30).map(r => ({name:r.name, type:r.initiatorType, dur:Math.round(r.duration)}))
    })`,
    returnByValue: true
  });
  console.log(JSON.stringify({ href, page: page.result.value, logs: logs.slice(-20) }, null, 2));
  await client.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
