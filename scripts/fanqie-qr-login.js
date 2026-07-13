#!/usr/bin/env node
'use strict';

// Keep the QR-login lifecycle inside one Chrome/CDP session.  The caller is
// responsible for running this under fanqie-browser-lease.sh so that a
// successful login is copied into the account's persistent Snap profile.

const fs = require('fs');
const path = require('path');
const CDP = require('chrome-remote-interface');

function option(name, fallback = '') {
  const i = process.argv.indexOf(name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

const port = Number(option('--port', '9224'));
const expected = option('--expected');
const out = option('--out', '/home/admin/ai/output/qr-login/current.png');
const waitMs = Number(option('--wait-ms', String(20 * 60 * 1000)));
const settleMs = Number(option('--settle-ms', '45000'));
const fresh = option('--fresh', 'yes') !== 'no';
const writerLoginUrl = 'https://fanqienovel.com/main/writer/login?enter_from=author_zone';

if (!Number.isInteger(port) || port <= 0 || !expected) {
  throw new Error('Usage: fanqie-qr-login.js --port PORT --expected ACCOUNT --out FILE [--wait-ms MS] [--fresh yes|no]');
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function rejectAfter(ms, message) {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error(message)), ms);
  });
}

function log(event, extra = {}) {
  console.log(`${event} ${JSON.stringify(extra)}`);
}

async function value(Runtime, expression, awaitPromise = false) {
  const result = await Runtime.evaluate({ expression, returnByValue: true, awaitPromise });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || 'Runtime.evaluate failed');
  }
  return result.result.value;
}

function pngDimensions(buffer) {
  const magic = '89504e470d0a1a0a';
  if (buffer.length < 24 || buffer.subarray(0, 8).toString('hex') !== magic) return null;
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

async function currentAccount(Runtime) {
  // A stale writer renderer can leave a fetch promise pending forever after a
  // QR expires.  Treat that as "not logged in" and keep the QR lifecycle
  // recoverable instead of wedging the whole lease until its outer timeout.
  try {
    const info = await Promise.race([
      value(Runtime, `
        (async () => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 5000);
          try {
            const response = await fetch('/api/user/info/v2', {
              credentials: 'include',
              signal: controller.signal
            });
            return await response.json();
          } catch (error) {
            return { __error: String(error) };
          } finally {
            clearTimeout(timer);
          }
        })()
      `, true),
      rejectAfter(8000, 'Timed out while checking QR login state')
    ]);
    return info && info.data && typeof info.data.name === 'string' ? info.data.name : '';
  } catch (_) {
    return '';
  }
}

async function authCookieEvidence(Network) {
  const result = await Network.getAllCookies();
  const names = /^(?:sessionid|sessionid_ss|sid_tt|sid_guard|sid_ucp_v1|ssid_ucp_v1|uid_tt|uid_tt_ss)$/;
  const matched = (result.cookies || []).filter(cookie => {
    const domain = String(cookie.domain || '').replace(/^\./, '');
    return domain === 'fanqienovel.com' && names.test(cookie.name || '');
  });
  return {
    count: matched.length,
    has_sessionid: matched.some(cookie => cookie.name === 'sessionid')
  };
}

function exactElementExpression(text) {
  return `(() => {
    const wanted = ${JSON.stringify(text)};
    const priority = el => {
      if (el.tagName === 'BUTTON') return 0;
      if (el.tagName === 'A') return 1;
      if (el.getAttribute('role') === 'button') return 2;
      return 3;
    };
    const candidates = [...document.querySelectorAll('body *')]
      .map(el => {
        const label = (el.innerText || el.textContent || '').trim();
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return { el, label, rect, visible: !!(rect.width && rect.height && style.display !== 'none' && style.visibility !== 'hidden') };
      })
      .filter(item => item.visible && (item.label === wanted || item.label.replace(/\s+/g, '') === wanted || (item.label.includes(wanted) && item.label.length <= wanted.length + 4)))
      .sort((a, b) => priority(a.el) - priority(b.el) || (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
    const item = candidates[0];
    if (!item) return null;
    item.el.scrollIntoView({ block: 'center', inline: 'center' });
    const rect = item.el.getBoundingClientRect();
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      tag: item.el.tagName,
      text: item.label,
      viewport: { width: innerWidth, height: innerHeight }
    };
  })()`;
}

function directClickExpression(text) {
  return `(() => {
    const wanted = ${JSON.stringify(text)};
    const priority = el => el.tagName === 'BUTTON' ? 0 : el.tagName === 'A' ? 1 : el.getAttribute('role') === 'button' ? 2 : 3;
    const candidates = [...document.querySelectorAll('body *')]
      .filter(el => {
        const label = (el.innerText || el.textContent || '').trim();
        return label === wanted || label.replace(/\s+/g, '') === wanted || (label.includes(wanted) && label.length <= wanted.length + 4);
      })
      .map(el => ({ el, rect: el.getBoundingClientRect(), style: getComputedStyle(el) }))
      .filter(item => item.rect.width && item.rect.height && item.style.display !== 'none' && item.style.visibility !== 'hidden')
      .sort((a, b) => priority(a.el) - priority(b.el) || (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
    if (!candidates.length) return false;
    candidates[0].el.scrollIntoView({ block: 'center', inline: 'center' });
    candidates[0].el.click();
    return true;
  })()`;
}

async function realClick(Input, point) {
  await Input.dispatchMouseEvent({ type: 'mouseMoved', x: point.x, y: point.y });
  await Input.dispatchMouseEvent({ type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await Input.dispatchMouseEvent({ type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
}

async function findExact(Runtime, text) {
  return safeValue(Runtime, exactElementExpression(text));
}

async function waitForExact(Runtime, text, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await findExact(Runtime, text);
    if (found) return found;
    await sleep(250);
  }
  return null;
}

async function extractRawQr(Runtime) {
  return safeValue(Runtime, `(() => {
    const square = rect => rect.width >= 120 && rect.height >= 120 && Math.abs(rect.width - rect.height) < 10;
    const valid = data => typeof data === 'string' && /^data:image\\/png;base64,/i.test(data);
    const candidates = [];
    for (const img of document.images) {
      const rect = img.getBoundingClientRect();
      const data = img.currentSrc || img.src || '';
      if (square(rect) && valid(data)) candidates.push({ type: 'img', data, width: rect.width, height: rect.height });
    }
    for (const canvas of document.querySelectorAll('canvas')) {
      const rect = canvas.getBoundingClientRect();
      let data = '';
      try { data = canvas.toDataURL('image/png'); } catch (_) {}
      if (square(rect) && valid(data)) candidates.push({ type: 'canvas', data, width: rect.width, height: rect.height });
    }
    candidates.sort((a, b) => (b.width * b.height) - (a.width * a.height));
    return candidates[0] || null;
  })()`);
}

async function safeValue(Runtime, expression, awaitPromise = false, timeoutMs = 8000) {
  try {
    return await Promise.race([
      value(Runtime, expression, awaitPromise),
      rejectAfter(timeoutMs, 'Timed out while reading QR login page state')
    ]);
  } catch (_) {
    return undefined;
  }
}

function saveRawQr(raw, event) {
  const base64 = raw.data.replace(/^data:image\/png;base64,/i, '');
  const png = Buffer.from(base64, 'base64');
  const dimensions = pngDimensions(png);
  if (!dimensions || dimensions.width < 200 || dimensions.height < 200 || dimensions.width !== dimensions.height) {
    throw new Error(`QR asset failed PNG validation: ${JSON.stringify(dimensions)}`);
  }

  fs.mkdirSync(path.dirname(out), { recursive: true });
  const temporary = `${out}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, png);
  fs.renameSync(temporary, out);
  log(event, { out, source: raw.type, rendered: `${raw.width}x${raw.height}`, png: `${dimensions.width}x${dimensions.height}` });
}

// QR codes normally expire in a few minutes.  Keep one login lease alive and
// refresh only when the page explicitly reports expiry; this avoids silently
// leaving a user with a stale image or forcing a costly browser restart.
async function refreshExpiredQr(Runtime, previousData) {
  const text = await safeValue(Runtime, 'document.body ? document.body.innerText : ""');
  const indicatesExpiry = typeof text === 'string' &&
    /二维码(?:已)?(?:失效|过期)|(?:请|点击)?刷新(?:二维码)?/.test(text);
  if (!indicatesExpiry) return null;

  const clicked = await safeValue(Runtime, directClickExpression('点击刷新')) ||
    await safeValue(Runtime, directClickExpression('刷新二维码')) ||
    await safeValue(Runtime, directClickExpression('刷新'));
  if (!clicked) return null;
  log('QR_REFRESH_CLICKED');

  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    try {
      const fresh = await Promise.race([
        extractRawQr(Runtime),
        rejectAfter(8000, 'Timed out while waiting for refreshed QR')
      ]);
      if (fresh && fresh.data !== previousData) return fresh;
    } catch (_) {
      // A transient renderer stall is recoverable; retry until the bounded
      // refresh window elapses.
    }
    await sleep(300);
  }
  return null;
}

async function refreshExpiredQrAcrossPageTargets(previousData) {
  let targets;
  try {
    targets = await CDP.List({ port });
  } catch (_) {
    return null;
  }
  for (const target of targets.filter(item => item.type === 'page')) {
    let client;
    try {
      client = await CDP({ port, target });
      const refreshed = await refreshExpiredQr(client.Runtime, previousData);
      if (refreshed) return refreshed;
    } catch (_) {
      // Login popups can disappear during refresh; continue scanning live
      // Fanqie targets instead of sacrificing the whole login lease.
    } finally {
      await client?.close().catch(() => {});
    }
  }
  return null;
}

// The current writer portal sometimes opens its login sheet in a separate
// page target.  Looking only at the originating writer tab then falsely
// reports that "扫码登录" is absent.  Search every live Fanqie page target
// for a raw QR asset and, where necessary, select the scan tab there.
async function rawQrAcrossPageTargets() {
  let targets;
  try {
    targets = await CDP.List({ port });
  } catch (_) {
    return null;
  }
  for (const target of targets.filter(item => item.type === 'page')) {
    let client;
    try {
      client = await CDP({ port, target });
      const direct = await extractRawQr(client.Runtime);
      if (direct) return direct;
      const scan = await findExact(client.Runtime, '扫码登录');
      if (!scan) continue;
      await value(client.Runtime, directClickExpression('扫码登录'));
      const deadline = Date.now() + 4000;
      while (Date.now() < deadline) {
        const raw = await extractRawQr(client.Runtime);
        if (raw) return raw;
        await sleep(250);
      }
    } catch (_) {
      // A login popup can close while we enumerate it; continue with the
      // remaining live targets instead of treating that as a login failure.
    } finally {
      await client?.close().catch(() => {});
    }
  }
  return null;
}

async function openScanTab(Runtime, Input) {
  let scan = await findExact(Runtime, '扫码登录');
  if (!scan) {
    // Do not use a generic "登录" match here.  The password-login form has
    // its own submit button with that exact text, and clicking it strands the
    // flow on the wrong branch instead of opening the QR-capable dialog.
    const labels = ['立即登录', '登录/注册'];
    const entryDeadline = Date.now() + 120000;
    while (!scan && Date.now() < entryDeadline) {
      for (const label of labels) {
        const entry = await findExact(Runtime, label);
        if (!entry) continue;
        log('LOGIN_ENTRY_FOUND', { label, ...entry });
        // Prefer the framework-owned DOM click.  On recent writer-zone builds
        // a synthetic coordinate click can tear down the inspected target
        // while the login modal is mounting.
        const direct = await safeValue(Runtime, directClickExpression(label));
        if (!direct) await realClick(Input, entry);
        const popupDeadline = Date.now() + 30000;
        while (Date.now() < popupDeadline) {
          const popupRaw = await rawQrAcrossPageTargets();
          if (popupRaw) return popupRaw;
          await sleep(250);
        }
        // The writer portal can take tens of seconds to hydrate its modal on
        // this host.  Stay with the verified entry instead of immediately
        // falling back to an unrelated password-login submit control.
        scan = await waitForExact(Runtime, '扫码登录', 90000);
        if (scan) break;
        // A few versions of the page ignore the first low-level click.  This
        // fallback still clicks the exact DOM element, never a screenshot.
        await realClick(Input, entry);
        scan = await waitForExact(Runtime, '扫码登录', 30000);
        if (scan) break;
      }
      if (!scan) await sleep(250);
    }
  }

  if (!scan) {
    // Legacy writer-zone headers expose the login entry as an icon without a
    // text node.  Only use this as a final, viewport-relative fallback.
    const viewport = await safeValue(Runtime, '({ width: innerWidth, height: innerHeight })') || { width: 1050, height: 637 };
    const point = { x: Math.max(20, viewport.width - 110), y: 43 };
    log('LOGIN_ENTRY_FALLBACK', point);
    await realClick(Input, point);
    scan = await waitForExact(Runtime, '扫码登录', 60000);
  }

  if (!scan) {
    const body = await safeValue(Runtime, 'document.body ? document.body.innerText.slice(0, 1200) : "NO_BODY"') || 'PAGE_UNRESPONSIVE';
    const matching = await safeValue(Runtime,
      '(() => [...document.querySelectorAll("body *")]' +
      '.map(el => { const rect = el.getBoundingClientRect(); return {' +
      'tag: el.tagName, text: (el.innerText || el.textContent || "").trim().slice(0, 160),' +
      'x: rect.x, y: rect.y, width: rect.width, height: rect.height,' +
      'display: getComputedStyle(el).display, visibility: getComputedStyle(el).visibility }; })' +
      '.filter(item => item.text.includes("立即登录") || item.text === "登录" || item.text === "注册").slice(0, 24))()') || [];
    throw new Error('Could not open the login dialog; matching elements: ' + JSON.stringify(matching) + '; page text: ' + body);
  }

  log('SCAN_TAB_FOUND', scan);
  const directScan = await safeValue(Runtime, directClickExpression('扫码登录'));
  if (!directScan) await realClick(Input, scan);
  let raw = null;
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    raw = await extractRawQr(Runtime);
    if (raw) return raw;
    await sleep(300);
  }

  // The low-level event can be swallowed by the dialog transition.  Retry
  // using the same exact text selector, then look again for a raw QR asset.
  await safeValue(Runtime, directClickExpression('扫码登录'));
  const retryDeadline = Date.now() + 10000;
  while (Date.now() < retryDeadline) {
    raw = await extractRawQr(Runtime);
    if (raw) return raw;
    await sleep(300);
  }
  throw new Error('Raw QR image was not found after selecting 扫码登录');
}

async function waitForUsableWriterPage(Runtime, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = await safeValue(Runtime, `(() => ({
      ready: document.readyState,
      textLength: (document.body && document.body.innerText || '').trim().length,
      hasApp: !!document.querySelector('#app')
    }))()`);
    if (state && state.ready !== 'loading' && (state.textLength > 20 || state.hasApp)) return true;
    await sleep(500);
  }
  return false;
}

async function openQrWithPageRetries(Page, Runtime, Input) {
  let lastError = null;
  for (let attempt = 1; attempt <= 6; attempt++) {
    try {
      await Promise.race([
        Page.navigate({ url: writerLoginUrl }),
        rejectAfter(30000, `writer navigation timed out on attempt ${attempt}`)
      ]);
      const usable = await waitForUsableWriterPage(Runtime);
      if (!usable) throw new Error(`writer page remained blank on attempt ${attempt}`);
      return await openScanTab(Runtime, Input);
    } catch (error) {
      lastError = error;
      log('QR_OPEN_RETRY', { attempt, reason: error.message || String(error) });
      await sleep(Math.min(6000, 1200 * attempt));
    }
  }
  throw lastError || new Error('Could not open QR login after writer-page retries');
}

async function main() {
  const targets = await CDP.List({ port });
  const target = targets.find(item => item.type === 'page' && /fanqienovel\.com/.test(item.url || '')) || targets.find(item => item.type === 'page');
  if (!target) throw new Error(`No page target available on CDP port ${port}`);

  const client = await CDP({ port, target });
  const { Page, Runtime, Network, Storage, Input, Browser } = client;
  try {
    await Page.enable();
    await Runtime.enable();
    await Network.enable();

    if (fresh) {
      await Network.clearBrowserCookies();
      try {
        await Storage.clearDataForOrigin({ origin: 'https://fanqienovel.com', storageTypes: 'all' });
      } catch (_) {
        // Cookie clearing is the required part; Storage is unavailable in a
        // few Chromium builds and is only a best-effort supplement.
      }
    }

    const raw = await openQrWithPageRetries(Page, Runtime, Input);
    let rawData = raw.data;
    saveRawQr(raw, 'RAW_QR_READY');

    const deadline = Date.now() + waitMs;
    let lastExpiryProbe = 0;
    while (Date.now() < deadline) {
      const actual = await currentAccount(Runtime);
      if (actual) {
        if (actual !== expected) throw new Error(`Scanned into the wrong account: expected ${expected}, got ${actual}`);
        const cookieDeadline = Date.now() + 15000;
        let authEvidence = { count: 0, has_sessionid: false };
        while (Date.now() < cookieDeadline) {
          authEvidence = await authCookieEvidence(Network);
          if (authEvidence.has_sessionid) break;
          await sleep(500);
        }
        if (!authEvidence.has_sessionid) throw new Error('Login identity was returned, but a persistent Fanqie sessionid cookie was not available');
        log('LOGIN_SETTLING', { account: actual, auth_cookies: authEvidence.count, settle_ms: settleMs });
        await sleep(settleMs);
        const confirmed = await currentAccount(Runtime);
        if (confirmed !== expected) throw new Error('Login did not remain valid during cookie-settle window: ' + (confirmed || 'LOGIN_REQUIRED'));
        // Browser.close() allows Chromium to checkpoint Cookies before the
        // lease copies the profile.  Killing it immediately can lose a very
        // recent QR-login session on this host.
        try {
          await Browser.close();
        } catch (error) {
          throw new Error('Could not gracefully close browser for cookie checkpoint: ' + (error.message || String(error)));
        }
        await sleep(2000);
        log('LOGIN_OK', { account: actual, auth_cookies: authEvidence.count, checkpoint: 'graceful-close-requested' });
        return;
      }
      if (Date.now() - lastExpiryProbe >= 10000) {
        lastExpiryProbe = Date.now();
        const refreshed = await refreshExpiredQrAcrossPageTargets(rawData);
        if (refreshed) {
          rawData = refreshed.data;
          saveRawQr(refreshed, 'RAW_QR_REFRESHED');
        }
      }
      await sleep(2000);
    }
    throw new Error(`QR login timed out after ${Math.round(waitMs / 1000)} seconds`);
  } finally {
    await client.close().catch(() => {});
  }
}

main().catch(error => {
  console.error(`LOGIN_FAILED ${error && error.stack || error}`);
  process.exit(1);
});
