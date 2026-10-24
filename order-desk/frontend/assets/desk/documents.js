import { ApiError } from './api.js';
import { UUID, OrdersApi } from './orders-api.js';
import { validateProvenance, provenanceLocation } from './extraction-review.js';

export const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;
export const documentRoute = (workspace, order = '') => `#/workspaces/${workspace}/${order ? `orders/${order}/documents/` : 'documents/'}`;
export const incomingRoute = workspace => `#/workspaces/${workspace}/incoming/`;
export class DocumentController {
  constructor(client, render = () => {}, denied = async () => {}) { this.client = client; this.render = render; this.denied = denied; this.version = 0; this.state = this.empty(); }
  empty() { return { workspace: null, generation: null, order: null, rows: [], count: 0, page: 1, file: null, busy: false, pending: false, uncertain: false, message: '', extraction: null, uploadKey: null, linkOperation: null, linkSource: null, drafts: [], draftPage: 1, draftCount: 0, query: '', filter: '' }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context(workspace, generation, order = null) {
    if (workspace?.id === this.state.workspace?.id && workspace?.role === this.state.workspace?.role && generation === this.state.generation && order === this.state.order) { this.state.workspace = workspace; return; }
    this.abort?.abort(); this.version++;
    this.state = { ...this.empty(), workspace, generation, order }; this.render(this.state);
  }
  path(order = this.state.order) {
    if (order === 'incoming' && UUID.test(this.state.workspace?.id)) return `/api/v1/workspaces/${this.state.workspace.id}/incoming/`;
    if (!UUID.test(this.state.workspace?.id) || !UUID.test(order)) throw new Error('Choose a valid purchase-order ID.');
    return `/api/v1/workspaces/${this.state.workspace.id}/orders/${order}/documents/`;
  }
  validate(row) {
    if (!row || !UUID.test(row.id) || row.organization !== this.state.workspace.id || row.order !== (this.state.order === 'incoming' ? null : this.state.order) || (this.state.order === 'incoming' && (row.draft !== null && !UUID.test(row.draft))) || typeof row.original_name !== 'string' || !Number.isSafeInteger(row.size_bytes) || row.size_bytes < 1 || !['received', 'pending_review', 'rejected'].includes(row.status) || (row.download_url !== null && row.download_url !== `${this.path()}${row.id}/download/`)) throw new Error('Document response unavailable.');
    return row;
  }
  async list(page = 1) {
    if (!this.state.order || this.state.pending) return;
    this.abort?.abort(); const abort = this.abort = new AbortController(); const version = ++this.version;
    this.update({ rows: [], busy: true, page, message: '' });
    try {
      const suffix = this.state.order === 'incoming' ? `?${new URLSearchParams({ page, q: this.state.query, status: this.state.filter })}` : `intake/?page=${page}`;
      const data = await this.client.request(`${this.path()}${suffix}`, { signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      if (!Array.isArray(data.results) || data.results.length > 50 || !Number.isSafeInteger(data.count) || data.count < 0) throw new Error('Document response unavailable.');
      data.results.forEach(row => this.validate(row)); this.update({ rows: data.results, count: data.count }); return true;
    } catch (error) { if (version === this.version && !abort.signal.aborted) { this.update({ message: error.status === 404 ? 'Purchase order not found or unavailable in this workspace.' : error.message }); if (error.status === 403) await this.denied(false); } }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ busy: false }); }
  }
  select(file) {
    if (this.state.pending || this.state.uncertain) return;
    let message = '';
    if (file && (!/\.(pdf|csv)$/i.test(file.name) || !file.size || file.size > MAX_DOCUMENT_BYTES)) message = 'Choose a nonempty PDF or CSV, up to 10 MiB. Server validation still applies.';
    this.update({ file: message ? null : file, message, uploadKey: file && !message && this.state.order === 'incoming' ? crypto.randomUUID() : null });
  }
  canUpload() { return ['admin', 'reviewer'].includes(this.state.workspace?.role) && this.state.order && this.state.file && !this.state.busy && !this.state.pending && !this.state.uncertain; }
  async upload() {
    if (!this.canUpload()) return;
    const version = this.version; const abort = this.abort = new AbortController();
    const context = { workspace: this.state.workspace.id, generation: this.state.generation, order: this.state.order };
    const file = this.state.file; this.update({ pending: true, message: 'Uploading and validating source bytes…' });
    try {
      await this.client.refreshCsrf(abort.signal);
      if (version !== this.version || abort.signal.aborted) return;
      const form = new FormData(); form.append('file', file, file.name);
      const incoming = this.state.order === 'incoming';
      const row = await this.client.request(`${this.path()}${incoming ? '' : 'intake/'}`, { method: 'POST', body: form, signal: abort.signal, idempotencyKey: incoming ? this.state.uploadKey : null });
      if (version !== this.version || abort.signal.aborted) return;
      this.validate(row); this.update({ pending: false, file: null, uploadKey: null }); await this.list();
      if (this.state.workspace?.id === context.workspace && this.state.generation === context.generation && this.state.order === context.order) this.update({ message: 'Source received. No extraction, matching or review was performed.' });
    } catch (error) {
      if (version !== this.version || abort.signal.aborted) return;
      if (!(error instanceof ApiError) || error.status >= 500) this.update({ uncertain: true, message: 'Upload outcome is unconfirmed. Do not repeat it blindly. Check the document list before selecting and uploading again.' });
      else { this.update({ message: error.message }); if (error.status === 403) await this.denied(true); }
    } finally { if (version === this.version && !abort.signal.aborted) this.update({ pending: false }); }
  }
  async reconcileUpload() {
    if (!this.state.uncertain || this.state.pending || this.state.order !== 'incoming' || !this.state.uploadKey) return;
    const version = this.version, abort = this.abort = new AbortController();
    this.update({ pending: true });
    try {
      const data = await this.client.request(`${this.path()}?operation_key=${this.state.uploadKey}`, { signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      if (!Array.isArray(data.results) || data.results.length > 1 || data.count !== data.results.length) throw new Error('Upload reconciliation unavailable.');
      data.results.forEach(row => this.validate(row));
      const found = data.count === 1;
      this.update({ uncertain: false, pending: false, ...(found ? { file: null, uploadKey: null } : {}), message: found ? 'Upload confirmed by its recorded request. Refresh the inbox.' : 'No committed source found. Retry the same selected file with its retained request key.' });
      if (found) await this.list();
    } catch (error) { if (version === this.version && !abort.signal.aborted) { this.update({ message: error.message }); if (error.status === 403) await this.denied(false); } }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ pending: false }); }
  }
  async chooseLink(row, page = 1) {
    if (this.state.pending || this.state.busy || this.state.linkOperation || row.draft) return;
    const version = this.version, abort = this.abort = new AbortController();
    this.update({ busy: true, linkSource: row, drafts: [], draftPage: page });
    try {
      const data = await new OrdersApi(this.client).list(this.state.workspace.id, page, abort.signal);
      if (version === this.version && !abort.signal.aborted) this.update({ drafts: data.results, draftCount: data.count });
    } catch (error) { if (version === this.version && !abort.signal.aborted) { this.update({ message: error.message }); if (error.status === 403) await this.denied(false); } }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ busy: false }); }
  }
  async linkSource(values = null) {
    if (this.state.pending || this.state.busy || !this.state.linkSource || !['admin', 'reviewer'].includes(this.state.workspace?.role)) return;
    const version = this.version, abort = this.abort = new AbortController();
    this.update({ pending: true });
    try {
      let operation = this.state.linkOperation;
      if (!operation) {
        if (!values) return;
        const payload = { operation_key: crypto.randomUUID() };
        if (values.draft_id) {
          const revision = await new OrdersApi(this.client).revision(this.state.workspace.id, values.draft_id, abort.signal);
          if (version !== this.version || abort.signal.aborted) return;
          Object.assign(payload, { draft_id: values.draft_id, expected_revision: revision });
        } else Object.assign(payload, { customer_name: values.customer_name, customer_reference: values.customer_reference });
        operation = { source: this.state.linkSource.id, payload };
        this.update({ linkOperation: operation });
      }
      await this.client.refreshCsrf(abort.signal);
      if (version !== this.version || abort.signal.aborted) return;
      const row = await this.client.request(`${this.path()}${operation.source}/link/`, { method: 'POST', body: operation.payload, signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      this.validate(row);
      this.update({ pending: false, linkSource: null, linkOperation: null, drafts: [], message: 'Source linked. Open its draft for manual review or its extraction proposals.' });
      await this.list();
    } catch (error) {
      if (version !== this.version || abort.signal.aborted) return;
      if (error instanceof ApiError && error.status < 500) this.update({ linkOperation: null });
      this.update({ message: this.state.linkOperation ? 'Draft link outcome unknown. Reconcile the identical saved request before another link.' : error.message });
      if (error.status === 403) await this.denied(true);
    } finally { if (version === this.version && !abort.signal.aborted) this.update({ pending: false }); }
  }
  async download(row) {
    if (this.state.pending || this.state.busy || !row.download_url) return null;
    const version = this.version; const abort = this.abort = new AbortController();
    this.update({ busy: true, message: 'Requesting authorized source bytes…' });
    try {
      const blob = await this.client.request(`${this.path()}${row.id}/download/`, { signal: abort.signal, binary: true });
      if (version !== this.version || abort.signal.aborted) return null;
      if (!(blob instanceof Blob) || blob.size !== row.size_bytes || blob.size > MAX_DOCUMENT_BYTES) throw new Error('Downloaded source is unavailable.');
      this.update({ message: 'Source bytes received. Download does not change review status.' }); return blob;
    } catch (error) { if (version === this.version && !abort.signal.aborted) { this.update({ message: error.message }); if (error.status === 403) await this.denied(false); } return null; }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ busy: false }); }
  }
  extractionPath(row) {
    this.validate(row);
    const path = `${this.path()}${row.id}/extraction/`;
    if (row.extraction_url !== path) throw new Error('Local extraction unavailable for this source.');
    return path;
  }
  validateExtraction(data, row) {
    if (!data || !Array.isArray(data.results) || data.results.length > 50 || !Number.isSafeInteger(data.count) || data.count < 0 || data.count > 500) throw new Error('Extraction response unavailable.');
    const job = data.job;
    if (job !== null && (!UUID.test(job?.id) || job.document !== row.id || job.organization !== this.state.workspace.id || !['order-csv-v1', 'order-text-pdf-v1'].includes(job.parser_version) || !/^[0-9a-f]{64}$/.test(job.source_sha256) || !['queued', 'running', 'succeeded', 'failed'].includes(job.status) || !Number.isInteger(job.attempts) || job.attempts < 0 || job.attempts > 3 || typeof job.lease_expired !== 'boolean' || typeof job.error_code !== 'string' || (job.error_row !== null && (!Number.isInteger(job.error_row) || job.error_row < 1)))) throw new Error('Extraction response unavailable.');
    if ((!job || job.status !== 'succeeded') && (data.count || data.results.length)) throw new Error('Extraction response unavailable.');
    for (const fields of data.results) {
      if (!fields || !fields.sku || !fields.quantity || Object.keys(fields).some(key => !['sku', 'quantity', 'description', 'unit'].includes(key))) throw new Error('Extraction response unavailable.');
      for (const [key, field] of Object.entries(fields)) validateProvenance(field, key, job.parser_version, job.result_pages);
    }
    return data;
  }
  async openExtraction(row, page = 1) {
    if (this.state.busy || this.state.pending) return;
    if (this.beforeExtractionChange && !this.beforeExtractionChange(row)) return;
    const abort = this.abort = new AbortController(); const version = ++this.version;
    this.update({ busy: true, extraction: { row, page, job: null, rows: [], count: 0, loaded: false }, message: 'Loading local extraction status…' });
    try {
      const data = await this.client.request(`${this.extractionPath(row)}?page=${page}`, { signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      this.validateExtraction(data, row);
      this.update({ extraction: { row, page, job: data.job, rows: data.results, count: data.count, loaded: true }, message: '' });
    } catch (error) { if (version === this.version && !abort.signal.aborted) { this.update({ message: error.message }); if (error.status === 403) await this.denied(false); } }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ busy: false }); }
  }
  canExtract(retry = false) {
    const e = this.state.extraction;
    return ['admin', 'reviewer'].includes(this.state.workspace?.role) && e?.loaded && !this.state.busy && !this.state.pending && (retry ? e.job?.status === 'failed' && e.job.attempts < 3 && e.job.can_retry !== false : e.job === null);
  }
  async queueExtraction(retry = false) {
    if (!this.canExtract(retry)) return;
    const row = this.state.extraction.row; const version = this.version; const abort = this.abort = new AbortController();
    this.update({ pending: true, message: retry ? 'Requesting another extraction attempt…' : 'Queuing local extraction…' });
    try {
      await this.client.refreshCsrf(abort.signal);
      if (version !== this.version || abort.signal.aborted) return;
      await this.client.request(`${this.extractionPath(row)}${retry ? 'retry/' : ''}`, { method: 'POST', body: {}, signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      this.update({ pending: false }); await this.openExtraction(row);
    } catch (error) { if (version === this.version && !abort.signal.aborted) { this.update({ message: error.status === 403 ? error.message : 'Extraction request outcome is unconfirmed. Refresh status before retrying.', extraction: { ...this.state.extraction, loaded: false } }); if (error.status === 403) await this.denied(true); } }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ pending: false }); }
  }
}

const $ = id => document.getElementById(id);
let displayedContext;
export function renderDocuments(controller, visible) {
  const s = controller.state; $('documents-screen').hidden = !visible;
  const incoming = s.order === 'incoming';
  $('incoming-controls').hidden = !incoming;
  $('incoming-link-panel').hidden = !incoming || !s.linkSource;
  $('documents-heading').textContent = incoming ? 'Incoming customer orders' : 'Documents for this order';
  $('incoming-request').textContent = incoming && s.uploadKey ? `Upload request ${s.uploadKey}` : '';
  if (!incoming || !s.workspace) { $('incoming-query').value = ''; $('incoming-filter').value = ''; $('incoming-customer').value = ''; $('incoming-reference').value = ''; }
  $('incoming-link-label').textContent = s.linkSource ? `Source: ${s.linkSource.original_name}` : '';
  $('incoming-drafts').replaceChildren(new Option('Create a new draft', ''), ...s.drafts.filter(draft => draft.status === 'draft').map(draft => new Option(`${draft.customer_name || 'Unresolved customer'} · ${draft.customer_reference || 'No reference'} · ${draft.line_count} lines`, draft.id)));
  for (const id of ['incoming-drafts', 'incoming-customer', 'incoming-reference', 'incoming-link-submit', 'incoming-link-cancel']) $(id).disabled = s.busy || s.pending || Boolean(s.linkOperation);
  $('incoming-link-reconcile').hidden = !s.linkOperation;
  $('incoming-link-reconcile').disabled = s.pending || s.busy;
  $('incoming-draft-page').textContent = `Draft page ${s.draftPage} · ${s.draftCount} drafts`;
  $('incoming-draft-previous').disabled = s.pending || s.busy || Boolean(s.linkOperation) || s.draftPage <= 1;
  $('incoming-draft-next').disabled = s.pending || s.busy || Boolean(s.linkOperation) || s.draftPage * 50 >= s.draftCount;
  const context = `${s.generation}/${s.workspace?.id ?? ''}/${s.order ?? ''}`;
  if (context !== displayedContext) { displayedContext = context; $('documents-order-id').value = s.order ?? ''; }
  $('documents-order').textContent = incoming ? 'Receive PDF or CSV sources before creating an internal order. Confirm customer identity during review. Unsupported extraction requires manual draft entry.' : s.order ? `Purchase-order ID: ${s.order}` : 'Open an existing purchase order by ID, or use the document link on its confirmed conversion result.';
  $('documents-message').textContent = s.message;
  $('documents-file-info').textContent = s.file ? `${s.file.name} · ${s.file.size} bytes` : 'No file selected';
  if (!s.file) $('document-file').value = '';
  $('document-upload-form').hidden = !s.order || !['admin', 'reviewer'].includes(s.workspace?.role);
  $('document-file').disabled = s.pending || s.uncertain; $('document-upload').disabled = !controller.canUpload();
  $('documents-refresh').disabled = s.pending || s.busy || !s.order;
  $('documents-check').hidden = !s.uncertain;
  $('documents-rows').replaceChildren(...s.rows.map(row => {
    const tr = document.createElement('tr');
    const status = incoming ? `${row.processing_status || 'Received'} · ${row.draft ? 'Linked: review draft' : 'Next: create or link draft'}${row.duplicate_count ? ` · Possible duplicate: ${row.duplicate_count} other source(s) with identical bytes` : ''} · Received ${new Date(row.uploaded_at).toLocaleString()} · ${row.customer_name || 'Unresolved customer'} ${row.customer_reference || ''}` : row.status === 'received' ? 'Received · not automatically reviewed' : row.status === 'pending_review' ? 'Pending review' : 'Rejected';
    for (const value of [row.original_name, `${row.size_bytes} bytes`, status]) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
    const td = document.createElement('td'); const button = document.createElement('button'); button.textContent = row.download_url ? 'Download source' : 'Legacy storage requires adoption'; button.disabled = s.pending || s.busy || !row.download_url;
    button.addEventListener('click', async () => {
      const version = controller.version; const blob = await controller.download(row); if (!blob || version !== controller.version) return;
      const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = row.original_name.replace(/[\r\n\\/]/g, '_'); link.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    }); td.append(button);
    if (incoming) {
      const action = document.createElement(row.draft ? 'a' : 'button');
      action.textContent = row.draft ? 'Review linked draft' : 'Create or link draft';
      if (row.draft) action.href = `#/workspaces/${s.workspace.id}/draft-orders/${row.draft}/`;
      else { action.disabled = s.busy || s.pending || Boolean(s.linkOperation) || !['admin', 'reviewer'].includes(s.workspace?.role); action.addEventListener('click', () => controller.chooseLink(row)); }
      td.append(action);
    }
    if (row.extraction_url) { const extraction = document.createElement('button'); extraction.textContent = /\.pdf$/i.test(row.original_name) ? 'PDF extraction' : 'CSV extraction'; extraction.disabled = s.busy || s.pending; extraction.addEventListener('click', () => controller.openExtraction(row)); td.append(extraction); }
    tr.append(td); return tr;
  }));
  $('documents-empty').textContent = s.busy ? 'Loading documents…' : s.rows.length ? '' : s.order ? 'No source documents listed.' : '';
  $('documents-page').textContent = `Page ${s.page} · ${s.count} documents`;
  $('documents-previous').disabled = s.busy || s.pending || s.page <= 1;
  $('documents-next').disabled = s.busy || s.pending || s.page * 50 >= s.count;
  renderExtraction(controller);
}

function renderExtraction(controller) {
  const s = controller.state; const e = s.extraction; $('document-extraction').hidden = !e;
  $('extraction-fields').replaceChildren();
  if (!e) return;
  $('extraction-source').textContent = e.row.original_name;
  const job = e.job;
  const status = !e.loaded ? 'Status unavailable. Refresh before requesting extraction.' : !job ? 'No extraction queued.' : job.status === 'queued' ? 'Queued; waiting for the local processor.' : job.status === 'running' ? (job.lease_expired ? 'Processing lease expired. An authorized processor can resume it.' : 'Processing source…') : job.status === 'failed' ? `Extraction failed: ${job.error_code}${job.error_row ? ` at source row ${job.error_row}` : ''}. No partial proposals were published. Use manual draft editing for unsupported or scanned documents.` : 'Extracted proposals ready for staff review. No order lines or approvals were changed.';
  $('extraction-status').textContent = status;
  $('extraction-identity').textContent = job ? `Job ${job.id} · ${job.parser_version} · attempt ${job.attempts}/3 · source SHA-256 ${job.source_sha256}` : '';
  $('extraction-manual-link').hidden = job?.status !== 'failed'; $('extraction-manual-link').href = s.workspace ? `#/workspaces/${s.workspace.id}/draft-orders/` : '#';
  $('extraction-queue').hidden = !!job; $('extraction-queue').disabled = !controller.canExtract();
  $('extraction-retry').hidden = job?.status !== 'failed'; $('extraction-retry').disabled = !controller.canExtract(true);
  $('extraction-refresh').disabled = s.busy || s.pending;
  $('extraction-previous').disabled = s.busy || s.pending || e.page <= 1;
  $('extraction-next').disabled = s.busy || s.pending || e.page * 50 >= e.count;
  for (const fields of e.rows) {
    const article = document.createElement('article');
    for (const [name, field] of Object.entries(fields)) { const p = document.createElement('p'); p.textContent = `${name}: ${field.value} · ${provenanceLocation(field, job.parser_version)} · raw: ${field.raw}`; article.append(p); }
    $('extraction-fields').append(article);
  }
}
