#!/usr/bin/env node
'use strict';

// Refresh an already-open Fanqie QR-login modal without restarting its
// browser lease.  It only exports a square raw PNG data URL and never takes
// a page screenshot.

const fs = require('fs');
const path = require('path');
const CDP = require('chrome-remote-interface');

function option(name, fallback) {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

const port = Number(option('--port', '9224'));
const out = option('--out', '/home/admin/ai/output/qr-login/current.png');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function value(Runtime, expression) {
  const result = await Runtime.evaluate({ expression, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Runtime evaluation failed');
  return result.result.value;
}

function pngDimensions(buffer) {
  if (buffer.length < 24 || buffer.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') return null;
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

async function rawQr(Runtime) {
  return value(Runtime,
    '(() => {' +
    'const square = rect => rect.width >= 120 && rect.height >= 120 && Math.abs(rect.width - rect.height) < 10;' +
    'const rawPng = data => typeof data === "string" && /^data:image\\/png;base64,/i.test(data);' +
    'const candidates = [];' +
    'for (const img of document.images) { const rect = img.getBoundingClientRect(); const data = img.currentSrc || img.src || ""; if (square(rect) && rawPng(data)) candidates.push({type:"img",data,width:rect.width,height:rect.height}); }' +
    'for (const canvas of document.querySelectorAll("canvas")) { const rect = canvas.getBoundingClientRect(); let data = ""; try { data = canvas.toDataURL("image/png"); } catch (_) {} if (square(rect) && rawPng(data)) candidates.push({type:"canvas",data,width:rect.width,height:rect.height}); }' +
    'candidates.sort((a,b) => (b.width*b.height) - (a.width*a.height)); return candidates[0] || null;' +
    '})()');
}

function pointForExactText(text) {
  return '(() => {' +
    'const wanted = ' + JSON.stringify(text) + ';' +
    'const priority = el => el.tagName === "BUTTON" ? 0 : el.tagName === "A" ? 1 : el.getAttribute("role") === "button" ? 2 : 3;' +
    'const candidates = [...document.querySelectorAll("body *")].filter(el => (el.innerText || el.textContent || "").trim() === wanted).map(el => ({el,rect:el.getBoundingClientRect(),style:getComputedStyle(el)})).filter(item => item.rect.width && item.rect.height && item.style.display !== "none" && item.style.visibility !== "hidden").sort((a,b) => priority(a.el) - priority(b.el) || (a.rect.width*a.rect.height) - (b.rect.width*b.rect.height));' +
    'if (!candidates.length) return null; const el = candidates[0].el; el.scrollIntoView({block:"center",inline:"center"}); const rect = el.getBoundingClientRect(); return {x:rect.left + rect.width/2,y:rect.top + rect.height/2,text:wanted,tag:el.tagName};' +
    '})()';
}

function directClickForExactText(text) {
  return '(() => {' +
    'const wanted = ' + JSON.stringify(text) + ';' +
    'const candidates = [...document.querySelectorAll("body *")].filter(el => (el.innerText || el.textContent || "").trim() === wanted).map(el => ({el,rect:el.getBoundingClientRect(),style:getComputedStyle(el)})).filter(item => item.rect.width && item.rect.height && item.style.display !== "none" && item.style.visibility !== "hidden");' +
    'if (!candidates.length) return false; const el = candidates[0].el; el.scrollIntoView({block:"center",inline:"center"}); el.click(); return true;' +
    '})()';
}

async function realClick(Input, point) {
  await Input.dispatchMouseEvent({ type: 'mouseMoved', x: point.x, y: point.y });
  await Input.dispatchMouseEvent({ type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await Input.dispatchMouseEvent({ type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
}

async function main() {
  const targets = await CDP.List({ port });
  const target = targets.find(item => item.type === 'page' && /fanqienovel\.com/.test(item.url || '')) || targets.find(item => item.type === 'page');
  if (!target) throw new Error('No page target on CDP port ' + port);
  const client = await CDP({ port, target });
  const Runtime = client.Runtime;
  const Input = client.Input;
  try {
    const before = await rawQr(Runtime);
    const beforeData = before && before.data;
    let clicked = null;
    for (const label of ['点击刷新', '刷新二维码', '刷新']) {
      const point = await value(Runtime, pointForExactText(label));
      if (!point) continue;
      clicked = point;
      await value(Runtime, directClickForExactText(label));
      break;
    }
    if (!clicked) {
      const text = await value(Runtime, 'document.body ? document.body.innerText.slice(0, 1200) : "NO_BODY"');
      throw new Error('No QR refresh control found; page text: ' + text);
    }
    console.log('QR_REFRESH_CLICKED ' + JSON.stringify(clicked));

    const deadline = Date.now() + 20000;
    let fresh = null;
    while (Date.now() < deadline) {
      const candidate = await rawQr(Runtime);
      if (candidate && (!beforeData || candidate.data !== beforeData)) {
        fresh = candidate;
        break;
      }
      await sleep(250);
    }
    if (!fresh) throw new Error('QR did not change after refresh click');

    const png = Buffer.from(fresh.data.replace(/^data:image\/png;base64,/i, ''), 'base64');
    const dimensions = pngDimensions(png);
    if (!dimensions || dimensions.width < 200 || dimensions.height < 200 || dimensions.width !== dimensions.height) {
      throw new Error('Refreshed QR failed PNG validation: ' + JSON.stringify(dimensions));
    }
    fs.mkdirSync(path.dirname(out), { recursive: true });
    const temporary = out + '.tmp-' + process.pid;
    fs.writeFileSync(temporary, png);
    fs.renameSync(temporary, out);
    console.log('RAW_QR_REFRESHED ' + JSON.stringify({ out, source: fresh.type, rendered: fresh.width + 'x' + fresh.height, png: dimensions.width + 'x' + dimensions.height }));
  } finally {
    await client.close().catch(() => {});
  }
}

main().catch(error => {
  console.error('QR_REFRESH_FAILED ' + (error && error.stack || error));
  process.exit(1);
});
