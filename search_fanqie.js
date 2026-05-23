const CDP = require('chrome-remote-interface');

const bookNames = [
  '故人来信',
  '旧友寄书',
  '旧时书信',
  '往日来鸿',
  '故纸温言',
  '旧笺新寄'
];

async function searchBook(client, bookName) {
  const { Page, Runtime } = client;

  console.log(`\n搜索: ${bookName}`);
  await Page.navigate({ url: `https://fanqienovel.com/search?q=${encodeURIComponent(bookName)}` });
  await Page.loadEventFired();
  await new Promise(resolve => setTimeout(resolve, 2000));

  const result = await Runtime.evaluate({
    expression: `
      (() => {
        const results = document.querySelectorAll('.search-result-item, .book-item, [class*="search"], [class*="book"]');
        if (results.length === 0) {
          return { found: false, message: '未找到搜索结果' };
        }
        const titles = Array.from(results).slice(0, 3).map(el => el.textContent.trim()).filter(t => t);
        return { found: titles.length > 0, titles };
      })()
    `,
    returnByValue: true
  });

  return result.result.value;
}

(async () => {
  let client;
  try {
    client = await CDP({ port: 9222 });
    const { Page } = client;
    await Page.enable();

    const results = {};
    for (const bookName of bookNames) {
      results[bookName] = await searchBook(client, bookName);
    }

    console.log('\n=== 搜索结果汇总 ===');
    for (const [name, result] of Object.entries(results)) {
      console.log(`\n${name}:`);
      console.log(result.found ? `  ❌ 已存在相关作品` : `  ✅ 可用`);
      if (result.titles) {
        console.log(`  相关作品: ${result.titles.join(', ')}`);
      }
    }
  } catch (err) {
    console.error('错误:', err.message);
  } finally {
    if (client) await client.close();
  }
})();
