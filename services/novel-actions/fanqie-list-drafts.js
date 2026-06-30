#!/usr/bin/env node
const CDP = require('chrome-remote-interface');

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i < 0 || !process.argv[i + 1]) throw new Error(`Missing ${name}`);
  return process.argv[i + 1];
}

const port = Number(arg('--port'));
const bookId = arg('--book-id');
const book = arg('--book');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const client = await CDP({ port });
  try {
    const { Page, Runtime } = client;
    await Page.enable();
    const url = `https://fanqienovel.com/main/writer/chapter-manage/${bookId}&${encodeURIComponent(book)}?type=2`;
    await Page.navigate({ url });
    await sleep(4000);
    const all = [];
    for (let page = 1; page <= 20; page++) {
      const result = await Runtime.evaluate({
        returnByValue: true,
        expression: `(() => [...document.querySelectorAll('tr')].map(row => {
          const anchor = row.querySelector('.table-title a');
          if (!anchor) return null;
          const title = (anchor.innerText || '').trim();
          const match = title.match(/第\s*0*(\d+)\s*章/);
          const cells = [...row.querySelectorAll('td')].map(td => (td.innerText || '').trim());
          return match ? { no: Number(match[1]), title, words: Number(cells[1] || 0) } : null;
        }).filter(Boolean))()`
      });
      all.push(...(result.result.value || []));
      const next = await Runtime.evaluate({
        returnByValue: true,
        expression: `(() => { const el = [...document.querySelectorAll('li')]
          .find(x => x.getAttribute('aria-label') === '下一页' && !String(x.className).includes('disabled'));
          if (!el) return false; el.click(); return true; })()`
      });
      if (!next.result.value) break;
      await sleep(1600);
    }
    const unique = new Map();
    for (const row of all) unique.set(row.no, row);
    const rows = [...unique.values()].sort((a, b) => a.no - b.no);
    console.log(JSON.stringify({ total: rows.length, rows }));
  } finally {
    await client.close();
  }
})().catch(error => { console.error(error.stack || error); process.exit(1); });
