const CDP = require('chrome-remote-interface');
(async () => {
  const c = await CDP({ port: 9223 });
  const r = await c.Runtime.evaluate({
    expression: `(() => {
      const i = [...document.querySelectorAll('input')];
      return {
        url: location.href,
        number: i[0]?.value,
        title: i[1]?.value,
        bodyText: document.body.innerText.slice(0, 800),
        editorChars: document.querySelector('.ProseMirror')?.innerText.length
      };
    })()`,
    returnByValue: true
  });
  console.log(JSON.stringify(r.result.value, null, 2));
  await c.close();
})();
