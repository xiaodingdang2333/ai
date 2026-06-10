#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

function arg(name, fallback = undefined) {
  const i = process.argv.indexOf(name);
  if (i === -1) return fallback;
  if (!process.argv[i + 1]) throw new Error(`Missing value for ${name}`);
  return process.argv[i + 1];
}

const command = process.argv[2];
const workRoot = arg('--work-root', process.env.WORK_ROOT || '/home/admin/ai');
const stateFile = arg('--state', path.join(workRoot, 'output/fanqie-upload/nightly/state.json'));
const threshold = Number(arg('--threshold', '100000'));

function loadState() {
  if (!fs.existsSync(stateFile)) return { books: {} };
  return JSON.parse(fs.readFileSync(stateFile, 'utf8'));
}

function saveState(state) {
  fs.mkdirSync(path.dirname(stateFile), { recursive: true });
  fs.writeFileSync(stateFile, `${JSON.stringify(state, null, 2)}\n`);
}

function chapterFiles(book) {
  const dir = path.join(workRoot, 'txt', book, '正文');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir)
    .map(name => {
      const match = name.match(/^第0*(\d+)章_/);
      return match ? { no: Number(match[1]), file: path.join(dir, name) } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.no - b.no);
}

function bodyCharCount(file) {
  const raw = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = raw.split('\n');
  const first = lines.findIndex(line => line.trim());
  if (first >= 0 && /^#{1,6}\s+/.test(lines[first].trim())) lines.splice(first, 1);
  return lines.join('\n').replace(/\s/g, '').length;
}

function totalThrough(book, lastNo) {
  return chapterFiles(book)
    .filter(item => item.no <= lastNo)
    .reduce((sum, item) => sum + bodyCharCount(item.file), 0);
}

function ensureBook(state, book) {
  state.books[book] ||= { lastPublishedNo: 0, totalPublishedChars: 0, notified100k: false };
  return state.books[book];
}

if (command === 'get') {
  const book = arg('--book');
  const state = loadState();
  const entry = ensureBook(state, book);
  console.log(JSON.stringify(entry));
} else if (command === 'record') {
  const book = arg('--book');
  const chapter = Number(arg('--chapter'));
  const state = loadState();
  const entry = ensureBook(state, book);
  if (chapter > entry.lastPublishedNo) entry.lastPublishedNo = chapter;
  entry.totalPublishedChars = totalThrough(book, entry.lastPublishedNo);
  const crossed = entry.totalPublishedChars >= threshold && !entry.notified100k;
  if (crossed) entry.notified100k = true;
  saveState(state);
  console.log(JSON.stringify({ ...entry, crossed100k: crossed }));
} else if (command === 'init') {
  const book = arg('--book');
  const last = Number(arg('--last'));
  const state = loadState();
  const entry = ensureBook(state, book);
  entry.lastPublishedNo = Math.max(entry.lastPublishedNo || 0, last);
  entry.totalPublishedChars = totalThrough(book, entry.lastPublishedNo);
  if (entry.totalPublishedChars >= threshold) entry.notified100k = true;
  saveState(state);
  console.log(JSON.stringify(entry));
} else {
  console.error('Usage: fanqie-nightly-state.js get|record|init --book <name> [--chapter N|--last N]');
  process.exit(2);
}
