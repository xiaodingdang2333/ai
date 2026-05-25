const CDP = require('chrome-remote-interface');
const { spawnSync } = require('child_process');
const path = require('path');
const { loadChapters, resolveBookDir } = require('./fanqie_chapters');

function argValue(args, name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (!args[index + 1]) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

async function getClient(port) {
  const targets = await CDP.List({ port });
  const target = targets
    .filter(item => item.type === 'page' && /fanqienovel\.com/.test(item.url))
    .find(item => /chapter-manage/.test(item.url))
    || targets.filter(item => item.type === 'page' && /fanqienovel\.com/.test(item.url))[0];
  if (!target) throw new Error(`Fanqie page not found on CDP port ${port}`);
  return CDP({ port, target });
}

async function readDrafts(Runtime) {
  const result = await Runtime.evaluate({
    expression: `JSON.stringify((() => {
      const anchors = [...document.querySelectorAll('a')];
      const drafts = [];
      for (let i = 0; i < anchors.length; i += 1) {
        const text = (anchors[i].innerText || anchors[i].textContent || '').trim();
        const m = text.match(/^\\u7b2c(\\d+)\\u7ae0\\s*(.+)$/);
        if (!m) continue;
        const edit = anchors.slice(i + 1).find(a => /modifydraft/.test(a.href || ''));
        if (edit) drafts.push({ no: Number(m[1]), text, href: edit.href });
      }
      const newDraft = anchors.find(a => (a.innerText || a.textContent || '').trim() === '\\u65b0\\u5efa\\u8349\\u7a3f')?.href;
      return { drafts, newDraft, url: location.href };
    })())`,
    returnByValue: true
  });
  return JSON.parse(result.result.value);
}

async function navigate(Runtime, url) {
  await Runtime.evaluate({ expression: `location.href=${JSON.stringify(url)}` });
  const started = Date.now();
  while (Date.now() - started < 30000) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    const ready = await Runtime.evaluate({
      expression: `JSON.stringify({
        url: location.href,
        hasEditor: !!document.querySelector('.ProseMirror,[contenteditable="true"]')
      })`,
      returnByValue: true
    });
    const state = JSON.parse(ready.result.value);
    if (/\/publish\/[^?]+/.test(state.url) && state.hasEditor) return state.url;
  }
  throw new Error(`Timed out waiting for editor: ${url}`);
}

async function navigatePage(Runtime, url, waitMs = 5000) {
  await Runtime.evaluate({ expression: `location.href=${JSON.stringify(url)}` });
  await new Promise(resolve => setTimeout(resolve, waitMs));
}

function fill(bookDir, chapterNo, port) {
  const child = spawnSync(process.execPath, [
    path.join(__dirname, 'fanqie_fill_from_export.js'),
    '--book', bookDir,
    '--chapter', String(chapterNo),
    '--port', String(port),
    '--save-draft'
  ], {
    cwd: path.join(__dirname, '..'),
    encoding: 'utf8',
    stdio: 'pipe'
  });
  process.stdout.write(child.stdout);
  process.stderr.write(child.stderr);
  if (child.status !== 0) throw new Error(`Fill failed for chapter ${chapterNo}`);
}

async function main() {
  const args = process.argv.slice(2);
  const bookDir = resolveBookDir(argValue(args, '--book'));
  const from = Number(argValue(args, '--from', '20'));
  const to = Number(argValue(args, '--to', '30'));
  const port = Number(argValue(args, '--port', '9223'));
  const chapters = loadChapters(bookDir).filter(chapter => chapter.no >= from && chapter.no <= to);
  const client = await getClient(port);
  const { Runtime } = client;

  try {
    let listing = await readDrafts(Runtime);
    const draftBoxUrl = listing.url;
    if (!listing.newDraft) throw new Error('New draft link not found; open the draft box first');

    for (const chapter of chapters) {
      listing = await readDrafts(Runtime);
      const existing = listing.drafts.find(item => item.no === chapter.no);
      const targetUrl = existing ? existing.href : listing.newDraft;
      console.log(`\n${existing ? 'Repairing' : 'Creating'} ${chapter.title}`);
      console.log(targetUrl);
      await navigate(Runtime, targetUrl);
      fill(bookDir, chapter.no, port);
      await navigatePage(Runtime, draftBoxUrl);
    }
  } finally {
    await client.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
