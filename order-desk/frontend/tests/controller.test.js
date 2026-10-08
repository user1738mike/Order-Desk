import test from 'node:test';
import assert from 'node:assert/strict';
import { DeskController } from '../assets/desk/controller.js';
import { ApiError } from '../assets/desk/api.js';

const a = { id: 'a', name: 'Alpha', role: 'viewer' };
const b = { id: 'b', name: 'Beta', role: 'reviewer' };
const product = { sku: '<script>unsafe</script>', description: 'A product', is_active: true };
const list = { results: [a, b], count: 2, next: null };
function fixture(override = async () => undefined) {
  const calls = [];
  const api = {
    refreshCsrf: async () => {}, login: async () => {}, logout: async () => {},
    request: async (path, options = {}) => {
      calls.push({ path, options });
      const result = await override(path, options);
      if (result !== undefined) return result;
      if (path === '/api/v1/workspaces/') return list;
      if (path === '/api/v1/workspaces/current/') return { workspace: options.method === 'PUT' ? (options.body.workspace_id === 'a' ? a : b) : null };
      return { results: [product], count: 1 };
    },
  };
  const desk = new DeskController(api);
  return { api, desk, calls };
}
test('anonymous session opens login, outages offer retry rather than fake logout', async () => {
  for (const [error, phase] of [[new ApiError(403, {}), 'login'], [new Error('offline'), 'error']]) {
    const { desk } = fixture(async () => { throw error; });
    await desk.start(); assert.equal(desk.state.phase, phase);
  }
});
test('existing session restores selected workspace through fresh server context', async () => {
  const { desk, calls } = fixture(async path => path === '/api/v1/workspaces/current/' ? { workspace: a } : undefined);
  await desk.start();
  assert.equal(desk.state.workspace.id, 'a');
  assert.equal(desk.state.items.length, 1);
  assert.match(calls.at(-1).path, /workspaces\/a\/catalog/);
});
test('login goes to selection; only explicit selection opens catalogue', async () => {
  const { desk, calls } = fixture();
  await desk.login('member@example.test', 'synthetic');
  assert.equal(desk.state.phase, 'desk'); assert.equal(desk.state.workspace, null);
  assert.equal(calls.length, 2);
  await desk.selectWorkspace('b');
  assert.equal(desk.state.workspace.id, 'b'); assert.equal(desk.state.items.length, 1);
  assert.equal(calls[2].options.method, 'PUT');
});
test('empty workspace list is explained and never attempts catalogue access', async () => {
  const { desk, calls } = fixture(async path => path === '/api/v1/workspaces/' ? { results: [], count: 0 } : undefined);
  await desk.start();
  assert.match(desk.state.message, /no active workspaces/); assert.equal(calls.length, 2);
});
test('search is literal URL-encoded, blank omitted, filters and pagination are bounded API queries', async () => {
  const { desk, calls } = fixture(); await desk.selectWorkspace('a');
  await desk.search(' A&B_% ', 'false');
  let params = new URL(calls.at(-1).path, 'http://localhost').searchParams;
  assert.equal(params.get('q'), 'A&B_%'); assert.equal(params.get('is_active'), 'false');
  await desk.goToPage(2); assert.match(calls.at(-1).path, /page=2/);
  await desk.search('  ', ''); params = new URL(calls.at(-1).path, 'http://localhost').searchParams;
  assert.equal(params.has('q'), false); assert.equal(params.has('is_active'), false);
  assert.equal(params.get('page'), '1');
});
test('workspace switch erases old rows and resets filters before fetching new rows', async () => {
  let resolve;
  const { desk } = fixture(async path => path.includes('/b/catalog/') ? new Promise(done => { resolve = done; }) : undefined);
  await desk.selectWorkspace('a'); await desk.search('old', 'false');
  const pending = desk.selectWorkspace('b');
  await new Promise(done => setImmediate(done));
  assert.deepEqual(desk.state.items, []); assert.equal(desk.state.query, ''); assert.equal(desk.state.activity, '');
  resolve({ results: [{ sku: 'B only' }], count: 1 }); await pending;
  assert.equal(desk.state.items[0].sku, 'B only');
});
test('late responses cannot display products from a previous workspace', async () => {
  let resolve;
  const { desk } = fixture(async path => path.includes('/a/catalog/') ? new Promise(done => { resolve = done; }) : undefined);
  const old = desk.selectWorkspace('a'); await new Promise(done => setImmediate(done));
  await desk.selectWorkspace('b');
  resolve({ results: [{ sku: 'A private' }], count: 1 }); await old;
  assert.equal(desk.state.workspace.id, 'b'); assert.equal(desk.state.items[0].sku, product.sku);
});
test('out-of-order search responses never replace newest results', async () => {
  let resolve;
  const { desk } = fixture(async path => path.includes('q=old') ? new Promise(done => { resolve = done; }) : undefined);
  await desk.selectWorkspace('a'); const old = desk.search('old', '');
  await new Promise(done => setImmediate(done)); await desk.search('new', '');
  resolve({ results: [{ sku: 'old result' }], count: 1 }); await old;
  assert.equal(desk.state.items[0].sku, product.sku); assert.equal(desk.state.query, 'new');
});
test('revocation clears rows and context without looping on stale session selection', async () => {
  const { desk } = fixture(async path => {
    if (path.includes('/catalog/')) throw new ApiError(403, {});
    if (path === '/api/v1/workspaces/current/') return { workspace: a };
  });
  await desk.start();
  assert.equal(desk.state.phase, 'desk'); assert.equal(desk.state.workspace, null);
  assert.deepEqual(desk.state.items, []); assert.equal(desk.state.busy, false);
  assert.match(desk.state.message, /access changed/);
});
test('expired session during catalogue request clears data and returns to sign in', async () => {
  let expired = false;
  const { desk } = fixture(async path => {
    if (expired && (path.includes('/catalog/') || path === '/api/v1/workspaces/')) throw new ApiError(403, {});
  });
  await desk.selectWorkspace('a'); expired = true; await desk.loadCatalogue();
  assert.equal(desk.state.phase, 'login'); assert.equal(desk.state.workspace, null); assert.deepEqual(desk.state.items, []);
});
test('selection denial releases busy state and refreshes available workspaces', async () => {
  const { desk } = fixture(async (path, options) => { if (options.method === 'PUT') throw new ApiError(403, {}); });
  await desk.selectWorkspace('a'); assert.equal(desk.state.busy, false); assert.equal(desk.state.workspace, null);
});
test('catalogue outage has no stale results and can be retried', async () => {
  let fail = true;
  const { desk } = fixture(async path => { if (fail && path.includes('/catalog/')) throw new Error('offline'); });
  await desk.selectWorkspace('a'); assert.equal(desk.state.catalogError, true); assert.deepEqual(desk.state.items, []);
  fail = false; await desk.loadCatalogue(); assert.equal(desk.state.catalogError, false); assert.equal(desk.state.items.length, 1);
});
test('logout removes data, late catalogue responses cannot restore it, server failures are visible', async () => {
  let resolve;
  const { desk, api } = fixture(async path => path.includes('/catalog/') ? new Promise(done => { resolve = done; }) : undefined);
  const pending = desk.selectWorkspace('a'); await new Promise(done => setImmediate(done));
  await desk.logout(); resolve({ results: [product], count: 1 }); await pending;
  assert.equal(desk.state.phase, 'login'); assert.equal(desk.state.workspace, null); assert.deepEqual(desk.state.items, []);
  api.logout = async () => { throw new Error('offline'); };
  await desk.logout(); assert.equal(desk.state.phase, 'error'); assert.match(desk.state.message, /not confirmed/);
  assert.equal(desk.state.retryAction, 'logout');
});
test('workspace pagination uses our same-origin path rather than returned URL', async () => {
  const { desk, calls } = fixture(async path => path.endsWith('?page=2') ? { results: [b], next: 'https://untrusted.test/' } : undefined);
  desk.update({ workspaces: [a] }); await desk.moreWorkspaces();
  assert.equal(calls.at(-1).path, '/api/v1/workspaces/?page=2'); assert.equal(desk.state.workspaces.length, 2); assert.equal(desk.state.moreWorkspaces, true);
});
