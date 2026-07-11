#!/usr/bin/env node

const fs = require('fs');
const CDP = require('chrome-remote-interface');

function option(name, fallback = '') {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] || fallback : fallback;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function evaluate(Runtime, expression, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const result = await withTimeout(
        Runtime.evaluate({ expression, returnByValue: true, awaitPromise: false }),
        30000,
        'Runtime.evaluate'
      );
      if (result.exceptionDetails) {
        throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || 'Browser evaluation failed');
      }
      return result.result.value;
    } catch (error) {
      lastError = error;
      if (attempt < attempts) await sleep(2000 * attempt);
    }
  }
  throw lastError;
}

async function waitFor(Runtime, expression, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await evaluate(Runtime, expression);
    if (value) return value;
    await sleep(750);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function connect(port) {
  const targets = await withTimeout(CDP.List({ port }), 10000, 'CDP target listing');
  const target = targets.find(item => item.type === 'page' && item.url.includes('chatgpt.com'))
    || targets.find(item => item.type === 'page');
  if (!target) throw new Error(`No ChatGPT browser page on CDP port ${port}`);
  const client = await withTimeout(CDP({ port, target }), 10000, 'CDP connection');
  await withTimeout(client.Page.enable(), 10000, 'Page.enable');
  await withTimeout(client.Runtime.enable(), 10000, 'Runtime.enable');
  await withTimeout(client.DOM.enable(), 10000, 'DOM.enable');
  await withTimeout(client.Accessibility.enable(), 10000, 'Accessibility.enable');
  return client;
}

function loadPrompt() {
  const promptFile = option('--prompt-file');
  const prompt = option('--prompt');
  if (promptFile) return fs.readFileSync(promptFile, 'utf8').trim();
  if (prompt) return prompt.trim();
  throw new Error('Use --prompt or --prompt-file');
}

async function pageState(Runtime) {
  return evaluate(Runtime, `(() => {
    const messages = [...document.querySelectorAll('[data-message-author-role]')]
      .map(node => ({ role: node.getAttribute('data-message-author-role'), text: (node.innerText || '').trim() }))
      .filter(item => item.text);
    return {
      url: location.href,
      title: document.title,
      loginRequired: /Log in|Sign up/.test(document.body.innerText || '') && !document.querySelector('#prompt-textarea'),
      composerReady: Boolean(document.querySelector('#prompt-textarea[contenteditable="true"]')),
      generating: Boolean(document.querySelector('[data-testid="stop-button"], button[aria-label*="Stop"]')),
      messages,
      latestAssistant: [...messages].reverse().find(item => item.role === 'assistant')?.text || ''
    };
  })()`);
}

async function axPageState(Accessibility) {
  const result = await withTimeout(Accessibility.getFullAXTree(), 30000, 'Accessibility.getFullAXTree');
  const rows = (result.nodes || [])
    .map(node => ({ role: node.role?.value || '', name: node.name?.value || '' }))
    .filter(item => item.name);
  const staticTexts = rows.filter(item => item.role === 'StaticText').map(item => item.name);
  const marker = staticTexts.lastIndexOf('ChatGPT said:');
  const tail = marker >= 0 ? staticTexts.slice(marker + 1) : [];
  const response = tail
    .filter(text => !['ChatGPT can make mistakes. Check important info.', 'Follow up', 'High'].includes(text))
    .join('\n')
    .trim();
  return {
    generating: rows.some(item => item.role === 'button' && item.name === 'Stop answering'),
    loginRequired: rows.some(item => /Log in|Sign up/.test(item.name)),
    latestAssistant: response,
    title: rows.find(item => item.role === 'RootWebArea')?.name || ''
  };
}

async function waitForDomNode(DOM, selector, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const document = await withTimeout(DOM.getDocument({ depth: 2 }), 10000, 'DOM.getDocument');
      const match = await withTimeout(
        DOM.querySelector({ nodeId: document.root.nodeId, selector }),
        10000,
        `DOM.querySelector ${selector}`
      );
      if (match.nodeId) return match.nodeId;
    } catch (_) {
      // ChatGPT can briefly replace the document while navigating.
    }
    await sleep(750);
  }
  throw new Error(`Timed out waiting for DOM selector ${selector}`);
}

async function waitForCompletion(Runtime, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  let sawAssistant = false;
  let stableText = '';
  let stableSince = 0;
  let transientErrors = 0;
  while (Date.now() < deadline) {
    try {
      const state = await pageState(Runtime);
      transientErrors = 0;
      if (state.latestAssistant) {
        sawAssistant = true;
        if (state.latestAssistant !== stableText) {
          stableText = state.latestAssistant;
          stableSince = Date.now();
        }
        if (!state.generating && Date.now() - stableSince >= 5000) return state;
      }
    } catch (error) {
      transientErrors += 1;
      if (transientErrors >= 5) throw error;
    }
    await sleep(1500);
  }
  if (!sawAssistant) throw new Error('ChatGPT produced no assistant response before timeout');
  throw new Error(`ChatGPT response did not settle before ${timeoutSeconds}s timeout`);
}

async function waitForCompletionAX(Accessibility, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  let sawAssistant = false;
  let stableText = '';
  let stableSince = 0;
  let transientErrors = 0;
  while (Date.now() < deadline) {
    try {
      const state = await axPageState(Accessibility);
      transientErrors = 0;
      if (state.latestAssistant) {
        sawAssistant = true;
        if (state.latestAssistant !== stableText) {
          stableText = state.latestAssistant;
          stableSince = Date.now();
        }
        if (!state.generating && Date.now() - stableSince >= 5000) {
          const targets = await CDP.List({ port: Number(option('--port', '9224')) });
          const page = targets.find(item => item.type === 'page' && item.url.includes('chatgpt.com'));
          return { ...state, url: page?.url || '' };
        }
      }
    } catch (error) {
      transientErrors += 1;
      if (transientErrors >= 5) throw error;
    }
    await sleep(1500);
  }
  if (!sawAssistant) throw new Error('ChatGPT produced no assistant response before timeout');
  throw new Error(`ChatGPT response did not settle before ${timeoutSeconds}s timeout`);
}

async function sendPrompt(client, prompt, timeoutSeconds) {
  const { Page, DOM, Accessibility, Input } = client;
  await withTimeout(Page.navigate({ url: 'https://chatgpt.com/' }), 20000, 'ChatGPT navigation');
  const editorNode = await waitForDomNode(DOM, '#prompt-textarea[contenteditable="true"]', 45000);
  const initial = await axPageState(Accessibility);
  if (initial.loginRequired) throw new Error('LOGIN_REQUIRED');

  await withTimeout(DOM.focus({ nodeId: editorNode }), 10000, 'DOM.focus composer');
  await withTimeout(Input.insertText({ text: prompt }), 10000, 'Input.insertText prompt');
  await sleep(350);
  await withTimeout(Input.dispatchKeyEvent({ type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }), 10000, 'Enter key down');
  await withTimeout(Input.dispatchKeyEvent({ type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }), 10000, 'Enter key up');

  const conversationDeadline = Date.now() + 30000;
  while (Date.now() < conversationDeadline) {
    const targets = await CDP.List({ port: Number(option('--port', '9224')) });
    const page = targets.find(item => item.type === 'page' && item.url.includes('chatgpt.com'));
    if (page?.url.includes('/c/')) break;
    await sleep(750);
  }
  return waitForCompletionAX(Accessibility, timeoutSeconds);
}

async function main() {
  const port = Number(option('--port', '9224'));
  const timeoutSeconds = Number(option('--wait-seconds', '600'));
  const output = option('--output');
  const observeCurrent = process.argv.includes('--observe-current');
  const prompt = observeCurrent ? '' : loadPrompt();
  const client = await connect(port);
  try {
    const state = observeCurrent
      ? await waitForCompletionAX(client.Accessibility, timeoutSeconds)
      : await sendPrompt(client, prompt, timeoutSeconds);
    const result = {
      status: 'completed',
      url: state.url,
      title: state.title,
      response: state.latestAssistant
    };
    if (output) fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n', 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await client.close();
  }
}

main().catch(error => {
  const result = { status: 'failed', error: error.stack || String(error) };
  const output = option('--output');
  if (output) fs.writeFileSync(output, JSON.stringify(result, null, 2) + '\n', 'utf8');
  console.error(JSON.stringify(result, null, 2));
  process.exit(1);
});
