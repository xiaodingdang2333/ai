#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const CLIENT = process.env.SONOVEL_CLIENT || '/home/admin/ai/scripts/sonovel-client.js';

function parseArgs(argv) {
  const input = argv[0];
  const options = {
    input,
    concurrency: 2,
    successLimit: 3,
    bookTimeoutMs: 45_000,
    batchTimeoutMs: 90_000,
  };
  for (let i = 1; i < argv.length; i += 2) {
    const value = Number(argv[i + 1]);
    if (argv[i] === '--concurrency') options.concurrency = Math.max(1, Math.min(3, value || 1));
    else if (argv[i] === '--success-limit') options.successLimit = Math.max(1, Math.min(6, value || 3));
    else if (argv[i] === '--book-timeout-seconds') options.bookTimeoutMs = Math.max(5, value || 45) * 1000;
    else if (argv[i] === '--batch-timeout-seconds') options.batchTimeoutMs = Math.max(10, value || 90) * 1000;
    else throw new Error(`Unknown option: ${argv[i]}`);
  }
  if (!input) throw new Error('Usage: sonovel-ranking-queue.js <official-ranking-books.json> [options]');
  return options;
}

function emit(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

function boundedAppend(current, chunk, limit = 32_000) {
  const next = current + chunk;
  return next.length > limit ? next.slice(-limit) : next;
}

function killProcessGroup(child, signal) {
  if (!child.pid) return;
  try {
    process.kill(-child.pid, signal);
  } catch (_) {
    try { child.kill(signal); } catch (_) { /* already stopped */ }
  }
}

function runPacket(book, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [CLIENT, 'packet', book.title, book.author || ''], {
      detached: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    child.stdout.on('data', (chunk) => { stdout = boundedAppend(stdout, chunk.toString()); });
    child.stderr.on('data', (chunk) => { stderr = boundedAppend(stderr, chunk.toString()); });
    const timer = setTimeout(() => {
      timedOut = true;
      killProcessGroup(child, 'SIGTERM');
      setTimeout(() => killProcessGroup(child, 'SIGKILL'), 1500).unref();
    }, timeoutMs);
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ ok: false, reason: error.message });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (timedOut) {
        resolve({ ok: false, reason: `单本下载超过${Math.round(timeoutMs / 1000)}秒，已跳过`, timedOut: true });
      } else if (code === 0) {
        resolve({ ok: true, packet: stdout.trim() });
      } else {
        resolve({ ok: false, reason: (stderr || stdout || `exit ${code}`).trim() });
      }
    });
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const books = JSON.parse(fs.readFileSync(options.input, 'utf8'));
  if (!Array.isArray(books)) throw new Error('Input must be a JSON array');

  const started = Date.now();
  const deadline = started + options.batchTimeoutMs;
  const results = new Array(books.length);
  const active = new Map();
  let cursor = 0;
  let processed = 0;
  let succeeded = 0;
  let skipped = 0;
  let stopReason = '';

  const progress = () => emit({
    event: 'progress',
    processed,
    total: books.length,
    succeeded,
    skipped,
    active_titles: [...active.values()],
    elapsed_seconds: Math.round((Date.now() - started) / 1000),
    concurrency: options.concurrency,
  });

  async function worker(workerId) {
    while (true) {
      if (succeeded >= options.successLimit) {
        stopReason = 'target_reached';
        return;
      }
      if (Date.now() >= deadline) {
        stopReason = 'batch_timeout';
        return;
      }
      if (active.size > 0 && succeeded + active.size >= options.successLimit) {
        await new Promise((resolve) => setTimeout(resolve, 25));
        continue;
      }
      const index = cursor;
      cursor += 1;
      if (index >= books.length) return;
      const book = books[index];
      if (!book || !book.title) {
        results[index] = { ...(book || {}), status: 'skipped', reason: '书名为空' };
        processed += 1;
        skipped += 1;
        progress();
        continue;
      }
      const remaining = Math.max(1000, deadline - Date.now());
      const timeout = Math.min(options.bookTimeoutMs, remaining);
      active.set(workerId, book.title);
      progress();
      const outcome = await runPacket(book, timeout);
      active.delete(workerId);
      processed += 1;
      if (outcome.ok) {
        succeeded += 1;
        results[index] = { ...book, status: 'downloaded_needs_official_verification', packet: outcome.packet };
      } else {
        skipped += 1;
        results[index] = { ...book, status: 'skipped', reason: outcome.reason, timed_out: Boolean(outcome.timedOut) };
      }
      progress();
    }
  }

  progress();
  await Promise.all(Array.from({ length: options.concurrency }, (_, index) => worker(index + 1)));
  if (!stopReason && Date.now() >= deadline) stopReason = 'batch_timeout';
  if (!stopReason && succeeded >= options.successLimit) stopReason = 'target_reached';
  if (!stopReason) stopReason = 'input_exhausted';

  for (let index = 0; index < books.length; index += 1) {
    if (!results[index]) {
      results[index] = {
        ...books[index],
        status: 'not_attempted',
        reason: stopReason === 'target_reached' ? '已取得目标样本数' : `整批任务已到${Math.round(options.batchTimeoutMs / 1000)}秒截止时间`,
      };
    }
  }

  const outputDir = process.env.SONOVEL_OUTPUT_DIR || '/home/admin/ai/output/sonovel';
  fs.mkdirSync(outputDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const output = path.join(outputDir, `ranking-queue-${stamp}-${process.pid}.json`);
  fs.writeFileSync(output, `${JSON.stringify(results, null, 2)}\n`);
  emit({
    event: 'complete',
    output,
    processed,
    total: books.length,
    succeeded,
    skipped,
    stop_reason: stopReason,
    elapsed_seconds: Math.round((Date.now() - started) / 1000),
    concurrency: options.concurrency,
  });
  process.stdout.write(`${output}\n`);
}

main().catch((error) => {
  emit({ event: 'fatal', error: error.message });
  process.exitCode = 1;
});
