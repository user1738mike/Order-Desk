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
let chrome, secondaryChrome, secondarySocket, server, ws, sequence = 0;
let closeSecondBrowser;
const pending = new Map();
const exceptions = [];
let dropConversionResponse = false;
let dropApplicationResponse = false;
let submittedApplication;
let acceptNextDialog = false;
// Refuse existing fixtures or occupied ports before entering owned cleanup.
assert.ok(!existsSync(resolve(root, 'backend/var/frontend_browser_fixture.json')),
  'An earlier browser fixture exists. Review it before rerunning.');
for (const port of [8001, 9223, 9224]) {
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
    '-e', 'PRIVATE_DOCUMENT_ROOT=/tmp/orderdesk-private-browser',
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
    if (reply.method === 'Page.javascriptDialogOpening') {
      const accept = acceptNextDialog; acceptNextDialog = false;
      command('Page.handleJavaScriptDialog', { accept }).catch(error => exceptions.push(error.message));
    }
    if (reply.method === 'Fetch.requestPaused') {
      if ((dropConversionResponse || dropApplicationResponse) && reply.params.responseStatusCode === 201) {
        if (dropApplicationResponse) submittedApplication = JSON.parse(reply.params.request.postData);
        dropConversionResponse = false; dropApplicationResponse = false;
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
    await waitFor("document.getElementById('draft-readiness-state').textContent === 'Ready for internal conversion' && document.querySelectorAll('#draft-lines tr').length === 50 && !document.getElementById('draft-line-next').disabled");
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
  // Manual editing uses a separate source, preserving the conversion fixture.
  const field = async (id, value) => evaluate(`document.getElementById(${JSON.stringify(id)}).value=${JSON.stringify(value)}; document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('input', {bubbles:true}))`);
  const editOpen = () => waitFor("document.getElementById('draft-editor').open");
  const saveEdit = async () => {
    await evaluate("document.getElementById('editor-form').requestSubmit()");
    await waitFor("!document.getElementById('draft-editor').open && !document.getElementById('edit-header').hidden");
  };
  await evaluate("document.getElementById('new-draft').click()"); await editOpen();
  await field('edit-customer-name', 'Manual Browser Customer'); await field('edit-customer-reference', '00042');
  await field('edit-intake', '<img src=x onerror=window.injected=true> Synthetic manual intake');
  await saveEdit();
  await waitFor("document.getElementById('draft-fields').textContent.includes('Manual Browser Customer') && document.getElementById('draft-blockers').textContent.includes('requested line')");
  const manualId = (await evaluate('location.hash')).split('/').at(-2);
  assert.equal(await evaluate("document.querySelectorAll('#draft-intake img').length"), 0);
  await evaluate("document.getElementById('edit-header').click()"); await editOpen();
  await field('edit-customer-name', '\u2003');
  await evaluate("document.getElementById('editor-form').requestSubmit()");
  await waitFor("document.querySelector('[data-error=customer_name]').textContent.includes('nonblank')");
  await field('edit-customer-name', 'Unsaved operator value');
  const manualHash = await evaluate('location.hash');
  await evaluate(`location.hash='#/workspaces/${data.a}/draft-orders/'`);
  await waitFor(`location.hash===${JSON.stringify(manualHash)} && document.getElementById('draft-editor').open`);
  assert.equal(await evaluate("document.getElementById('edit-customer-name').value"), 'Unsaved operator value');
  // A second real browser profile has its own cookie/authentication session.
  const base = 'http://127.0.0.1:8001';
  secondaryChrome = spawn(chromePath, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=9224', `--user-data-dir=${resolve(scratch, `second-profile-${process.pid}`)}`, 'about:blank'],
    { windowsHide: true, stdio: 'ignore' });
  let secondaryTab;
  for (let i = 0; i < 100; i++) {
    try { secondaryTab = (await (await fetch('http://127.0.0.1:9224/json')).json()).find(tab => tab.type === 'page'); } catch {}
    if (secondaryTab) break; await delay(100);
  }
  assert.ok(secondaryTab, 'Second browser session unavailable.');
  secondarySocket = new WebSocket(secondaryTab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { secondarySocket.onopen = resolve; secondarySocket.onerror = reject; });
  let secondarySequence = 0;
  function secondCommand(method, params = {}) {
    const id = ++secondarySequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Second browser command timed out.')), 15000);
      secondarySocket.onmessage = event => {
        const reply = JSON.parse(event.data);
        if (reply.method === 'Runtime.exceptionThrown') exceptions.push('Second browser reported an uncaught exception.');
        if (reply.id !== id) return;
        clearTimeout(timer); reply.error ? reject(new Error(reply.error.message)) : resolve(reply.result);
      };
      secondarySocket.send(JSON.stringify({ id, method, params }));
    });
  }
  closeSecondBrowser = () => secondCommand('Browser.close').catch(() => {});
  await secondCommand('Runtime.enable');
  await secondCommand('Page.navigate', { url: base + '/' });
  for (let i = 0; i < 100; i++) {
    const result = await secondCommand('Runtime.evaluate', { expression: "location.origin==='http://127.0.0.1:8001' && document.readyState==='complete'", returnByValue: true });
    if (result.result.value) break; await delay(100);
  }
  async function secondRequest(path, method = 'GET', body = undefined, revision = null) {
    const expression = `(async () => {
      const token = ${method !== 'GET'} ? (await (await fetch('/api/v1/auth/csrf/', {credentials:'same-origin'})).json()).csrf_token : null;
      const response = await fetch(${JSON.stringify(path)}, {method:${JSON.stringify(method)},credentials:'same-origin',redirect:'error',headers:{
        ...(${body !== undefined} ? {'Content-Type':'application/json','X-CSRFToken':token} : {}),
        ...(${Boolean(revision)} ? {'If-Match':${JSON.stringify(`"${revision}"`)}} : {})
      }, ...(${body !== undefined} ? {body:${JSON.stringify(JSON.stringify(body) ?? '')}} : {})});
      return {status:response.status,data:await response.json()};
    })()`;
    const reply = await secondCommand('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    assert.ok(!reply.exceptionDetails, 'Second browser API request failed.'); return reply.result.value;
  }
  assert.equal((await secondRequest('/api/v1/auth/login/', 'POST', { email: data.email, password: data.password })).status, 200);
  const manualPath = `/api/v1/workspaces/${data.a}/draft-orders/${manualId}/`;
  const secondRevision = (await secondRequest(manualPath + 'revision/')).data.revision;
  assert.equal((await secondRequest(manualPath, 'PATCH', { customer_name: 'Other session winner' }, secondRevision)).status, 200);
  await evaluate("document.getElementById('editor-form').requestSubmit()");
  await waitFor("document.getElementById('editor-message').textContent.includes('Server data changed') && document.getElementById('editor-save').disabled");
  assert.equal(await evaluate("document.getElementById('edit-customer-name').value"), 'Unsaved operator value');
  assert.equal((await secondRequest(manualPath)).data.customer_name, 'Other session winner');
  acceptNextDialog = true; await evaluate("document.getElementById('editor-reload').click()");
  await waitFor("document.getElementById('edit-customer-name').value === 'Other session winner' && !document.getElementById('editor-save').disabled");
  await field('edit-customer-reference', ''); await saveEdit();
  assert.equal((await secondRequest(manualPath)).data.customer_reference, '');
  await evaluate("document.getElementById('add-line').click()"); await editOpen();
  await field('edit-position', '1'); await field('edit-requested-sku', '0001.Mixed-Case');
  await field('edit-requested-description', '<script>not executable</script> Requested text');
  await field('edit-quantity', '1.234'); await field('edit-unit', 'ea'); await saveEdit();
  await waitFor("document.querySelectorAll('#draft-lines tr').length===1 && document.getElementById('draft-blockers').textContent.includes('Attach unmatched')");
  await evaluate("[...document.querySelectorAll('#draft-lines button')].find(b => b.textContent==='Edit line').click()"); await editOpen();
  await field('edit-quantity', '999999999.999'); await saveEdit();
  await waitFor("document.getElementById('draft-lines').textContent.includes('999999999.999')");
  await evaluate("[...document.querySelectorAll('#draft-lines button')].find(b => b.textContent==='Attach catalogue').click()"); await editOpen();
  await waitFor("document.querySelectorAll('#attach-item option').length===51 && !document.getElementById('attach-next').disabled");
  await evaluate("document.getElementById('attach-next').click()");
  await waitFor("document.getElementById('attach-page').textContent==='Page 2' && document.querySelectorAll('#attach-item option').length===3");
  await field('attach-query', '0001.Mixed-Case'); await evaluate("document.getElementById('attach-search').click()");
  await waitFor("document.querySelectorAll('#attach-item option').length===2 && document.getElementById('attach-item').textContent.includes('0001.Mixed-Case')");
  const itemId = await evaluate("document.getElementById('attach-item').options[1].value");
  await field('attach-item', itemId); await saveEdit();
  await waitFor("document.getElementById('draft-readiness-state').textContent === 'Ready for internal conversion' && !document.getElementById('convert-draft').disabled");
  const matchedLine = (await secondRequest(manualPath + 'lines/')).data.results[0];
  assert.equal(matchedLine.quantity, '999999999.999'); assert.equal(matchedLine.catalogue_item_id, itemId);
  await evaluate("[...document.querySelectorAll('#draft-lines button')].find(b => b.textContent==='Detach catalogue').click()"); await editOpen(); await saveEdit();
  await waitFor("document.getElementById('draft-blockers').textContent.includes('Attach unmatched')");
  const detachedLine = (await secondRequest(manualPath + 'lines/')).data.results[0];
  for (const key of ['id', 'requested_sku', 'requested_description', 'quantity', 'unit']) assert.equal(detachedLine[key], matchedLine[key]);
  assert.equal(detachedLine.catalogue_item_id, null); assert.equal(detachedLine.catalogue_sku_snapshot, ''); assert.equal(detachedLine.catalogue_description_snapshot, '');
  await evaluate("document.getElementById('matching-load').click()");
  await waitFor("document.querySelector('#matching-results button') && !document.querySelector('#matching-results button').disabled");
  assert.match(await evaluate("document.getElementById('matching-results').textContent"), /exact-sku-v1.*case, punctuation and leading zeros preserved/);
  assert.match(await evaluate("document.getElementById('matching-results').textContent"), /Units and prices: not modeled/);
  const matchingRevision = (await secondRequest(manualPath + 'revision/')).data.revision;
  assert.equal((await secondRequest(manualPath, 'PATCH', { customer_reference: 'Matching concurrent edit' }, matchingRevision)).status, 200);
  await evaluate("document.querySelector('#matching-results button').click()");
  await waitFor("document.getElementById('matching-message').textContent.includes('Reload and compare')");
  assert.equal((await secondRequest(`${manualPath}lines/${detachedLine.id}/`)).data.catalogue_item_id, null);
  await evaluate("document.getElementById('matching-reload').click()");
  await waitFor("document.querySelector('#matching-results button') && !document.querySelector('#matching-results button').disabled");
  assert.equal((await secondRequest(`/api/v1/workspaces/${data.a}/catalog/items/${itemId}/`, 'PATCH', { is_active: false })).status, 200);
  await evaluate("document.querySelector('#matching-results button').click()");
  await waitFor("document.getElementById('matching-message').textContent.includes('Reload and compare')");
  assert.equal((await secondRequest(`${manualPath}lines/${detachedLine.id}/`)).data.catalogue_item_id, null);
  assert.equal((await secondRequest(`/api/v1/workspaces/${data.a}/catalog/items/${itemId}/`, 'PATCH', { is_active: true })).status, 200);
  await evaluate("document.getElementById('matching-reload').click()");
  await waitFor("document.querySelector('#matching-results button') && !document.querySelector('#matching-results button').disabled");
  await evaluate("document.querySelector('#matching-results button').click()");
  await waitFor("document.getElementById('matching-results').textContent.includes('already attached') && document.getElementById('draft-readiness-state').textContent==='Ready for internal conversion'");
  const suggestedLine = (await secondRequest(`${manualPath}lines/${detachedLine.id}/`)).data;
  assert.equal(suggestedLine.catalogue_item_id, itemId);
  for (const fieldName of ['requested_sku', 'requested_description', 'quantity', 'unit']) assert.equal(suggestedLine[fieldName], detachedLine[fieldName]);
  const matchingShot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(resolve(scratch, 'catalogue-matching-desktop.png'), Buffer.from(matchingShot.data, 'base64'));
  // Keep the following manual/unmatched regressions in their original state.
  await evaluate("[...document.querySelectorAll('#draft-lines button')].find(b => b.textContent==='Detach catalogue').click()"); await editOpen(); await saveEdit();
  await waitFor("document.getElementById('draft-blockers').textContent.includes('Attach unmatched')");
  await evaluate("document.getElementById('matching-load').click()");
  await waitFor("document.querySelector('#matching-results button') && !document.querySelector('#matching-results button').disabled");
  fixtures('viewer');
  let deniedMatchingStatus;
  const deniedMatchingHandler = ws.onmessage;
  ws.onmessage = event => { const reply = JSON.parse(event.data); if (reply.method === 'Fetch.requestPaused' && reply.params.request.url.includes('/accept-suggestion/')) deniedMatchingStatus = reply.params.responseStatusCode; deniedMatchingHandler(event); };
  await command('Fetch.enable', { patterns: [{ urlPattern: '*accept-suggestion/*', requestStage: 'Response' }] });
  await evaluate("document.querySelector('#matching-results button').click()");
  for (let count = 0; count < 100 && deniedMatchingStatus === undefined; count++) await delay(50);
  assert.equal(deniedMatchingStatus, 403);
  await command('Fetch.disable'); ws.onmessage = deniedMatchingHandler;
  // The access recheck reloads draft state, replacing the transient message.
  await waitFor("document.getElementById('role').textContent.includes('viewer') && !document.querySelector('#matching-results button')");
  assert.equal((await secondRequest(`${manualPath}lines/${detachedLine.id}/`)).data.catalogue_item_id, null);
  fixtures('admin'); await command('Page.reload');
  await waitFor("document.getElementById('draft-lines').textContent.includes('0001.Mixed-Case') && !document.getElementById('matching-load').disabled");
  // Hold an actual authorized response until the workspace has changed.
  let delayedMatching;
  let matchingRequest, matchingCanceled = false;
  const matchingMessageHandler = ws.onmessage;
  ws.onmessage = event => { const reply = JSON.parse(event.data); if (reply.method === 'Network.requestWillBeSent' && reply.params.request.url.includes('/suggestions/')) matchingRequest = reply.params.requestId; if (reply.method === 'Network.loadingFailed' && reply.params.requestId === matchingRequest) matchingCanceled = reply.params.canceled === true; if (reply.method === 'Fetch.requestPaused' && reply.params.request.url.includes('/suggestions/')) { delayedMatching = reply.params.requestId; return; } matchingMessageHandler(event); };
  await command('Network.enable');
  await command('Fetch.enable', { patterns: [{ urlPattern: '*draft-orders/*/suggestions/*', requestStage: 'Response' }] });
  await evaluate("document.getElementById('matching-load').click()");
  for (let count = 0; count < 100 && !delayedMatching; count++) await delay(50);
  assert.ok(delayedMatching, 'Expected the authorized matching response to be held.');
  await choose(data.b);
  try { await command('Fetch.continueRequest', { requestId: delayedMatching }); }
  catch (error) { assert.match(error.message, /Invalid InterceptionId/); assert.equal(matchingCanceled, true, 'The obsolete response must have been canceled by the browser.'); }
  await command('Fetch.disable'); await command('Network.disable'); ws.onmessage = matchingMessageHandler;
  assert.equal(await evaluate("document.getElementById('catalogue-suggestions').hidden"), true);
  assert.equal(await evaluate("document.getElementById('matching-results').textContent.includes('0001.Mixed-Case')"), false);
  await choose(data.a);
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.a}/draft-orders/${manualId}/`)}`);
  await waitFor("document.getElementById('draft-lines').textContent.includes('0001.Mixed-Case') && !document.getElementById('edit-header').disabled");
  const manualShot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(resolve(scratch, 'manual-draft-desktop.png'), Buffer.from(manualShot.data, 'base64'));
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate("document.getElementById('edit-header').click()"); await editOpen();
  assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Manual editing mobile viewport overflows.');
  const manualMobile = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  await writeFile(resolve(scratch, 'manual-draft-mobile.png'), Buffer.from(manualMobile.data, 'base64'));
  await evaluate("document.getElementById('editor-discard').click()");
  await command('Emulation.setDeviceMetricsOverride', { width: 1365, height: 900, deviceScaleFactor: 1, mobile: false });
  await openReady();
  // A cached admin UI does not bypass a fresh server demotion.
  fixtures('viewer'); await confirm();
  await waitFor("document.getElementById('convert-draft').hidden && document.getElementById('draft-message').textContent.includes('not permitted')");
  fixtures('assert_no_conversion');
  fixtures('admin'); await command('Page.reload');
  await waitFor("!document.getElementById('convert-draft').disabled");
  fixtures('deactivate'); await confirm();
  await waitFor("document.getElementById('draft-message').textContent.includes('not ready') && document.getElementById('convert-draft').disabled && document.getElementById('draft-blockers').textContent.includes('inactive')");
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
  assert.equal(await evaluate("document.getElementById('edit-header').hidden && document.getElementById('add-line').hidden && document.querySelectorAll('#draft-lines button').length===0"), true);
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
  await waitFor(`location.hash===${JSON.stringify(manualHash)} && document.getElementById('draft-fields').textContent.includes('Other session winner')`);
  await evaluate("history.forward()");
  await waitFor("document.getElementById('draft-status').textContent.includes('Converted') && !document.getElementById('draft-content').hidden");
  // Source documents belong to the confirmed purchase order, not its source draft.
  await evaluate(`location.hash='#/workspaces/${data.a}/orders/${orderId}/documents/'`);
  await waitFor("!document.getElementById('documents-screen').hidden && document.getElementById('documents-empty').textContent==='No source documents listed.' && !document.getElementById('documents-refresh').disabled");
  const sourcePdf = '%PDF-1.7\nSynthetic local source\n%%EOF\n';
  const sourceCsv = 'sku,quantity\r\n0001.Mixed-Case,1.234\r\n';
  async function pickDocument(name, bytes) {
    await evaluate(`(() => { const transfer = new DataTransfer(); transfer.items.add(new File([${JSON.stringify(bytes)}], ${JSON.stringify(name)}, {type:'application/octet-stream'})); const picker=document.getElementById('document-file'); picker.files=transfer.files; picker.dispatchEvent(new Event('change')); })()`);
  }
  // Independently author a tiny text PDF with explicit font/table layout. The
  // browser uploads real bytes; no parser response or provenance is fabricated.
  function syntheticTextPdf(lines) {
    const escape = value => value.replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)');
    const stream = ['BT /F1 10 Tf 14 TL 50 742 Td', ...lines.flatMap((line, index) => [...(index ? ['T*'] : []), `(${escape(line)}) Tj`]), 'ET'].join('\n');
    const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Count 1 /Kids [4 0 R] >>', '<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>', `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];
    let result = '%PDF-1.4\n'; const offsets = [0];
    objects.forEach((object, index) => { offsets.push(result.length); result += `${index + 1} 0 obj\n${object}\nendobj\n`; });
    const xref = result.length;
    return result + `xref\n0 ${offsets.length}\n0000000000 65535 f \n` + offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('') + `trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  }
  await pickDocument('empty.pdf', ''); assert.match(await evaluate("document.getElementById('documents-message').textContent"), /nonempty/);
  await pickDocument('unsafe.html', '<script>alert(1)</script>'); assert.equal(await evaluate("document.getElementById('document-upload').disabled"), true);
  await pickDocument('malformed.pdf', 'not pdf'); await evaluate("document.getElementById('document-upload-form').requestSubmit()");
  await waitFor("document.getElementById('documents-message').textContent.includes('supported signature') && !document.getElementById('document-upload').disabled");
  for (const [name, bytes] of [['source.pdf', sourcePdf], ['0001.Mixed-Case.csv', sourceCsv]]) {
    await pickDocument(name, bytes); await evaluate("document.getElementById('document-upload-form').requestSubmit()");
    await waitFor(`document.getElementById('documents-rows').textContent.includes(${JSON.stringify(name)}) && document.getElementById('documents-message').textContent.includes('Source received')`);
  }
  assert.match(await evaluate("document.getElementById('documents-rows').textContent"), /Received.*not automatically reviewed/);
  const documentBase = `/api/v1/workspaces/${data.a}/orders/${orderId}/documents/`;
  const listedDocuments = await evaluate(`fetch(${JSON.stringify(documentBase + 'intake/')}).then(r=>r.json())`);
  assert.equal(listedDocuments.count, 2);
  for (const row of listedDocuments.results) {
    const bytes = await evaluate(`fetch(${JSON.stringify(row.download_url)}).then(async r=>({status:r.status,bytes:await r.text(),disposition:r.headers.get('Content-Disposition'),cache:r.headers.get('Cache-Control'),nosniff:r.headers.get('X-Content-Type-Options')}))`);
    assert.equal(bytes.status, 200); assert.equal(bytes.bytes, row.original_name.endsWith('.pdf') ? sourcePdf : sourceCsv);
    assert.match(bytes.disposition, /^attachment;/); assert.match(bytes.cache, /no-store/); assert.equal(bytes.nosniff, 'nosniff');
    assert.equal(await evaluate(`fetch(${JSON.stringify(row.download_url.replace(data.a, data.b))}).then(r=>r.status)`), 404);
  }
  // Invoke the actual Download control and verify the browser's saved source bytes.
  const downloadDirectory = resolve(scratch, `downloads-${process.pid}`);
  await mkdir(downloadDirectory, { recursive: true });
  await command('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloadDirectory });
  await evaluate("document.querySelector('#documents-rows button').click()");
  const firstDocument = listedDocuments.results[0];
  for (let count=0; count<100 && !existsSync(resolve(downloadDirectory, firstDocument.original_name)); count++) await delay(100);
  assert.equal(await readFile(resolve(downloadDirectory, firstDocument.original_name), 'utf8'), firstDocument.original_name.endsWith('.csv') ? sourceCsv : sourcePdf);
  // Queue from the actual operator UI; a separate restricted process dies after
  // claiming, then another invocation recovers the durable expired lease.
  await evaluate("[...document.querySelectorAll('#documents-rows button')].find(b=>b.textContent==='CSV extraction').click()");
  await waitFor("!document.getElementById('extraction-queue').disabled");
  await evaluate("document.getElementById('extraction-queue').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('Queued')");
  const csvDocument = listedDocuments.results.find(row => row.original_name.endsWith('.csv'));
  const queued = await evaluate(`fetch(${JSON.stringify(csvDocument.extraction_url)}).then(r=>r.json())`);
  const crashScript = "import os; from unittest.mock import patch; from django.core.management import call_command\nwith patch('apps.orders.extraction_services.LEASE_SECONDS', -1), patch('apps.orders.extraction_services.extract_csv', side_effect=lambda source: os._exit(9)):\n call_command('process_csv_extraction', workspace='" + data.a + "', actor='" + data.user + "', job='" + queued.job.id + "')";
  const crashed = spawnSync('docker', ['exec', container, 'python', 'manage.py', 'shell', '-c', crashScript], { cwd: root, windowsHide: true, encoding: 'utf8' });
  assert.equal(crashed.status, 9, 'Synthetic processor must exit after durable claim.');
  await evaluate("document.getElementById('extraction-refresh').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('lease expired')");
  function processCSV(jobId) {
    const result = spawnSync('docker', ['exec', container, 'python', 'manage.py', 'process_csv_extraction', '--workspace', data.a, '--actor', data.user, '--job', jobId], { cwd: root, windowsHide: true, encoding: 'utf8' });
    assert.equal(result.status, 0, `Restricted CSV processor failed: ${result.stderr}`);
  }
  processCSV(queued.job.id);
  await evaluate("document.getElementById('extraction-refresh').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('ready for staff review')");
  assert.match(await evaluate("document.getElementById('extraction-fields').textContent"), /0001.Mixed-Case.*source rows 2/);
  assert.match(await evaluate("document.getElementById('extraction-fields').textContent"), /1.234/);
  assert.equal(await evaluate(`fetch(${JSON.stringify(csvDocument.download_url)}).then(r=>r.text())`), sourceCsv);
  // Explicit review starts with nothing selected. Keep the prior manual line,
  // correct a selected quantity, reject a stale aggregate, then reconcile an
  // actually committed application whose response was lost in this browser.
  await field('review-draft-id', manualId);
  await evaluate("document.getElementById('review-open-form').requestSubmit()");
  await waitFor("!document.getElementById('review-content').hidden && document.querySelectorAll('#review-candidates article').length===1");
  assert.equal(await evaluate("document.querySelectorAll('#review-candidates input[type=checkbox]:checked').length"), 0);
  assert.equal(await evaluate("document.getElementById('review-apply').disabled"), true);
  const reviewCandidate = await evaluate("document.querySelector('#review-candidates article').dataset.candidate");
  async function selectValue(id, value) { await evaluate(`document.getElementById(${JSON.stringify(id)}).value=${JSON.stringify(value)};document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('change',{bubbles:true}))`); }
  async function checkValue(id) { await evaluate(`document.getElementById(${JSON.stringify(id)}).checked=true;document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('change',{bubbles:true}))`); }
  await selectValue(`review-action-${reviewCandidate}`, 'create');
  await field(`review-position-${reviewCandidate}`, '2');
  await checkValue(`review-select-${reviewCandidate}-sku`);
  await checkValue(`review-select-${reviewCandidate}-quantity`);
  await checkValue(`review-correct-${reviewCandidate}-quantity`);
  await field(`review-value-${reviewCandidate}-quantity`, '1.250');
  assert.match(await evaluate("document.getElementById('review-preview').textContent"), /1.250 \(deliberate correction\)/);
  const applyRevision = (await secondRequest(manualPath + 'revision/')).data.revision;
  assert.equal((await secondRequest(manualPath, 'PATCH', { customer_reference: 'Other-session apply revision' }, applyRevision)).status, 200);
  acceptNextDialog = true; await evaluate("document.getElementById('review-apply').click()");
  await waitFor("document.getElementById('review-message').textContent.includes('Your choices are kept') && document.getElementById('review-apply').disabled");
  assert.equal(await evaluate(`document.getElementById('review-value-${reviewCandidate}-quantity').value`), '1.250');
  assert.equal((await secondRequest(manualPath + 'lines/')).data.count, 1);
  await evaluate("document.getElementById('review-refresh').click()");
  await waitFor("!document.getElementById('review-comparison').hidden");
  acceptNextDialog = true; await evaluate("document.getElementById('review-accept-comparison').click()");
  await waitFor("!document.getElementById('review-apply').disabled");
  dropApplicationResponse = true;
  await command('Fetch.enable', { patterns: [{ urlPattern: '*documents/*/extraction/apply/', requestStage: 'Response' }] });
  acceptNextDialog = true; await evaluate("document.getElementById('review-apply').click()");
  await waitFor("document.getElementById('review-message').textContent.includes('unconfirmed') && !document.getElementById('review-reconcile').hidden");
  assert.equal(await evaluate("document.getElementById('review-receipt').textContent"), '');
  assert.equal(await evaluate(`document.getElementById('review-value-${reviewCandidate}-quantity').disabled`), true);
  await evaluate("document.getElementById('review-reconcile').click()");
  await waitFor("document.getElementById('review-message').textContent.includes('confirmed by replay') && document.getElementById('review-readiness').textContent.includes('catalogue_unmatched')");
  const appliedLines = (await secondRequest(manualPath + 'lines/')).data;
  assert.equal(appliedLines.count, 2); assert.equal(appliedLines.results[0].id, detachedLine.id);
  for (const key of ['requested_sku', 'requested_description', 'quantity', 'unit']) assert.equal(appliedLines.results[0][key], detachedLine[key]);
  const appliedLine = appliedLines.results.find(row => row.position === 2);
  assert.equal(appliedLine.requested_sku, '0001.Mixed-Case'); assert.equal(appliedLine.quantity, '1.250'); assert.equal(appliedLine.catalogue_item_id, null);
  const csvApplyPath = `${csvDocument.extraction_url}apply/`;
  const originalApplication = await secondRequest(csvApplyPath, 'POST', submittedApplication);
  assert.equal(originalApplication.status, 200); assert.equal(originalApplication.data.decisions[0].fields.quantity.source.raw, '1.234'); assert.equal(originalApplication.data.decisions[0].fields.quantity.value, '1.250'); assert.equal(originalApplication.data.decisions[0].fields.quantity.corrected, true);
  const editedRevision = (await secondRequest(manualPath + 'revision/')).data.revision;
  assert.equal((await secondRequest(`${manualPath}lines/${appliedLine.id}/`, 'PATCH', { quantity: '9.875' }, editedRevision)).status, 200);
  const replay = await secondRequest(csvApplyPath, 'POST', submittedApplication);
  assert.equal(replay.status, 200); assert.equal(replay.data.application_id, originalApplication.data.application_id);
  assert.equal((await secondRequest(`${manualPath}lines/${appliedLine.id}/`)).data.quantity, '9.875');
  assert.equal((await secondRequest(manualPath)).data.status, 'draft');
  // A late authorized read cannot refill private review state after workspace
  // replacement. The delayed response is real HTTP, released after navigation.
  let delayedReview;
  let reviewRequest, reviewCanceled = false;
  const originalMessage = ws.onmessage;
  ws.onmessage = event => { const reply = JSON.parse(event.data); if (reply.method === 'Network.requestWillBeSent' && reply.params.request.url.includes('/extraction/review/')) reviewRequest = reply.params.requestId; if (reply.method === 'Network.loadingFailed' && reply.params.requestId === reviewRequest) reviewCanceled = reply.params.canceled === true; if (reply.method === 'Fetch.requestPaused' && reply.params.request.url.includes('/extraction/review/')) { delayedReview = reply.params.requestId; return; } originalMessage(event); };
  await command('Network.enable');
  await command('Fetch.enable', { patterns: [{ urlPattern: '*documents/*/extraction/review/*', requestStage: 'Response' }] });
  await evaluate("document.getElementById('review-refresh').click()");
  for (let count = 0; count < 100 && !delayedReview; count++) await delay(50);
  assert.ok(delayedReview, 'Expected the authorized review response to be held.');
  await choose(data.b);
  try { await command('Fetch.continueRequest', { requestId: delayedReview }); }
  catch (error) { assert.match(error.message, /Invalid InterceptionId/); assert.equal(reviewCanceled, true, 'The obsolete review must have been canceled by the browser.'); }
  await command('Fetch.disable'); await command('Network.disable'); ws.onmessage = originalMessage;
  assert.equal(await evaluate("document.getElementById('extraction-review').hidden"), true);
  assert.equal(await evaluate("document.getElementById('review-candidates').textContent.includes('0001.Mixed-Case')"), false);
  await choose(data.a);
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.a}/orders/${orderId}/documents/`)}`);
  await waitFor("document.getElementById('documents-rows').textContent.includes('0001.Mixed-Case.csv')");
  // The supported text-PDF profile uses the same durable source/job/review
  // boundary and records page/text offsets rather than invented coordinates.
  const textPdf = syntheticTextPdf(['ORDER DESK TEXT PO v1', 'SKU | QUANTITY | UNIT | DESCRIPTION', 'PDF-REQUEST | 2.500 | each | Synthetic PDF request', 'END PAGE 1/1']);
  await pickDocument('supported-text.pdf', textPdf);
  await evaluate("document.getElementById('document-upload-form').requestSubmit()");
  await waitFor("document.getElementById('documents-rows').textContent.includes('supported-text.pdf') && document.getElementById('documents-message').textContent.includes('Source received')");
  await evaluate("[...document.querySelectorAll('#documents-rows tr')].find(r=>r.textContent.includes('supported-text.pdf')).querySelectorAll('button')[1].click()");
  await waitFor("!document.getElementById('extraction-queue').disabled");
  await evaluate("document.getElementById('extraction-queue').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('Queued')");
  const pdfDocument = await evaluate(`fetch(${JSON.stringify(documentBase + 'intake/')}).then(r=>r.json()).then(d=>d.results.find(r=>r.original_name==='supported-text.pdf'))`);
  const pdfQueued = await evaluate(`fetch(${JSON.stringify(pdfDocument.extraction_url)}).then(r=>r.json())`);
  const processedPdf = spawnSync('docker', ['exec', container, 'python', 'manage.py', 'process_document_extraction', '--workspace', data.a, '--actor', data.user, '--job', pdfQueued.job.id], { cwd: root, windowsHide: true, encoding: 'utf8' });
  assert.equal(processedPdf.status, 0, `Restricted PDF processor failed: ${processedPdf.stderr}`);
  await evaluate("document.getElementById('extraction-refresh').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('ready for staff review')");
  assert.match(await evaluate("document.getElementById('extraction-fields').textContent"), /PDF-REQUEST.*source page 1, line 3.*text offsets/);
  const pdfResult = await evaluate(`fetch(${JSON.stringify(pdfDocument.extraction_url)}).then(r=>r.json())`);
  assert.equal(pdfResult.job.parser_version, 'order-text-pdf-v1');
  for (const sourceField of Object.values(pdfResult.results[0])) assert.equal([...pdfResult.job.result_pages[sourceField.page - 1]].slice(sourceField.span_start, sourceField.span_end).join(''), sourceField.raw);
  assert.equal(await evaluate(`fetch(${JSON.stringify(pdfDocument.download_url)}).then(r=>r.text())`), textPdf);
  await field('review-draft-id', manualId); await evaluate("document.getElementById('review-open-form').requestSubmit()");
  await waitFor("!document.getElementById('review-content').hidden && document.querySelectorAll('#review-candidates article').length===1");
  const pdfCandidate = await evaluate("document.querySelector('#review-candidates article').dataset.candidate");
  await selectValue(`review-action-${pdfCandidate}`, 'update'); await selectValue(`review-target-${pdfCandidate}`, appliedLine.id);
  await checkValue(`review-select-${pdfCandidate}-quantity`); await checkValue(`review-select-${pdfCandidate}-description`); await checkValue(`review-correct-${pdfCandidate}-description`); await field(`review-value-${pdfCandidate}-description`, 'Human PDF correction');
  assert.match(await evaluate("document.getElementById('review-candidates').textContent"), /Current target: 9.875/);
  acceptNextDialog = true; await evaluate("document.getElementById('review-apply').click()");
  await waitFor("document.getElementById('review-message').textContent.includes('confirmed') && document.getElementById('review-message').textContent.includes('still need a decision')");
  const pdfEdited = (await secondRequest(`${manualPath}lines/${appliedLine.id}/`)).data;
  assert.equal(pdfEdited.quantity, '2.500'); assert.equal(pdfEdited.requested_description, 'Human PDF correction'); assert.equal(pdfEdited.requested_sku, '0001.Mixed-Case'); assert.equal(pdfEdited.unit, '');
  const beforeReject = (await secondRequest(manualPath)).data.updated_at;
  await selectValue(`review-action-${pdfCandidate}`, 'reject'); await checkValue(`review-select-${pdfCandidate}-sku`); await checkValue(`review-select-${pdfCandidate}-unit`);
  acceptNextDialog = true; await evaluate("document.getElementById('review-apply').click()");
  await waitFor("document.getElementById('review-message').textContent.includes('Every supported field has a recorded decision')");
  assert.equal((await secondRequest(manualPath)).data.updated_at, beforeReject);
  assert.equal((await secondRequest(manualPath)).data.status, 'draft');
  const pdfAfter = await evaluate(`fetch(${JSON.stringify(documentBase + 'intake/')}).then(r=>r.json()).then(d=>d.results.find(r=>r.id===${JSON.stringify(pdfDocument.id)}))`);
  assert.equal(pdfAfter.status, 'received');
  // A real PDF without extractable text fails visibly and offers manual entry;
  // it publishes no partial candidates and cannot be retried as a parser fix.
  await pickDocument('no-text.pdf', syntheticTextPdf([])); await evaluate("document.getElementById('document-upload-form').requestSubmit()");
  await waitFor("document.getElementById('documents-rows').textContent.includes('no-text.pdf') && document.getElementById('documents-message').textContent.includes('Source received')");
  await evaluate("[...document.querySelectorAll('#documents-rows tr')].find(r=>r.textContent.includes('no-text.pdf')).querySelectorAll('button')[1].click()");
  await waitFor("!document.getElementById('extraction-queue').disabled"); await evaluate("document.getElementById('extraction-queue').click()"); await waitFor("document.getElementById('extraction-status').textContent.includes('Queued')");
  const blankPdf = await evaluate(`fetch(${JSON.stringify(documentBase + 'intake/')}).then(r=>r.json()).then(d=>d.results.find(r=>r.original_name==='no-text.pdf'))`);
  const blankQueued = await evaluate(`fetch(${JSON.stringify(blankPdf.extraction_url)}).then(r=>r.json())`);
  const failedPdf = spawnSync('docker', ['exec', container, 'python', 'manage.py', 'process_document_extraction', '--workspace', data.a, '--actor', data.user, '--job', blankQueued.job.id], { cwd: root, windowsHide: true, encoding: 'utf8' }); assert.equal(failedPdf.status, 0);
  await evaluate("document.getElementById('extraction-refresh').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('no_text') && !document.getElementById('extraction-manual-link').hidden");
  assert.equal(await evaluate("document.getElementById('extraction-review').hidden && document.getElementById('extraction-retry').disabled && document.getElementById('extraction-fields').children.length===0"), true);
  await pickDocument('invalid-quantity.csv', 'sku,quantity\nA,1\nB,invalid\n');
  await evaluate("document.getElementById('document-upload-form').requestSubmit()");
  await waitFor("document.getElementById('documents-rows').textContent.includes('invalid-quantity.csv') && document.getElementById('documents-message').textContent.includes('Source received')");
  await evaluate("[...document.querySelectorAll('#documents-rows tr')].find(r=>r.textContent.includes('invalid-quantity.csv')).querySelectorAll('button')[1].click()");
  await waitFor("!document.getElementById('extraction-queue').disabled");
  await evaluate("document.getElementById('extraction-queue').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('Queued')");
  const failedDocument = await evaluate(`fetch(${JSON.stringify(documentBase + 'intake/')}).then(r=>r.json()).then(d=>d.results.find(r=>r.original_name==='invalid-quantity.csv'))`);
  const failing = await evaluate(`fetch(${JSON.stringify(failedDocument.extraction_url)}).then(r=>r.json())`);
  processCSV(failing.job.id);
  await evaluate("document.getElementById('extraction-refresh').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('invalid_quantity at source row 3')");
  assert.equal(await evaluate("document.getElementById('extraction-fields').children.length"), 0);
  await evaluate("document.getElementById('extraction-retry').click()");
  await waitFor("document.getElementById('extraction-status').textContent.includes('Queued')");
  processCSV(failing.job.id);
  await evaluate("document.getElementById('extraction-refresh').click()");
  await waitFor("document.getElementById('extraction-identity').textContent.includes('attempt 2/3') && document.getElementById('extraction-status').textContent.includes('failed')");
  assert.equal(await evaluate(`(async()=>{const {csrf_token}=await(await fetch('/api/v1/auth/csrf/')).json();const form=new FormData();form.append('file',new File([new Uint8Array(10485761)],'too-large.pdf'));return(await fetch(${JSON.stringify(documentBase + 'intake/')},{method:'POST',headers:{'X-CSRFToken':csrf_token},body:form})).status})()`), 413);
  fixtures('viewer');
  assert.equal((await secondRequest(csvApplyPath, 'POST', submittedApplication)).status, 403);
  assert.equal(await evaluate(`(async()=>{const {csrf_token}=await(await fetch('/api/v1/auth/csrf/')).json();const form=new FormData();form.append('file',new File([${JSON.stringify(sourcePdf)}],'denied.pdf'));return(await fetch(${JSON.stringify(documentBase + 'intake/')},{method:'POST',headers:{'X-CSRFToken':csrf_token},body:form})).status})()`), 403);
  assert.equal(await evaluate(`fetch(${JSON.stringify(firstDocument.download_url)}).then(r=>r.status)`), 200);
  assert.equal(await evaluate(`(async()=>{const {csrf_token}=await(await fetch('/api/v1/auth/csrf/')).json();return(await fetch(${JSON.stringify(csvDocument.extraction_url)},{method:'POST',headers:{'X-CSRFToken':csrf_token,'Content-Type':'application/json'},body:'{}'})).status})()`), 403);
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Document mobile viewport overflows.');
  const documentShot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(resolve(scratch, 'private-documents-mobile.png'), Buffer.from(documentShot.data, 'base64'));
  // Return to the existing catalogue revocation/logout regression.
  await choose(data.b);
  fixtures('revoke');
  assert.equal(await evaluate(`fetch(${JSON.stringify(firstDocument.download_url)}).then(r=>r.status)`), 403);
  await search('BETA');
  await waitFor("document.getElementById('notice').textContent.includes('access changed')");
  assert.equal(await evaluate("document.getElementById('catalogue').hidden"), true);
  assert.equal(await evaluate("document.querySelectorAll('#items tr').length"), 0);
  await evaluate("document.getElementById('logout').click()");
  await waitFor("!document.getElementById('login-panel').hidden");
  assert.equal(await evaluate("fetch('/api/v1/workspaces/', {credentials:'same-origin'}).then(r => r.status)"), 403);
  assert.deepEqual(exceptions, []);
  console.log('PASS: real browser session/catalogue regressions; manual creation/header/line editing, validation and dirty navigation, two authenticated sessions with stale-write rejection/input preservation, active catalogue pagination/attach/detach, exact decimals and readiness invalidation; draft review, role denial, locked source, lost conversion response and same-order replay.');
  console.log('Runtime server: orderdesk_app; synthetic fixtures: test_orderdesk; screenshots: ignored backend/var/frontend-browser/.');
  console.log('PASS: private PDF/CSV source intake, malformed and oversized rejection, exact browser attachment download, recorded status, viewer upload denial, cross-tenant/revoked download denial; isolated temporary storage.');
  console.log('PASS: durable local CSV job, real processor exit/recovery, exact field provenance, immutable download, visible failure and explicit retry; restricted worker and viewer denial.');
  console.log('PASS: explicit CSV source/target selection and corrected quantity with immutable provenance, stale revision preservation/comparison, lost application response and identical-key reconciliation, no duplicate lines or overwrite of later manual corrections, independent readiness/conversion, viewer replay denial and late workspace-response isolation.');
  console.log('PASS: actual bounded text-PDF extraction and unchanged private bytes, verified page/text offset provenance, explicit existing-line correction, partial acceptance plus deliberate rejection, no automatic review/conversion, and visible no-text PDF failure with manual fallback.');
  console.log('PASS: real exact-SKU suggestion evidence, unchecked units/prices, stale draft, deactivated catalogue and revoked-role rejection, deliberate acceptance with unchanged requested values and refreshed readiness, late workspace-response isolation; manual detach remains available.');
} finally {
  if (secondarySocket?.readyState === WebSocket.OPEN) await closeSecondBrowser?.();
  secondarySocket?.close(); secondaryChrome?.kill();
  if (ws?.readyState === WebSocket.OPEN) await command('Browser.close').catch(() => {});
  ws?.close(); chrome?.kill();
  if (server) spawnSync('docker', ['stop', container], { cwd: root, windowsHide: true, stdio: 'ignore' });
  server?.kill();
  fixtures('cleanup');
}
