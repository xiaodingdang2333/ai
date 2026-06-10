const CDP = require('chrome-remote-interface');

(async () => {
  const client = await CDP({ port: 9223 });
  const { Runtime } = client;
  const result = await Runtime.evaluate({
    expression: `Array.from(document.querySelectorAll('a,button,[role=button],div,span')).map((el, i) => ({
      i,
      tag: el.tagName,
      text: (el.innerText || el.textContent || '').trim().slice(0, 80),
      cls: el.className,
      href: el.href || '',
      rect: (() => { const r = el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; })()
    })).filter(x => x.text.includes('登录') || x.text.includes('注册')).slice(0, 80)`,
    returnByValue: true
  });
  console.log(JSON.stringify(result.result.value, null, 2));
  await client.close();
})();
