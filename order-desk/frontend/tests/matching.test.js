import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../assets/desk/api.js';
import { MatchingController } from '../assets/desk/matching.js';

const w = '11111111-1111-4111-8111-111111111111';
const d = '22222222-2222-4222-8222-222222222222';
const l = '33333333-3333-4333-8333-333333333333';
const c = '44444444-4444-4444-8444-444444444444';
const revision = 'a'.repeat(64);
function response() { return { id: d, organization_id: w, rule_version: 'exact-sku-v1', draft_revision: revision, count: 1, results: [{ line_id: l, position: 1, source_sku: ' 0001.Mixed-Case ', source_truncated: false, normalized_sku: '0001.Mixed-Case', state: 'exact', candidate: { id: c, sku: '0001.Mixed-Case', description: '<img src=x>', description_truncated: false, is_active: true, revision: 'b'.repeat(64) }, attachment: { id: null, state: 'none' }, checks: { unit: 'not_modeled', pricing: 'not_modeled', quantity: 'not_assessed' } }] }; }
function fixture(request = async () => response()) {
  const calls = [], denied = [], opened = [];
  const drafts = { state: { generation: 1, workspace: { id: w, role: 'reviewer' }, draftId: d, draft: { status: 'draft' }, revision, linePage: 1, lines: [{ id: l, position: 1, requested_sku: ' 0001.Mixed-Case ', catalogue_item_id: null }], loading: false, linesLoading: false, dirty: false, converting: false }, open: async id => opened.push(id) };
  const client = { refreshCsrf: async () => calls.push('csrf'), request: async (path, options) => { calls.push({ path, options }); return request(path, options); } };
  const controller = new MatchingController(client, drafts, () => {}, async action => denied.push(action)); controller.context();
  return { controller, drafts, calls, denied, opened };
}

test('assessment is explicit, scoped and never writes on load', async () => {
  const { controller, calls } = fixture(); assert.deepEqual(controller.state.rows, []); assert.equal(calls.length, 0);
  await controller.load(); assert.equal(controller.state.rows[0].state, 'exact'); assert.match(calls[0].path, new RegExp(`${w}/draft-orders/${d}/suggestions/\\?page=1$`)); assert.equal(calls[0].options.method, undefined); assert.match(controller.state.message, /not checked/);
});
test('source normalization follows Python Unicode whitespace without discarding BOM', async () => {
  for (const [source, normalized, state] of [
    ['\u00850001.Mixed-Case\u0085', '0001.Mixed-Case', 'exact'],
    ['\u001c0001.Mixed-Case\u001f', '0001.Mixed-Case', 'exact'],
    ['\ufeff0001.Mixed-Case', '\ufeff0001.Mixed-Case', 'no_match'],
  ]) {
    const data = response(); Object.assign(data.results[0], { source_sku: source, normalized_sku: normalized, state });
    if (state === 'no_match') data.results[0].candidate = null;
    const { controller, drafts } = fixture(async () => data); drafts.state.lines[0].requested_sku = source;
    await controller.load(); assert.equal(controller.state.rows[0].state, state); assert.equal(controller.state.blocked, false);
  }
});
test('assessment bounds count Unicode codepoints without splitting astral SKU characters', async () => {
  for (const length of [3000, 4097]) {
    const source = '\u{1f600}'.repeat(length), bounded = '\u{1f600}'.repeat(Math.min(length, 4096));
    const data = response(); Object.assign(data.results[0], { source_sku: bounded, normalized_sku: bounded, source_truncated: length > 4096, state: length > 4096 ? 'unsupported_sku' : 'exact' });
    if (length > 4096) data.results[0].candidate = null;
    else Object.assign(data.results[0].candidate, { sku: source, description: '\u{1f600}'.repeat(4096) });
    const { controller, drafts } = fixture(async () => data); drafts.state.lines[0].requested_sku = source;
    await controller.load(); assert.equal(controller.state.rows[0].source_sku, bounded); assert.equal(controller.state.blocked, false);
  }
});
test('acceptance sends exact evidence, original revision and fresh CSRF then reloads actual state', async () => {
  const { controller, calls, opened } = fixture(async (path, options) => options?.method === 'POST' ? { id: l, organization_id: w, order_id: d, catalogue_item_id: c, catalogue_sku_snapshot: '0001.Mixed-Case' } : response());
  await controller.load(); await controller.accept(controller.state.rows[0]);
  const write = calls.find(call => call.options?.method === 'POST'); assert.equal(calls[calls.indexOf(write) - 1], 'csrf'); assert.equal(write.options.revision, revision); assert.deepEqual(write.options.body, { catalogue_item_id: c, rule_version: 'exact-sku-v1', source_sku: '0001.Mixed-Case', catalogue_revision: 'b'.repeat(64) }); assert.deepEqual(opened, [d]);
});
test('viewer can inspect while dirty, converted, unmatched and inactive rows cannot be accepted', async () => {
  const { controller, drafts, calls } = fixture(); drafts.state.workspace.role = 'viewer'; await controller.load(); await controller.accept(controller.state.rows[0]); assert.equal(calls.length, 1);
  drafts.state.workspace.role = 'reviewer'; const row = controller.state.rows[0];
  for (const state of ['inactive', 'no_match', 'already_attached', 'ambiguous']) assert.equal(controller.canAccept({ ...row, state }), false);
  for (const property of ['dirty', 'converting', 'loading', 'linesLoading']) { drafts.state[property] = true; assert.equal(controller.canAccept(row), false); drafts.state[property] = false; }
  drafts.state.draft.status = 'converted'; assert.equal(controller.canAccept(row), false);
});
test('source and catalogue conflicts block acceptance without replacing the revision', async () => {
  for (const status of [409, 412]) {
    let writes = 0; const { controller, drafts } = fixture(async (path, options) => { if (options?.method === 'POST') { writes++; throw new ApiError(status, { detail: 'changed' }); } return response(); });
    await controller.load(); const row = controller.state.rows[0]; await controller.accept(row); await controller.accept(row); assert.equal(writes, 1); assert.equal(drafts.state.revision, revision); assert.equal(controller.state.blocked, true); assert.match(controller.state.message, /Reload and compare/);
  }
});
test('unconfirmed outcomes forbid blind retry until deliberate actual-state reload', async () => {
  let writes = 0; const { controller, opened } = fixture(async (path, options) => { if (options?.method === 'POST') { writes++; throw new TypeError('Lost reply'); } return response(); });
  await controller.load(); const row = controller.state.rows[0]; await controller.accept(row); await controller.accept(row); await controller.load(); assert.equal(writes, 1); assert.equal(controller.state.uncertain, true);
  await controller.reload(); assert.deepEqual(opened, [d]); assert.equal(controller.state.uncertain, false);
});
test('fresh write denial rechecks access and pending clicks do not duplicate requests', async () => {
  const { controller, denied } = fixture(async (path, options) => { if (options?.method === 'POST') throw new ApiError(403, { detail: 'Denied' }); return response(); });
  await controller.load(); await controller.accept(controller.state.rows[0]); assert.deepEqual(denied, [true]);
  let done, posts = 0; const f = fixture(async (path, options) => { if (options?.method === 'POST') { posts++; return new Promise(resolve => { done = resolve; }); } return response(); }); await f.controller.load(); const row = f.controller.state.rows[0]; const pending = f.controller.accept(row); await new Promise(resolve => setImmediate(resolve)); await f.controller.accept(row); assert.equal(posts, 1); done({ id: l, organization_id: w, order_id: d, catalogue_item_id: c, catalogue_sku_snapshot: row.normalized_sku }); await pending;
});
test('late workspace and session assessment responses are discarded', async () => {
  for (const change of ['workspace', 'generation', 'revision', 'linePage', 'dirty']) {
    let done; const { controller, drafts } = fixture(() => new Promise(resolve => { done = resolve; })); const load = controller.load();
    if (change === 'workspace') drafts.state.workspace = { id: c, role: 'admin' }; else if (change === 'dirty') drafts.state.dirty = true; else drafts.state[change] = change === 'revision' ? 'c'.repeat(64) : 2;
    controller.context(); done(response()); await load; assert.deepEqual(controller.state.rows, []);
  }
});
test('foreign, stale and fabricated rule evidence fails closed', async () => {
  for (const mutate of [data => { data.organization_id = c; }, data => { data.draft_revision = 'd'.repeat(64); }, data => { data.results[0].line_id = c; }, data => { data.results[0].source_sku = 'other'; }, data => { data.rule_version = 'fuzzy'; }, data => { data.results[0].checks.pricing = 'checked'; }, data => { data.results[0].candidate.sku = 'folded'; }]) {
    const data = response(); mutate(data); const { controller } = fixture(async () => data); await controller.load(); assert.deepEqual(controller.state.rows, []); assert.equal(controller.state.blocked, true);
  }
});
