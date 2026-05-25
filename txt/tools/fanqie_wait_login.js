const CDP = require('chrome-remote-interface');

const timeoutMs = Number(process.argv[2] || 180000);
const started = Date.now();

(async () => {
  const client = await CDP({ port: 9223 });
  const { Page, Runtime } = client;
  await Page.enable();
  while (Date.now() - started < timeoutMs) {
    const result = await Runtime.evaluate({
      expression: `({url: location.href, title: document.title, text: document.body.innerText.slice(0, 1200)})`,
      returnByValue: true
    });
    const page = result.result.value;
    if (!/login/.test(page.url) && !/(扫码登录|验证码登录|登录\/注册)/.test(page.text || '')) {
      console.log(JSON.stringify({ loggedIn: true, page }, null, 2));
      await client.close();
      return;
    }
    await new Promise(r => setTimeout(r, 3000));
  }
  const result = await Runtime.evaluate({
    expression: `({url: location.href, title: document.title, text: document.body.innerText.slice(0, 1200)})`,
    returnByValue: true
  });
  console.log(JSON.stringify({ loggedIn: false, page: result.result.value }, null, 2));
  await client.close();
  process.exit(2);
})().catch(err => {
  console.error(err);
  process.exit(1);
});
