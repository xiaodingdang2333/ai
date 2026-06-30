#!/usr/bin/env node

const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const input = process.argv[2];
if (!input) {
  process.stderr.write('Usage: sonovel-ranking-queue.js <official-ranking-books.json>\n');
  process.exit(2);
}

const books = JSON.parse(fs.readFileSync(input, 'utf8'));
if (!Array.isArray(books)) throw new Error('Input must be a JSON array');

const results = [];
for (const book of books) {
  if (!book.title) continue;
  const run = spawnSync('node', [
    '/home/admin/ai/scripts/sonovel-client.js',
    'packet',
    book.title,
    book.author || '',
  ], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  if (run.status === 0) {
    results.push({
      ...book,
      status: 'downloaded_needs_official_verification',
      packet: run.stdout.trim(),
    });
    process.stdout.write(`[downloaded] ${book.title}\n`);
  } else {
    results.push({
      ...book,
      status: 'skipped',
      reason: (run.stderr || run.stdout || 'unknown error').trim(),
    });
    process.stdout.write(`[skipped] ${book.title}\n`);
  }
}

const outputDir = '/home/admin/ai/output/sonovel';
fs.mkdirSync(outputDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const output = path.join(outputDir, `ranking-queue-${stamp}.json`);
fs.writeFileSync(output, `${JSON.stringify(results, null, 2)}\n`);
process.stdout.write(`${output}\n`);
