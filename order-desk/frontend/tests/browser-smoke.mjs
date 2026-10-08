// Real Chromium + same-origin Django session + directly authenticated runtime
// PostgreSQL. No dependency installation, mocked API, or main-database fixtures.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { createServer } from 'node:net';

const root = resolve(import.meta.dirname, '../..');
const scratch = resolve(root, 'backend/var/frontend-browser');
const container = `orderdesk-browser-${process.pid}`;
const chromePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
let chrome, server, ws, sequence = 0;
const pending = new Map();
const exceptions = [];
let dropConversionResponse = false;
// Refuse existing fixtures or occupied ports before entering owned cleanup.
assert.ok(!existsSync(resolve(root, 'backend/var/frontend_browser_fixture.json')),
  'An earlier browser fixture exists. Review it before rerunning.');
for (const port of [8001, 9223]) {
  await new Promise((resolve, reject) => {
    const probe = createServer(); probe.once('error', reject);
    probe.listen(port, '127.0.0.1', () => probe.close(resolve));
  });
}
function fixtures(action, orderId = null) {
  const result = spawnSync('docker', ['compose', 'run', '--rm', '-e', 'DATABASE_NAME=test_orderdesk',
    '-e', `FRONTEND_FIXTURE_ACTION=${action}`, ...(orderId ? ['-e', `FRONTEND_ORDER_ID=${orderId}`] : []), 'manage', 'python', 'manage.py', 'shell', '-c',
    "exec(open('/frontend/tests/browser_fixture.py').read())"], { cwd: root, windowsHide: true, encoding: 'utf8' });
  if (result.status !== 0) throw new Error(`Fixture ${action} failed: ${result.stderr}${result.stdout}`);
}
function command(method, params = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve, reject, timer }); ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const reply = await command('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (reply.exceptionDetails) throw new Error('Browser expression failed.');
  return reply.result.value;
}
async function waitFor(expression) {
  for (let count = 0; count < 150; count++) { if (await evaluate(expression)) return; await delay(100); }
  throw new Error(`Timed out waiting for: ${expression}`);
}
async function choose(id) {
  await evaluate(`document.getElementById('workspace').value=${JSON.stringify(id)}; document.getElementById('workspace').dispatchEvent(new Event('change'))`);
  await waitFor("!document.getElementById('workspace').disabled && document.querySelectorAll('#items tr').length > 0");
}
async function search(value) {
  await evaluate(`document.getElementById('search').value=${JSON.stringify(value)}; document.getElementById('search-form').requestSubmit()`);
  await waitFor("document.getElementById('catalogue').getAttribute('aria-busy') === 'false'");
}
try {
  await mkdir(scratch, { recursive: true });
  fixtures('create');
  const data = JSON.parse(await readFile(resolve(root, 'backend/var/frontend_browser_fixture.json'), 'utf8'));
  server = spawn('docker', ['compose', 'run', '--rm', '--name', container, '-p', '127.0.0.1:8001:8001',
    'rlscheck', 'python', 'manage.py', 'shell', '-c',
    "import sys; from django.conf import settings; from django.core.management import call_command; sys.path.insert(0, '/frontend/tests'); settings.WSGI_APPLICATION = 'browser_server.application'; call_command('check_runtime_role'); call_command('runserver', '0.0.0.0:8001', use_reloader=False)"],
    { cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let serverOutput = '';
  server.stdout.on('data', chunk => { serverOutput += chunk; });
  server.stderr.on('data', chunk => { serverOutput += chunk; });
  let ready = false;
  for (let i = 0; i < 120; i++) {
    try { ready = (await fetch('http://127.0.0.1:8001/api/v1/health/ready/')).ok; } catch {}
    if (ready || server.exitCode !== null) break;
    await delay(500);
  }
  assert.ok(ready, `Runtime server did not start: ${serverOutput}`);
  chrome = spawn(chromePath, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=9223', `--user-data-dir=${resolve(scratch, `profile-${process.pid}`)}`, 'about:blank'],
    { windowsHide: true, stdio: 'ignore' });
  let tabs;
  for (let i = 0; i < 100; i++) {
    try { tabs = await (await fetch('http://127.0.0.1:9223/json')).json(); } catch {}
    if (tabs?.find(tab => tab.type === 'page')) break;
    await delay(100);
  }
  const tab = tabs?.find(tab => tab.type === 'page');
  assert.ok(tab, 'Chromium remote debugging is unavailable.');
  ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => {
    const reply = JSON.parse(event.data);
    if (reply.method === 'Runtime.exceptionThrown') exceptions.push(reply.params);
    if (reply.method === 'Fetch.requestPaused') {
      if (dropConversionResponse && reply.params.responseStatusCode === 201) {
        dropConversionResponse = false;
        command('Fetch.failRequest', { requestId: reply.params.requestId, errorReason: 'ConnectionClosed' }).then(() => command('Fetch.disable')).catch(error => exceptions.push(error.message));
      } else command('Fetch.continueRequest', { requestId: reply.params.requestId }).catch(error => exceptions.push(error.message));
    }
    if (pending.has(reply.id)) {
      const entry = pending.get(reply.id); pending.delete(reply.id); clearTimeout(entry.timer);
      reply.error ? entry.reject(new Error(reply.error.message)) : entry.resolve(reply.result);
    }
  };
  await command('Runtime.enable'); await command('Page.enable');
  await command('Emulation.setDeviceMetricsOverride', { width: 1365, height: 900, deviceScaleFactor: 1, mobile: false });
  await command('Page.navigate', { url: 'http://127.0.0.1:8001/' });
  await waitFor("document.getElementById('login-panel') && !document.getElementById('login-panel').hidden");
  await evaluate(`document.getElementById('email').value=${JSON.stringify(data.email)}; document.getElementById('password').value='invalid-synthetic'; document.getElementById('login-form').requestSubmit()`);
  await waitFor("document.getElementById('notice').textContent.includes('Invalid email or password')");
  await evaluate(`document.getElementById('password').value=${JSON.stringify(data.password)}; document.getElementById('login-form').requestSubmit()`);
  await waitFor("!document.getElementById('desk').hidden && !document.getElementById('workspace').disabled");
  assert.equal(await evaluate("document.getElementById('catalogue').hidden"), true);
  await choose(data.a);
  assert.equal(await evaluate("document.querySelectorAll('#items tr').length"), 50);
  await evaluate("document.getElementById('next').click()");
  // The additional draft-match fixture is the 53rd catalogue item.
  await waitFor("document.querySelectorAll('#items tr').length === 3");
  await search('not-a-real-product');
  assert.equal(await evaluate("document.querySelectorAll('#items tr').length"), 0);
  await search('ALPHA-00');
  assert.equal(await evaluate("document.querySelectorAll('#items tr').length"), 10);
  await evaluate("document.getElementById('search').value=''; document.getElementById('activity').value='false'; document.getElementById('activity').dispatchEvent(new Event('change'))");
  await waitFor("document.querySelectorAll('#items tr').length === 1");
  assert.match(await evaluate("document.getElementById('items').textContent"), /ALPHA-051/);
  await choose(data.b);
  assert.match(await evaluate("document.getElementById('items').textContent"), /BETA-ONLY/);
  assert.equal(await evaluate("document.querySelectorAll('#items img').length"), 0);
  assert.equal(await evaluate("window.injected === true"), false);
  const shot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(resolve(scratch, 'catalogue-desktop.png'), Buffer.from(shot.data, 'base64'));
  await command('Page.reload');
  await waitFor("document.getElementById('items')?.textContent.includes('BETA-ONLY')");
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile viewport overflows.');
  const mobile = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(resolve(scratch, 'catalogue-mobile.png'), Buffer.from(mobile.data, 'base64'));
  await command('Emulation.setDeviceMetricsOverride', { width: 1365, height: 900, deviceScaleFactor: 1, mobile: false });
  await choose(data.a);
  await evaluate("document.getElementById('drafts-tab').click()");
  await waitFor("document.querySelectorAll('#draft-rows tr').length === 50");
  await evaluate("document.getElementById('draft-next').click()");
  await waitFor("document.querySelectorAll('#draft-rows tr').length === 3");
  await evaluate(`document.querySelector('#draft-rows a[href$="${data.blocked}/"]').click()`);
  await waitFor("document.querySelectorAll('#draft-blockers li').length === 3");
  assert.match(await evaluate("document.getElementById('draft-lines').textContent"), /Missing quantity/);
  assert.equal(await evaluate("document.getElementById('convert-draft').hidden"), true);
  await evaluate(`location.hash='#/workspaces/${data.a}/draft-orders/${data.foreign}/'`);
  await waitFor("document.getElementById('draft-detail-state').textContent.includes('not found')");
  assert.equal(await evaluate("document.getElementById('draft-content').hidden"), true);
  assert.equal(await evaluate("document.getElementById('draft-fields').textContent.includes('FOREIGN-DRAFT-PRIVATE')"), false);
  async function openReady() {
    await evaluate(`location.hash='#/workspaces/${data.a}/draft-orders/${data.ready}/'`);
    await waitFor("document.getElementById('draft-readiness-state').textContent === 'Ready for internal conversion' && document.querySelectorAll('#draft-lines tr').length === 50");
  }
  async function confirm() {
    await evaluate("document.getElementById('convert-draft').click()");
    await waitFor("document.getElementById('conversion-confirm').open");
    await evaluate("document.getElementById('confirm-conversion').click()");
  }
  await openReady();
  assert.match(await evaluate("document.getElementById('draft-lines').textContent"), /0001.Mixed-Case/);
  await evaluate("document.getElementById('draft-line-next').click()");
  await waitFor("document.querySelectorAll('#draft-lines tr').length === 2");
  assert.match(await evaluate("document.getElementById('draft-lines').textContent"), /999999999.999/);
  assert.equal(await evaluate("document.querySelectorAll('#draft-intake img').length"), 0);
  assert.equal(await evaluate("(async () => { const {csrf_token} = await (await fetch('/api/v1/auth/csrf/')).json(); return (await fetch(location.hash.slice(1).replace('/workspaces/', '/api/v1/workspaces/') + 'convert/', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf_token},body:'{}'})).status; })()"), 403);
  fixtures('assert_no_conversion');
  fixtures('admin'); await command('Page.reload');
  await waitFor("document.getElementById('draft-readiness-state').textContent === 'Ready for internal conversion' && !document.getElementById('convert-draft').disabled");
  // A cached admin UI does not bypass a fresh server demotion.
  fixtures('viewer'); await confirm();
  await waitFor("document.getElementById('convert-draft').hidden && document.getElementById('draft-message').textContent.includes('not permitted')");
  fixtures('assert_no_conversion');
  fixtures('admin'); await command('Page.reload');
  await waitFor("!document.getElementById('convert-draft').disabled");
  fixtures('deactivate'); await confirm();
  await waitFor("document.getElementById('draft-message').textContent.includes('not ready') && document.getElementById('convert-draft').disabled");
  assert.match(await evaluate("document.getElementById('draft-blockers').textContent"), /inactive/);
  fixtures('assert_no_conversion'); fixtures('reactivate');
  await evaluate("document.getElementById('draft-refresh').click()");
  await waitFor("document.getElementById('draft-readiness-state').textContent === 'Ready for internal conversion' && !document.getElementById('convert-draft').disabled");
  dropConversionResponse = true;
  await command('Fetch.enable', { patterns: [{ urlPattern: '*draft-orders/*/convert/', requestStage: 'Response' }] });
  await confirm();
  await waitFor("document.getElementById('draft-message').textContent.includes('unconfirmed') && !document.getElementById('convert-draft').disabled");
  assert.equal(await evaluate("document.getElementById('conversion-result').hidden"), true);
  // The committed response was lost; reconciliation must return the same row.
  await confirm();
  await waitFor("!document.getElementById('conversion-result').hidden && document.getElementById('draft-status').textContent.includes('Converted')");
  const orderId = (await evaluate("document.getElementById('conversion-id').textContent")).replace('Purchase-order ID: ', '');
  fixtures('assert_conversion', orderId);
  await confirm();
  await waitFor("document.getElementById('draft-message').textContent.includes('Existing internal') && !document.getElementById('convert-draft').disabled");
  fixtures('assert_conversion', orderId);
  await command('Page.reload');
  await waitFor("document.getElementById('draft-status').textContent.includes('Converted') && !document.getElementById('convert-draft').disabled");
  await confirm();
  await waitFor("document.getElementById('conversion-id').textContent.includes('Purchase-order ID:')");
  assert.equal((await evaluate("document.getElementById('conversion-id').textContent")).replace('Purchase-order ID: ', ''), orderId);
  const reviewShot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(resolve(scratch, 'draft-review-desktop.png'), Buffer.from(reviewShot.data, 'base64'));
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Draft mobile viewport overflows.');
  const reviewMobile = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(resolve(scratch, 'draft-review-mobile.png'), Buffer.from(reviewMobile.data, 'base64'));
  await evaluate("history.back()");
  await waitFor("document.getElementById('draft-detail-state').textContent.includes('not found')");
  await evaluate("history.forward()");
  await waitFor("document.getElementById('draft-status').textContent.includes('Converted') && !document.getElementById('draft-content').hidden");
  // Return to the existing catalogue revocation/logout regression.
  await choose(data.b);
  fixtures('revoke');
  await search('BETA');
  await waitFor("document.getElementById('notice').textContent.includes('access changed')");
  assert.equal(await evaluate("document.getElementById('catalogue').hidden"), true);
  assert.equal(await evaluate("document.querySelectorAll('#items tr').length"), 0);
  await evaluate("document.getElementById('logout').click()");
  await waitFor("!document.getElementById('login-panel').hidden");
  assert.equal(await evaluate("fetch('/api/v1/workspaces/', {credentials:'same-origin'}).then(r => r.status)"), 403);
  assert.deepEqual(exceptions, []);
  console.log('PASS: real browser session/catalogue regressions; draft/line pagination, direct/reload/history routes, blocked/ready review, viewer and demoted-admin denial, stale-readiness conflict, lost committed response, authorized replay and exact single-order/decimal snapshots.');
  console.log('Runtime server: orderdesk_app; synthetic fixtures: test_orderdesk; screenshots: ignored backend/var/frontend-browser/.');
} finally {
  if (ws?.readyState === WebSocket.OPEN) await command('Browser.close').catch(() => {});
  ws?.close(); chrome?.kill();
  if (server) spawnSync('docker', ['stop', container], { cwd: root, windowsHide: true, stdio: 'ignore' });
  server?.kill();
  fixtures('cleanup');
}
