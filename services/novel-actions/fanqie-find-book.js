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
    const deadline = Date.now() + 60000;
    let refreshed = false;
    while (Date.now() < deadline) {
      const ready = await Runtime.evaluate({
        returnByValue: true,
        expression: `document.querySelectorAll('a[href*="/chapter-manage/"]').length`
      });
      if (Number(ready.result.value || 0) > 0) break;
      if (!refreshed && Date.now() > deadline - 30000) {
        await Page.reload({ignoreCache: true});
        refreshed = true;
      }
      await sleep(1000);
    }
    const result = await Runtime.evaluate({
      returnByValue: true,
      expression: `(() => [...document.querySelectorAll('a[href*="/chapter-manage/"]')]
        .map(a => {
          const href = a.href || '';
          const tail = href.split('/chapter-manage/')[1] || '';
          const amp = tail.indexOf('&');
          if (amp < 1) return null;
          const bookId = tail.slice(0, amp);
          if ([...bookId].some(ch => ch < '0' || ch > '9')) return null;
          const encodedTitle = tail.slice(amp + 1).split('?')[0];
          let title = '';
          try { title = decodeURIComponent(encodedTitle); } catch (_) { title = encodedTitle; }
          return { book_id: bookId, title, href };
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
