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
    const result = await Runtime.evaluate({
      returnByValue: true,
      awaitPromise: true,
      expression: `(async () => {
        const all = [];
        for (let pageIndex = 0; pageIndex < 10; pageIndex++) {
          const endpoint = '/api/author/chapter/draft_list/v1?book_id=${bookId}&page_index=' + pageIndex + '&page_count=80';
          const response = await fetch(endpoint, {credentials: 'include'});
          const json = await response.json();
          if (!json || json.code !== 0) return {code: json && json.code, message: json && json.message, rows: all};
          const items = (json.data && json.data.draft_list) || [];
          all.push(...items);
          const total = Number(json.data && json.data.total_count || 0);
          if (!items.length || all.length >= total) break;
        }
        return {code: 0, rows: all};
      })()`
    });
    const payload = result.result.value || {};
    if (payload.code !== 0) throw new Error(`草稿列表API失败：${JSON.stringify(payload)}`);
    const rows = (payload.rows || []).map(row => {
      const title = row.title || row.chapter_title || '';
      const match = title.match(/第\s*0*(\d+)\s*章/);
      return {
        no: match ? Number(match[1]) : 0,
        title,
        words: Number(row.word_number || row.word_count || row.words || 0),
        item_id: String(row.item_id || row.id || ''),
      };
    }).filter(row => row.no).sort((a, b) => a.no - b.no);
    console.log(JSON.stringify({ total: rows.length, rows }));
  } finally {
    await client.close();
  }
})().catch(error => { console.error(error.stack || error); process.exit(1); });
