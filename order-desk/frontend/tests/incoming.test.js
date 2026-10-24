import test from 'node:test';
import assert from 'node:assert/strict';
import { DocumentController, incomingRoute } from '../assets/desk/documents.js';
import { ApiError } from '../assets/desk/api.js';
import { parseRoute } from '../assets/desk/orders-api.js';

const workspace = { id: '11111111-1111-1111-1111-111111111111', role: 'reviewer' };
const id = '22222222-2222-2222-2222-222222222222';
const draft = '33333333-3333-3333-3333-333333333333';
const source = { id, organization: workspace.id, order: null, draft: null, original_name: 'request.csv', size_bytes: 20, status: 'received', download_url: `/api/v1/workspaces/${workspace.id}/incoming/${id}/download/` };
const file = () => new File(['sku,quantity\n00042,2\n'], 'request.csv');
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

test('incoming route and headers do not require an internal order', async () => {
  assert.deepEqual(parseRoute(incomingRoute(workspace.id)), { screen: 'documents', workspace: workspace.id, order: 'incoming' });
  const calls = [];
  const controller = new DocumentController({ request: async path => { calls.push(path); return { count: 1, results: [source] }; } });
  controller.context(workspace, 1, 'incoming');
  assert.equal(await controller.list(), true);
  assert.match(calls[0], /\/incoming\/\?page=1/);
  assert.equal(controller.state.rows[0].order, null);
});

test('uncertain upload reconciles its exact key and preserves retry identity when absent', async () => {
  const calls = [];
  let phase = 'upload';
  const controller = new DocumentController({ refreshCsrf: async () => {}, request: async (path, options) => {
    calls.push([path, options]);
    if (phase === 'upload') throw new ApiError(503, { detail: 'unknown' });
    return { count: 0, results: [] };
  } });
  controller.context(workspace, 1, 'incoming'); controller.select(file());
  const key = controller.state.uploadKey;
  await controller.upload();
  assert.equal(controller.state.uncertain, true);
  assert.equal(calls[0][1].idempotencyKey, key);
  controller.select(file()); assert.equal(controller.state.uploadKey, key);
  phase = 'reconcile'; await controller.reconcileUpload();
  assert.equal(controller.state.uncertain, false);
  assert.equal(controller.state.uploadKey, key);
  assert.match(calls[1][0], new RegExp(`operation_key=${key}`));
  assert.ok(controller.state.file);
});

test('lost draft-link response replays identical operation and never starts a new create', async () => {
  const payloads = []; let fail = true;
  const controller = new DocumentController({ refreshCsrf: async () => {}, request: async (path, options) => {
    if (options?.method === 'POST') { payloads.push(options.body); if (fail) throw new Error('response lost'); return { ...source, draft }; }
    return { count: 1, results: [{ ...source, draft }] };
  } });
  controller.context(workspace, 1, 'incoming'); controller.update({ linkSource: source });
  await controller.linkSource({ customer_name: 'Buyer', customer_reference: '0007' });
  assert.ok(controller.state.linkOperation);
  fail = false; await controller.linkSource();
  assert.deepEqual(payloads[0], payloads[1]);
  assert.equal(controller.state.linkOperation, null);
  assert.equal(controller.state.rows[0].draft, draft);
});

test('workspace replacement during CSRF refresh sends no upload or link mutation', async () => {
  for (const action of ['upload', 'link']) {
    const pending = deferred(); let mutations = 0;
    const controller = new DocumentController({ refreshCsrf: () => pending.promise, request: async () => { mutations++; } });
    controller.context(workspace, 1, 'incoming'); controller.select(file()); controller.update({ linkSource: source });
    const result = action === 'upload' ? controller.upload() : controller.linkSource({ customer_name: '', customer_reference: '' });
    controller.context(null, 2, null); pending.resolve(); await result;
    assert.equal(mutations, 0); assert.deepEqual(controller.state.rows, []); assert.equal(controller.state.linkOperation, null);
  }
});

test('late inbox and reconciliation cannot repopulate a demoted or replaced context', async () => {
  const pending = deferred();
  const controller = new DocumentController({ request: () => pending.promise });
  controller.context(workspace, 1, 'incoming'); const load = controller.list();
  controller.context({ ...workspace, role: 'viewer' }, 1, 'incoming');
  pending.resolve({ count: 1, results: [source] }); await load;
  assert.deepEqual(controller.state.rows, []); assert.equal(controller.state.file, null);
});
