import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiError } from '../assets/desk/api.js';
import { OrdersApi, blockers, parseRoute, validateReasons } from '../assets/desk/orders-api.js';
import { DraftController } from '../assets/desk/orders-controller.js';

const w = '11111111-1111-1111-1111-111111111111';
const b = '22222222-2222-2222-2222-222222222222';
const d = '33333333-3333-3333-3333-333333333333';
const p = '44444444-4444-4444-4444-444444444444';
const header = { id: d, organization_id: w, customer_name: 'Client', customer_reference: '', status: 'draft', source_type: 'manual', line_count: 1, original_intake_text: 'Manual', initiating_user_id: p, created_at: '2026-10-08T12:00:00Z', updated_at: '2026-10-08T12:00:00Z' };
const line = { id: p, organization_id: w, order_id: d, position: 1, requested_sku: '0001.Mixed-Case', requested_description: '<img src=x>', quantity: '999999999.999', unit: 'ea', catalogue_item_id: p, catalogue_sku_snapshot: '0001.Mixed-Case', catalogue_description_snapshot: 'Exact snapshot' };
const ready = { id: d, organization_id: w, ready_to_convert: true, line_count: 1, blocking_reasons: [] };
const result = { id: p, organization_id: w, source_draft_id: d, purchase_order_number: 'DRAFT-source', order_url: `/api/v1/workspaces/${w}/orders/${p}/` };
const page = results => ({ count: results.length, results, next: null });
function fixture(overrides = {}, role = 'admin') {
  const calls = [];
  const api = {
    list: async (...args) => { calls.push(args); return page([header]); },
    detail: async () => header, lines: async () => page([line]),
    review: async () => ({ line_count: 1 }), readiness: async () => ready,
    convert: async () => ({ ...result, replayed: false }), ...overrides,
  };
  const denied = [];
  const desk = new DraftController(api, () => {}, async action => denied.push(action));
  desk.context({ id: w, role }, 1);
  return { desk, api, calls, denied };
}
test('hash routes preserve explicit UUID context, direct detail and invalid routes', () => {
  assert.deepEqual(parseRoute(`#/workspaces/${w}/draft-orders/${d}/`), { screen: 'drafts', workspace: w, draft: d });
  assert.equal(parseRoute(`#/workspaces/${w}/draft-orders/`).draft, undefined);
  for (const hash of ['#/workspaces/not-uuid/draft-orders/', `#/workspaces/${w}/catalogue/${d}/`, '#/unknown', `#/workspaces/${w}/draft-orders/not-uuid/`]) assert.equal(parseRoute(hash).screen, 'missing');
});
test('list and line APIs request one fixed page and keep exact quantity and SKU strings', async () => {
  const calls = [];
  const api = new OrdersApi({ request: async path => { calls.push(path); return path.includes('/lines/') ? page([line]) : page([header]); } });
  await api.list(w, 2); const lines = await api.lines(w, d, 3);
  assert.match(calls[0], /draft-orders\/\?page=2$/); assert.match(calls[1], /lines\/\?page=3$/);
  assert.equal(lines.results[0].quantity, '999999999.999'); assert.equal(lines.results[0].requested_sku, '0001.Mixed-Case');
});
test('critical response validators reject foreign resources, numeric decimals and unbounded pages', async () => {
  for (const changed of [{ ...line, organization_id: b }, { ...line, order_id: b }, { ...line, quantity: 1.234 }, { ...line, quantity: 'NaN' }, { ...line, quantity: '0.000' }]) {
    const api = new OrdersApi({ request: async () => page([changed]) });
    await assert.rejects(api.lines(w, d, 1), /Unsupported response/);
  }
  for (const data of [null, { ...page([header]), results: Array(51).fill(header) }, page([{ ...header, status: 'approved' }])]) {
    const api = new OrdersApi({ request: async () => data });
    await assert.rejects(api.list(w, 1), /Unsupported response/);
  }
});
test('readiness validates blocker types, unique codes and ready consistency; no invented warnings', async () => {
  assert.equal(Object.keys(blockers).length, 7);
  for (const code of Object.keys(blockers)) assert.deepEqual(validateReasons([{ code, count: 1 }]), [{ code, count: 1 }]);
  for (const changed of [{ ...ready, ready_to_convert: 'true' }, { ...ready, blocking_reasons: [{ code: 'quantity_missing', count: 1 }] }, { ...ready, ready_to_convert: false, blocking_reasons: [{ code: 'guessed_warning', count: 1 }] }]) {
    const api = new OrdersApi({ request: async () => changed }); await assert.rejects(api.readiness(w, d), /Unsupported response/);
  }
});
test('conversion sends only empty JSON, fresh CSRF and distinguishes first success/replay', async () => {
  for (const status of [201, 200]) {
    const calls = [];
    const client = new ApiClient(async (path, options) => {
      calls.push({ path, ...options });
      return { status: path.endsWith('csrf/') ? 200 : status, ok: true, json: async () => path.endsWith('csrf/') ? { csrf_token: 'fresh' } : result };
    });
    const confirmed = await new OrdersApi(client).convert(w, d);
    assert.equal(confirmed.replayed, status === 200); assert.equal(calls[1].body, '{}');
    assert.equal(calls[1].headers['X-CSRFToken'], 'fresh'); assert.equal(calls[1].credentials, 'same-origin');
    assert.match(calls[1].path, /convert\/$/);
  }
});
test('malformed conversion successes and unsafe order links never become confirmed', async () => {
  for (const changed of [{ ...result, source_draft_id: b }, { ...result, order_url: 'https://other.test/' }, { ...result, organization_id: b }]) {
    const api = new OrdersApi({ refreshCsrf: async () => {}, request: async () => ({ data: changed, status: 201 }) });
    await assert.rejects(api.convert(w, d), /Unsupported response/);
  }
});
test('list pagination and detail navigation reset prior private content', async () => {
  const { desk, calls } = fixture(); await desk.list(2); assert.equal(calls[0][1], 2);
  await desk.open(d); assert.deepEqual(desk.state.rows, []); assert.equal(desk.state.draft.id, d); assert.equal(desk.state.lines[0].quantity, '999999999.999');
  await desk.list(); assert.equal(desk.state.draft, null); assert.equal(desk.state.readiness, null); assert.deepEqual(desk.state.lines, []);
});
test('independent panel failures preserve valid header and disable new conversion', async () => {
  const { desk } = fixture({ readiness: async () => { throw new Error('Readiness unavailable'); } });
  await desk.open(d); assert.equal(desk.state.draft.id, d); assert.equal(desk.state.review.line_count, 1); assert.equal(desk.canConvert(), false);
  assert.match(desk.state.errors.readiness, /unavailable/);
});
test('missing/foreign draft is explained and never turned into empty successful data', async () => {
  const { desk } = fixture({ detail: async () => { throw new ApiError(404, {}); } });
  await desk.open(d); assert.equal(desk.state.draft, null); assert.match(desk.state.errors.detail, /not found or unavailable/);
});
test('viewer and reviewer cannot invoke conversion; converted admin can authorize replay', async () => {
  for (const role of ['viewer', 'reviewer']) {
    let calls = 0; const { desk } = fixture({ convert: async () => { calls++; } }, role);
    await desk.open(d); await desk.convert(); assert.equal(calls, 0); assert.equal(desk.canConvert(), false);
  }
  const { desk } = fixture({ detail: async () => ({ ...header, status: 'converted' }), readiness: async () => ({ ...ready, ready_to_convert: false, blocking_reasons: [{ code: 'draft_already_converted', count: 1 }] }) });
  await desk.open(d); assert.equal(desk.canConvert(), true);
});
test('pending conversion suppresses duplicate posts and shows no optimistic result', async () => {
  let resolve, calls = 0; const { desk, api } = fixture({ convert: async () => { calls++; return new Promise(done => { resolve = done; }); } });
  await desk.open(d); const pending = desk.convert(); await desk.convert(); assert.equal(calls, 1); assert.equal(desk.state.converting, true); assert.equal(desk.state.result, null);
  api.detail = async () => ({ ...header, status: 'converted' }); resolve({ ...result, replayed: false }); await pending;
  assert.equal(desk.state.result.id, p); assert.equal(desk.state.draft.status, 'converted'); assert.equal(desk.state.converting, false);
});
test('server conflict overrides cached ready=true and refreshes blockers without retrying POST', async () => {
  let calls = 0; const reason = { code: 'catalogue_inactive', count: 1 };
  const { desk, api } = fixture({ convert: async () => { calls++; throw new ApiError(409, { detail: 'draft_not_ready', blocking_reasons: [reason] }); } });
  await desk.open(d); api.readiness = async () => ({ ...ready, ready_to_convert: false, blocking_reasons: [reason] });
  await desk.convert(); assert.equal(calls, 1); assert.equal(desk.state.result, null); assert.equal(desk.canConvert(), false); assert.deepEqual(desk.state.conflict, [reason]);
});
test('ambiguous network result is unconfirmed; explicit replay confirms the same source', async () => {
  let calls = 0; const { desk, api } = fixture({ convert: async () => { calls++; throw new TypeError('lost response'); } });
  await desk.open(d); await desk.convert(); assert.equal(desk.state.result, null); assert.equal(desk.state.uncertain, true); assert.equal(calls, 1);
  api.convert = async () => ({ ...result, replayed: true }); api.detail = async () => ({ ...header, status: 'converted' });
  await desk.convert(); assert.equal(desk.state.uncertain, false); assert.equal(desk.state.result.id, p); assert.match(desk.state.message, /Existing/);
});
test('action 403 revalidates role; read 403 revalidates session/workspace, without assuming logout', async () => {
  const { desk, denied } = fixture({ convert: async () => { throw new ApiError(403, {}); } });
  await desk.open(d); await desk.convert(); assert.deepEqual(denied, [true]); assert.equal(desk.state.result, null);
  const read = fixture({ detail: async () => { throw new ApiError(403, {}); } }); await read.desk.open(d); assert.deepEqual(read.denied, [false]);
});
test('late detail, readiness and conversion never repopulate a replaced workspace or session', async () => {
  for (const operation of ['detail', 'readiness', 'convert']) {
    let resolve;
    const { desk, api } = fixture();
    if (operation === 'convert') await desk.open(d);
    api[operation] = async () => new Promise(done => { resolve = done; });
    const pending = operation === 'convert' ? desk.convert() : desk.open(d);
    await new Promise(done => setImmediate(done));
    desk.context({ id: b, role: 'admin' }, 2);
    resolve(operation === 'detail' ? header : operation === 'readiness' ? ready : result);
    await pending; assert.equal(desk.state.draft, null); assert.equal(desk.state.readiness, null); assert.equal(desk.state.result, null);
    desk.context(null, 3); assert.equal(desk.state.workspace, null);
  }
});
test('same-workspace new session generation rejects old private results', async () => {
  let resolve; const { desk } = fixture({ detail: async () => new Promise(done => { resolve = done; }) });
  const pending = desk.open(d); desk.context({ id: w, role: 'viewer' }, 2); resolve(header); await pending; assert.equal(desk.state.draft, null);
});
test('late line-page response cannot replace the newest page', async () => {
  let resolve; const { desk, api } = fixture(); await desk.open(d);
  api.lines = async (_w, _d, number) => number === 2 ? new Promise(done => { resolve = done; }) : page([{ ...line, position: 101 }]);
  const old = desk.lines(2); await desk.lines(3); resolve(page([{ ...line, position: 51 }])); await old;
  assert.equal(desk.state.linePage, 3); assert.equal(desk.state.lines[0].position, 101);
});
