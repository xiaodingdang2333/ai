#!/usr/bin/env node

const { spawnSync } = require('node:child_process');

const BASE = process.env.SONOVEL_URL || 'http://127.0.0.1:7765';
const USER_AGENT = 'Mozilla/5.0 (compatible; novel-market-study/1.0)';
const DOWNLOAD_FORMATS = new Set(['epub', 'txt', 'html', 'pdf']);

function normalizeTitle(value) {
  return String(value || '').normalize('NFKC').toLowerCase().replace(/[\p{P}\p{S}\s]+/gu, '');
}

function decodeHtml(value) {
  return String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&#39;/gi, "'")
    .replace(/&quot;/gi, '"')
    .replace(/<[^>]+>/g, '')
    .trim();
}

function responseCookies(response) {
  const values = typeof response.headers.getSetCookie === 'function'
    ? response.headers.getSetCookie()
    : [response.headers.get('set-cookie')].filter(Boolean);
  return values.map((value) => value.split(';', 1)[0]).join('; ');
}

async function searchShuhaige(title) {
  try {
    const home = await fetch('https://www.shuhaige.net/', {
      headers: { 'User-Agent': USER_AGENT }, signal: AbortSignal.timeout(8000),
    });
    const cookie = responseCookies(home);
    await home.text();
    const body = new URLSearchParams({ searchkey: title, searchtype: 'all' });
    const response = await fetch('https://www.shuhaige.net/search.html', {
      method: 'POST', body, signal: AbortSignal.timeout(10_000),
      headers: {
        'User-Agent': USER_AGENT,
        Referer: 'https://www.shuhaige.net/',
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        ...(cookie ? { Cookie: cookie } : {}),
      },
    });
    if (!response.ok) return [];
    const html = await response.text();
    const results = [];
    const pattern = /<h3[^>]*>\s*<a[^>]+href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>\s*<\/h3>/gi;
    for (const match of html.matchAll(pattern)) {
      const bookName = decodeHtml(match[2]);
      if (!bookName) continue;
      results.push({
        bookName,
        author: '',
        sourceId: 2,
        latestChapter: '',
        url: new URL(match[1], 'https://www.shuhaige.net/').toString(),
      });
    }
    return results;
  } catch (_) {
    return [];
  }
}

async function getJson(path) {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${path}`);
  return response.json();
}

function localBooks(payload) {
  return (payload.data || []).filter((item) => item
    && typeof item.name === 'string'
    && !item.name.startsWith('.'));
}

async function search(keyword) {
  const payload = await getJson(`/search/aggregated?kw=${encodeURIComponent(keyword)}`);
  return Array.isArray(payload.data) ? payload.data : [];
}

function printResults(items) {
  const rows = items.map((item, index) => ({
    index: index + 1,
    bookName: item.bookName,
    author: item.author,
    sourceId: item.sourceId,
    latestChapter: item.latestChapter,
    url: item.url,
  }));
  process.stdout.write(`${JSON.stringify(rows, null, 2)}\n`);
}

function normalizeFormat(value) {
  const format = String(value || '').trim().toLowerCase();
  if (format && !DOWNLOAD_FORMATS.has(format)) {
    throw new Error(`Unsupported format: ${format}`);
  }
  return format;
}

async function downloadSelected(selected, format = '') {
  if (!selected || !selected.bookName || !selected.url || selected.sourceId === undefined || selected.sourceId === null) {
    throw new Error('Selected result is incomplete');
  }
  const outputFormat = normalizeFormat(format);
  const before = await getJson('/local-books');
  const beforeFiles = new Map(localBooks(before).map((item) => [item.name, item]));
  const query = new URLSearchParams({
    bookName: selected.bookName,
    author: selected.author || '',
    sourceId: String(selected.sourceId),
    latestChapter: selected.latestChapter || '',
    url: selected.url,
  });
  if (outputFormat) query.set('format', outputFormat);
  const response = await fetch(`${BASE}/book-fetch?${query}`);
  // Some builds return HTTP 500 after a non-fatal cover lookup error while the
  // background chapter download continues. The completed local file is the
  // authoritative success signal.
  if (!response.ok && response.status !== 500) {
    throw new Error(`${response.status} ${response.statusText}: download failed`);
  }
  await response.text();

  let created = null;
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const after = await getJson('/local-books');
    const files = localBooks(after).sort((a, b) => b.timestamp - a.timestamp);
    created = files.find((item) => !beforeFiles.has(item.name))
      || files.find((item) => {
        const prior = beforeFiles.get(item.name);
        return prior && (item.timestamp > prior.timestamp || item.size !== prior.size);
      })
      || null;
    if (created) break;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  if (!created) throw new Error('download did not produce a local file within 10 minutes');
  process.stdout.write(`${JSON.stringify({ selected, file: created || null, format: outputFormat || 'epub' }, null, 2)}\n`);
}

async function download(title, author = '', format = '') {
  const items = await search(title);
  const exact = items.filter((item) => item.bookName === title);
  const candidates = exact.length ? exact : items;
  const selected = candidates.find((item) => !author || item.author === author);
  if (!selected) {
    printResults(items);
    throw new Error(`No downloadable result for: ${title}${author ? ` / ${author}` : ''}`);
  }

  await downloadSelected(selected, format);
}

async function packet(title, author = '') {
  const wanted = normalizeTitle(title);
  const quickItems = await searchShuhaige(title);
  const quickExact = quickItems.filter((item) => normalizeTitle(item.bookName) === wanted);
  const items = quickExact.length ? quickItems : await search(title);
  const exact = items.filter((item) => normalizeTitle(item.bookName) === wanted);
  const selected = exact.find((item) => author && normalizeTitle(item.author) === normalizeTitle(author))
    || exact[0];
  if (!selected) {
    printResults(items);
    throw new Error(`No exact source result for: ${title}`);
  }
  const result = spawnSync('/home/admin/ai/scripts/fetch-novel-study-packet.py', [
    selected.url,
    '--title', title,
    '--author', author || selected.author || '未知',
    '--front', process.env.NOVEL_PACKET_FRONT || '5',
    '--middle', process.env.NOVEL_PACKET_MIDDLE || '2',
    '--tail', process.env.NOVEL_PACKET_TAIL || '2',
    '--concurrency', process.env.NOVEL_PACKET_CHAPTER_CONCURRENCY || '6',
  ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  if (result.status !== 0) throw new Error((result.stderr || result.stdout).trim());
  process.stdout.write(result.stdout);
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (command === 'search' && args[0]) {
    printResults(await search(args.join(' ')));
    return;
  }
  if (command === 'download' && args[0]) {
    await download(args[0], args[1] || '', args[2] || '');
    return;
  }
  if (command === 'download-url' && args[0] && args[3]) {
    await downloadSelected({
      bookName: args[0],
      author: args[1] || '',
      sourceId: args[2],
      url: args[3],
      latestChapter: '',
    }, args[4] || '');
    return;
  }
  if (command === 'packet' && args[0]) {
    await packet(args[0], args[1] || '');
    return;
  }
  if (command === 'list') {
    const payload = await getJson('/local-books');
    process.stdout.write(`${JSON.stringify(localBooks(payload), null, 2)}\n`);
    return;
  }
  throw new Error('Usage: sonovel-client.js search <keyword> | packet <exact-title> [official-author] | download <exact-title> [author] [format] | download-url <title> <author> <source-id> <url> [format] | list');
}

main().catch((error) => {
  process.stderr.write(`sonovel-client: ${error.message}\n`);
  process.exitCode = 1;
});
