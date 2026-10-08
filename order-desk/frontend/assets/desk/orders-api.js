// Allowlisted response validation; decimal quantities remain strings throughout.
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const blockers = {
  draft_already_converted: ['This source draft has already been converted.', 'draft-header'],
  customer_name_missing: ['A customer name is required.', 'draft-header'],
  lines_missing: ['Add at least one requested line.', 'draft-lines-section'],
  quantity_missing: ['Provide a positive quantity for every line.', 'draft-lines-section'],
  catalogue_unmatched: ['Attach unmatched lines to catalogue items.', 'draft-lines-section'],
  catalogue_inactive: ['Replace catalogue items that are inactive.', 'draft-lines-section'],
  catalogue_sku_too_long: ['Catalogue SKU snapshots must fit the 128-character purchase-order limit.', 'draft-lines-section'],
};
const valid = condition => { if (!condition) throw new Error('Unsupported response. Refresh and try again.'); };
const text = value => typeof value === 'string';
const count = value => Number.isSafeInteger(value) && value >= 0;
function identity(data, workspace, draft) {
  valid(data && UUID.test(data.id) && data.organization_id === workspace);
  if (draft) valid(data.id === draft);
  return data;
}
function header(data, workspace, draft, detail = false) {
  identity(data, workspace, draft);
  valid(['draft', 'converted'].includes(data.status) && data.source_type === 'manual');
  valid(text(data.customer_name) && text(data.customer_reference) && count(data.line_count));
  valid(text(data.updated_at) && Number.isFinite(Date.parse(data.updated_at)));
  valid(text(data.created_at) && Number.isFinite(Date.parse(data.created_at)));
  if (detail) valid(text(data.original_intake_text) && UUID.test(data.initiating_user_id));
  return data;
}
function page(data, validateItem) {
  valid(data && count(data.count) && Array.isArray(data.results) && data.results.length <= 50);
  valid(data.next === null || text(data.next));
  data.results.forEach(validateItem);
  return data;
}
export function validateReasons(reasons) {
  valid(Array.isArray(reasons) && reasons.length <= 7);
  const seen = new Set();
  for (const reason of reasons) {
    valid(reason && Object.hasOwn(blockers, reason.code) && count(reason.count) && reason.count > 0 && !seen.has(reason.code));
    seen.add(reason.code);
  }
  return reasons;
}
export class OrdersApi {
  constructor(client) { this.client = client; }
  path(workspace, draft = '') {
    valid(UUID.test(workspace) && (!draft || UUID.test(draft)));
    return `/api/v1/workspaces/${workspace}/draft-orders/${draft ? `${draft}/` : ''}`;
  }
  async list(workspace, number, signal) {
    return page(await this.client.request(`${this.path(workspace)}?page=${number}`, { signal }), item => header(item, workspace));
  }
  async detail(workspace, draft, signal) {
    return header(await this.client.request(this.path(workspace, draft), { signal }), workspace, draft, true);
  }
  async lines(workspace, draft, number, signal) {
    let position = 0;
    return page(await this.client.request(`${this.path(workspace, draft)}lines/?page=${number}`, { signal }), item => {
      valid(item && UUID.test(item.id) && item.organization_id === workspace && item.order_id === draft);
      valid(count(item.position) && item.position > position); position = item.position;
      for (const key of ['requested_sku', 'requested_description', 'unit', 'catalogue_sku_snapshot', 'catalogue_description_snapshot']) valid(text(item[key]));
      valid(item.catalogue_item_id === null || UUID.test(item.catalogue_item_id));
      valid(item.quantity === null || (text(item.quantity) && /^(?:[1-9][0-9]{0,8}|0)\.[0-9]{3}$/.test(item.quantity) && item.quantity !== '0.000'));
    });
  }
  async review(workspace, draft, signal) {
    const data = identity(await this.client.request(`${this.path(workspace, draft)}review/`, { signal }), workspace, draft);
    for (const key of ['line_count', 'unmatched_line_count', 'missing_quantity_line_count', 'unresolved_line_count', 'inactive_catalogue_line_count']) valid(count(data[key]));
    valid(typeof data.customer_name_empty === 'boolean' && typeof data.customer_reference_empty === 'boolean');
    return data;
  }
  async readiness(workspace, draft, signal) {
    const data = identity(await this.client.request(`${this.path(workspace, draft)}readiness/`, { signal }), workspace, draft);
    validateReasons(data.blocking_reasons);
    valid(count(data.line_count) && typeof data.ready_to_convert === 'boolean' && data.ready_to_convert === (data.blocking_reasons.length === 0));
    return data;
  }
  async convert(workspace, draft, signal) {
    await this.client.refreshCsrf(signal);
    const { data, status } = await this.client.request(`${this.path(workspace, draft)}convert/`, { method: 'POST', body: {}, signal, withStatus: true });
    identity(data, workspace);
    valid([200, 201].includes(status) && data.source_draft_id === draft && text(data.purchase_order_number));
    valid(data.order_url === `/api/v1/workspaces/${workspace}/orders/${data.id}/`);
    return { ...data, replayed: status === 200 };
  }
}
export function parseRoute(hash) {
  if (!hash || hash === '#') return { screen: 'catalogue' };
  const match = /^#\/workspaces\/([^/]+)\/(catalogue|draft-orders)\/(?:([^/]+)\/)?$/.exec(hash);
  if (!match || !UUID.test(match[1]) || (match[3] && (!UUID.test(match[3]) || match[2] !== 'draft-orders'))) return { screen: 'missing' };
  return { screen: match[2] === 'catalogue' ? 'catalogue' : 'drafts', workspace: match[1].toLowerCase(), draft: match[3]?.toLowerCase() };
}
