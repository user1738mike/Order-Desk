import { ApiError } from './api.js';
import { OrdersApi, UUID } from './orders-api.js';

const REVISION = /^[0-9a-f]{64}$/;
const FIELDS = ['sku', 'quantity', 'description', 'unit'];
const TARGET_FIELDS = { sku: 'requested_sku', description: 'requested_description', quantity: 'quantity', unit: 'unit' };
const valid = condition => { if (!condition) throw new Error('Review response unavailable. Refresh before applying.'); };
export function validateProvenance(field, name, parser, pages = null) {
  valid(field && typeof field.value === 'string' && field.value.length <= 4096 && typeof field.raw === 'string' && field.raw.length <= 4096 && field.column === name);
  if (parser === 'order-csv-v1') valid(Number.isSafeInteger(field.row) && field.row >= 2 && Number.isSafeInteger(field.end_row) && field.end_row >= field.row && Number.isSafeInteger(field.column_index) && field.column_index >= 1 && field.column_index <= 4);
  else if (parser === 'order-text-pdf-v1') {
    valid(Number.isSafeInteger(field.page) && field.page >= 1 && Number.isSafeInteger(field.line) && field.line >= 1 && Number.isSafeInteger(field.span_start) && field.span_start >= 0 && Number.isSafeInteger(field.span_end) && field.span_end >= field.span_start && field.span_end - field.span_start === Array.from(field.raw).length);
    if (pages !== null && pages !== undefined) {
      valid(Array.isArray(pages) && pages.length >= 1 && pages.length <= 10 && pages.every(page => typeof page === 'string' && Array.from(page).length <= 65536) && pages.reduce((total, page) => total + Array.from(page).length, 0) <= 262144 && field.page <= pages.length);
      const text = Array.from(pages[field.page - 1]); valid(field.span_end <= text.length && text.slice(field.span_start, field.span_end).join('') === field.raw);
    }
  }
  else valid(false);
}
export function provenanceLocation(field, parser) {
  return parser === 'order-csv-v1' ? `source rows ${field.row}-${field.end_row}, column ${field.column_index} (${field.column})` : `source page ${field.page}, line ${field.line}, ${field.column}, text offsets ${field.span_start}-${field.span_end}`;
}

export class ExtractionReviewController {
  constructor(client, render = () => {}, denied = async () => {}, saved = async () => {}, operationKey = () => crypto.randomUUID()) {
    this.client = client; this.api = new OrdersApi(client); this.render = render; this.denied = denied; this.saved = saved; this.operationKey = operationKey; this.version = 0; this.state = this.empty();
  }
  empty() { return { workspace: null, generation: null, order: null, source: null, sourceJob: null, available: false, drafts: [], draftCount: 0, draftPage: 1, draftId: null, review: null, candidates: {}, page: 1, lines: [], lineCount: 0, linePage: 1, choices: {}, busy: false, pending: false, uncertain: false, blocked: false, comparison: null, operation: null, receipt: null, readiness: null, message: '', errors: [] }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context(workspace, generation, order, extraction) {
    const source = extraction?.row ?? null;
    const key = `${generation}/${workspace?.id ?? ''}/${workspace?.role ?? ''}/${order ?? ''}/${source?.id ?? ''}/${source?.draft ?? ''}`;
    const job = extraction?.job ?? null;
    if (key !== this.contextKey || (job && this.state.sourceJob && job.id !== this.state.sourceJob.id)) {
      this.contextKey = key; this.version++; this.abort?.abort(); this.state = { ...this.empty(), workspace, generation, order, source, sourceJob: job, available: job?.status === 'succeeded' }; this.render(this.state); return;
    }
    this.state.workspace = workspace;
    this.state.available = job?.status === 'succeeded';
    if (job) this.state.sourceJob = job;
  }
  path(suffix) {
    const s = this.state;
    valid(UUID.test(s.workspace?.id) && (UUID.test(s.order) || s.order === 'incoming') && UUID.test(s.source?.id));
    if (s.order === 'incoming') return `/api/v1/workspaces/${s.workspace.id}/incoming/${s.source.id}/extraction/${suffix}/`;
    return `/api/v1/workspaces/${s.workspace.id}/orders/${s.order}/documents/${s.source.id}/extraction/${suffix}/`;
  }
  live(version, abort) { return version === this.version && !abort.signal.aborted; }
  hasUnsaved() { return Object.values(this.state.choices).some(choice => choice.action || choice.fields.length) || this.state.uncertain; }
  canChange() { return !this.state.pending && !this.state.uncertain && !this.state.busy; }
  discard() { if (this.state.pending || this.state.uncertain) return false; this.update({ choices: {}, operation: null, comparison: null, errors: [], blocked: false }); return true; }
  validateReview(data, draftId) {
    const s = this.state; const job = data?.job;
    valid(job && job.id === s.sourceJob?.id && job.document === s.source.id && job.organization === s.workspace.id && job.status === 'succeeded' && ['order-csv-v1', 'order-text-pdf-v1'].includes(job.parser_version) && job.parser_version === s.sourceJob.parser_version && job.source_sha256 === s.sourceJob.source_sha256 && REVISION.test(job.source_sha256));
    valid(REVISION.test(data.result_revision) && REVISION.test(data.draft_revision) && data.draft?.id === draftId && data.draft.organization_id === s.workspace.id && ['draft', 'converted'].includes(data.draft.status) && typeof data.draft.customer_name === 'string' && typeof data.draft.customer_reference === 'string');
    valid(Number.isSafeInteger(data.count) && data.count >= 0 && data.count <= 500 && Array.isArray(data.results) && data.results.length <= 50 && Array.isArray(data.reviewed_fields));
    const ids = new Set();
    for (const candidate of data.results) {
      valid(UUID.test(candidate?.candidate_id) && !ids.has(candidate.candidate_id) && candidate.fields?.sku && candidate.fields.quantity && Object.keys(candidate.fields).every(name => FIELDS.includes(name))); ids.add(candidate.candidate_id);
      for (const [name, field] of Object.entries(candidate.fields)) validateProvenance(field, name, job.parser_version, job.result_pages);
    }
    for (const reviewed of data.reviewed_fields) valid(UUID.test(reviewed?.candidate_id) && Array.isArray(reviewed.fields) && reviewed.fields.every(name => FIELDS.includes(name)));
    return data;
  }
  async listDrafts(page = 1) {
    if (this.state.order === 'incoming') { if (this.state.source?.draft) await this.load(this.state.source.draft); else this.update({ message: 'Create or link a draft from this source before reviewing proposals.' }); return; }
    if (!this.state.available || !this.canChange()) return;
    this.abort?.abort(); const abort = this.abort = new AbortController(); const version = ++this.version;
    this.update({ busy: true, message: '', draftPage: page });
    try { const data = await this.api.list(this.state.workspace.id, page, abort.signal); if (this.live(version, abort)) this.update({ drafts: data.results, draftCount: data.count }); }
    catch (error) { if (this.live(version, abort)) { this.update({ message: error.message }); if (error.status === 403) await this.denied(false); } }
    finally { if (this.live(version, abort)) this.update({ busy: false }); }
  }
  async load(draftId, page = 1, compare = false) {
    if (this.state.order === 'incoming' && draftId !== this.state.source?.draft) return;
    if (!this.state.available || !UUID.test(draftId) || !this.canChange()) return;
    this.abort?.abort(); const abort = this.abort = new AbortController(); const version = ++this.version;
    const changedTarget = this.state.draftId !== draftId;
    if (changedTarget && this.hasUnsaved()) return;
    this.update({ busy: true, message: '', ...(changedTarget ? { draftId, review: null, candidates: {}, choices: {}, receipt: null, readiness: null, blocked: false, operation: null } : {}) });
    try {
      const [data, lines] = await Promise.all([this.client.request(`${this.path('review')}?draft_id=${draftId}&page=${page}`, { signal: abort.signal }), this.api.lines(this.state.workspace.id, draftId, 1, abort.signal)]);
      if (!this.live(version, abort)) return;
      this.validateReview(data, draftId);
      const existing = this.state.review;
      if (existing && (existing.result_revision !== data.result_revision || existing.job.id !== data.job.id)) { this.update({ blocked: true, message: 'The source result changed. Copy your corrections, then discard this selection and reopen the source.' }); return; }
      if (existing && existing.draft_revision !== data.draft_revision && this.hasUnsaved()) {
        const targets = {};
        if (compare) {
          for (const choice of Object.values(this.state.choices)) if (choice.action === 'update' && choice.line_id && !targets[choice.line_id]) {
            targets[choice.line_id] = lines.results.find(line => line.id === choice.line_id) ?? await this.client.request(`${this.api.path(this.state.workspace.id, draftId)}lines/${choice.line_id}/`, { signal: abort.signal });
            valid(targets[choice.line_id].id === choice.line_id && targets[choice.line_id].organization_id === this.state.workspace.id && targets[choice.line_id].order_id === draftId);
          }
        }
        if (!this.live(version, abort)) return;
        this.update({ blocked: true, comparison: compare ? { data, lines, targets } : null, message: compare ? 'Current server values are shown beside your kept selection. Confirm the comparison before using this new revision.' : 'The draft changed. Your choices are kept. Refresh for comparison before applying.' }); return;
      }
      const candidates = { ...this.state.candidates }; for (const candidate of data.results) candidates[candidate.candidate_id] = candidate;
      this.update({ review: data, candidates, page, lines: lines.results, lineCount: lines.count, linePage: 1, comparison: null, blocked: data.draft.status !== 'draft' });
    } catch (error) { if (this.live(version, abort)) { this.update({ message: error.message, blocked: true }); if (error.status === 403) await this.denied(false); } }
    finally { if (this.live(version, abort)) this.update({ busy: false }); }
  }
  async loadLines(page) {
    if (!this.state.review || !this.canChange()) return;
    this.abort?.abort(); const abort = this.abort = new AbortController(); const version = ++this.version; this.update({ busy: true });
    try { const data = await this.api.lines(this.state.workspace.id, this.state.draftId, page, abort.signal); if (this.live(version, abort)) this.update({ lines: data.results, lineCount: data.count, linePage: page }); }
    catch (error) { if (this.live(version, abort)) { this.update({ message: error.message }); if (error.status === 403) await this.denied(false); } }
    finally { if (this.live(version, abort)) this.update({ busy: false }); }
  }
  acceptComparison() {
    const c = this.state.comparison;
    if (!c || !this.canChange() || c.data.draft.status !== 'draft') return;
    const choices = { ...this.state.choices };
    for (const [id, choice] of Object.entries(choices)) if (choice.action === 'update') choices[id] = { ...choice, target: c.targets[choice.line_id] ?? choice.target };
    this.update({ review: c.data, lines: c.lines.results, lineCount: c.lines.count, linePage: 1, choices, comparison: null, blocked: false, operation: null, errors: [], message: 'Comparison confirmed. Preview your kept choices against the refreshed draft before applying.' });
  }
  choice(id) { return this.state.choices[id] ?? { action: '', fields: [], corrections: {}, position: '', line_id: '', target: null }; }
  change(id, patch) {
    if (!this.canChange() || !this.state.candidates[id]) return;
    this.update({ choices: { ...this.state.choices, [id]: { ...this.choice(id), ...patch } }, operation: null, receipt: null, errors: [] });
  }
  selectField(id, name, selected) {
    const choice = this.choice(id); if (!this.state.candidates[id]?.fields[name]) return;
    const corrections = { ...choice.corrections }; if (!selected) delete corrections[name];
    this.change(id, { fields: selected ? [...new Set([...choice.fields, name])] : choice.fields.filter(field => field !== name), corrections });
  }
  correction(id, name, enabled, value = this.state.candidates[id]?.fields[name]?.value ?? '') {
    const choice = this.choice(id); if (!choice.fields.includes(name) || choice.action === 'reject') return;
    const corrections = { ...choice.corrections }; if (enabled) corrections[name] = value; else delete corrections[name]; this.change(id, { corrections });
  }
  target(id, lineId) {
    const line = this.state.lines.find(item => item.id === lineId); this.change(id, { line_id: line?.id ?? '', target: line ?? null });
  }
  selection() {
    const mappings = [], errors = []; const targets = new Set(), positions = new Set();
    for (const [id, choice] of Object.entries(this.state.choices).sort(([a], [b]) => a.localeCompare(b))) {
      if (!choice.fields.length && !choice.action) continue;
      const row = this.state.candidates[id]; const label = row ? provenanceLocation(Object.values(row.fields)[0], this.state.sourceJob.parser_version) : 'Unknown source row';
      if (!row || !['create', 'update', 'reject'].includes(choice.action) || !choice.fields.length) { errors.push(`${label}: choose an action and at least one field.`); continue; }
      const mapping = { candidate_id: id, action: choice.action, fields: [...choice.fields].sort() };
      if (choice.action === 'reject') { mappings.push(mapping); continue; }
      if (Object.keys(choice.corrections).length) mapping.corrections = { ...choice.corrections };
      const proposed = {};
      for (const name of choice.fields) {
        const value = Object.hasOwn(choice.corrections, name) ? choice.corrections[name] : row.fields[name].value; proposed[name] = value;
        if (typeof value !== 'string' || value.length > (name === 'unit' ? 32 : 4096)) errors.push(`${label}: ${name} is too long or unavailable.`);
        if (name === 'quantity' && (!/^\d{1,9}(?:\.\d{1,3})?$/.test(value) || !/[1-9]/.test(value))) errors.push(`${label}: quantity must be a positive exact decimal with up to 9 integer digits and 3 decimal places. Correct it deliberately; no rounding is performed.`);
      }
      if (choice.action === 'create') {
        if (!/^\d{1,10}$/.test(String(choice.position)) || Number(choice.position) < 1 || Number(choice.position) > 2147483647) errors.push(`${label}: choose a position from 1 to 2147483647.`);
        else { mapping.position = Number(choice.position); if (positions.has(mapping.position) || this.state.lines.some(line => line.position === mapping.position)) errors.push(`${label}: the proposed position is already used.`); positions.add(mapping.position); }
        if (!(proposed.sku ?? '').trim() && !(proposed.description ?? '').trim()) errors.push(`${label}: a new line needs a selected SKU or description.`);
      } else {
        if (!UUID.test(choice.line_id) || !choice.target) errors.push(`${label}: explicitly choose an existing target line.`);
        else { mapping.line_id = choice.line_id; if (targets.has(choice.line_id)) errors.push(`${label}: a target line can appear only once in a request.`); targets.add(choice.line_id); }
      }
      mappings.push(mapping);
    }
    if (!mappings.length) errors.push('Select at least one field and its action. Nothing is selected automatically.');
    if (mappings.length > 50) errors.push('Apply at most 50 source rows in one operation.');
    return { mappings, errors };
  }
  canApply() { return ['admin', 'reviewer'].includes(this.state.workspace?.role) && this.state.review?.draft.status === 'draft' && this.state.available && this.canChange() && !this.state.blocked && !this.selection().errors.length; }
  async apply(retry = false) {
    if (retry ? !this.state.uncertain || this.state.pending || this.state.busy || !['admin', 'reviewer'].includes(this.state.workspace?.role) : !this.canApply()) return;
    const version = this.version; const abort = this.abort = new AbortController();
    const operation = retry ? this.state.operation : { job_id: this.state.review.job.id, draft_id: this.state.draftId, result_revision: this.state.review.result_revision, expected_draft_revision: this.state.review.draft_revision, operation_key: this.operationKey(), mappings: this.selection().mappings };
    this.update({ pending: true, operation, message: 'Submitting the explicit selection...', errors: [], readiness: null });
    try {
      await this.client.refreshCsrf(abort.signal);
      const response = await this.client.request(this.path('apply'), { method: 'POST', body: operation, signal: abort.signal, withStatus: true });
      if (!this.live(version, abort)) return;
      const receipt = response.data;
      valid([200, 201].includes(response.status) && UUID.test(receipt?.application_id) && receipt.job_id === operation.job_id && receipt.draft_id === operation.draft_id && REVISION.test(receipt.revision) && typeof receipt.review_complete === 'boolean' && Array.isArray(receipt.decisions) && receipt.decisions.length === operation.mappings.length);
      for (const decision of receipt.decisions) valid(operation.mappings.some(mapping => mapping.candidate_id === decision.candidate_id && mapping.action === decision.action) && (decision.action === 'reject' ? decision.line_id === null : UUID.test(decision.line_id)));
      this.update({ pending: false, uncertain: false, receipt: { ...receipt, replayed: response.status === 200 }, choices: {}, operation: null, blocked: false });
      // A historical receipt is not current draft state. Always read current data.
      await this.load(operation.draft_id, this.state.page);
      if (version !== this.version && this.state.draftId !== operation.draft_id) return;
      const refreshVersion = this.version;
      try { const readiness = await this.api.readiness(this.state.workspace.id, operation.draft_id, this.abort.signal); if (refreshVersion === this.version && !this.abort.signal.aborted) this.update({ readiness }); }
      catch { if (refreshVersion === this.version) this.update({ message: 'Application confirmed; current readiness could not be refreshed. Open the draft to check it.' }); }
      if (refreshVersion !== this.version) return;
      await this.saved(operation.draft_id);
      if (refreshVersion === this.version) this.update({ message: `Application ${receipt.application_id} confirmed${response.status === 200 ? ' by replay' : ''}. ${receipt.review_complete ? 'Every supported field has a recorded decision.' : 'Some source fields still need a decision.'} Readiness and conversion remain separate.` });
    } catch (error) {
      if (!this.live(version, abort)) return;
      if (!(error instanceof ApiError) || error.status >= 500) this.update({ uncertain: true, blocked: true, message: 'Application outcome is unconfirmed. Choices and the exact operation key are kept. Reconcile using the identical repeat-safe request before changing the selection or leaving.' });
      else if ([409, 412].includes(error.status)) this.update({ uncertain: false, blocked: true, operation: null, message: `${error.message} Your choices are kept. Refresh for comparison; source or duplicate-row conflicts require a deliberate new mapping.` });
      else if (error.status === 403) { this.update({ uncertain: false, blocked: true, operation: null, message: 'Application is not permitted. Workspace access is being rechecked.' }); await this.denied(true); }
      else this.update({ uncertain: false, operation: null, errors: [error.message], message: 'Nothing was confirmed. Correct the selection; your values are kept.' });
    } finally { if (this.live(version, abort)) this.update({ pending: false }); }
  }
}

const $ = id => document.getElementById(id);
function element(tag, text = '', className = '') { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
function labeled(control, label) { const wrapper = element('label', label); wrapper.append(control); return wrapper; }
export function renderExtractionReview(controller, visible = true) {
  const s = controller.state; const panel = $('extraction-review'); panel.hidden = !visible || !s.available;
  if (panel.hidden) { if (!s.source) { $('review-candidates').replaceChildren(); $('review-preview').replaceChildren(); $('review-drafts').replaceChildren(); $('review-receipt').textContent = ''; $('review-message').textContent = ''; $('review-draft-id').value = ''; } return; }
  const focused = panel.contains(document.activeElement) ? { id: document.activeElement.id, start: document.activeElement.selectionStart, end: document.activeElement.selectionEnd } : null;
  const writable = ['admin', 'reviewer'].includes(s.workspace?.role); const locked = !controller.canChange() || !writable;
  $('review-open-form').hidden = s.order === 'incoming';
  $('review-load-drafts').textContent = s.order === 'incoming' ? 'Review linked draft' : 'List available drafts';
  $('review-message').textContent = s.message;
  $('review-open').disabled = !controller.canChange();
  $('review-draft-id').disabled = !controller.canChange();
  $('review-load-drafts').disabled = !controller.canChange();
  $('review-draft-previous').disabled = !controller.canChange() || s.draftPage <= 1;
  $('review-draft-next').disabled = !controller.canChange() || s.draftPage * 50 >= s.draftCount;
  $('review-draft-page').textContent = `Draft page ${s.draftPage} · ${s.draftCount} drafts`;
  $('review-drafts').replaceChildren(...s.drafts.map(draft => { const button = element('button', `${draft.customer_name || 'Unnamed customer'} · ${draft.customer_reference || 'No reference'} · ${draft.line_count} lines · ${draft.id}`, 'quiet'); button.type = 'button'; button.disabled = !controller.canChange() || draft.status !== 'draft'; button.addEventListener('click', () => { if (!controller.hasUnsaved() || window.confirm('Discard these unsaved selections before choosing another draft?')) { controller.discard(); $('review-draft-id').value = draft.id; controller.load(draft.id); } }); return button; }));
  $('review-content').hidden = !s.review;
  if (!s.review) return;
  const currentDraft = s.comparison?.data.draft ?? s.review.draft;
  $('review-current-draft').textContent = `${currentDraft.customer_name || 'Unnamed customer'} · ${currentDraft.customer_reference || 'No reference'} · ${currentDraft.status} · draft ${s.draftId}${s.comparison ? ' · refreshed values awaiting confirmation' : ''}`;
  $('review-draft-link').href = `#/workspaces/${s.workspace.id}/draft-orders/${s.draftId}/`;
  $('review-comparison').hidden = !s.comparison;
  $('review-accept-comparison').disabled = !controller.canChange() || s.comparison?.data.draft.status !== 'draft';
  $('review-refresh').disabled = !controller.canChange();
  $('review-discard').disabled = !controller.canChange();
  $('review-errors').replaceChildren(...[...s.errors, ...controller.selection().errors].map(message => element('li', message)));
  $('review-apply').hidden = !writable; $('review-apply').disabled = !controller.canApply();
  $('review-reconcile').hidden = !s.uncertain; $('review-reconcile').disabled = s.pending || s.busy || !writable;
  $('review-page').textContent = `Proposal page ${s.page} · ${s.review.count} source rows`;
  $('review-previous').disabled = !controller.canChange() || s.page <= 1;
  $('review-next').disabled = !controller.canChange() || s.page * 50 >= s.review.count;
  $('review-line-page').textContent = `Target line page ${s.linePage} · ${s.lineCount} lines`;
  $('review-line-previous').disabled = !controller.canChange() || s.linePage <= 1;
  $('review-line-next').disabled = !controller.canChange() || s.linePage * 50 >= s.lineCount;
  const articles = s.review.results.map(candidate => {
    const id = candidate.candidate_id; const choice = controller.choice(id); const article = element('article', '', 'extraction-candidate'); article.dataset.candidate = id;
    article.append(element('h4', provenanceLocation(Object.values(candidate.fields)[0], s.sourceJob.parser_version)));
    const action = element('select'); action.id = `review-action-${id}`; action.add(new Option('Choose an action', '')); action.add(new Option('Create a new requested line', 'create')); action.add(new Option('Update an explicitly chosen line', 'update')); action.add(new Option('Reject selected fields', 'reject')); action.value = choice.action; action.disabled = locked;
    action.addEventListener('change', () => controller.change(id, { action: action.value, ...(action.value === 'reject' ? { corrections: {} } : {}) })); article.append(labeled(action, 'Target action'));
    if (choice.action === 'create') { const position = element('input'); position.id = `review-position-${id}`; position.inputMode = 'numeric'; position.value = choice.position; position.disabled = locked; position.addEventListener('input', () => controller.change(id, { position: position.value })); article.append(labeled(position, 'New line position (choose explicitly)')); }
    if (choice.action === 'update') { const target = element('select'); target.id = `review-target-${id}`; target.add(new Option('Choose an existing line by its ID', '')); const rows = [...s.lines]; if (choice.target && !rows.some(line => line.id === choice.target.id)) rows.unshift(choice.target); for (const line of rows) target.add(new Option(`Position ${line.position}: ${line.requested_sku || line.requested_description} · quantity ${line.quantity ?? 'missing'} · ${line.id}`, line.id)); target.value = choice.line_id; target.disabled = locked; target.addEventListener('change', () => controller.target(id, target.value)); article.append(labeled(target, 'Existing target line')); }
    const reviewed = s.review.reviewed_fields.find(item => item.candidate_id === id)?.fields ?? [];
    for (const [name, source] of Object.entries(candidate.fields)) {
      const group = element('fieldset', '', 'extraction-field'); const selected = choice.fields.includes(name); const select = element('input'); select.type = 'checkbox'; select.id = `review-select-${id}-${name}`; select.checked = selected; select.disabled = locked; select.addEventListener('change', () => controller.selectField(id, name, select.checked)); group.append(labeled(select, `${name}${reviewed.includes(name) ? ' · previous decision recorded' : ' · undecided'}`));
      group.append(element('p', `Raw source: ${source.raw}`, 'source-value'), element('p', `Extracted candidate: ${source.value}`, 'source-value'), element('p', provenanceLocation(source, s.sourceJob.parser_version), 'muted small'));
      const target = s.comparison?.targets[choice.line_id] ?? choice.target; const current = choice.action === 'create' ? '(new line)' : choice.action === 'reject' ? '(no draft change)' : target ? target[TARGET_FIELDS[name]] ?? '(missing)' : '(choose target line)'; group.append(element('p', `Current target: ${current}`));
      if (choice.action !== 'reject') { const correct = element('input'); correct.type = 'checkbox'; correct.id = `review-correct-${id}-${name}`; correct.checked = Object.hasOwn(choice.corrections, name); correct.disabled = locked || !selected; correct.addEventListener('change', () => controller.correction(id, name, correct.checked)); group.append(labeled(correct, 'Use a deliberate correction'));
        const input = element('input'); input.id = `review-value-${id}-${name}`; input.value = choice.corrections[name] ?? source.value; input.maxLength = name === 'unit' ? 32 : 4096; if (name === 'quantity') input.inputMode = 'decimal'; input.disabled = locked || !selected || !correct.checked; input.addEventListener('input', () => controller.correction(id, name, true, input.value)); group.append(labeled(input, `Proposed ${name} (exact text)`)); }
      article.append(group);
    }
    return article;
  });
  $('review-candidates').replaceChildren(...articles);
  const preview = [];
  for (const [id, choice] of Object.entries(s.choices)) {
    if (!choice.fields.length) continue; const candidate = s.candidates[id]; if (!candidate) continue;
    preview.push(element('li', `${provenanceLocation(Object.values(candidate.fields)[0], s.sourceJob.parser_version)}: ${choice.action || 'action required'}${choice.action === 'create' ? ` at position ${choice.position || '?'}` : choice.action === 'update' ? ` line ${choice.line_id || '?'}` : ''}; ${choice.fields.map(name => `${name} = ${Object.hasOwn(choice.corrections, name) ? choice.corrections[name] : candidate.fields[name].value}${Object.hasOwn(choice.corrections, name) ? ' (deliberate correction)' : ' (extracted value)'}`).join('; ')}`));
  }
  $('review-preview').replaceChildren(...preview);
  $('review-readiness').textContent = s.readiness ? s.readiness.ready_to_convert ? 'Current draft is ready for a separate conversion action.' : `Current readiness blockers: ${s.readiness.blocking_reasons.map(reason => `${reason.code} (${reason.count})`).join(', ')}` : 'Readiness has not been refreshed for this panel.';
  $('review-receipt').textContent = s.receipt ? `Committed application ${s.receipt.application_id} · draft revision ${s.receipt.revision}${s.receipt.replayed ? ' · replay of the original application' : ''}` : '';
  if (focused?.id && $(focused.id) && !$(focused.id).disabled) { const node = $(focused.id); node.focus({ preventScroll: true }); if (focused.start !== null && ['text', 'search'].includes(node.type)) node.setSelectionRange(focused.start, focused.end); }
}
