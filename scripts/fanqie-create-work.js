#!/usr/bin/env node
/* Create or inspect a Fanqie work through the logged-in writer browser.
 *
 * This is deliberately browser-driven: it does not call undocumented create
 * APIs or bypass writer-center validation.  Run it through
 * fanqie-account-cache.sh with so the account browser lease is held for the
 * whole transaction.
 */

const CDP = require('chrome-remote-interface');
const fs = require('fs');

function option(name, fallback = '') {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] || fallback : fallback;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function emit(value) {
  const serialized = JSON.stringify(value, null, 2);
  const output = option('--output');
  if (output) fs.writeFileSync(output, `${serialized}\n`, 'utf8');
  console.log(serialized);
}

async function clickVisibleText(Runtime, text) {
  const result = await Runtime.evaluate({
    returnByValue: true,
    expression: `(() => {
      const needle = ${JSON.stringify('PLACEHOLDER')};
      const visible = (node) => {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      };
      const nodes = [...document.querySelectorAll('button,a,[role="button"],div,span')]
        .filter(node => visible(node) && (node.innerText || node.textContent || '').trim() === needle);
      const node = nodes.find(item => ![...item.children].some(child => visible(child) && (child.innerText || child.textContent || '').trim() === needle)) || nodes[0];
      if (!node) return {ok: false};
      node.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
      node.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
      node.click();
      return {ok: true, tag: node.tagName, cls: node.className || ''};
    })()`.replace('PLACEHOLDER', JSON.stringify(text)),
  });
  if (!result.result.value || !result.result.value.ok) throw new Error(`Could not click visible text: ${text}`);
}

async function main() {
  const port = Number(option('--port', '9223'));
  const mode = option('--mode', 'inspect');
  const targets = await CDP.List({port});
  const target = targets.find((item) => item.type === 'page' && item.url.includes('fanqienovel.com'))
    || targets.find((item) => item.type === 'page');
  if (!target) throw new Error(`No browser page is available on CDP port ${port}`);
  const client = await CDP({port, target});
  try {
    const {Page, Runtime} = client;
    await Page.enable();
    await Page.navigate({url: 'https://fanqienovel.com/main/writer/book-manage'});
    let createReady = false;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      const ready = await Runtime.evaluate({
        returnByValue: true,
        expression: `Boolean(document.querySelector('.write-button'))`,
      });
      if (ready.result.value) {
        createReady = true;
        break;
      }
      await sleep(1000);
    }
    if (!createReady) {
      throw new Error('Timed out waiting for the Fanqie create-work control');
    }

    if (!['inspect', 'form'].includes(mode)) {
      throw new Error(`Unsupported mode: ${mode}`);
    }

    const hover = await Runtime.evaluate({
      returnByValue: true,
      expression: `(() => {
        const button = document.querySelector('.write-button');
        if (!button) return {ok: false, error: 'create button not found'};
        for (const type of ['pointerover', 'mouseover', 'mouseenter', 'mousemove']) {
          button.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
        }
        return {ok: true, rect: button.getBoundingClientRect().toJSON()};
      })()`,
    });
    await sleep(800);
    if (mode === 'form') {
      const opened = await Runtime.evaluate({
        returnByValue: true,
        expression: `(() => {
          const node = document.querySelector('.write-button-dropdown-item:nth-child(2)');
          if (!node) return false;
          node.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
          node.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
          node.click();
          return true;
        })()`,
      });
      if (!opened.result.value) throw new Error('Could not locate the create-book menu item');
      await sleep(1800);
    }
    const result = await Runtime.evaluate({
      returnByValue: true,
      expression: `(() => ({
        url: location.href,
        text: document.body.innerText.slice(-5000),
        createButton: document.querySelector('.write-button')?.outerHTML || '',
        popupNodes: [...document.querySelectorAll('[class*="popup"], [class*="popover"], [role="dialog"]')]
          .filter((node) => node.getBoundingClientRect().width > 0 && node.getBoundingClientRect().height > 0)
          .map((node) => ({text: (node.innerText || '').trim(), html: node.outerHTML.slice(0, 5000)})),
        inputs: [...document.querySelectorAll('input,textarea')].map((node) => ({
          tag: node.tagName,
          type: node.type || '',
          name: node.name || '',
          placeholder: node.placeholder || '',
          value: node.value || '',
          html: node.outerHTML.slice(0, 1200)
        })),
        controls: [...document.querySelectorAll('button,a,[role="button"]')]
          .filter((node) => (node.innerText || node.textContent || '').trim().includes('创建'))
          .map((node) => ({text: (node.innerText || node.textContent || '').trim(), html: node.outerHTML.slice(0, 1600)})),
        createCandidates: [...document.querySelectorAll('button,a,[role="button"],div,span')]
          .filter((node) => (node.innerText || node.textContent || '').trim().includes('创建书本'))
          .map((node) => ({
            text: (node.innerText || node.textContent || '').trim(),
            visible: node.getBoundingClientRect().width > 0 && node.getBoundingClientRect().height > 0,
            html: node.outerHTML.slice(0, 1800)
          })),
      }))()`,
    });
    emit({hover: hover.result.value, page: result.result.value});
  } finally {
    await client.close();
  }
}

main().catch((error) => {
  const output = option('--output');
  if (output) fs.writeFileSync(output, JSON.stringify({error: error.stack || String(error)}, null, 2) + '\n', 'utf8');
  console.error(error.stack || error);
  process.exit(1);
});
