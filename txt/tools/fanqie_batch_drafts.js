const CDP = require('chrome-remote-interface');
const { spawnSync } = require('child_process');
const path = require('path');
const { loadChapters, resolveBookDir } = require('./fanqie_chapters');

function usage() {
  console.log(`Usage:
  node tools/fanqie_batch_drafts.js --book <book-dir-or-name> --from 22 --to 30 [--port 9223]

Creates a fresh Fanqie draft page for each chapter, fills it, and clicks "存草稿".
It does not click publish.
`);
}

function argValue(args, name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (!args[index + 1]) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

async function fanqieTarget(port) {
  const targets = await CDP.List({ port });
  const pages = targets.filter(item => item.type === 'page' && /fanqienovel\.com/.test(item.url));
  return pages.find(item => /\/publish\//.test(item.url)) || pages.reverse()[0];
}

async function createBlankDraft(port) {
  const target = await fanqieTarget(port);
  if (!target) throw new Error(`Fanqie page not found on CDP port ${port}`);
  const client = await CDP({ port, target });
  const { Runtime } = client;
  let base = target.url;
  if (/\/publish\//.test(base)) {
    base = base.replace(/\/publish\/[^?]+/, '/publish/');
  } else {
    const hrefResult = await Runtime.evaluate({
      expression: `[...document.querySelectorAll('a')].find(a=>(a.innerText||a.textContent||'').trim()==='\\u521b\\u5efa\\u7ae0\\u8282')?.href`,
      returnByValue: true
    });
    base = hrefResult.result.value;
  }
  if (!base) throw new Error('Cannot find Fanqie create chapter URL');

  await Runtime.evaluate({ expression: `location.href=${JSON.stringify(base)}` });
  const started = Date.now();
  while (Date.now() - started < 30000) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    const ready = await Runtime.evaluate({
      expression: `JSON.stringify({
        url: location.href,
        hasEditor: !!document.querySelector('.ProseMirror,[contenteditable="true"]'),
        empty: (document.querySelector('.ProseMirror,[contenteditable="true"]')?.innerText || '').trim().length < 50
      })`,
      returnByValue: true
    });
    const state = JSON.parse(ready.result.value);
    if (/\/publish\/[^?]+/.test(state.url) && state.hasEditor && state.empty) {
      await client.close();
      return state.url;
    }
  }
  await client.close();
  throw new Error('Timed out waiting for blank draft editor');
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('-h') || args.includes('--help')) {
    usage();
    return;
  }

  const bookDir = resolveBookDir(argValue(args, '--book'));
  const from = Number(argValue(args, '--from'));
  const to = Number(argValue(args, '--to'));
  const port = Number(argValue(args, '--port', '9223'));
  if (!from || !to) throw new Error('--from and --to are required');

  const chapters = loadChapters(bookDir).filter(chapter => chapter.no >= from && chapter.no <= to);
  if (!chapters.length) throw new Error(`No chapters found in range ${from}-${to}`);

  const results = [];
  for (const chapter of chapters) {
    console.log(`\nCreating draft for ${chapter.title}`);
    const url = await createBlankDraft(port);
    console.log(`Draft URL: ${url}`);
    const child = spawnSync(process.execPath, [
      path.join(__dirname, 'fanqie_fill_from_export.js'),
      '--book', bookDir,
      '--chapter', String(chapter.no),
      '--port', String(port),
      '--save-draft'
    ], {
      cwd: path.join(__dirname, '..'),
      encoding: 'utf8',
      stdio: 'pipe'
    });
    process.stdout.write(child.stdout);
    process.stderr.write(child.stderr);
    if (child.status !== 0) throw new Error(`Fill failed for chapter ${chapter.no}`);
    results.push({ no: chapter.no, title: chapter.title, url });
  }

  console.log('\nSaved drafts:');
  for (const item of results) {
    console.log(`${String(item.no).padStart(3, '0')} ${item.title} ${item.url}`);
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
