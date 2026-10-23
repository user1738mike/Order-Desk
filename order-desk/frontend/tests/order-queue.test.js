import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../assets/desk/api.js';
import { parseRoute } from '../assets/desk/orders-api.js';
import { OrderQueueController, queueRoute, nextOrderAction } from '../assets/desk/order-queue.js';

const w = '11111111-1111-1111-1111-111111111111', o = '22222222-2222-2222-2222-222222222222';
const row = { id: o, organization_id: w, source_draft_id: null, customer_name: 'Buyer', customer_reference: null, purchase_order_number: 'INT-1', status: 'draft', is_active: true, created_at: '2026-10-23T10:00:00Z', updated_at: '2026-10-23T10:00:00Z' };
function fixture() {
  const calls = [], denied = [];
  const client = { request: async (path, options) => { calls.push([path, options]); return { count: 1, results: [{ ...row }] }; } };
  const controller = new OrderQueueController(client, () => {}, async () => denied.push(true));
  controller.context({ id: w, role: 'viewer' }, 1, parseRoute(queueRoute(w, 'purchase')));
  return { controller, client, calls, denied };
}
test('queue filters round trip through refresh/deep links with literal punctuation', () => {
  for (const screen of ['purchase', 'documents']) {
    const route = parseRoute(queueRoute(w, screen, { query: '001 %_ &?#/', status: 'pending_review', page: 2 }));
    assert.deepEqual(route, { screen, workspace: w, query: '001 %_ &?#/', status: 'pending_review', page: 2 });
  }
  for (const suffix of ['q=a&q=b', 'status=unknown', 'page=0', 'page=-1', 'page=1.5', 'page=9007199254740992', 'other=1', 'q=a%00b', `q=${'a'.repeat(201)}`]) assert.equal(parseRoute(`#/workspaces/${w}/purchase-orders/?${suffix}`).screen, 'missing');
});
test('viewer searches scalar headers using bounded page and filter parameters', async () => {
  const { controller, calls } = fixture();
  controller.context({ id: w, role: 'viewer' }, 1, parseRoute(queueRoute(w, 'purchase', { query: 'Buyer %_' })));
  await controller.load();
  assert.equal(controller.state.rows[0].id, o);
  assert.equal(new URL(calls[0][0], 'http://local').searchParams.get('q'), 'Buyer %_');
  assert.equal(controller.state.busy, false); assert.equal(controller.state.loaded, true);
});
test('late queue responses cannot repopulate switched workspace, role, route or logout', async () => {
  for (const change of ['workspace', 'role', 'route', 'logout']) {
    const { controller, client } = fixture(); let resolve;
    client.request = () => new Promise(done => { resolve = done; });
    const loading = controller.load();
    const workspace = change === 'logout' ? null : { id: change === 'workspace' ? o : w, role: change === 'role' ? 'admin' : 'viewer' };
    controller.context(workspace, change === 'logout' ? 2 : 1, { screen: change === 'route' ? 'drafts' : 'purchase', workspace: workspace?.id });
    resolve({ count: 1, results: [row] }); await loading;
    assert.deepEqual(controller.state.rows, []); assert.equal(controller.state.count, 0);
  }
});
test('malformed/foreign queue payloads fail closed and leave refresh available', async () => {
  for (const patch of [{ organization_id: o }, { source_draft_id: 'bad' }, { status: 'invented' }, { created_at: 'bad' }]) {
    const { controller, client } = fixture(); client.request = async () => ({ count: 1, results: [{ ...row, ...patch }] });
    await controller.load(); assert.deepEqual(controller.state.rows, []); assert.equal(controller.state.loaded, false); assert.equal(controller.state.busy, false);
  }
});
test('a delayed search cannot replace a newer filter result', async () => {
  const { controller, client } = fixture(); let resolve;
  client.request = () => new Promise(done => { resolve = done; });
  const old = controller.load();
  controller.context({ id: w, role: 'viewer' }, 1, parseRoute(queueRoute(w, 'purchase', { query: 'new search', status: 'approved' })));
  client.request = async () => ({ count: 0, results: [] });
  await controller.load(); resolve({ count: 1, results: [row] }); await old;
  assert.equal(controller.state.query, 'new search'); assert.equal(controller.state.status, 'approved'); assert.deepEqual(controller.state.rows, []);
});
test('logout clears private query state even while the deep link remains in the URL', async () => {
  const { controller } = fixture();
  const route = parseRoute(queueRoute(w, 'purchase', { query: 'Private customer reference', status: 'draft' }));
  controller.context({ id: w, role: 'viewer' }, 1, route); await controller.load();
  controller.context(null, 2, route);
  assert.equal(controller.state.query, ''); assert.equal(controller.state.status, ''); assert.equal(controller.state.workspace, null); assert.deepEqual(controller.state.rows, []);
});
test('revocation clears queue and refreshes access; failures do not show an empty success', async () => {
  const { controller, client, denied } = fixture(); await controller.load();
  client.request = async () => { throw new ApiError(403, { detail: 'Access changed' }); };
  await controller.load(); assert.deepEqual(controller.state.rows, []); assert.deepEqual(denied, [true]); assert.equal(controller.state.loaded, false);
  client.request = async () => ({ count: 0, results: [] }); await controller.load(); assert.equal(controller.state.loaded, true); assert.match(controller.state.message, /No orders/);
});
test('next action distinguishes inactive, review, rejected and approved without claiming delivery', () => {
  assert.match(nextOrderAction({ ...row, status: 'approved' }), /readiness/);
  assert.match(nextOrderAction({ ...row, status: 'rejected' }), /rejection/);
  assert.match(nextOrderAction({ ...row, status: 'pending_review' }), /decision/);
  assert.match(nextOrderAction({ ...row, is_active: false }), /Inactive/);
});
