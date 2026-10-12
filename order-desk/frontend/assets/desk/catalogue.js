import { ApiError } from './api.js';

// Only server-authorized administrators can write. Retry receipts stay in memory.
export class CatalogueController {
  constructor(api, render = () => {}, changed = async () => {}, denied = async () => {}) {
    this.api = api; this.render = render; this.changed = changed; this.denied = denied;
    this.version = 0; this.state = this.empty();
  }
  empty() { return { workspace: null, generation: null, pending: false, uncertain: false, file: null, report: null, key: null, create: null, message: '' }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context(workspace, generation) {
    if (this.state.workspace?.id === workspace?.id && this.state.workspace?.role === workspace?.role && this.state.generation === generation) return;
    this.abort?.abort(); this.version += 1;
    this.state = { ...this.empty(), workspace, generation }; this.render(this.state);
  }
  canWrite() { return this.state.workspace?.role === 'admin' && !this.state.pending && !this.state.uncertain; }
  base() { return `/api/v1/workspaces/${encodeURIComponent(this.state.workspace.id)}/catalog/`; }
  select(file) {
    if (!this.canWrite()) return;
    this.version += 1;
    const valid = file && file.size > 0 && file.size <= 1048576;
    this.update({ file: valid ? file : null, report: null, key: null, message: file && !valid ? 'Choose a nonempty CSV no larger than 1 MiB.' : '' });
  }
  async run(operation, mutation = false) {
    const version = this.version;
    this.abort = new AbortController();
    this.update({ pending: true, message: '' });
    try {
      if (mutation) await this.api.refreshCsrf(this.abort.signal);
      if (version !== this.version) return;
      await operation(version, this.abort.signal);
    } catch (error) {
      if (version !== this.version) return;
      if (error instanceof ApiError && error.status === 403) {
        this.context(null, null); await this.denied(); return;
      }
      const ambiguous = mutation && (!(error instanceof ApiError) || error.status >= 500);
      this.update({ uncertain: ambiguous || this.state.uncertain,
        ...(error.details?.report ? { report: error.details.report } : {}),
        message: ambiguous ? 'The write outcome is unconfirmed. Reconcile before another action.' : error instanceof ApiError ? error.message : 'Unable to validate. Check your connection and retry.' });
    } finally { if (version === this.version) this.update({ pending: false }); }
  }
  async validate() {
    if (!this.canWrite() || !this.state.file) return;
    const form = new FormData(); form.append('file', this.state.file);
    this.update({ report: null, key: null });
    await this.run(async (version, signal) => {
      const report = await this.api.request(this.base() + 'imports/dry-run/', { method: 'POST', body: form, signal });
      if (version === this.version) this.update({ report, message: report.can_import ? 'Validation passed. Review the preview, then explicitly import.' : 'Correct the listed CSV errors and select the revised file.' });
    });
  }
  async execute(reconcile = false) {
    if (this.state.pending || this.state.workspace?.role !== 'admin' || !this.state.file || this.state.create) return;
    if (reconcile ? !this.state.uncertain || !this.state.key : !this.canWrite() || !this.state.report?.can_import) return;
    const key = this.state.key ?? crypto.randomUUID(); this.update({ key });
    const form = new FormData(); form.append('file', this.state.file);
    await this.run(async (version, signal) => {
      const result = await this.api.request(this.base() + 'imports/', { method: 'POST', body: form, signal, idempotencyKey: key });
      if (version !== this.version) return;
      this.update({ uncertain: false, file: null, report: null, key: null, message: `Import confirmed: ${result.created_count} products. Receipt ${result.import_id}.` });
      await this.changed();
    }, true);
  }
  async create(sku, description) {
    if (!this.canWrite()) return;
    const version = this.version;
    this.update({ create: { sku, description }, report: null, key: null });
    await this.run(async (version, signal) => {
      const item = await this.api.request(this.base() + 'items/', { method: 'POST', body: { sku, description }, signal });
      if (version !== this.version) return;
      this.update({ create: null, message: `Created ${item.sku}.` }); await this.changed();
    }, true);
    if (version === this.version && !this.state.uncertain) this.update({ create: null });
  }
  async reconcileCreate() {
    if (this.state.pending || !this.state.uncertain || !this.state.create || this.state.workspace?.role !== 'admin') return;
    await this.run(async (version, signal) => {
      let item;
      try { item = await this.api.request(this.base() + 'items/by-sku/?' + new URLSearchParams({ sku: this.state.create.sku }), { signal }); }
      catch (error) { if (!(error instanceof ApiError) || error.status !== 404) throw error; }
      if (version !== this.version) return;
      this.update({ uncertain: false, create: null, message: item ? `Catalogue contains ${item.sku}: ${item.description}. Compare these values before another action.` : 'That exact SKU is absent. You may deliberately submit creation again.' });
      await this.changed();
    });
  }
}

export function renderCatalogue(controller, visible) {
  const $ = id => document.getElementById(id), s = controller.state;
  const context = `${s.workspace?.id}:${s.workspace?.role}:${s.generation}`;
  if (controller.renderedContext !== context) {
    controller.renderedContext = context;
    for (const id of ['catalogue-sku', 'catalogue-description', 'catalogue-file']) $(id).value = '';
  }
  $('catalogue-manage').hidden = !visible || s.workspace?.role !== 'admin';
  $('catalogue-write-message').textContent = s.message;
  for (const id of ['catalogue-sku', 'catalogue-description', 'catalogue-file', 'catalogue-create']) $(id).disabled = !controller.canWrite();
  $('catalogue-validate').disabled = !controller.canWrite() || !s.file;
  $('catalogue-import').disabled = !controller.canWrite() || !s.report?.can_import;
  $('catalogue-reconcile').hidden = !s.uncertain;
  $('catalogue-reconcile').disabled = s.pending;
  if (!s.file) $('catalogue-file').value = '';
  if (!s.workspace) { $('catalogue-sku').value = ''; $('catalogue-description').value = ''; }
  $('catalogue-import-report').textContent = s.report ? `${s.report.summary?.rows_total ?? 0} rows; ${s.report.summary?.rows_ready ?? 0} ready; ${s.report.summary?.rows_invalid ?? 0} invalid. ${s.report.preview_truncated ? 'Preview limited to 25 rows.' : ''} ${s.report.errors_truncated ? 'Only the first 100 errors are shown.' : ''}` : '';
  $('catalogue-import-errors').replaceChildren(...(s.report?.errors ?? []).map(error => { const li = document.createElement('li'); li.textContent = `Row ${error.row_number}, ${error.field}: ${error.message}`; return li; }));
  $('catalogue-import-preview').replaceChildren(...(s.report?.preview ?? []).map(item => { const row = document.createElement('tr'); for (const value of [item.row_number, item.sku, item.description, item.is_active ? 'Active' : 'Inactive']) { const td = document.createElement('td'); td.textContent = value; row.append(td); } return row; }));
}
