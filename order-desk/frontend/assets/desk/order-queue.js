import { UUID } from './orders-api.js';
import { purchaseRoute } from './purchase.js';
import { documentRoute } from './documents.js';
import { draftRoute } from './orders-view.js';

export const ORDER_STATES = ['draft', 'pending_review', 'approved', 'rejected'];
export function queueRoute(workspace, screen, { query = '', status = '', page = 1 } = {}) {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (status) params.set('status', status);
  if (page !== 1) params.set('page', String(page));
  return (screen === 'documents' ? documentRoute(workspace) : purchaseRoute(workspace)) + (params.size ? `?${params}` : '');
}
const valid = condition => { if (!condition) throw new Error('Order queue response unavailable. Refresh the queue.'); };
const text = (value, limit) => typeof value === 'string' && [...value].length <= limit;
export class OrderQueueController {
  constructor(client, render = () => {}, denied = async () => {}) { this.client = client; this.render = render; this.denied = denied; this.version = 0; this.state = this.empty(); }
  empty() { return { workspace: null, generation: null, screen: null, query: '', status: '', page: 1, rows: [], count: 0, busy: false, loaded: false, message: '' }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context(workspace, generation, route) {
    const screen = ['documents', 'purchase'].includes(route.screen) && !route.order && route.workspace === workspace?.id ? route.screen : null;
    const query = screen ? route.query ?? '' : '', status = screen ? route.status ?? '' : '', page = screen ? route.page ?? 1 : 1;
    const s = this.state;
    if (s.workspace?.id === workspace?.id && s.workspace?.role === workspace?.role && s.generation === generation && s.screen === screen && s.query === query && s.status === status && s.page === page) return;
    this.abort?.abort(); this.version++;
    this.state = { ...this.empty(), workspace, generation, screen, query, status, page }; this.render(this.state);
  }
  async load() {
    const s = this.state;
    if (!s.screen || !UUID.test(s.workspace?.id)) return;
    this.abort?.abort(); const abort = this.abort = new AbortController(), version = ++this.version;
    const live = () => version === this.version && !abort.signal.aborted;
    this.update({ rows: [], count: 0, busy: true, loaded: false, message: 'Loading orders…' });
    try {
      const params = new URLSearchParams({ page: String(s.page), q: s.query, status: s.status });
      const data = await this.client.request(`/api/v1/workspaces/${s.workspace.id}/orders/queue/?${params}`, { signal: abort.signal });
      if (!live()) return;
      valid(data && Number.isSafeInteger(data.count) && data.count >= 0 && Array.isArray(data.results) && data.results.length === Math.min(50, Math.max(0, data.count - (s.page - 1) * 50)));
      const seen = new Set();
      for (const row of data.results) {
        valid(UUID.test(row.id) && !seen.has(row.id) && row.organization_id === s.workspace.id && (row.source_draft_id === null || UUID.test(row.source_draft_id)));
        valid(text(row.customer_name, 255) && text(row.purchase_order_number, 64) && (row.customer_reference === null || text(row.customer_reference, 128)) && ORDER_STATES.includes(row.status) && (!s.status || row.status === s.status) && typeof row.is_active === 'boolean');
        valid(typeof row.created_at === 'string' && Number.isFinite(Date.parse(row.created_at)) && typeof row.updated_at === 'string' && Number.isFinite(Date.parse(row.updated_at)));
        seen.add(row.id);
      }
      this.update({ rows: data.results, count: data.count, loaded: true, message: data.count ? `${data.count.toLocaleString()} orders` : 'No orders match these filters. Converted drafts appear here; start a manual draft from Draft orders.' });
    } catch (error) {
      if (live()) { this.update({ rows: [], count: 0, message: error.message }); if (error.status === 403) await this.denied(); }
    } finally { if (live()) this.update({ busy: false }); }
  }
}
export function nextOrderAction(row) {
  if (!row.is_active) return 'Inactive · inspect history';
  return { draft: 'Inspect and submit for review', pending_review: 'Review decision required', approved: 'Check export readiness', rejected: 'Inspect rejection before resubmission' }[row.status];
}
const $ = id => document.getElementById(id);
export function renderOrderQueue(controller, visible) {
  const s = controller.state;
  $('order-queue').hidden = !visible;
  $('order-queue').setAttribute('aria-busy', String(s.busy));
  $('queue-message').textContent = s.message;
  // Keep typed, unsubmitted search text through asynchronous loading renders.
  const contextKey = JSON.stringify([s.workspace?.id, s.generation, s.screen, s.query, s.status, s.page]);
  if ($('queue-search').dataset.context !== contextKey) {
    $('queue-search').value = s.query; $('queue-status').value = s.status;
    $('queue-search').dataset.context = contextKey;
  }
  $('queue-rows').replaceChildren(...s.rows.map(row => {
    const tr = document.createElement('tr');
    for (const value of [row.customer_name, row.customer_reference || 'Not recorded', row.purchase_order_number, new Date(row.created_at).toLocaleString(), row.status.replaceAll('_', ' '), nextOrderAction(row)]) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
    const td = document.createElement('td');
    for (const [label, href] of [['Open order', purchaseRoute(s.workspace.id, row.id)], ['Source documents', documentRoute(s.workspace.id, row.id)], ...(row.source_draft_id ? [['Source draft', draftRoute(s.workspace.id, row.source_draft_id)]] : [])]) { const link = document.createElement('a'); link.href = href; link.textContent = label; td.append(link, document.createTextNode(' ')); }
    tr.append(td); return tr;
  }));
  $('queue-page').textContent = s.loaded ? `Page ${s.page} of ${Math.max(1, Math.ceil(s.count / 50))}` : '';
  $('queue-previous').disabled = s.busy || s.page <= 1;
  $('queue-next').disabled = s.busy || !s.loaded || s.page * 50 >= s.count;
  $('queue-refresh').disabled = s.busy;
}
