import { ApiError } from './api.js';

export function editPayload(mode, input) {
  const data = {}, errors = {};
  if (['create', 'header'].includes(mode)) {
    for (const field of ['customer_name', 'customer_reference']) {
      data[field] = input[field] ?? '';
      if (data[field] && !data[field].trim()) errors[field] = ['Provide a nonblank value or an empty string.'];
    }
    if (mode === 'create') data.original_intake_text = input.original_intake_text ?? '';
  } else if (['line', 'add-line'].includes(mode)) {
    for (const field of ['requested_sku', 'requested_description', 'unit']) data[field] = input[field] ?? '';
    const quantity = input.quantity ?? '';
    if (quantity !== '' && (!/^\d{1,9}(?:\.\d{1,3})?$/.test(quantity) || !/[1-9]/.test(quantity))) errors.quantity = ['Use a positive decimal, up to 9 integer digits and 3 decimal places, or leave blank.'];
    data.quantity = quantity === '' ? null : quantity;
    if (!data.requested_sku.trim() && !data.requested_description.trim()) errors.requested_sku = ['Provide a requested SKU or description.'];
    if (mode === 'add-line') {
      const position = input.position ?? '';
      if (!/^\d{1,10}$/.test(position) || Number(position) < 1 || Number(position) > 2147483647) errors.position = ['Provide a line position from 1 to 2147483647.'];
      else data.position = Number(position);
    }
  } else if (mode === 'attach') {
    data.catalogue_item_id = input.catalogue_item_id;
    if (!data.catalogue_item_id) errors.catalogue_item_id = ['Choose an active catalogue item.'];
  }
  return { data, errors };
}

export class DraftEditor {
  constructor(api, drafts, render = () => {}, saved = async () => {}, denied = async () => {}) {
    this.api = api; this.drafts = drafts; this.render = render; this.saved = saved; this.denied = denied; this.version = 0;
    this.state = this.empty();
  }
  empty() { return { open: false, mode: null, input: {}, errors: {}, message: '', pending: false, blocked: false, dirty: false, lineId: null, revision: null, items: [], catalogCount: 0, catalogPage: 1, catalogQuery: '', catalogBusy: false }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context() {
    const key = `${this.drafts.state.generation}/${this.drafts.state.workspace?.id ?? ''}/${this.drafts.state.draftId ?? ''}`;
    if (key !== this.contextKey) { this.contextKey = key; this.version++; this.abort?.abort(); this.catalogAbort?.abort(); this.state = this.empty(); this.render(this.state); }
  }
  canEdit(mode = 'header') {
    const s = this.drafts.state;
    return ['admin', 'reviewer'].includes(s.workspace?.role) && (mode === 'create' || (s.draft?.status === 'draft' && s.revision && !s.loading && !s.converting));
  }
  begin(mode, line = null) {
    if (!this.canEdit(mode) || this.state.pending) return;
    this.version++; this.state = this.empty();
    let input = {};
    if (mode === 'header') input = { customer_name: this.drafts.state.draft.customer_name, customer_reference: this.drafts.state.draft.customer_reference };
    if (mode === 'line') input = { requested_sku: line.requested_sku, requested_description: line.requested_description, quantity: line.quantity ?? '', unit: line.unit };
    this.update({ open: true, mode, input, lineId: line?.id ?? null, revision: this.drafts.state.revision });
    this.drafts.update({ dirty: true });
    if (mode === 'attach') this.catalogue('', 1);
  }
  change(field, value) { this.update({ input: { ...this.state.input, [field]: value }, dirty: true }); }
  discard() { this.version++; this.abort?.abort(); this.catalogAbort?.abort(); this.state = this.empty(); this.render(this.state); this.drafts.update({ dirty: false }); }
  async catalogue(query, page = 1) {
    this.catalogAbort?.abort(); const abort = this.catalogAbort = new AbortController(); const version = this.version;
    const params = new URLSearchParams({ page: String(page), is_active: 'true' }); if (query.trim()) params.set('q', query.trim());
    this.update({ items: [], catalogBusy: true, catalogQuery: query, catalogPage: page });
    try {
      const data = await this.api.client.request(`/api/v1/workspaces/${this.drafts.state.workspace.id}/catalog/items/?${params}`, { signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      if (!Array.isArray(data.results) || data.results.length > 50 || !Number.isSafeInteger(data.count) || data.results.some(item => item.organization_id !== this.drafts.state.workspace.id || item.is_active !== true || typeof item.sku !== 'string')) throw new Error('Catalogue response unavailable.');
      this.update({ items: data.results, catalogCount: data.count });
    } catch { if (version === this.version && !abort.signal.aborted) this.update({ message: 'Unable to load the catalogue. Search again to retry.' }); }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ catalogBusy: false }); }
  }
  async save() {
    if (!this.state.open || this.state.pending || this.state.blocked || !this.canEdit(this.state.mode)) return;
    const { data, errors } = editPayload(this.state.mode, this.state.input);
    if (Object.keys(errors).length) { this.update({ errors }); return; }
    const version = this.version; const abort = this.abort = new AbortController();
    const { mode, lineId, revision } = this.state; const { workspace, draftId } = this.drafts.state;
    this.update({ pending: true, errors: {}, message: '' });
    this.drafts.update({ readiness: null, assessedAt: null });
    try {
      const result = mode === 'create' ? await this.api.create(workspace.id, data, abort.signal) : await this.api.edit(workspace.id, draftId, mode, lineId, data, revision, abort.signal);
      if (version !== this.version || abort.signal.aborted) return;
      this.discard(); await this.saved(mode === 'create' ? result.id : draftId);
    } catch (error) {
      if (version !== this.version || abort.signal.aborted) return;
      if (error instanceof ApiError && [409, 412].includes(error.status)) this.update({ blocked: true, message: 'Server data changed or the source is locked. Your unsaved values are kept. Compare them before deliberately reloading and discarding.' });
      else if (error instanceof ApiError && error.status === 400) this.update({ errors: error.details ?? {}, message: 'Correct the highlighted fields and save again.' });
      else if (error instanceof ApiError && error.status === 403) { this.update({ blocked: true, message: 'Editing is not permitted. Access will be rechecked.' }); await this.denied(); }
      else this.update({ blocked: true, message: 'Save outcome is unconfirmed. Do not repeat creation or line insertion. Check server data before restarting; your values remain here to compare or copy.' });
    } finally { if (version === this.version && !abort.signal.aborted) this.update({ pending: false }); }
  }
  async reload() {
    if (this.state.pending) return;
    const { mode, lineId } = this.state;
    if (mode === 'create') { this.discard(); await this.drafts.list(); return; }
    const version = this.version;
    await this.drafts.open(this.drafts.state.draftId, true);
    if (version !== this.version) return;
    if (!this.canEdit(mode)) { this.update({ blocked: true, message: 'The source is locked or editing access is unavailable. Copy your unsaved values before discarding.' }); return; }
    let line = this.drafts.state.lines.find(item => item.id === lineId);
    if (lineId && !line) {
      const s = this.drafts.state;
      line = await this.api.client.request(`${this.api.path(s.workspace.id, s.draftId)}lines/${lineId}/`);
      if (version !== this.version) return;
    }
    this.begin(mode, line);
  }
}
