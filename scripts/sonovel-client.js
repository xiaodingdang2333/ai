#!/usr/bin/env node

const { spawnSync } = require('node:child_process');

const BASE = process.env.SONOVEL_URL || 'http://127.0.0.1:7765';

async function getJson(path) {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${path}`);
  return response.json();
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

async function download(title, author = '') {
  const items = await search(title);
  const exact = items.filter((item) => item.bookName === title);
  const candidates = exact.length ? exact : items;
  const selected = candidates.find((item) => !author || item.author === author);
  if (!selected) {
    printResults(items);
    throw new Error(`No downloadable result for: ${title}${author ? ` / ${author}` : ''}`);
  }

  const before = await getJson('/local-books');
  const beforeNames = new Set((before.data || []).map((item) => item.name));
  const query = new URLSearchParams(selected).toString();
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
    const files = (after.data || []).sort((a, b) => b.timestamp - a.timestamp);
    created = files.find((item) => !beforeNames.has(item.name)) || null;
    if (created) break;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  if (!created) throw new Error('download did not produce a local file within 10 minutes');
  process.stdout.write(`${JSON.stringify({ selected, file: created || null }, null, 2)}\n`);
}

async function packet(title, author = '') {
  const items = await search(title);
  const selected = items.find((item) => item.bookName === title && Number(item.sourceId) === 6)
    || items.find((item) => item.bookName === title);
  if (!selected) {
    printResults(items);
    throw new Error(`No exact source result for: ${title}`);
  }
  if (Number(selected.sourceId) !== 6) {
    throw new Error(`Selective packet currently supports source 6; found source ${selected.sourceId}`);
  }
  const result = spawnSync('/home/admin/ai/scripts/fetch-novel-study-packet.py', [
    selected.url,
    '--title', title,
    '--author', author || selected.author || '未知',
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
    await download(args[0], args[1] || '');
    return;
  }
  if (command === 'packet' && args[0]) {
    await packet(args[0], args[1] || '');
    return;
  }
  if (command === 'list') {
    const payload = await getJson('/local-books');
    process.stdout.write(`${JSON.stringify(payload.data || [], null, 2)}\n`);
    return;
  }
  throw new Error('Usage: sonovel-client.js search <keyword> | packet <exact-title> [official-author] | download <exact-title> [author] | list');
}

main().catch((error) => {
  process.stderr.write(`sonovel-client: ${error.message}\n`);
  process.exitCode = 1;
});
