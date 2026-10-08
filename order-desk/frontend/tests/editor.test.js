import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../assets/desk/api.js';
import { OrdersApi } from '../assets/desk/orders-api.js';
import { DraftEditor, editPayload } from '../assets/desk/editor.js';

const w = '11111111-1111-1111-1111-111111111111';
const d = '22222222-2222-2222-2222-222222222222';
const l = '33333333-3333-3333-3333-333333333333';
const revision = 'a'.repeat(64);
function fixture(api = {}, role = 'admin') {
  const drafts = { state: { generation: 1, workspace: { id: w, role }, draftId: d, draft: { id: d, status: 'draft', customer_name: 'Original', customer_reference: '00042' }, revision, readiness: { ready_to_convert: true } }, update(patch) { Object.assign(this.state, patch); }, open: async () => {} };
  const saved = [], denied = [];
  const editor = new DraftEditor(api, drafts, () => {}, async id => saved.push(id), async () => denied.push(true));
  editor.context();
  return { editor, drafts, saved, denied };
}

test('header whitelist preserves blank, exact strings and rejects Unicode whitespace', () => {
  const payload = editPayload('header', { customer_name: '', customer_reference: ' 00042 ', status: 'converted', id: l });
  assert.deepEqual(payload, { data: { customer_name: '', customer_reference: ' 00042 ' }, errors: {} });
  for (const value of ['  ', '\t\r\n', '\u2003']) assert.deepEqual(editPayload('header', { customer_name: value }).errors.customer_name, ['Provide a nonblank value or an empty string.']);
  assert.equal(editPayload('create', { original_intake_text: '<img src=x>' }).data.original_intake_text, '<img src=x>');
});

test('quantity payload preserves exact decimals; rejects rounding, scientific/comma/zero and excessive precision', () => {
  for (const value of ['1.234', '999999999.999', '0001.001']) {
    const { data, errors } = editPayload('line', { requested_sku: '0001.Mixed-Case', quantity: value });
    assert.deepEqual(errors, {}); assert.equal(data.quantity, value); assert.equal(data.requested_sku, '0001.Mixed-Case');
  }
  assert.equal(editPayload('line', { requested_description: 'Text', quantity: '' }).data.quantity, null);
  for (const value of ['0', '0.000', '-1', '1e2', '1,234', '1.2345', '1000000000', 'Infinity', 'NaN', ' ']) assert.ok(editPayload('line', { requested_sku: 'SKU', quantity: value }).errors.quantity, value);
  assert.ok(editPayload('line', {}).errors.requested_sku);
  for (const position of ['0', '1.5', '2147483648', '-1']) assert.ok(editPayload('add-line', { position, requested_sku: 'SKU' }).errors.position);
  assert.equal(editPayload('add-line', { position: '2', requested_sku: 'SKU' }).data.position, 2);
});

test('attachment/detachment only send documented fields', () => {
  assert.deepEqual(editPayload('attach', { catalogue_item_id: l, requested_sku: 'Change' }), { data: { catalogue_item_id: l }, errors: {} });
  assert.deepEqual(editPayload('detach', { catalogue_item_id: l, requested_sku: 'Change' }), { data: {}, errors: {} });
  assert.ok(editPayload('attach', {}).errors.catalogue_item_id);
});

test('all edit APIs send revision precondition and fresh CSRF using stable resource IDs', async () => {
  const calls = [];
  const api = new OrdersApi({ refreshCsrf: async () => calls.push('csrf'), request: async (path, options) => { calls.push({ path, options }); return { id: path.endsWith(`${d}/`) ? d : l, organization_id: w, order_id: d, status: 'draft', source_type: 'manual', customer_name: '', customer_reference: '', line_count: 0, created_at: '2026-10-09T12:00:00Z', updated_at: '2026-10-09T12:00:00Z', original_intake_text: '', initiating_user_id: l }; } });
  for (const mode of ['header', 'add-line', 'line', 'attach', 'detach']) {
    await api.edit(w, d, mode, l, {}, revision);
    assert.equal(calls.at(-2), 'csrf'); assert.equal(calls.at(-1).options.revision, revision);
    assert.equal(calls.at(-1).options.method, ['header', 'line'].includes(mode) ? 'PATCH' : 'POST');
    if (['line', 'attach', 'detach'].includes(mode)) assert.ok(calls.at(-1).path.includes(l));
  }
  await assert.rejects(api.edit(w, d, 'header', null, {}, null), /Unsupported/);
});

test('validation failures preserve values and support explicit corrected save', async () => {
  let calls = 0;
  const { editor, saved } = fixture({ edit: async () => { if (++calls === 1) throw new ApiError(400, { customer_name: ['Invalid.'] }); return { id: d }; } });
  editor.begin('header'); editor.change('customer_name', 'Unsaved'); await editor.save();
  assert.equal(editor.state.input.customer_name, 'Unsaved'); assert.deepEqual(editor.state.errors.customer_name, ['Invalid.']); assert.equal(editor.state.pending, false);
  editor.change('customer_name', 'Corrected'); await editor.save(); assert.deepEqual(saved, [d]); assert.equal(editor.state.open, false);
});

test('stale or locked save preserves unsaved values and blocks automatic retry', async () => {
  for (const status of [409, 412]) {
    let calls = 0;
    const { editor, drafts, saved } = fixture({ edit: async () => { calls++; throw new ApiError(status, { detail: 'draft_revision_conflict' }); } });
    editor.begin('header'); editor.change('customer_name', 'My unsaved copy'); await editor.save(); await editor.save();
    assert.equal(calls, 1); assert.equal(editor.state.input.customer_name, 'My unsaved copy'); assert.equal(editor.state.blocked, true); assert.deepEqual(saved, []); assert.equal(drafts.state.readiness, null);
  }
});

test('pending mutation prevents duplicate requests and successful save invalidates readiness', async () => {
  let resolve, calls = 0;
  const { editor, drafts, saved } = fixture({ edit: async () => { calls++; return new Promise(done => { resolve = done; }); } });
  editor.begin('header'); const pending = editor.save(); await editor.save();
  assert.equal(calls, 1); assert.equal(editor.state.pending, true); assert.equal(drafts.state.readiness, null);
  resolve({ id: d }); await pending; assert.deepEqual(saved, [d]); assert.equal(drafts.state.dirty, false);
});

test('ambiguous creation and insertion outcomes never automatically repeat POST', async () => {
  for (const mode of ['create', 'add-line']) {
    let calls = 0; const fail = async () => { calls++; throw new TypeError('connection lost'); };
    const { editor } = fixture({ create: fail, edit: fail });
    editor.begin(mode); if (mode === 'add-line') { editor.change('position', '1'); editor.change('requested_sku', 'SKU'); }
    await editor.save(); await editor.save(); assert.equal(calls, 1); assert.equal(editor.state.blocked, true); assert.match(editor.state.message, /unconfirmed/);
  }
});

test('viewer and converted sources cannot edit; reviewer can; action denial rechecks access', async () => {
  const viewer = fixture({}, 'viewer'); viewer.editor.begin('header'); assert.equal(viewer.editor.state.open, false);
  const reviewer = fixture({}, 'reviewer'); reviewer.editor.begin('header'); assert.equal(reviewer.editor.state.open, true);
  reviewer.drafts.state.draft.status = 'converted'; assert.equal(Boolean(reviewer.editor.canEdit()), false);
  const { editor, denied } = fixture({ edit: async () => { throw new ApiError(403, {}); } });
  editor.begin('header'); await editor.save(); assert.deepEqual(denied, [true]); assert.equal(editor.state.blocked, true);
});

test('session/workspace replacement clears private inputs and ignores late mutation results', async () => {
  let resolve; const { editor, drafts, saved } = fixture({ edit: async () => new Promise(done => { resolve = done; }) });
  editor.begin('header'); editor.change('customer_name', 'Private'); const pending = editor.save();
  drafts.state.generation++; editor.context(); resolve({ id: d }); await pending;
  assert.deepEqual(editor.state.input, {}); assert.equal(editor.state.open, false); assert.deepEqual(saved, []);
});

test('bounded active catalogue search validates tenant data and rejects late search results', async () => {
  let resolve; const calls = [];
  const { editor } = fixture({ client: { request: async path => { calls.push(path); if (path.includes('q=old')) return new Promise(done => { resolve = done; }); return { count: 1, results: [{ id: l, organization_id: w, sku: '0001.Case', is_active: true }] }; } } });
  editor.begin('header'); const old = editor.catalogue('old'); await editor.catalogue('new', 2); resolve({ count: 0, results: [] }); await old;
  assert.match(calls.at(-1), /page=2&is_active=true&q=new/); assert.equal(editor.state.items[0].id, l);
  editor.api.client.request = async () => ({ count: 1, results: [{ organization_id: d, sku: 'Private', is_active: true }] });
  await editor.catalogue('foreign'); assert.deepEqual(editor.state.items, []); assert.match(editor.state.message, /Unable/);
});
