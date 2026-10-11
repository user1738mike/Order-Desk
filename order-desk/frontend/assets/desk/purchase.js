import { ApiError } from './api.js';
import { UUID } from './orders-api.js';

export const PROFILE = 'generic-po-csv-v1';
export const MAX_EXPORT_BYTES = 2 * 1024 * 1024;
const HEX = /^[0-9a-f]{64}$/;
const HEADERS = ['profile', 'order_id', 'source_draft_id', 'order_number', 'order_date', 'customer_name', 'line_number', 'sku', 'description', 'quantity', 'unit'];
const CODES = ['not_converted', 'not_approved', 'inactive_order', 'no_lines', 'line_limit', 'required', 'text_limit', 'unsafe_formula', 'unsupported_control', 'invalid_quantity', 'output_limit'];
const valid = condition => { if (!condition) throw new Error('Order response unavailable. Check current status.'); };
const text = (value, maximum) => typeof value === 'string' && [...value].length <= maximum;
const count = value => Number.isSafeInteger(value) && value >= 0;
const quantity = value => typeof value === 'string' && /^(?:0|[1-9][0-9]{0,13})\.[0-9]{4}$/.test(value) && value !== '0.0000';
export const purchaseRoute = (workspace, order = '') => `#/workspaces/${workspace}/${order ? `orders/${order}/export/` : 'purchase-orders/'}`;

export class PurchaseController {
  constructor(client, render = () => {}, denied = async () => {}) { this.client = client; this.render = render; this.denied = denied; this.version = 0; this.state = this.empty(); }
  empty() { return { workspace: null, generation: null, orderId: null, order: null, preview: null, page: 1, busy: false, pending: false, uncertain: false, message: '' }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context(workspace, generation, orderId = null) {
    if (workspace?.id === this.state.workspace?.id && workspace?.role === this.state.workspace?.role && generation === this.state.generation && orderId === this.state.orderId) { this.state.workspace = workspace; return; }
    this.abort?.abort(); this.version++;
    this.state = { ...this.empty(), workspace, generation, orderId }; this.render(this.state);
  }
  path() { valid(UUID.test(this.state.workspace?.id) && UUID.test(this.state.orderId)); return `/api/v1/workspaces/${this.state.workspace.id}/orders/${this.state.orderId}/`; }
  writer() { return ['admin', 'reviewer'].includes(this.state.workspace?.role); }
  live(version, abort) { return version === this.version && !abort.signal.aborted; }
  validateOrder(order) {
    valid(order?.id === this.state.orderId && ['draft', 'pending_review', 'approved', 'rejected'].includes(order.status) && typeof order.is_active === 'boolean');
    valid(text(order.customer_name, 255) && text(order.purchase_order_number, 64) && Array.isArray(order.lines) && order.lines.length <= 500);
    const seen = new Set();
    for (const row of order.lines) { valid(UUID.test(row.id) && !seen.has(row.line_number) && Number.isSafeInteger(row.line_number) && row.line_number > 0 && text(row.sku, 128) && text(row.description, 8000) && text(row.unit, 32) && quantity(row.quantity)); seen.add(row.line_number); }
    return order;
  }
  validateArtifact(artifact) {
    if (artifact === null) return null;
    valid(artifact && UUID.test(artifact.id) && artifact.organization_id === this.state.workspace.id && artifact.order_id === this.state.orderId && artifact.profile === PROFILE && HEX.test(artifact.source_revision));
    valid(['running', 'failed', 'succeeded'].includes(artifact.status) && Number.isInteger(artifact.attempts) && artifact.attempts >= 1 && artifact.attempts <= 3 && typeof artifact.lease_expired === 'boolean' && text(artifact.error_code, 64));
    if (artifact.status === 'succeeded') valid(count(artifact.size_bytes) && artifact.size_bytes > 0 && artifact.size_bytes <= MAX_EXPORT_BYTES && HEX.test(artifact.sha256) && artifact.download_url === `${this.path()}exports/${artifact.id}/download/`);
    else valid(artifact.download_url === null);
    return artifact;
  }
  validatePreview(data) {
    valid(data?.profile === PROFILE && data.order?.id === this.state.orderId && data.order.organization_id === this.state.workspace.id && (data.order.source_draft_id === null || UUID.test(data.order.source_draft_id)) && data.order.status === this.state.order.status && data.order.is_active === this.state.order.is_active);
    valid(HEX.test(data.source_revision) && JSON.stringify(data.headers) === JSON.stringify(HEADERS) && count(data.count) && count(data.blocker_count) && Array.isArray(data.results) && data.results.length <= 50 && Array.isArray(data.blocking_reasons) && data.blocking_reasons.length <= 100);
    valid(data.count <= 500 && data.results.length === Math.min(50, Math.max(0, data.count - (this.state.page - 1) * 50)));
    valid(typeof data.eligible === 'boolean' && data.eligible === (data.blocker_count === 0) && data.blocker_count >= data.blocking_reasons.length && data.blocking_reasons.length === Math.min(100, data.blocker_count));
    for (const blocker of data.blocking_reasons) valid(CODES.includes(blocker.code) && text(blocker.path, 128));
    let position = 0;
    for (const row of data.results) { valid(UUID.test(row.id) && Number.isSafeInteger(row.line_number) && row.line_number > position && text(row.sku, 128) && text(row.description, 256) && typeof row.description_truncated === 'boolean' && text(row.quantity, 128) && text(row.unit, 32)); position = row.line_number; }
    this.validateArtifact(data.artifact);
    if (data.artifact) valid(data.artifact.source_revision === data.source_revision);
    return data;
  }
  async load(page = 1) {
    if (!this.state.orderId || this.state.pending || !Number.isSafeInteger(page) || page < 1) return false;
    this.abort?.abort(); const abort = this.abort = new AbortController(); const version = ++this.version;
    this.update({ busy: true, order: null, preview: null, page, message: '' });
    try {
      const order = await this.client.request(this.path(), { signal: abort.signal });
      if (!this.live(version, abort)) return false;
      this.update({ order: this.validateOrder(order) });
      if (this.writer()) {
        const data = await this.client.request(`${this.path()}exports/?profile=${PROFILE}&page=${page}`, { signal: abort.signal });
        if (!this.live(version, abort)) return false;
        this.update({ preview: this.validatePreview(data) });
      }
      this.update({ uncertain: false, message: 'Current order status loaded. Inspect it before choosing another action.' }); return true;
    } catch (error) { if (this.live(version, abort)) { this.update({ order: null, preview: null, message: error.message }); if (error.status === 403) await this.denied(this.writer()); } return false; }
    finally { if (this.live(version, abort)) this.update({ busy: false }); }
  }
  can(action) {
    const s = this.state; if (!this.writer() || s.busy || s.pending || s.uncertain || !s.order?.is_active || !s.preview) return false;
    if (action === 'submit') return ['draft', 'rejected'].includes(s.order.status);
    if (action === 'approve') return s.order.status === 'pending_review';
    if (action === 'generate') { const a = s.preview.artifact; return s.preview.eligible && (!a || a.status === 'succeeded' || (a.attempts < 3 && (a.status === 'failed' || a.lease_expired))); }
    return false;
  }
  async mutate(action) {
    if (!this.can(action)) return;
    const version = this.version; const abort = this.abort = new AbortController();
    this.update({ pending: true, message: 'Requesting the chosen action…' });
    try {
      await this.client.refreshCsrf(abort.signal);
      if (!this.live(version, abort)) return;
      const result = await this.client.request(`${this.path()}${action === 'generate' ? 'exports' : action}/`, { method: 'POST', body: action === 'generate' ? { profile: PROFILE } : {}, signal: abort.signal, withStatus: true });
      if (!this.live(version, abort)) return;
      if (action === 'generate') { valid([200, 201, 202].includes(result.status)); this.validateArtifact(result.data); valid(result.data !== null && result.data.status === (result.status === 202 ? 'running' : 'succeeded')); }
      else { valid(result.status === 200); this.validateOrder(result.data); valid(result.data.status === (action === 'submit' ? 'pending_review' : 'approved')); }
      this.update({ pending: false }); await this.load();
    } catch (error) {
      if (!this.live(version, abort)) return;
      const uncertain = !(error instanceof ApiError) || error.status >= 500;
      this.update({ uncertain, preview: null, message: uncertain ? 'Action outcome is unconfirmed. Check current status before deliberately choosing another action.' : error.message });
      if (error.status === 403) await this.denied(true);
    } finally { if (this.live(version, abort)) this.update({ pending: false }); }
  }
  async download() {
    const artifact = this.state.preview?.artifact;
    if (!this.writer() || this.state.busy || this.state.pending || this.state.uncertain || !this.state.preview?.eligible || artifact?.status !== 'succeeded') return null;
    const version = this.version; const abort = this.abort = new AbortController(); this.update({ busy: true, message: 'Requesting authorized CSV bytes…' });
    try {
      this.validateArtifact(artifact);
      const blob = await this.client.request(artifact.download_url, { binary: true, signal: abort.signal });
      if (!this.live(version, abort)) return null;
      valid(blob instanceof Blob && blob.size === artifact.size_bytes && blob.size <= MAX_EXPORT_BYTES);
      const digest = Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', await blob.arrayBuffer())), byte => byte.toString(16).padStart(2, '0')).join('');
      if (!this.live(version, abort)) return null;
      valid(digest === artifact.sha256); this.update({ message: 'CSV verified. Download does not submit it to an ERP.' }); return blob;
    } catch (error) { if (this.live(version, abort)) { this.update({ preview: null, message: error.message }); if (error.status === 403) await this.denied(true); } return null; }
    finally { if (this.live(version, abort)) this.update({ busy: false }); }
  }
}

const $ = id => document.getElementById(id);
export function renderPurchase(controller, visible) {
  const s = controller.state; $('purchase-screen').hidden = !visible;
  $('purchase-message').textContent = s.message;
  $('purchase-open-id').value = s.orderId ?? '';
  $('purchase-refresh').disabled = !s.orderId || s.busy || s.pending;
  $('purchase-content').hidden = !s.order;
  $('purchase-summary').textContent = s.order ? `${s.order.purchase_order_number} · ${s.order.customer_name} · ${s.order.status.replaceAll('_', ' ')}${s.order.is_active ? '' : ' · Inactive'}` : '';
  $('purchase-lines').replaceChildren(...(s.order?.lines ?? []).map(row => { const tr = document.createElement('tr'); for (const value of [row.line_number, row.sku, row.description, row.quantity, row.unit]) { const td = document.createElement('td'); td.textContent = value; tr.append(td); } return tr; }));
  for (const action of ['submit', 'approve', 'generate']) { $(`purchase-${action}`).hidden = !controller.writer(); $(`purchase-${action}`).disabled = !controller.can(action); }
  $('purchase-export').hidden = !controller.writer() || !s.preview;
  $('purchase-blockers').replaceChildren(...(s.preview?.blocking_reasons ?? []).map(reason => { const li = document.createElement('li'); li.textContent = `${reason.path}: ${reason.code.replaceAll('_', ' ')}`; return li; }));
  const p = s.preview, a = p?.artifact;
  $('purchase-export-status').textContent = p ? `${PROFILE} · ${p.eligible ? 'Eligible' : `${p.blocker_count} blockers`} · ${a ? `${a.status} · attempt ${a.attempts}${a.lease_expired ? ' · lease expired' : ''}${a.error_code ? ` · ${a.error_code}` : ''}` : 'Not generated'}` : '';
  $('purchase-preview').replaceChildren(...(p?.results ?? []).map(row => { const tr = document.createElement('tr'); for (const value of [row.line_number, row.sku, row.description + (row.description_truncated ? '… [preview truncated]' : ''), row.quantity, row.unit]) { const td = document.createElement('td'); td.textContent = value; tr.append(td); } return tr; }));
  $('purchase-page').textContent = p ? `Preview page ${s.page} of ${Math.max(1, Math.ceil(p.count / 50))}` : '';
  $('purchase-previous').disabled = s.busy || s.pending || s.uncertain || s.page <= 1;
  $('purchase-next').disabled = s.busy || s.pending || s.uncertain || !p || s.page * 50 >= p.count;
  $('purchase-download').disabled = s.busy || s.pending || s.uncertain || !p?.eligible || a?.status !== 'succeeded';
}
