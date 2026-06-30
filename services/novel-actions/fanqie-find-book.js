#!/usr/bin/env node
const CDP = require('chrome-remote-interface');

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i < 0 || !process.argv[i + 1]) throw new Error(`Missing ${name}`);
  return process.argv[i + 1];
}

const port = Number(arg('--port'));
const expected = arg('--title');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const client = await CDP({ port });
  try {
    const { Page, Runtime } = client;
    await Page.enable();
    await Page.navigate({ url: 'https://fanqienovel.com/main/writer/book-manage' });
    await sleep(5000);
    const result = await Runtime.evaluate({
      returnByValue: true,
      expression: `(() => [...document.querySelectorAll('a[href*="/chapter-manage/"]')]
        .map(a => {
          const href = a.href || '';
          const match = href.match(/chapter-manage\/(\d+)&([^?]+)/);
          if (!match) return null;
          let title = '';
          try { title = decodeURIComponent(match[2]); } catch (_) { title = match[2]; }
          return { book_id: match[1], title, href };
        }).filter(Boolean))()`
    });
    const rows = result.result.value || [];
    const exact = rows.filter(row => row.title === expected);
    if (exact.length !== 1) {
      console.log(JSON.stringify({ book_id: '', title: expected, candidates: rows }));
      process.exit(exact.length ? 3 : 2);
    }
    console.log(JSON.stringify(exact[0]));
  } finally {
    await client.close();
  }
})().catch(error => { console.error(error.stack || error); process.exit(1); });
