const fs = require('fs');
const path = require('path');

const DEFAULT_BOOK = path.join(
  __dirname,
  '..',
  '快穿：恶毒女配觉醒后，全员跪求我原谅'
);

function usage() {
  console.log(`Usage:
  node tools/fanqie_chapters.js list [--book <book-dir-or-name>]
  node tools/fanqie_chapters.js export [--book <book-dir-or-name>] [--out <file.jsonl>]
  node tools/fanqie_chapters.js write-one <chapter-no> [--book <book-dir-or-name>] [--out <dir>]

Defaults:
  --book can be a full path or a novel folder name under F:\\ai\\txt
  default: ${DEFAULT_BOOK}
  --out  output/fanqie-upload/chapters.jsonl
`);
}

function argValue(args, name, fallback) {
  const index = args.indexOf(name);
  if (index === -1) return fallback;
  if (!args[index + 1]) throw new Error(`Missing value for ${name}`);
  return args[index + 1];
}

function resolveBookDir(book) {
  const value = book || DEFAULT_BOOK;
  const direct = path.resolve(value);
  if (fs.existsSync(direct)) return direct;
  const underTxt = path.resolve(path.join(__dirname, '..', value));
  if (fs.existsSync(underTxt)) return underTxt;
  return direct;
}

function normalizeNewlines(text) {
  return text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

function titleFromFileName(fileName) {
  return path.basename(fileName, '.md').replace('_', ' ');
}

function parseChapter(filePath) {
  const raw = normalizeNewlines(fs.readFileSync(filePath, 'utf8'));
  const lines = raw.split('\n');
  const firstContentIndex = lines.findIndex(line => line.trim().length > 0);
  const firstLine = firstContentIndex >= 0 ? lines[firstContentIndex].trim() : '';
  const markdownTitle = firstLine.match(/^#{1,6}\s+(.+?)\s*$/);
  const title = markdownTitle ? markdownTitle[1].trim() : titleFromFileName(filePath);
  const noMatch = title.match(/第\s*0*(\d+)\s*章/) || path.basename(filePath).match(/第\s*0*(\d+)\s*章/);
  if (!noMatch) throw new Error(`Cannot find chapter number: ${filePath}`);

  const bodyLines = lines.filter((line, index) => {
    if (index !== firstContentIndex) return true;
    return !markdownTitle;
  });
  const body = bodyLines.join('\n').trim() + '\n';

  return {
    no: Number(noMatch[1]),
    title,
    body,
    bodyChars: body.trim().length,
    file: filePath
  };
}

function loadChapters(bookDir) {
  const chapterDir = path.join(bookDir, '正文');
  if (!fs.existsSync(chapterDir)) throw new Error(`Chapter directory not found: ${chapterDir}`);
  return fs.readdirSync(chapterDir)
    .filter(name => name.toLowerCase().endsWith('.md'))
    .map(name => parseChapter(path.join(chapterDir, name)))
    .sort((a, b) => a.no - b.no || a.title.localeCompare(b.title, 'zh-Hans-CN'));
}

function ensureParent(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function list(chapters) {
  const total = chapters.reduce((sum, chapter) => sum + chapter.bodyChars, 0);
  for (const chapter of chapters) {
    console.log(`${String(chapter.no).padStart(3, '0')}  ${chapter.bodyChars.toString().padStart(5)}字  ${chapter.title}`);
  }
  console.log(`\nTOTAL ${chapters.length} chapters, ${total} chars`);
}

function exportJsonl(chapters, outFile) {
  ensureParent(outFile);
  const data = chapters.map(chapter => JSON.stringify({
    no: chapter.no,
    title: chapter.title,
    body: chapter.body,
    bodyChars: chapter.bodyChars,
    source: chapter.file
  })).join('\n') + '\n';
  fs.writeFileSync(outFile, data, 'utf8');
  console.log(`Wrote ${chapters.length} chapters to ${outFile}`);
}

function writeOne(chapters, no, outDir) {
  const chapter = chapters.find(item => item.no === no);
  if (!chapter) throw new Error(`Chapter not found: ${no}`);
  fs.mkdirSync(outDir, { recursive: true });
  const titleFile = path.join(outDir, `${String(no).padStart(3, '0')}-title.txt`);
  const bodyFile = path.join(outDir, `${String(no).padStart(3, '0')}-body.txt`);
  fs.writeFileSync(titleFile, chapter.title, 'utf8');
  fs.writeFileSync(bodyFile, chapter.body, 'utf8');
  console.log(`Wrote ${titleFile}`);
  console.log(`Wrote ${bodyFile}`);
}

function main() {
  const [, , command, ...args] = process.argv;
  if (!command || command === '-h' || command === '--help') {
    usage();
    return;
  }

  const bookDir = resolveBookDir(argValue(args, '--book', DEFAULT_BOOK));
  const chapters = loadChapters(bookDir);

  if (command === 'list') {
    list(chapters);
    return;
  }

  if (command === 'export') {
    const outFile = path.resolve(argValue(args, '--out', path.join(__dirname, '..', 'output', 'fanqie-upload', 'chapters.jsonl')));
    exportJsonl(chapters, outFile);
    return;
  }

  if (command === 'write-one') {
    const no = Number(args.find(value => /^\d+$/.test(value)));
    if (!no) throw new Error('write-one requires a chapter number');
    const outDir = path.resolve(argValue(args, '--out', path.join(__dirname, '..', 'output', 'fanqie-upload', 'single')));
    writeOne(chapters, no, outDir);
    return;
  }

  throw new Error(`Unknown command: ${command}`);
}

if (require.main === module) {
  main();
}

module.exports = {
  DEFAULT_BOOK,
  loadChapters,
  parseChapter,
  resolveBookDir,
  shortTitle: titleFromFileName
};
