import { ApiError } from './api.js';
import { UUID } from './orders-api.js';

export const MAX_DOCUMENT_BYTES = 10 * 1024 * 1024;
export const documentRoute = (workspace, order = '') => `#/workspaces/${workspace}/${order ? `orders/${order}/documents/` : 'documents/'}`;
export class DocumentController {
  constructor(client, render = () => {}, denied = async () => {}) { this.client = client; this.render = render; this.denied = denied; this.version = 0; this.state = this.empty(); }
  empty() { return { workspace: null, generation: null, order: null, rows: [], count: 0, page: 1, file: null, busy: false, pending: false, uncertain: false, message: '' }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context(workspace, generation, order = null) {
    if (workspace?.id === this.state.workspace?.id && generation === this.state.generation && order === this.state.order) { this.state.workspace = workspace; return; }
    this.abort?.abort(); this.version++;
    this.state = { ...this.empty(), workspace, generation, order }; this.render(this.state);
  }
  path(order = this.state.order) {
    if (!UUID.test(this.state.workspace?.id) || !UUID.test(order)) throw new Error('Choose a valid purchase-order ID.');
    return `/api/v1/workspaces/${this.state.workspace.id}/orders/${order}/documents/`;
  }
  validate(row) {
    if (!row || !UUID.test(row.id) || row.organization !== this.state.workspace.id || row.order !== this.state.order || typeof row.original_name !== 'string' || !Number.isSafeInteger(row.size_bytes) || row.size_bytes < 1 || !['received', 'pending_review', 'rejected'].includes(row.status) || (row.download_url !== null && row.download_url !== `${this.path()}${row.id}/download/`)) throw new Error('Document response unavailable.');
    return row;
  }
  async list(page = 1) {
    if (!this.state.order || this.state.pending) return;
    this.abort?.abort(); const abort = this.abort = new AbortController(); const version = ++this.version;
    this.update({ rows: [], busy: true, page, message: '' });
    try {
      const data = await this.client.request(`${this.path()}intake/?page=${page}`, { signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      if (!Array.isArray(data.results) || data.results.length > 50 || !Number.isSafeInteger(data.count) || data.count < 0) throw new Error('Document response unavailable.');
      data.results.forEach(row => this.validate(row)); this.update({ rows: data.results, count: data.count }); return true;
    } catch (error) { if (version === this.version && !abort.signal.aborted) { this.update({ message: error.status === 404 ? 'Purchase order not found or unavailable in this workspace.' : error.message }); if (error.status === 403) await this.denied(false); } }
    finally { if (version === this.version && !abort.signal.aborted) this.update({ busy: false }); }
  }
  select(file) {
    if (this.state.pending) return;
    let message = '';
    if (file && (!/\.(pdf|csv)$/i.test(file.name) || !file.size || file.size > MAX_DOCUMENT_BYTES)) message = 'Choose a nonempty PDF or CSV, up to 10 MiB. Server validation still applies.';
    this.update({ file: message ? null : file, message });
  }
  canUpload() { return ['admin', 'reviewer'].includes(this.state.workspace?.role) && this.state.order && this.state.file && !this.state.busy && !this.state.pending && !this.state.uncertain; }
  async upload() {
    if (!this.canUpload()) return;
    const version = this.version; const abort = this.abort = new AbortController();
    const context = { workspace: this.state.workspace.id, generation: this.state.generation, order: this.state.order };
    const file = this.state.file; this.update({ pending: true, message: 'Uploading and validating source bytes…' });
    try {
      await this.client.refreshCsrf(abort.signal);
      const form = new FormData(); form.append('file', file, file.name);
      const row = await this.client.request(`${this.path()}intake/`, { method: 'POST', body: form, signal: abort.signal });
      if (version !== this.version || abort.signal.aborted) return;
      this.validate(row); this.update({ pending: false, file: null }); await this.list();
      if (this.state.workspace?.id === context.workspace && this.state.generation === context.generation && this.state.order === context.order) this.update({ message: 'Source received. No extraction, matching or review was performed.' });
    } catch (error) {
      if (version !== this.version || abort.signal.aborted) return;
      if (!(error instanceof ApiError) || error.status >= 500) this.update({ uncertain: true, message: 'Upload outcome is unconfirmed. Do not repeat it blindly. Check the document list before selecting and uploading again.' });
      else { this.update({ message: error.message }); if (error.status === 403) await this.denied(true); }
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
}

const $ = id => document.getElementById(id);
let displayedContext;
export function renderDocuments(controller, visible) {
  const s = controller.state; $('documents-screen').hidden = !visible;
  const context = `${s.generation}/${s.workspace?.id ?? ''}/${s.order ?? ''}`;
  if (context !== displayedContext) { displayedContext = context; $('documents-order-id').value = s.order ?? ''; }
  $('documents-order').textContent = s.order ? `Purchase-order ID: ${s.order}` : 'Open an existing purchase order by ID, or use the document link on its confirmed conversion result.';
  $('documents-message').textContent = s.message;
  $('documents-file-info').textContent = s.file ? `${s.file.name} · ${s.file.size} bytes` : 'No file selected';
  if (!s.file) $('document-file').value = '';
  $('document-upload-form').hidden = !s.order || !['admin', 'reviewer'].includes(s.workspace?.role);
  $('document-file').disabled = s.pending; $('document-upload').disabled = !controller.canUpload();
  $('documents-refresh').disabled = s.pending || s.busy || !s.order;
  $('documents-check').hidden = !s.uncertain;
  $('documents-rows').replaceChildren(...s.rows.map(row => {
    const tr = document.createElement('tr');
    for (const value of [row.original_name, `${row.size_bytes} bytes`, row.status === 'received' ? 'Received · not automatically reviewed' : row.status === 'pending_review' ? 'Pending review' : 'Rejected']) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
    const td = document.createElement('td'); const button = document.createElement('button'); button.textContent = row.download_url ? 'Download source' : 'Legacy storage requires adoption'; button.disabled = s.pending || s.busy || !row.download_url;
    button.addEventListener('click', async () => {
      const version = controller.version; const blob = await controller.download(row); if (!blob || version !== controller.version) return;
      const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = row.original_name.replace(/[\r\n\\/]/g, '_'); link.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
    }); td.append(button); tr.append(td); return tr;
  }));
  $('documents-empty').textContent = s.busy ? 'Loading documents…' : s.rows.length ? '' : s.order ? 'No source documents listed.' : '';
  $('documents-page').textContent = `Page ${s.page} · ${s.count} documents`;
  $('documents-previous').disabled = s.busy || s.pending || s.page <= 1;
  $('documents-next').disabled = s.busy || s.pending || s.page * 50 >= s.count;
}
