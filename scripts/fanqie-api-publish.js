#!/usr/bin/env node
const crypto = require('crypto');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const workRoot = process.env.WORK_ROOT || '/home/admin/ai';
const txtRoot = path.join(workRoot, 'txt');

function arg(name, fallback = '') {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  if (!process.argv[index + 1]) throw new Error(`Missing value for ${name}`);
  return process.argv[index + 1];
}

const account = arg('--account');
const expectedAccount = arg('--expected-account');
const book = arg('--book');
const bookId = arg('--book-id');
const aiUse = arg('--ai-use', 'no');
const from = Number(arg('--from', '1'));
const to = Number(arg('--to', String(Number.MAX_SAFE_INTEGER)));

if (!account || !expectedAccount || !book || !bookId) {
  throw new Error('Usage: fanqie-api-publish.js --account account-a --expected-account NAME --book BOOK --book-id ID [--ai-use yes|no] [--from N] [--to N]');
}

const cookieDb = `/root/snap/chromium/common/fanqie-profiles/live/${account}/Default/Cookies`;
const bookDir = path.join(txtRoot, book);
const chapterDir = path.join(bookDir, '正文');

function decodeCookieHeader(db) {
  const py = [
    'import sqlite3, json, base64',
    `con=sqlite3.connect('file:${db}?mode=ro', uri=True)`,
    'rows=con.execute("select host_key,name,encrypted_value,value from cookies where host_key like \'%fanqie%\' order by name").fetchall()',
    'print(json.dumps([[h,n,base64.b64encode(e).decode(),v] for h,n,e,v in rows], ensure_ascii=False))',
  ].join('\n');
  const rows = JSON.parse(cp.execFileSync('python3', ['-c', py], { encoding: 'utf8' }));
  const key = crypto.pbkdf2Sync(Buffer.from('peanuts'), Buffer.from('saltysalt'), 1, 16, 'sha1');
  const parts = [];
  for (const [host, name, b64, value] of rows) {
    const encrypted = Buffer.from(b64, 'base64');
    const prefix = encrypted.slice(0, 3).toString('latin1');
    let decoded = '';
    if (value) {
      decoded = value;
    } else if (prefix === 'v10' || prefix === 'v11') {
      const decipher = crypto.createDecipheriv('aes-128-cbc', key, Buffer.alloc(16, 0x20));
      let plain = Buffer.concat([decipher.update(encrypted.slice(3)), decipher.final()]);
      const hostHash = crypto.createHash('sha256').update(host).digest();
      if (plain.length > 32 && plain.slice(0, 32).equals(hostHash)) plain = plain.slice(32);
      decoded = plain.toString('utf8');
    }
    if (decoded) parts.push(`${name}=${decoded}`);
  }
  if (!parts.length) throw new Error(`No usable Fanqie cookies found for ${account}`);
  return `Cookie: ${parts.join('; ')}`;
}

const cookieHeader = decodeCookieHeader(cookieDb);

function curl(args) {
  return cp.execFileSync('curl', [
    '-sS',
    '--max-time',
    '60',
    '-H',
    cookieHeader,
    '-H',
    'User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/149 Safari/537.36',
    '-H',
    `Referer: https://fanqienovel.com/main/writer/publish/${bookId}`,
    ...args,
  ], { encoding: 'utf8', maxBuffer: 60 * 1024 * 1024 });
}

function apiJson(args) {
  const out = curl(args);
  try {
    return JSON.parse(out);
  } catch (_) {
    return { code: -99999, message: 'Non-JSON response', body: out.slice(0, 1000) };
  }
}

function normalize(text) {
  return text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

function parseChapter(no) {
  if (!fs.existsSync(chapterDir)) throw new Error(`Chapter directory not found: ${chapterDir}`);
  const padded = String(no).padStart(3, '0');
  const file = fs.readdirSync(chapterDir).find(name => name.startsWith(`第${padded}章_`) && name.endsWith('.md'));
  if (!file) throw new Error(`Local chapter not found: ${book} 第${padded}章`);
  const raw = normalize(fs.readFileSync(path.join(chapterDir, file), 'utf8'));
  const lines = raw.split('\n');
  const first = lines.findIndex(line => line.trim());
  const titleLine = (first >= 0 ? lines[first] : path.basename(file, '.md')).replace(/^#{1,6}\s+/, '').trim();
  const shortTitle = titleLine.replace(/^第\s*0*\d+\s*章\s*/, '').trim();
  const body = lines.filter((_, index) => index !== first).join('\n').trim() + '\n';
  return {
    no,
    padded,
    title: `第${padded}章 ${shortTitle}`,
    body,
    chars: body.trim().length,
  };
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function bodyToHtml(body) {
  return normalize(body)
    .trim()
    .split(/\n\s*\n+/)
    .map(part => part.trim())
    .filter(Boolean)
    .map(part => `<p>${escapeHtml(part).replace(/\n/g, '<br>')}</p>`)
    .join('');
}

function allDrafts() {
  const rows = [];
  let total = 0;
  for (let pageIndex = 0; pageIndex < 50; pageIndex++) {
    const res = apiJson([`https://fanqienovel.com/app/book/draft_list/v0/?book_id=${bookId}&page_index=${pageIndex}&page_count=10`]);
    if (res.code !== 0) throw new Error(`Draft list failed for ${book}: ${JSON.stringify(res).slice(0, 1000)}`);
    if (pageIndex === 0) total = Number(res.data.total_count || 0);
    const list = res.data.draft_list || [];
    rows.push(...list);
    if (rows.length >= total || !list.length) break;
  }
  return { total, rows };
}

function chapterCount() {
  const res = apiJson([`https://fanqienovel.com/app/book/chapter_list/v0/?book_id=${bookId}&page_index=0&page_count=10`]);
  if (res.code !== 0) throw new Error(`Chapter list failed for ${book}: ${JSON.stringify(res).slice(0, 1000)}`);
  return Number(res.data.total_count || 0);
}

function volume() {
  const res = apiJson([`https://fanqienovel.com/app/book/volume_list/v0/?book_id=${bookId}&order=1`]);
  if (res.code !== 0) throw new Error(`Volume list failed for ${book}: ${JSON.stringify(res).slice(0, 1000)}`);
  const item = (res.data.volume_list || [])[0];
  if (!item) throw new Error(`No volume found for ${book}`);
  return { id: item.volume_id, name: item.volume_name };
}

function chapterNumber(title) {
  const match = String(title || '').match(/第\s*0*(\d+)\s*章/);
  return match ? Number(match[1]) : 0;
}

function publishChapter(chapter, row, vol) {
  const payload = {
    book_id: bookId,
    content: bodyToHtml(chapter.body),
    timer_status: '0',
    timer_time: '',
    volume_name: vol.name,
    title: chapter.title,
    volume_id: vol.id,
    publish_status: '1',
    item_id: row.item_id,
    speak_content: '',
    speak_delete: '0',
    speak_id: '',
    has_chapter_ad: '0',
    chapter_ad_types: '',
    speak_type: '0',
    timer_chapter_preview: '',
    use_ai: aiUse === 'yes' ? '1' : '0',
  };
  const args = ['-X', 'POST'];
  for (const [key, value] of Object.entries(payload)) args.push('--form-string', `${key}=${value}`);
  args.push('https://fanqienovel.com/app/book/publish_article/v0/');
  return apiJson(args);
}

function isDailyLimit(res) {
  const text = `${res.message || ''} ${res.body || ''}`;
  return res.code === -1019 || text.includes('上限') || text.includes('提交字数超出每日上限');
}

function main() {
  const user = apiJson(['https://fanqienovel.com/api/user/info/v2']);
  if (user.code !== 0 || user.data?.name !== expectedAccount) {
    throw new Error(`Account mismatch for ${book}: expected ${expectedAccount}, got ${user.data?.name || user.message || 'UNKNOWN'}`);
  }
  console.log(`ACCOUNT ${expectedAccount}`);
  const vol = volume();
  console.log(`VOLUME ${vol.id} ${vol.name}`);

  const published = [];
  let stop = null;
  while (true) {
    const drafts = allDrafts();
    const candidates = drafts.rows
      .map(row => ({ row, title: row.title || row.chapter_title || '', no: chapterNumber(row.title || row.chapter_title) }))
      .filter(item => item.no && item.no >= from && item.no <= to)
      .sort((a, b) => a.no - b.no);
    if (!candidates.length) {
      console.log('No matching drafts found.');
      break;
    }

    const { row, no, title } = candidates[0];
    const chapter = parseChapter(no);
    if (chapter.title !== title) {
      console.log(`WARN_TITLE_MISMATCH local=${chapter.title} draft=${title}`);
    }

    const beforeDraftTotal = drafts.total;
    const beforeChapterTotal = chapterCount();
    const res = publishChapter(chapter, row, vol);
    if (res.code !== 0) {
      if (isDailyLimit(res)) {
        stop = { type: 'daily-limit', no: chapter.padded, title, message: res.message || '' };
        console.log(`DAILY_LIMIT at ${title}`);
        break;
      }
      throw new Error(`Publish failed for ${book} ${title}: ${JSON.stringify(res).slice(0, 1000)}`);
    }

    let afterDrafts = null;
    let afterChapterTotal = 0;
    let stillInDraft = true;
    for (let i = 0; i < 8; i++) {
      afterDrafts = allDrafts();
      afterChapterTotal = chapterCount();
      stillInDraft = afterDrafts.rows.some(item => (item.title || item.chapter_title) === title);
      if (!stillInDraft && afterChapterTotal >= beforeChapterTotal + 1) break;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1000);
    }
    if (stillInDraft) {
      throw new Error(`Publish verification failed for ${book} ${title}: draft still present after success response`);
    }
    published.push(chapter.padded);
    console.log(`PUBLISH ${title} draft ${beforeDraftTotal}->${afterDrafts.total} chapter ${beforeChapterTotal}->${afterChapterTotal}`);
  }

  const finalDrafts = allDrafts();
  const remainingWords = finalDrafts.rows.reduce((sum, row) => sum + Number(row.word_number || row.word_count || row.words || 0), 0);
  const remainingTitles = finalDrafts.rows
    .map(row => row.title || row.chapter_title || '')
    .filter(title => /^第\s*\d+\s*章/.test(title))
    .sort((a, b) => chapterNumber(a) - chapterNumber(b));
  const summary = {
    book,
    account: expectedAccount,
    published,
    stop,
    final_draft_total: finalDrafts.total,
    final_chapter_total: chapterCount(),
    remaining_platform_words: remainingWords,
    remaining: remainingTitles,
  };
  console.log(`SUMMARY ${JSON.stringify(summary)}`);
}

try {
  main();
} catch (error) {
  console.error(error.message || error);
  process.exit(1);
}
