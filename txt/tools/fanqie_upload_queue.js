const { spawnSync } = require('child_process');
const path = require('path');
const readline = require('readline');
const { loadChapters, resolveBookDir } = require('./fanqie_chapters');

function usage() {
  console.log(`Usage:
  node tools/fanqie_upload_queue.js --book <book-dir-or-name> [--from 1] [--to 30] [--port 9223] [--save-draft]

This is an assisted queue:
  1. You log in and open Fanqie's new chapter editor in Chrome CDP.
  2. The script fills one chapter.
  3. You review/save/open the next blank chapter.
  4. Press Enter here to continue.

It never clicks publish.
`);
}

function argValue(args, name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (!args[index + 1]) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

function hasFlag(args, name) {
  return args.includes(name);
}

function ask(rl, question) {
  return new Promise(resolve => rl.question(question, resolve));
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('-h') || args.includes('--help')) {
    usage();
    return;
  }

  const bookArg = argValue(args, '--book');
  if (!bookArg) throw new Error('--book is required');

  const bookDir = resolveBookDir(bookArg);
  const from = Number(argValue(args, '--from', '1'));
  const to = Number(argValue(args, '--to', String(Number.MAX_SAFE_INTEGER)));
  const port = argValue(args, '--port', '9223');
  const saveDraft = hasFlag(args, '--save-draft');
  const chapters = loadChapters(bookDir).filter(chapter => chapter.no >= from && chapter.no <= to);
  if (!chapters.length) throw new Error(`No chapters found in range ${from}-${to}`);

  console.log(`Queue: ${chapters.length} chapters from ${bookDir}`);
  for (const chapter of chapters) {
    console.log(`${String(chapter.no).padStart(3, '0')} ${chapter.bodyChars}字 ${chapter.title}`);
  }
  console.log('');

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    await ask(rl, 'Open a blank Fanqie chapter editor in CDP Chrome, then press Enter to fill the first chapter...');
    for (let i = 0; i < chapters.length; i += 1) {
      const chapter = chapters[i];
      console.log(`\n[${i + 1}/${chapters.length}] Filling ${chapter.title}`);
      const child = spawnSync(process.execPath, [
        path.join(__dirname, 'fanqie_fill_from_export.js'),
        '--book', bookDir,
        '--chapter', String(chapter.no),
        '--port', port,
        ...(saveDraft ? ['--save-draft'] : [])
      ], {
        cwd: path.join(__dirname, '..'),
        stdio: 'inherit',
        encoding: 'utf8'
      });
      if (child.status !== 0) throw new Error(`Fill failed for chapter ${chapter.no}`);
      if (i < chapters.length - 1) {
        await ask(rl, 'Review/save it, open the next blank chapter editor, then press Enter to continue...');
      }
    }
    console.log('\nQueue finished.');
  } finally {
    rl.close();
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
