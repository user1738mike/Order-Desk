import test from 'node:test';
import assert from 'node:assert/strict';
import { CustomerController, customerRoute } from '../assets/desk/customers.js';
import { parseRoute } from '../assets/desk/orders-api.js';
import { ApiError } from '../assets/desk/api.js';

const w = '11111111-1111-1111-1111-111111111111', id = '22222222-2222-2222-2222-222222222222', draft = '33333333-3333-3333-3333-333333333333';
const workspace = { id: w, role: 'admin' };
const account = { id, organization_id: w, code: '00042', display_name: 'Confirmed Ltd', destination_id: '000007', requires_location: false, is_active: true, revision: 'a'.repeat(64) };
const page = results => ({ count: results.length, results });
const wait = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const status = { draft_id: draft, organization_id: w, draft_status: 'draft', required: true, confirmed: false, blockers: ['customer_unconfirmed'], decision: null, draft_revision: 'b'.repeat(64), requested: { customer_name: 'Original', customer_reference: '0001' }, candidate: null };

test('directory routes and exact identifiers retain leading zeros and require confirmation', async () => {
  assert.deepEqual(parseRoute(customerRoute(w)), { screen: 'customers', workspace: w });
  const calls = [];
  const controller = new CustomerController({ request: async path => { calls.push(path); return { requires_confirmation: true, matches: [{ account }] }; } });
  controller.context(workspace, 1, 'draft', draft);
  await controller.resolve('00042');
  assert.equal(controller.state.rows[0].code, '00042'); assert.match(calls[0], /identifier=00042/);
  assert.equal(controller.canConfirm(), false); assert.equal(controller.state.candidate, null);
});

test('lost reference creation reconciles its exact durable receipt without another post', async () => {
  let posts = 0, key;
  const controller = new CustomerController({ refreshCsrf: async () => {}, request: async (path, options = {}) => {
    if (options.method === 'POST') { posts++; key = options.idempotencyKey; throw new Error('response lost'); }
    if (path.includes('/operations/')) return { operation_key: key, organization_id: w, status: 'committed', kind: 'account.create', response: { ...account, operation_key: key } };
    return page([account]);
  } });
  controller.context(workspace, 1, 'directory');
  await controller.mutate('account', controller.base(), { code: '00042', display_name: 'Confirmed Ltd' });
  assert.equal(posts, 1); assert.ok(controller.state.operation);
  await controller.reconcile(); assert.equal(posts, 1); assert.equal(controller.state.operation, null);
  assert.equal(controller.state.rows[0].destination_id, '000007');
});

test('absent receipt retains an identical retry instead of manufacturing success', async () => {
  const payloads = [];
  const controller = new CustomerController({ refreshCsrf: async () => {}, request: async (path, options = {}) => {
    if (path.includes('/operations/')) throw new ApiError(404, {});
    if (options.method === 'POST') { payloads.push([options.body, options.idempotencyKey]); throw new ApiError(503, { detail: 'unknown' }); }
    return page([]);
  } });
  controller.context(workspace, 1, 'directory');
  await controller.mutate('account', controller.base(), { code: '00042', display_name: 'Confirmed Ltd' });
  await controller.reconcile(); assert.ok(controller.state.operation);
  await controller.send(); assert.deepEqual(payloads[0], payloads[1]);
});

test('context replacement during CSRF refresh sends no mutation and clears private proposals', async () => {
  const paused = wait(); let posts = 0;
  const controller = new CustomerController({ refreshCsrf: () => paused.promise, request: async () => { posts++; } });
  controller.context(workspace, 1, 'directory');
  const saving = controller.mutate('account', controller.base(), { code: '00042', display_name: 'Private' });
  controller.context(null, 2); paused.resolve(); await saving;
  assert.equal(posts, 0); assert.equal(controller.state.operation, null); assert.deepEqual(controller.state.rows, []);
});

test('late account reads cannot restore a replaced workspace, role or session', async () => {
  for (const replacement of [null, { ...workspace, role: 'viewer' }]) {
    const paused = wait(); const controller = new CustomerController({ request: () => paused.promise });
    controller.context(workspace, 1, 'directory'); const loading = controller.list();
    controller.context(replacement, 2, 'directory'); paused.resolve(page([account])); await loading;
    assert.deepEqual(controller.state.rows, []); assert.equal(controller.canWrite(), false);
  }
});

test('foreign or malformed responses fail closed and never become selectable identity', async () => {
  const controller = new CustomerController({ request: async () => page([{ ...account, organization_id: draft }]) });
  controller.context(workspace, 1, 'directory'); await controller.list();
  assert.deepEqual(controller.state.rows, []); assert.match(controller.state.message, /unavailable/);
});

test('reference patch carries exact original version and business conflict is not retried', async () => {
  const calls = [];
  const controller = new CustomerController({ refreshCsrf: async () => {}, request: async (path, options) => { calls.push(options); throw new ApiError(412, { detail: 'Compare changed reference' }); } });
  controller.context(workspace, 1, 'directory');
  await controller.mutate('account', controller.base() + id + '/', { display_name: 'Proposed' }, { id, method: 'PATCH', revision: account.revision });
  assert.equal(calls.length, 1); assert.equal(calls[0].method, 'PATCH'); assert.equal(calls[0].revision, account.revision);
  assert.equal(controller.state.operation, null); assert.match(controller.state.message, /Compare/);
});

test('deliberate customer confirmation binds observed draft and reference versions and replays the same operation', async () => {
  const posts = []; let lost = true;
  const decision = { id, organization_id: w, draft_id: draft, customer_id: id, snapshot: { account: { id, code: '00042', display_name: 'Confirmed Ltd' } } };
  const controller = new CustomerController({ refreshCsrf: async () => {}, request: async (path, options = {}) => {
    if (options.method === 'POST') { posts.push(options.body); if (lost) throw new Error('lost'); return decision; }
    return { ...status, confirmed: true, blockers: [], decision };
  } });
  controller.context({ ...workspace, role: 'reviewer' }, 1, 'draft', draft);
  controller.update({ account, status, candidate: { reference_revision: 'c'.repeat(64) } });
  assert.equal(controller.hasUnsaved(), true); await controller.confirm(); assert.ok(controller.state.operation);
  lost = false; await controller.reconcile(); assert.deepEqual(posts[0], posts[1]);
  assert.equal(posts[0].expected_draft_revision, status.draft_revision); assert.equal(posts[0].reference_revision, 'c'.repeat(64));
  assert.equal(controller.state.operation, null); assert.equal(controller.state.status.confirmed, true);
});
