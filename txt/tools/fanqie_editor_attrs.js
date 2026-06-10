const CDP = require('chrome-remote-interface');
(async () => {
  const c = await CDP({ port: 9223 });
  const r = await c.Runtime.evaluate({
    expression: `(() => {
      const e = document.querySelector('.ProseMirror');
      const box = e.getBoundingClientRect();
      return {
        attrs: [...e.attributes].map(a => [a.name, a.value]),
        html: e.outerHTML.slice(0, 800),
        active: document.activeElement === e,
        box: { x: box.x, y: box.y, w: box.width, h: box.height }
      };
    })()`,
    returnByValue: true
  });
  console.log(JSON.stringify(r.result.value, null, 2));
  await c.close();
})();
