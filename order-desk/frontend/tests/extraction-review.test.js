import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../assets/desk/api.js';
import { ExtractionReviewController, validateProvenance, provenanceLocation } from '../assets/desk/extraction-review.js';

const workspace = '11111111-1111-1111-1111-111111111111';
const order = '22222222-2222-2222-2222-222222222222';
const documentId = '33333333-3333-3333-3333-333333333333';
const jobId = '44444444-4444-4444-4444-444444444444';
const draftId = '55555555-5555-5555-5555-555555555555';
const lineId = '66666666-6666-6666-6666-666666666666';
const candidateId = '77777777-7777-7777-7777-777777777777';
const secondId = '88888888-8888-8888-8888-888888888888';
const applicationId = '99999999-9999-9999-9999-999999999999';
const operationKey = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const field = (column, value, index) => ({ column, value, raw: ` ${value} `, row: 2, end_row: 2, column_index: index });
const job = { id: jobId, document: documentId, organization: workspace, source_sha256: 'a'.repeat(64), parser_version: 'order-csv-v1', status: 'succeeded' };
const draft = { id: draftId, organization_id: workspace, initiating_user_id: lineId, customer_name: 'Synthetic customer', customer_reference: '00042', status: 'draft', source_type: 'manual', line_count: 1, original_intake_text: '', created_at: '2026-10-09T00:00:00Z', updated_at: '2026-10-09T00:00:00Z' };
const line = { id: lineId, organization_id: workspace, order_id: draftId, position: 1, requested_sku: 'MANUAL-KEEP', requested_description: 'Preserve manual description', quantity: '1.000', unit: 'ea', catalogue_item_id: null, catalogue_sku_snapshot: '', catalogue_description_snapshot: '' };
const candidate = { candidate_id: candidateId, fields: { sku: field('sku', '0001.Mixed-Case', 1), quantity: field('quantity', '1.234', 2), description: field('description', 'Synthetic description', 3) } };
const review = () => ({ job, result_revision: 'b'.repeat(64), draft, draft_revision: 'c'.repeat(64), count: 1, next: null, previous: null, results: [candidate], reviewed_fields: [] });
const receipt = body => ({ application_id: applicationId, job_id: body.job_id, draft_id: body.draft_id, revision: 'd'.repeat(64), review_complete: false, decisions: body.mappings.map(mapping => ({ candidate_id: mapping.candidate_id, action: mapping.action, line_id: mapping.action === 'reject' ? null : lineId, fields: Object.fromEntries(mapping.fields.map(name => [name, { source: candidate.fields[name], value: mapping.corrections?.[name] ?? candidate.fields[name].value, corrected: Object.hasOwn(mapping.corrections ?? {}, name) }])) })) });
function setup({ request = null, role = 'admin' } = {}) {
  const calls = [], denied = [], saved = []; let csrf = 0;
  const client = { refreshCsrf: async () => { csrf++; }, request: async (path, options = {}) => { calls.push({ path, options }); if (request) return request(path, options); if (options.method === 'POST') return { status: 201, data: receipt(options.body) }; if (path.includes('extraction/review/')) return review(); if (path.includes('lines/')) return { count: 1, next: null, previous: null, results: [line] }; if (path.includes('readiness/')) return { id: draftId, organization_id: workspace, ready_to_convert: false, line_count: 1, blocking_reasons: [{ code: 'catalogue_unmatched', count: 1 }] }; return { count: 1, next: null, previous: null, results: [draft] }; } };
  const controller = new ExtractionReviewController(client, () => {}, async action => denied.push(action), async id => saved.push(id), () => operationKey);
  controller.context({ id: workspace, role }, 1, order, { row: { id: documentId }, job });
  return { controller, calls, denied, saved, csrf: () => csrf };
}
function selectCreate(controller, fields = ['sku', 'quantity']) { controller.change(candidateId, { action: 'create', position: '2' }); for (const name of fields) controller.selectField(candidateId, name, true); }

test('loading source and target selects nothing and writes nothing', async () => {
  const { controller, calls } = setup(); await controller.load(draftId);
  assert.deepEqual(controller.state.choices, {}); assert.equal(controller.canApply(), false); assert.equal(calls.some(call => call.options.method === 'POST'), false);
  assert.equal(controller.state.candidates[candidateId].fields.sku.raw, ' 0001.Mixed-Case '); assert.equal(controller.state.lines[0].requested_sku, 'MANUAL-KEEP');
});

test('explicit field selection and correction preserve provenance and exact strings', async () => {
  const { controller, calls, csrf, saved } = setup(); await controller.load(draftId); selectCreate(controller);
  controller.correction(candidateId, 'quantity', true, '0001.250');
  assert.equal(controller.canApply(), true); await controller.apply();
  const body = calls.find(call => call.options.method === 'POST').options.body;
  assert.equal(body.operation_key, operationKey); assert.deepEqual(body.mappings, [{ candidate_id: candidateId, action: 'create', fields: ['quantity', 'sku'], corrections: { quantity: '0001.250' }, position: 2 }]);
  assert.equal(body.expected_draft_revision, 'c'.repeat(64)); assert.equal(body.result_revision, 'b'.repeat(64)); assert.equal(Object.hasOwn(body.mappings[0], 'raw'), false);
  assert.equal(csrf(), 1); assert.deepEqual(saved, [draftId]); assert.equal(controller.state.receipt.decisions[0].fields.quantity.corrected, true); assert.equal(controller.state.receipt.decisions[0].fields.quantity.source.raw, ' 1.234 '); assert.equal(controller.state.receipt.review_complete, false); assert.ok(controller.state.readiness); assert.deepEqual(controller.state.choices, {});
});

test('updating requires an explicit line ID; rejection does not send a target or correction', async () => {
  const { controller } = setup(); await controller.load(draftId);
  controller.change(candidateId, { action: 'update' }); controller.selectField(candidateId, 'sku', true); assert.equal(controller.canApply(), false);
  controller.target(candidateId, lineId); assert.equal(controller.canApply(), true); assert.equal(controller.selection().mappings[0].line_id, lineId);
  controller.change(candidateId, { action: 'reject', corrections: {} });
  assert.deepEqual(controller.selection().mappings, [{ candidate_id: candidateId, action: 'reject', fields: ['sku'] }]);
});

test('invalid precision, empty quantity, unselected corrections and duplicate targets fail closed', async () => {
  const { controller } = setup(); await controller.load(draftId); selectCreate(controller);
  controller.correction(candidateId, 'description', true, 'Unselected value'); assert.equal(Object.hasOwn(controller.choice(candidateId).corrections, 'description'), false);
  for (const value of ['1.2345', '', '1e3', '0.000', '1000000000', '-1', ' 1 ']) { controller.correction(candidateId, 'quantity', true, value); assert.equal(controller.canApply(), false, value); }
  controller.correction(candidateId, 'quantity', true, '1.234'); controller.change(candidateId, { action: 'update' }); controller.target(candidateId, lineId);
  controller.state.candidates[secondId] = { ...candidate, candidate_id: secondId }; controller.change(secondId, { action: 'update' }); controller.selectField(secondId, 'sku', true); controller.target(secondId, lineId);
  assert.equal(controller.canApply(), false); assert.match(controller.selection().errors.join(' '), /only once/);
});

test('validation errors retain selected fields and deliberate corrections', async () => {
  const { controller } = setup({ request: async (path, options) => { if (options.method === 'POST') throw new ApiError(400, { mappings: ['Source field invalid.'] }); return path.includes('extraction/review/') ? review() : { count: 1, next: null, results: [line] }; } });
  await controller.load(draftId); selectCreate(controller); controller.correction(candidateId, 'quantity', true, '1.250'); await controller.apply();
  assert.equal(controller.state.choices[candidateId].corrections.quantity, '1.250'); assert.equal(controller.state.pending, false); assert.equal(controller.state.receipt, null); assert.match(controller.state.errors.join(' '), /Source field invalid/); assert.equal(controller.canApply(), true);
});

test('stale draft keeps choices and blocks resubmission until comparison is deliberately accepted', async () => {
  let stale = false;
  const { controller, calls } = setup({ request: async (path, options) => { if (options.method === 'POST') { stale = true; throw new ApiError(412, { detail: 'draft_revision_conflict' }); } return path.includes('extraction/review/') ? { ...review(), draft_revision: stale ? 'e'.repeat(64) : 'c'.repeat(64) } : { count: 1, next: null, results: [{ ...line, quantity: stale ? '9.000' : '1.000' }] }; } });
  await controller.load(draftId); controller.change(candidateId, { action: 'update' }); controller.selectField(candidateId, 'quantity', true); controller.target(candidateId, lineId); controller.correction(candidateId, 'quantity', true, '1.250'); await controller.apply();
  assert.equal(controller.state.blocked, true); assert.equal(controller.state.choices[candidateId].corrections.quantity, '1.250'); await controller.apply(); assert.equal(calls.filter(call => call.options.method === 'POST').length, 1);
  await controller.load(draftId, 1, true); assert.equal(controller.state.comparison.targets[lineId].quantity, '9.000'); assert.equal(controller.state.review.draft_revision, 'c'.repeat(64)); assert.equal(controller.canApply(), false);
  controller.acceptComparison(); assert.equal(controller.state.review.draft_revision, 'e'.repeat(64)); assert.equal(controller.choice(candidateId).corrections.quantity, '1.250'); assert.equal(controller.choice(candidateId).target.quantity, '9.000'); assert.equal(controller.canApply(), true);
});

test('lost reply freezes the exact operation and reconciles by identical key without changing choices', async () => {
  let posts = 0; const submitted = [];
  const { controller } = setup({ request: async (path, options) => { if (options.method === 'POST') { submitted.push(structuredClone(options.body)); if (++posts === 1) throw new Error('Lost response'); return { status: 200, data: receipt(options.body) }; } if (path.includes('extraction/review/')) return review(); if (path.includes('readiness/')) return { id: draftId, organization_id: workspace, ready_to_convert: false, line_count: 1, blocking_reasons: [{ code: 'catalogue_unmatched', count: 1 }] }; return { count: 1, next: null, results: [line] }; } });
  await controller.load(draftId); selectCreate(controller); await controller.apply(); assert.equal(controller.state.uncertain, true); assert.equal(controller.discard(), false);
  controller.correction(candidateId, 'quantity', true, '9.999'); assert.equal(Object.hasOwn(controller.choice(candidateId).corrections, 'quantity'), false); await controller.apply(); assert.equal(posts, 1);
  await controller.apply(true); assert.deepEqual(submitted[0], submitted[1]); assert.equal(controller.state.uncertain, false); assert.equal(controller.state.receipt.replayed, true); assert.match(controller.state.message, /confirmed by replay/);
});

test('viewer can inspect but cannot apply; request denial rechecks current access', async () => {
  const viewer = setup({ role: 'viewer' }); await viewer.controller.load(draftId); selectCreate(viewer.controller); await viewer.controller.apply(); assert.equal(viewer.calls.some(call => call.options.method === 'POST'), false);
  const denied = setup({ request: async (path, options) => { if (options.method === 'POST') throw new ApiError(403, { detail: 'Denied' }); return path.includes('extraction/review/') ? review() : { count: 1, next: null, results: [line] }; } });
  await denied.controller.load(draftId); selectCreate(denied.controller); await denied.controller.apply(); assert.deepEqual(denied.denied, [true]); assert.equal(denied.controller.state.blocked, true);
});

test('late review and apply replies are discarded after workspace or session replacement', async () => {
  let finish;
  const slow = setup({ request: path => path.includes('extraction/review/') ? new Promise(resolve => { finish = resolve; }) : Promise.resolve({ count: 1, next: null, results: [line] }) });
  const load = slow.controller.load(draftId); slow.controller.context({ id: workspace, role: 'admin' }, 2, order, null); finish(review()); await load; assert.equal(slow.controller.state.review, null); assert.deepEqual(slow.controller.state.candidates, {});
  const applied = setup(); await applied.controller.load(draftId); selectCreate(applied.controller); applied.controller.client.request = (_path, options) => new Promise(resolve => { finish = () => resolve({ status: 201, data: receipt(options.body) }); });
  const apply = applied.controller.apply(); await Promise.resolve(); applied.controller.context({ id: workspace, role: 'admin' }, 3, order, null); finish(); await apply; assert.equal(applied.controller.state.receipt, null); assert.deepEqual(applied.saved, []);
});

test('foreign source or target and forged candidate responses cannot become writable', async () => {
  for (const data of [{ ...review(), job: { ...job, organization: order } }, { ...review(), draft: { ...draft, organization_id: order } }, { ...review(), results: [{ ...candidate, candidate_id: 'forged' }] }, { ...review(), results: [{ ...candidate, fields: { ...candidate.fields, sku: { ...candidate.fields.sku, row: -1 } } }] }, { ...review(), job: { ...job, status: 'failed' } }]) {
    const { controller } = setup({ request: async path => path.includes('extraction/review/') ? data : { count: 1, next: null, results: [line] } }); await controller.load(draftId); assert.equal(controller.state.review, null); assert.equal(controller.canApply(), false);
  }
});

test('PDF provenance is bounded text location evidence and remains distinct from CSV row locations', async () => {
  const pdfField = { value: '0001.Mixed-Case', raw: '0001.Mixed-Case', page: 2, line: 7, column: 'sku', span_start: 180, span_end: 195 };
  pdfField.span_end = pdfField.span_start + pdfField.raw.length;
  validateProvenance(pdfField, 'sku', 'order-text-pdf-v1', ['', `${' '.repeat(180)}${pdfField.raw}`]); assert.match(provenanceLocation(pdfField, 'order-text-pdf-v1'), /page 2, line 7.*offsets 180-/);
  for (const bad of [{ ...pdfField, page: 0 }, { ...pdfField, span_start: -1 }, { ...pdfField, span_end: 179 }, { ...pdfField, value: null }, { ...pdfField, column: 'identity' }]) assert.throws(() => validateProvenance(bad, 'sku', 'order-text-pdf-v1'));
  assert.throws(() => validateProvenance(pdfField, 'sku', 'unknown-parser'));
});
