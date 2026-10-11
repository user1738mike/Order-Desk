// Real production WSGI/static/TLS path. Synthetic fixtures only; no API mocks,
// certificate bypass or Docker socket. Worker jobs are handed to the operator.
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { lookup } from 'node:dns/promises';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { createHash, randomUUID } from 'node:crypto';

const origin = 'https://orderdesk.localhost:8443';
const data = JSON.parse(await readFile('/run-state/fixture.json', 'utf8'));
const home = '/tmp/browser-home';
await mkdir(`${home}/.pki/nssdb`, { recursive: true });
for (const args of [
  ['-N', '-d', `sql:${home}/.pki/nssdb`, '--empty-password'],
  ['-A', '-d', `sql:${home}/.pki/nssdb`, '-n', 'Order Desk local acceptance CA', '-t', 'C,,', '-i', '/trust/ca.crt'],
]) assert.equal(spawnSync('/usr/bin/certutil', args).status, 0);
const proxy = await lookup('proxy');
const chrome = spawn('/usr/bin/chromium', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--no-first-run',
  '--remote-debugging-port=9222', `--user-data-dir=${home}/profile`,
  `--host-resolver-rules=MAP orderdesk.localhost ${proxy.address}`, 'about:blank',
], { stdio: 'ignore' });
let ws, sequence = 0;
const pending = new Map(), exceptions = [], violations = [];
let lostExportResponse = false, exportResponseDropped = false;
let holdOrderResponse = false, heldOrderResponse = null;
try {
  let tabs;
  for (let i = 0; i < 100; i++) {
    try { tabs = await (await fetch('http://127.0.0.1:9222/json')).json(); } catch {}
    if (tabs?.some(tab => tab.type === 'page')) break;
    await delay(100);
  }
  assert.ok(tabs?.length, 'Chromium failed to start.');
  ws = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  ws.onmessage = event => {
    const reply = JSON.parse(event.data);
    if (reply.method === 'Fetch.requestPaused') {
      const paused = reply.params;
      if (holdOrderResponse && paused.request.method === 'GET' && paused.responseStatusCode) { heldOrderResponse = paused.requestId; return; }
      if (lostExportResponse && paused.request.method === 'POST' && paused.responseStatusCode) {
        lostExportResponse = false; exportResponseDropped = true;
        command('Fetch.failRequest', { requestId: paused.requestId, errorReason: 'ConnectionClosed' }).catch(() => {});
      } else command('Fetch.continueRequest', { requestId: paused.requestId }).catch(() => {});
    }
    if (reply.method === 'Runtime.exceptionThrown') exceptions.push('Uncaught browser exception');
    if (reply.method === 'Audits.issueAdded' && reply.params.issue.code === 'ContentSecurityPolicyIssue') violations.push(reply.params.issue.code);
    const entry = pending.get(reply.id);
    if (entry) { pending.delete(reply.id); clearTimeout(entry.timer); reply.error ? entry.reject(new Error(reply.error.message)) : entry.resolve(reply.result); }
  };
  function command(method, params = {}) {
    const id = ++sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout ${method}`)); }, 20000);
      pending.set(id, { resolve, reject, timer }); ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async function evaluate(expression) {
    const result = await command('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    assert.ok(!result.exceptionDetails, 'Browser evaluation failed.'); return result.result.value;
  }
  async function wait(expression) {
    for (let i = 0; i < 200; i++) { if (await evaluate(expression)) return; await delay(100); }
    await writeFile('/run-state/browser-failure.json', JSON.stringify(await evaluate(`({hash:location.hash,logoutDisabled:document.getElementById('logout')?.disabled,refreshDisabled:document.getElementById('purchase-refresh')?.disabled,deskHidden:document.getElementById('desk')?.hidden,loginHidden:document.getElementById('login-panel')?.hidden,alerts:Array.from(document.querySelectorAll('[role=alert]')).map(e=>e.textContent)})`)));
    throw new Error(`Browser state timed out: ${expression}`);
  }
  async function request(path, method = 'GET', body, revision) {
    return evaluate(`(async()=>{const token=${method !== 'GET'}?(await(await fetch('/api/v1/auth/csrf/')).json()).csrf_token:null;const r=await fetch(${JSON.stringify(path)},{method:${JSON.stringify(method)},headers:{...(${body !== undefined}?{'Content-Type':'application/json','X-CSRFToken':token}:{}),...(${Boolean(revision)}?{'If-Match':${JSON.stringify(`"${revision}"`)}}:{})},...(${body !== undefined}?{body:${JSON.stringify(JSON.stringify(body) ?? '')}}:{})});return{status:r.status,data:await r.json()}})()`);
  }
  async function worker(job, mode = 'normal') {
    const request_id = randomUUID();
    await writeFile('/run-state/worker-request.json', JSON.stringify({ actor: data.user, workspace: data.a, job, mode, request_id }));
    for (let i = 0; i < 300; i++) {
      try { const result = JSON.parse(await readFile('/run-state/worker-result.json')); if (result.request_id === request_id && result.job === job) { assert.equal(result.code, 0); return; } } catch (error) { if (!['ENOENT'].includes(error.code) && !(error instanceof SyntaxError)) throw error; }
      await delay(200);
    }
    throw new Error('Authorized real worker was not run.');
  }
  await command('Runtime.enable'); await command('Page.enable'); await command('Audits.enable'); await command('Network.enable');
  await command('Page.navigate', { url: origin });
  await wait("document.getElementById('login-panel') && !document.getElementById('login-panel').hidden");
  assert.equal(await evaluate('location.origin'), origin);
  await evaluate(`document.getElementById('email').value=${JSON.stringify(data.email)};document.getElementById('password').value=${JSON.stringify(data.password)};document.getElementById('login-form').requestSubmit()`);
  await wait("!document.getElementById('desk').hidden && !document.getElementById('workspace').disabled");
  for (const workspace of [data.a, data.b, data.a]) {
    await evaluate(`document.getElementById('workspace').value=${JSON.stringify(workspace)};document.getElementById('workspace').dispatchEvent(new Event('change'))`);
    await wait("!document.getElementById('workspace').disabled && document.querySelectorAll('#items tr').length===1");
    assert.match(await evaluate("document.getElementById('items').textContent"), workspace === data.a ? /0001.Mixed-Case/ : /PRIVATE-BETA/);
  }
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.b}/orders/${data.viewer_order}/export/`)}`);
  await wait("document.getElementById('purchase-summary').textContent.includes('Viewer-only fixture')");
  assert.equal(await evaluate("document.getElementById('purchase-approve').hidden"), true);
  assert.equal(await evaluate("document.getElementById('purchase-export').hidden"), true);
  assert.equal((await request(`/api/v1/workspaces/${data.b}/orders/${data.viewer_order}/exports/`, 'POST', {profile:'generic-po-csv-v1'})).status, 403);
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.a}/catalogue/`)}`);
  await wait("document.getElementById('workspace').value===" + JSON.stringify(data.a) + " && !document.getElementById('workspace').disabled");
  const cookies = (await command('Network.getCookies', { urls: [origin] })).cookies;
  for (const name of ['sessionid', 'csrftoken']) { const cookie = cookies.find(item => item.name === name); assert.ok(cookie?.secure); assert.equal(cookie.sameSite, 'Lax'); if (name === 'sessionid') assert.ok(cookie.httpOnly); }
  const base = `/api/v1/workspaces/${data.a}/`;
  const source = await request(base + 'orders/', 'POST', { customer_name: 'Synthetic source', purchase_order_number: 'LOCAL-SOURCE-' + randomUUID() });
  assert.equal(source.status, 201); const documents = base + `orders/${source.data.id}/documents/`;
  const upload = await evaluate(`(async()=>{const {csrf_token}=await(await fetch('/api/v1/auth/csrf/')).json();const form=new FormData();form.append('file',new File(['sku,quantity,description,unit\\r\\n0001.Mixed-Case,1.234,Source fitting,ea\\r\\n'],'source.csv'));const r=await fetch(${JSON.stringify(documents + 'intake/')},{method:'POST',headers:{'X-CSRFToken':csrf_token},body:form});return{status:r.status,data:await r.json()}})()`);
  assert.equal(upload.status, 201); const document = upload.data;
  // The document API intentionally omits its stored digest. Bind recovery proof
  // to independently known uploaded bytes, rather than inventing an API field.
  const sourceBytes = Buffer.from('sku,quantity,description,unit\r\n0001.Mixed-Case,1.234,Source fitting,ea\r\n');
  const sourceSha256 = createHash('sha256').update(sourceBytes).digest('hex');
  assert.equal(document.size_bytes, sourceBytes.length);
  assert.equal(await evaluate(`fetch(${JSON.stringify(document.download_url)}).then(r=>r.text())`), 'sku,quantity,description,unit\r\n0001.Mixed-Case,1.234,Source fitting,ea\r\n');
  assert.equal((await request(document.download_url.replace(data.a, data.b))).status, 404);
  const queued = await request(document.extraction_url, 'POST', {}); assert.equal(queued.status, 202);
  await worker(queued.data.id, 'interrupt');
  assert.equal((await request(document.extraction_url)).data.job.status, 'running');
  await delay(2100); await worker(queued.data.id);
  const extracted = await request(document.extraction_url); assert.equal(extracted.data.job.status, 'succeeded');
  assert.equal(extracted.data.job.source_sha256, sourceSha256);
  assert.equal(extracted.data.job.attempts, 2);
  const unsupported = await evaluate(`(async()=>{const {csrf_token}=await(await fetch('/api/v1/auth/csrf/')).json();const form=new FormData();form.append('file',new File(['SKU,quantity\\n0001.Mixed-Case,1\\n'],'unsupported.csv'));const r=await fetch(${JSON.stringify(documents + 'intake/')},{method:'POST',headers:{'X-CSRFToken':csrf_token},body:form});return{status:r.status,data:await r.json()}})()`);
  assert.equal(unsupported.status, 201);
  const unsupportedJob = await request(unsupported.data.extraction_url, 'POST', {});
  assert.equal(unsupportedJob.status, 202); await worker(unsupportedJob.data.id);
  const failedExtraction = await request(unsupported.data.extraction_url);
  assert.equal(failedExtraction.data.job.status, 'failed');
  assert.equal(failedExtraction.data.job.error_code, 'unsupported_headers');
  assert.deepEqual(failedExtraction.data.results, []);
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.a}/orders/${source.data.id}/documents/`)}`);
  await wait("Array.from(document.querySelectorAll('#documents-rows tr')).some(row=>row.textContent.includes('unsupported.csv'))");
  await evaluate("Array.from(document.querySelectorAll('#documents-rows tr')).find(row=>row.textContent.includes('unsupported.csv')).querySelectorAll('button')[1].click()");
  await wait("document.getElementById('extraction-status').textContent.includes('unsupported_headers') && !document.getElementById('extraction-manual-link').hidden");
  await evaluate("document.getElementById('extraction-manual-link').click()");
  await wait("!document.getElementById('new-draft').hidden && !document.getElementById('new-draft').disabled");
  await evaluate("document.getElementById('new-draft').click()");
  await wait("!document.getElementById('editor-save').disabled");
  await evaluate("for (const [id,value] of [['edit-customer-name','Manual unsupported intake'],['edit-customer-reference','MANUAL-ONLY'],['edit-intake','Synthetic unsupported CSV requires deliberate manual review']]) {const input=document.getElementById(id);input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}document.getElementById('editor-form').requestSubmit()");
  await wait("document.getElementById('draft-fields').textContent.includes('Manual unsupported intake') && !document.getElementById('draft-content').hidden");
  const manualId = (await evaluate('location.hash')).split('/')[4];
  const manual = await request(base + `draft-orders/${manualId}/`);
  assert.equal(manual.status, 200); assert.equal(manual.data.customer_reference, 'MANUAL-ONLY');
  assert.equal((await request(base + `draft-orders/${manualId}/readiness/`)).data.ready_to_convert, false);
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.a}/orders/${source.data.id}/documents/`)}`);
  await wait("document.getElementById('documents-rows').textContent.includes('source.csv')");
  await evaluate("Array.from(document.querySelectorAll('#documents-rows tr')).find(row=>row.textContent.includes('source.csv')).querySelectorAll('button')[1].click()");
  await wait("document.getElementById('extraction-status').textContent.includes('ready for staff review')");
  assert.match(await evaluate("document.getElementById('extraction-fields').textContent"), /0001.Mixed-Case/);
  const draft = await request(base + 'draft-orders/', 'POST', { customer_name: 'Local Buyer', customer_reference: 'LOCAL-REF', original_intake_text: 'Synthetic HTTPS intake' }); assert.equal(draft.status, 201);
  const detail = base + `draft-orders/${draft.data.id}/`;
  const reviewed = await request(document.extraction_url + `review/?draft_id=${draft.data.id}`); assert.equal(reviewed.status, 200);
  await evaluate(`document.getElementById('review-draft-id').value=${JSON.stringify(draft.data.id)};document.getElementById('review-open-form').requestSubmit()`);
  await wait("!document.getElementById('review-content').hidden && document.querySelectorAll('#review-candidates article').length===1");
  const application = { job_id: queued.data.id, draft_id: draft.data.id, result_revision: reviewed.data.result_revision, expected_draft_revision: reviewed.data.draft_revision, operation_key: randomUUID(), mappings: [{candidate_id: reviewed.data.results[0].candidate_id, action: 'create', position: 1, fields: ['sku','quantity','description','unit']}] };
  assert.equal((await request(document.extraction_url + 'apply/', 'POST', application)).status, 201);
  assert.equal((await request(document.extraction_url + 'apply/', 'POST', application)).status, 200);
  const suggestions = await request(detail + 'suggestions/'); assert.equal(suggestions.status, 200);
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.a}/draft-orders/${draft.data.id}/`)}`);
  await wait("!document.getElementById('matching-load').disabled");
  await evaluate("document.getElementById('matching-load').click()");
  await wait("document.getElementById('matching-results').textContent.includes('0001.Mixed-Case')");
  const row = suggestions.data.results[0]; assert.equal(row.state, 'exact');
  const accepted = await request(detail + `lines/${row.line_id}/accept-suggestion/`, 'POST', {catalogue_item_id: row.candidate.id, rule_version: suggestions.data.rule_version, source_sku: row.normalized_sku, catalogue_revision: row.candidate.revision}, suggestions.data.draft_revision);
  assert.equal(accepted.status, 200);
  assert.equal((await request(detail + 'readiness/')).data.ready_to_convert, true);
  const converted = await request(detail + 'convert/', 'POST', {}); assert.equal(converted.status, 201);
  const replay = await request(detail + 'convert/', 'POST', {}); assert.equal(replay.status, 200); assert.equal(replay.data.id, converted.data.id);
  const order = base + `orders/${converted.data.id}/`;
  await evaluate(`location.hash=${JSON.stringify(`#/workspaces/${data.a}/orders/${converted.data.id}/export/`)}`);
  await wait("!document.getElementById('purchase-submit').disabled");
  assert.match(await evaluate("document.getElementById('purchase-lines').textContent"), /0001.Mixed-Case.*1.2340/);
  await command('Page.handleJavaScriptDialog', { accept: false }).catch(() => {});
  let confirmNext = false;
  const onDialog = event => { const reply = JSON.parse(event.data); if (reply.method === 'Page.javascriptDialogOpening') command('Page.handleJavaScriptDialog', { accept: confirmNext }).catch(() => {}); };
  ws.addEventListener('message', onDialog);
  await evaluate("document.getElementById('purchase-submit').click()");
  assert.equal((await request(order)).data.status, 'draft');
  confirmNext = true; await evaluate("document.getElementById('purchase-submit').click()");
  await wait("!document.getElementById('purchase-approve').disabled");
  await evaluate("document.getElementById('purchase-approve').click()");
  await wait("!document.getElementById('purchase-generate').disabled");
  ws.removeEventListener('message', onDialog);
  await command('Fetch.enable', { patterns: [{urlPattern:'*/exports/',requestStage:'Response'}] });
  lostExportResponse = true;
  await evaluate("document.getElementById('purchase-generate').click()");
  await wait("document.getElementById('purchase-message').textContent.includes('unconfirmed')");
  assert.equal(exportResponseDropped, true);
  assert.equal(await evaluate("document.getElementById('purchase-generate').disabled && document.getElementById('purchase-download').disabled"), true);
  await command('Fetch.disable');
  await evaluate("document.getElementById('purchase-refresh').click()");
  await wait("!document.getElementById('purchase-download').disabled");
  const artifact = { data: (await request(order + 'exports/')).data.artifact };
  assert.equal(artifact.data.status, 'succeeded');
  assert.equal((await request(order + 'exports/', 'POST', { profile: 'generic-po-csv-v1' })).status, 200);
  await evaluate("document.getElementById('purchase-generate').click()");
  await wait("!document.getElementById('purchase-download').disabled && document.getElementById('purchase-message').textContent.includes('Current order status loaded')");
  assert.equal((await request(order + 'exports/')).data.artifact.id, artifact.data.id);
  await command('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: '/tmp/order-downloads', eventsEnabled: true });
  await evaluate("document.getElementById('purchase-download').click()");
  await wait("document.getElementById('purchase-message').textContent.includes('CSV verified')");
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  await command('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true);
  await command('Emulation.clearDeviceMetricsOverride');
  const csv = await evaluate(`fetch(${JSON.stringify(artifact.data.download_url)}).then(r=>r.text())`); assert.match(csv, /0001.Mixed-Case,Synthetic fitting,1.2340,ea\r\n$/);
  let savedCsv;
  for (let i = 0; i < 100; i++) { try { savedCsv = await readFile(`/tmp/order-downloads/order-${converted.data.id}.csv`, 'utf8'); break; } catch (error) { if (error.code !== 'ENOENT') throw error; await delay(100); } }
  assert.equal(savedCsv, csv, 'Operator download must preserve the exact private export bytes.');
  const { cssContentSize } = await command('Page.getLayoutMetrics');
  const screenshot = await command('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: cssContentSize.width, height: cssContentSize.height, scale: 1 } });
  await writeFile('/run-state/purchase.png', Buffer.from(screenshot.data, 'base64'));
  await writeFile('/run-state/workflow.json', JSON.stringify({ source: source.data.id, draft: draft.data.id, document: { ...document, sha256: sourceSha256 }, artifact: artifact.data, csv, job: queued.data.id }));
  await command('Fetch.enable', { patterns: [{urlPattern:origin + order,requestStage:'Response'}] });
  holdOrderResponse = true;
  await evaluate("document.getElementById('purchase-refresh').click()");
  for (let i = 0; i < 100 && !heldOrderResponse; i++) await delay(100);
  assert.ok(heldOrderResponse, 'A real private order response must be held for the context race.');
  await evaluate(`document.getElementById('workspace').value=${JSON.stringify(data.b)};document.getElementById('workspace').dispatchEvent(new Event('change'))`);
  await wait("document.getElementById('workspace').value===" + JSON.stringify(data.b) + " && !document.getElementById('workspace').disabled");
  holdOrderResponse = false;
  await command('Fetch.continueRequest', { requestId: heldOrderResponse }).catch(() => {});
  await command('Fetch.disable');
  assert.equal(await evaluate("document.getElementById('purchase-summary').textContent==='' && document.querySelectorAll('#purchase-lines tr').length===0 && document.querySelectorAll('#purchase-preview tr').length===0"), true);
  await evaluate('window.__orderDeskReloadMarker = true');
  await command('Page.reload'); await wait("window.__orderDeskReloadMarker === undefined && document.readyState === 'complete' && document.getElementById('desk') && !document.getElementById('desk').hidden && !document.getElementById('logout').disabled");
  assert.deepEqual(exceptions, []); assert.deepEqual(violations, []);
  await evaluate("document.getElementById('logout').click()"); await wait("!document.getElementById('login-panel').hidden");
  assert.equal((await request('/api/v1/workspaces/')).status, 403);
  assert.equal((await request('/api/v1/auth/login/', 'POST', {email:data.email,password:data.password})).status, 200);
  await writeFile('/run-state/session.json', JSON.stringify((await command('Network.getCookies', {urls:[origin]})).cookies));
  console.log('PASS: real Chromium with isolated CA trust, production static/CSP, secure session/CSRF, viewer export denial, workspace isolation, original private CSV bytes, restricted extraction, provenance review/application replay, exact matching, conversion replay, cancelled/confirmed operator approval, lost export response reconciliation, verified CSV controls/replay/download and mobile layout.');
  await command('Browser.close');
} finally { ws?.close(); chrome.kill(); }
