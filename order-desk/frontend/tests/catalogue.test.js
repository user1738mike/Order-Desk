import test from 'node:test';
import assert from 'node:assert/strict';
import { CatalogueController } from '../assets/desk/catalogue.js';
import { ApiError } from '../assets/desk/api.js';

const workspace = { id: 'a', role: 'admin' };
const file = () => new File(['sku,description,is_active\n0002.Mixed-Case,Fitting,true\n'], 'catalogue.csv');
function setup(request) {
  const controller = new CatalogueController({ request, refreshCsrf: async () => {} });
  controller.context(workspace, 1);
  return controller;
}
test('viewer and reviewer cannot invoke catalogue writes or validation', async () => {
  const c = setup(() => assert.fail('No request authorized'));
  for (const role of ['viewer', 'reviewer']) {
    c.context({ id: 'a', role }, 2);
    c.select(file()); await c.validate(); await c.create('sku', 'desc'); await c.execute();
    assert.equal(c.state.report, null);
  }
});
test('new file discards previous validation; oversized and empty files cannot be sent', async () => {
  const c = setup(() => assert.fail('Invalid file must not upload'));
  c.select(new File([], 'empty.csv')); assert.equal(c.state.file, null);
  c.select(new File(['x'.repeat(1048577)], 'large.csv')); assert.equal(c.state.file, null);
  c.select(file()); c.state.report = { can_import: true };
  c.select(file()); assert.equal(c.state.report, null);
});
test('validation never executes writes and exposes invalid row errors', async () => {
  const paths = [];
  const report = { can_import: false, errors: [{ row_number: 2, field: 'sku', message: 'Duplicate' }] };
  const c = setup(async path => { paths.push(path); return report; });
  c.select(file()); await c.validate(); await c.execute();
  assert.deepEqual(paths, ['/api/v1/workspaces/a/catalog/imports/dry-run/']);
  assert.equal(c.state.report, report);
});
test('lost import response reuses identical bytes/key and blocks replacement and duplicate clicks', async () => {
  const calls = []; let count = 0;
  const c = setup(async (path, options) => {
    calls.push({ path, options });
    if (path.endsWith('dry-run/')) return { can_import: true };
    if (++count === 1) throw new TypeError('Connection lost');
    return { created_count: 1, import_id: 'receipt' };
  });
  const original = file(); c.select(original); await c.validate(); await c.execute();
  assert.equal(c.state.uncertain, true);
  c.select(file()); assert.equal(c.state.file, original);
  await c.create('other', ''); assert.equal(calls.length, 2);
  await c.execute(true);
  assert.equal(c.state.uncertain, false);
  assert.equal(calls[1].options.idempotencyKey, calls[2].options.idempotencyKey);
  assert.equal(calls[1].options.body.get('file'), original);
  assert.equal(calls[2].options.body.get('file'), original);
});
test('workspace replacement erases private results and rejects a late validation response', async () => {
  let resolve;
  const c = setup(() => new Promise(r => { resolve = r; }));
  c.select(file()); const pending = c.validate();
  c.context({ id: 'b', role: 'admin' }, 2); resolve({ can_import: true }); await pending;
  assert.equal(c.state.report, null); assert.equal(c.state.file, null);
});
test('duplicate create clicks are suppressed and exact SKU strings are preserved', async () => {
  let resolve; const calls = [];
  const c = setup((_path, options) => { calls.push(options); return new Promise(r => { resolve = r; }); });
  const pending = c.create('0002.Mixed-Case/+x', 'Fitting'); await Promise.resolve();
  await c.create('duplicate', '');
  assert.equal(calls.length, 1); assert.equal(calls[0].body.sku, '0002.Mixed-Case/+x');
  resolve({ sku: '0002.Mixed-Case/+x' }); await pending;
});
test('ambiguous create requires exact lookup before another deliberate request', async () => {
  const calls = [];
  const c = setup(async path => { calls.push(path); if (path.includes('by-sku/')) return { sku: '0002', description: 'Saved' }; throw new TypeError('lost'); });
  await c.create('0002', 'Saved'); assert.equal(c.state.uncertain, true);
  await c.create('different', ''); assert.equal(calls.length, 1);
  await c.reconcileCreate(); assert.equal(c.state.uncertain, false);
  assert.match(c.state.message, /0002/);
});
test('revoked permission clears reports and invokes access refresh', async () => {
  const c = setup(async () => { throw new ApiError(403, { detail: 'Denied' }); });
  let refreshed = false; c.denied = async () => { refreshed = true; };
  c.select(file()); await c.validate();
  assert.equal(refreshed, true); assert.equal(c.state.file, null);
});
test('context replacement during CSRF bootstrap prevents sending a write', async () => {
  const c = setup(() => assert.fail('Old identity must not write'));
  let resolve; c.api.refreshCsrf = () => new Promise(r => { resolve = r; });
  const pending = c.create('private', ''); c.context(null, 2); resolve(); await pending;
  assert.equal(c.state.create, null); assert.equal(c.state.uncertain, false);
});
test('late committed creation cannot erase the new workspace operation', async () => {
  let resolve; const c = setup(() => new Promise(r => { resolve = r; }));
  const pending = c.create('private', ''); await Promise.resolve();
  c.context({ id: 'b', role: 'admin' }, 2); c.state.create = { sku: 'new-context' };
  resolve({ sku: 'private' }); await pending;
  assert.equal(c.state.create.sku, 'new-context'); assert.equal(c.state.message, '');
});
