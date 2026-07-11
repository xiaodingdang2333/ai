#!/usr/bin/env node
/* Export a deterministic manual Fanqie creation package from a Git novel project. */

const fs = require('fs');
const path = require('path');

function option(name, fallback = '') {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] || fallback : fallback;
}

function section(markdown, name) {
  const heading = `## ${name}`;
  const start = markdown.split(/\r?\n/).findIndex(line => line.trim() === heading);
  if (start < 0) return '';
  const lines = markdown.split(/\r?\n/).slice(start + 1);
  const end = lines.findIndex(line => line.startsWith('## '));
  return (end >= 0 ? lines.slice(0, end) : lines).join('\n').trim();
}

function walk(dir, depth = 0) {
  if (!fs.existsSync(dir) || depth > 3) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const target = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(target, depth + 1) : [target];
  });
}

function main() {
  const project = path.resolve(option('--project'));
  if (!option('--project')) throw new Error('Use --project <novel-project-directory>');
  const setup = path.join(project, '发布信息', 'TOMATO_PUBLICATION_SETUP.md');
  if (!fs.existsSync(setup)) throw new Error(`Missing publication setup: ${setup}`);
  const markdown = fs.readFileSync(setup, 'utf8');
  const imagePattern = /(?:cover|封面).*\.(?:png|jpe?g|webp)$/i;
  const covers = walk(project).filter(file => imagePattern.test(path.basename(file)));
  const packageData = {
    status: covers.length ? 'MANUAL_CREATE_PACKAGE_READY' : 'COVER_ASSET_MISSING',
    project,
    setup_path: setup,
    book_title: section(markdown, '书名'),
    tags: section(markdown, '标签'),
    protagonist_1: section(markdown, '主角名1'),
    protagonist_2: section(markdown, '主角名2'),
    synopsis: section(markdown, '简介'),
    cover_prompt: section(markdown, '封面提示词'),
    cover_status: section(markdown, '封面状态'),
    cover_files: covers,
    required_cover_size: '600x800',
    automatic_submission_allowed: false,
    next_action: covers.length
      ? 'Use these exact fields and the listed cover in the Fanqie create-book form.'
      : 'Generate and save a checked 600x800 cover before manual creation.',
  };
  const output = option('--output');
  const serialized = `${JSON.stringify(packageData, null, 2)}\n`;
  if (output) fs.writeFileSync(output, serialized, 'utf8');
  process.stdout.write(serialized);
  process.exitCode = covers.length ? 0 : 4;
}

try {
  main();
} catch (error) {
  console.error(error.stack || String(error));
  process.exit(1);
}
