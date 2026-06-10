const CDP = require('chrome-remote-interface');

(async () => {
  const client = await CDP({ port: 9223 });
  const { Runtime } = client;
  const result = await Runtime.evaluate({
    expression: `Array.from(document.querySelectorAll('a,button,[role=button],div,span')).map((el, i) => {
      const r = el.getBoundingClientRect();
      return {
        i,
        tag: el.tagName,
        text: (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
        cls: String(el.className || '').slice(0, 80),
        href: el.href || '',
        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)
      };
    }).filter(x => x.text && x.w > 0 && x.h > 0).slice(0, 220)`,
    returnByValue: true
  });
  console.log(JSON.stringify(result.result.value, null, 2));
  await client.close();
})().catch(err => {
  console.error(err);
  process.exit(1);
});
