import { ApiClient } from './api.js';
import { DeskController } from './controller.js';
import { OrdersApi, parseRoute } from './orders-api.js';
import { DraftController } from './orders-controller.js';
import { draftRoute, renderDrafts } from './orders-view.js';
import { DraftEditor } from './editor.js';
import { renderEditor } from './editor-view.js';
import { DocumentController, documentRoute, incomingRoute, renderDocuments } from './documents.js';
import { ExtractionReviewController, renderExtractionReview } from './extraction-review.js';
import { MatchingController, renderMatching } from './matching.js';
import { PurchaseController, purchaseRoute, renderPurchase } from './purchase.js';
import { CatalogueController, renderCatalogue } from './catalogue.js';
import { OrderQueueController, queueRoute, renderOrderQueue } from './order-queue.js';
import { CustomerController, customerRoute, renderCustomers } from './customers.js';

const $ = id => document.getElementById(id);
const customerTab = $('catalogue-tab').cloneNode(true);
customerTab.id = 'customers-tab'; customerTab.title = 'Customers'; customerTab.querySelector('.sidebar-label').textContent = 'Customers';
$('workspace-tabs').insertBefore(customerTab, $('drafts-tab'));
// Presentation preference only; no workspace or customer data is persisted.
$('sidebar-toggle').addEventListener('click', () => {
  const collapsed = $('desk').dataset.sidebar !== 'collapsed';
  $('desk').dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
  const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
  $('sidebar-toggle').setAttribute('aria-expanded', String(!collapsed));
  $('sidebar-toggle').setAttribute('aria-label', label);
  $('sidebar-toggle').title = label;
  $('sidebar-toggle').querySelector('.sidebar-label').textContent = label;
});
const client = new ApiClient();
let desk;
let editor;
let extractionReview;
let matching;
const customers = new CustomerController(client, () => { renderCustomers(customers); if (desk) renderOrders(orders.state); }, async () => desk.startWithoutSelection(), async id => { if (orders.state.draftId === id) await orders.open(id, true); });
const catalogue = new CatalogueController(client, () => renderCatalogue(catalogue, desk?.state.phase === 'desk' && parseRoute(location.hash).screen === 'catalogue'), async () => desk.loadCatalogue(), async () => desk.startWithoutSelection());
const queue = new OrderQueueController(client, () => renderOrderQueue(queue, desk?.state.phase === 'desk' && Boolean(queue.state.screen)), async () => desk.startWithoutSelection());
const purchase = new PurchaseController(client, () => { const route = parseRoute(location.hash); renderPurchase(purchase, desk?.state.phase === 'desk' && route.screen === 'purchase' && route.workspace === purchase.state.workspace?.id); }, async () => {
  const version = purchase.version, workspace = purchase.state.workspace?.id;
  try {
    const data = await client.request(`/api/v1/workspaces/${workspace}/context/`);
    if (version !== purchase.version) return;
    desk.update({ workspace: data.workspace });
    purchase.update({ order: null, preview: null, message: 'Access refreshed. Check current order status before another action.' });
  } catch { if (version === purchase.version) await desk.startWithoutSelection(); }
});
const documents = new DocumentController(client, () => { const route = parseRoute(location.hash); const visible = desk?.state.phase === 'desk' && route.screen === 'documents' && route.workspace === documents.state.workspace?.id; renderDocuments(documents, visible); extractionReview?.context(documents.state.workspace, documents.state.generation, documents.state.order, documents.state.extraction); if (extractionReview) renderExtractionReview(extractionReview, visible); }, async action => {
  const version = documents.version;
  if (action && documents.state.workspace) {
    try {
      const data = await client.request(`/api/v1/workspaces/${documents.state.workspace.id}/context/`);
      if (version !== documents.version) return;
      desk.update({ workspace: data.workspace }); await documents.list(); return;
    } catch { if (version !== documents.version) return; }
  }
  await desk.startWithoutSelection();
});
const orders = new DraftController(new OrdersApi(client), renderOrders, recheckAccess);
matching = new MatchingController(client, orders, () => { renderMatching(matching); if (editor) renderOrders(orders.state); }, recheckAccess);
extractionReview = new ExtractionReviewController(client, () => renderExtractionReview(extractionReview), async action => {
  const version = extractionReview.version;
  if (action && extractionReview.state.workspace) {
    try { const data = await client.request(`/api/v1/workspaces/${extractionReview.state.workspace.id}/context/`); if (version !== extractionReview.version) return; desk.update({ workspace: data.workspace }); return; }
    catch { if (version !== extractionReview.version) return; }
  }
  await desk.startWithoutSelection();
}, async id => {
  if (orders.state.draftId === id) await orders.open(id, true); else await orders.list(orders.state.page);
  await documents.list(documents.state.page);
});
documents.beforeExtractionChange = row => row.id === extractionReview.state.source?.id || discardForNavigation();
editor = new DraftEditor(orders.api, orders, () => renderEditor(editor), async id => {
  if (orders.state.draftId === id) await orders.open(id, true);
  else location.hash = draftRoute(orders.state.workspace.id, id);
}, () => recheckAccess(true));
function renderOrders(state) {
  const route = parseRoute(location.hash);
  if (customers.state.mode === 'draft' && customers.state.draftId === state.draftId && customers.state.workspace?.id === state.workspace?.id && customers.state.generation === state.generation) customers.observeRevision(state.revision);
  editor?.context();
  matching?.context();
  if (matching) renderMatching(matching);
  renderDrafts(state, desk?.state.phase === 'desk' && Boolean(state.workspace) && route.screen === 'drafts' && route.workspace === state.workspace.id, orders.canConvert() && !customers.hasUnsaved(), (mode, line) => editor.begin(mode, line));
  let documentLink = $('conversion-documents');
  if (!documentLink) { documentLink = document.createElement('a'); documentLink.id = 'conversion-documents'; documentLink.textContent = 'Open purchase-order documents'; $('conversion-result').append(documentLink); }
  documentLink.hidden = !state.result; documentLink.href = state.result ? documentRoute(state.workspace.id, state.result.id) : '#';
  let purchaseLink = $('conversion-purchase');
  if (!purchaseLink) { purchaseLink = document.createElement('a'); purchaseLink.id = 'conversion-purchase'; purchaseLink.textContent = 'Review approval and CSV export'; $('conversion-result').append(purchaseLink); }
  purchaseLink.hidden = !state.result; purchaseLink.href = state.result ? purchaseRoute(state.workspace.id, state.result.id) : '#';
  if (editor) {
    $('new-draft').hidden = !editor.canEdit('create');
    $('edit-header').hidden = !editor.canEdit(); $('add-line').hidden = !editor.canEdit();
    for (const id of ['new-draft', 'edit-header', 'add-line']) $(id).disabled = editor.state.open || state.converting || customers.state.pending || Boolean(customers.state.operation);
  }
}
async function recheckAccess(action) {
  const { workspace, draftId } = orders.state;
  const generation = orders.state.generation;
  const version = orders.version;
  if (action && workspace) {
    try {
      const data = await client.request(`/api/v1/workspaces/${workspace.id}/context/`);
      // Context can itself finish after logout or workspace replacement.
      if (orders.state.workspace?.id !== workspace.id || orders.state.generation !== generation || orders.version !== version) return;
      desk.update({ workspace: data.workspace });
      if (draftId) await orders.open(draftId, true); else await orders.list();
      return;
    } catch {
      if (orders.state.generation !== generation || orders.version !== version) return;
    }
  }
  await desk.startWithoutSelection();
}
let navigation = 0;
let acceptedHash = location.hash;
function discardForNavigation(signingOut = false) {
  if (customers.state.pending || customers.state.operation) { customers.update({ message: 'Reconcile the saved reference operation before leaving. Signing out clears private in-memory state.' }); if (!signingOut) return false; }
  if (!signingOut && customers.state.mode === 'draft' && customers.state.account && !customers.state.operation) { if (!window.confirm('Discard this proposed customer selection before leaving?')) return false; customers.update({ account: null, locations: [], candidate: null }); }
  if (documents.state.pending || documents.state.linkOperation || documents.state.uncertain) { documents.update({ message: 'Reconcile the pending source operation before leaving. Sign out clears private in-memory state.' }); if (!signingOut) return false; }
  if (!signingOut && catalogue.state.pending) return false;
  if (!signingOut && catalogue.state.uncertain) { catalogue.update({ message: 'Reconcile the unconfirmed catalogue write before leaving. Reloading discards the in-memory retry receipt.' }); return false; }
  if (purchase.state.pending) return false;
  if (matching?.state.pending) return false;
  if (extractionReview.state.pending || extractionReview.state.uncertain) { extractionReview.update({ message: 'Reconcile the pending or unconfirmed application using the identical request before leaving.' }); return false; }
  if (extractionReview.hasUnsaved()) {
    if (!window.confirm('Discard unsaved extraction choices and corrections before leaving?')) return false;
    extractionReview.discard();
  }
  if (editor.state.open) {
    if (editor.state.pending || (editor.state.dirty && !window.confirm('Discard unsaved draft values before leaving?'))) return false;
    editor.discard();
  }
  return true;
}
async function applyRoute() {
  if (location.hash !== acceptedHash && !discardForNavigation()) { history.replaceState(null, '', location.pathname + location.search + acceptedHash); return; }
  acceptedHash = location.hash;
  const version = ++navigation;
  const route = parseRoute(location.hash);
  if (desk.state.phase !== 'desk') return;
  if (route.workspace && route.workspace !== desk.state.workspace?.id) {
    await desk.selectWorkspace(route.workspace);
    if (version !== navigation || desk.state.workspace?.id !== route.workspace) return;
  }
  render(desk.state);
  if (queue.state.screen) await queue.load();
  if (customers.state.mode === 'directory') await customers.list();
  if (customers.state.mode === 'snapshot') await customers.loadSnapshot();
  if (route.screen === 'drafts' && orders.state.workspace) {
    if (route.draft) await orders.open(route.draft); else await orders.list();
    if (version === navigation) $('page-title').focus();
  }
  if (route.screen === 'documents' && documents.state.workspace && route.order) await documents.list();
  if (route.screen === 'purchase' && purchase.state.workspace && route.order) await purchase.load();
}
function render(state) {
  const route = parseRoute(location.hash);
  const customerMode = route.screen === 'customers' ? 'directory' : route.screen === 'drafts' && route.draft ? 'draft' : route.screen === 'purchase' && route.order ? 'snapshot' : null;
  customers.context(state.phase === 'desk' && route.workspace === state.workspace?.id && customerMode ? state.workspace : null, state.generation, customerMode, route.draft ?? route.order ?? null);
  renderCustomers(customers);
  queue.context(state.phase === 'desk' ? state.workspace : null, state.generation, route);
  renderOrderQueue(queue, state.phase === 'desk' && Boolean(queue.state.screen));
  catalogue.context(state.phase === 'desk' ? state.workspace : null, state.generation);
  renderCatalogue(catalogue, state.phase === 'desk' && route.screen === 'catalogue');
  $('loading').hidden = state.phase !== 'loading';
  $('login-panel').hidden = state.phase !== 'login';
  $('desk').hidden = state.phase !== 'desk';
  $('logout').hidden = !['desk', 'error'].includes(state.phase);
  $('notice').textContent = state.message;
  $('retry').hidden = !(state.phase === 'error' || state.catalogError);
  $('retry').textContent = state.retryAction === 'logout' ? 'Retry sign out' : 'Try again';
  for (const input of $('login-form').elements) input.disabled = state.busy;
  $('logout').disabled = state.busy;
  $('workspace').disabled = state.busy;
  const options = [new Option('Choose a workspace', '')];
  const workspaces = [...state.workspaces];
  if (state.workspace && !workspaces.some(item => item.id === state.workspace.id)) workspaces.unshift(state.workspace);
  for (const item of workspaces) options.push(new Option(item.name, item.id));
  $('workspace').replaceChildren(...options);
  $('workspace').value = state.workspace?.id ?? '';
  $('role').textContent = state.workspace ? `Your role: ${state.workspace.role}` : '';
  $('more-workspaces').hidden = !state.moreWorkspaces;
  $('more-workspaces').disabled = state.busy;
  $('choose-workspace').hidden = Boolean(state.workspace);
  $('catalogue').hidden = !state.workspace || route.screen !== 'catalogue';
  $('workspace-tabs').hidden = !state.workspace;
  $('catalogue-tab').href = state.workspace ? `#/workspaces/${state.workspace.id}/catalogue/` : '#';
  $('customers-tab').href = state.workspace ? customerRoute(state.workspace.id) : '#';
  $('customers-tab').setAttribute('aria-current', route.screen === 'customers' ? 'page' : 'false');
  $('drafts-tab').href = state.workspace ? draftRoute(state.workspace.id) : '#';
  $('documents-tab').href = state.workspace ? incomingRoute(state.workspace.id) : '#';
  $('purchase-tab').href = state.workspace ? purchaseRoute(state.workspace.id) : '#';
  $('purchase-queue-link').href = $('purchase-tab').href;
  $('documents-queue-link').href = $('documents-tab').href;
  $('purchase-documents-link').href = state.workspace && route.order ? documentRoute(state.workspace.id, route.order) : '#';
  $('documents-purchase-link').href = state.workspace && route.order ? purchaseRoute(state.workspace.id, route.order) : '#';
  $('documents-purchase-link').hidden = route.order === 'incoming';
  $('documents-queue-link').href = state.workspace ? documentRoute(state.workspace.id) : '#';
  $('purchase-tab').setAttribute('aria-current', route.screen === 'purchase' ? 'page' : 'false');
  $('documents-tab').setAttribute('aria-current', route.screen === 'documents' ? 'page' : 'false');
  $('catalogue-tab').setAttribute('aria-current', route.screen === 'catalogue' ? 'page' : 'false');
  $('drafts-tab').setAttribute('aria-current', route.screen === 'drafts' ? 'page' : 'false');
  $('route-missing').hidden = route.screen !== 'missing';
  $('breadcrumb').textContent = route.screen === 'drafts' ? 'WORKSPACE / DRAFT ORDERS' : 'WORKSPACE / CATALOGUE';
  $('page-title').textContent = route.screen === 'drafts' ? route.draft ? 'Draft review' : 'Draft orders' : 'Product catalogue';
  $('page-subtitle').textContent = route.screen === 'drafts' ? 'Inspect manual requests and their readiness for internal conversion.' : 'Browse your workspace’s products and catalogue status.';
  if (route.screen === 'customers') { $('breadcrumb').textContent = 'WORKSPACE / CUSTOMER REFERENCE DATA'; $('page-title').textContent = 'Customers'; $('page-subtitle').textContent = 'Approved identifiers, delivery locations and explicit account confirmation.'; }
  $('catalogue').setAttribute('aria-busy', String(state.catalogBusy));
  if (route.screen === 'documents') { $('breadcrumb').textContent = 'WORKSPACE / SOURCE DOCUMENTS'; $('page-title').textContent = route.order === 'incoming' ? 'Incoming orders' : route.order ? 'Document intake' : 'Find an order for document intake'; $('page-subtitle').textContent = 'Private source bytes and their recorded review status.'; }
  if (route.screen === 'purchase') { $('breadcrumb').textContent = 'WORKSPACE / INTERNAL ORDERS'; $('page-title').textContent = route.order ? 'Approval and CSV export' : 'Internal orders'; $('page-subtitle').textContent = 'Find an order, inspect its source and review its next action.'; }
  purchase.context(state.phase === 'desk' ? state.workspace : null, state.generation, route.screen === 'purchase' && route.workspace === state.workspace?.id ? route.order ?? null : null);
  renderPurchase(purchase, state.phase === 'desk' && route.screen === 'purchase' && Boolean(route.order) && route.workspace === state.workspace?.id);
  documents.context(state.phase === 'desk' ? state.workspace : null, state.generation, route.screen === 'documents' && route.workspace === state.workspace?.id ? route.order ?? null : null);
  renderDocuments(documents, state.phase === 'desk' && Boolean(state.workspace) && route.screen === 'documents' && Boolean(route.order) && route.workspace === state.workspace.id);
  extractionReview.context(documents.state.workspace, documents.state.generation, documents.state.order, documents.state.extraction);
  renderExtractionReview(extractionReview, state.phase === 'desk' && route.screen === 'documents' && route.workspace === state.workspace?.id);
  // Preserve the user's unsent search text during loading/render updates.
  if (!state.workspace || state.phase === 'loading') { $('search').value = ''; $('activity').value = ''; }
  $('result-count').textContent = state.catalogBusy ? 'Loading products…' : `${state.count.toLocaleString()} ${state.count === 1 ? 'product' : 'products'}`;
  const rows = state.items.map(item => {
    const row = document.createElement('tr');
    for (const value of [item.sku, item.description || '—']) {
      const cell = document.createElement('td');
      cell.textContent = value; row.append(cell);
    }
    const cell = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = `badge${item.is_active ? '' : ' inactive'}`;
    badge.textContent = item.is_active ? 'Active' : 'Inactive';
    cell.append(badge); row.append(cell);
    return row;
  });
  $('items').replaceChildren(...rows);
  $('catalogue-state').hidden = Boolean(rows.length);
  $('catalogue-state').textContent = state.catalogBusy ? 'Loading your workspace catalogue…' : state.catalogError ? 'Catalogue unavailable. Use Try again to reload.' : state.query || state.activity ? 'No products match these filters.' : 'This workspace has no catalogue products yet.';
  $('page-label').textContent = `Page ${state.page} of ${Math.max(1, Math.ceil(state.count / 50))}`;
  $('previous').disabled = state.catalogBusy || state.catalogError || state.page <= 1;
  $('next').disabled = state.catalogBusy || state.catalogError || state.page * 50 >= state.count;
  orders.context(state.phase === 'desk' ? state.workspace : null, state.generation);
  renderOrders(orders.state);
}

desk = new DeskController(client, render);
$('catalogue-create-form').addEventListener('submit', event => { event.preventDefault(); catalogue.create($('catalogue-sku').value, $('catalogue-description').value); });
$('catalogue-file').addEventListener('change', event => catalogue.select(event.target.files[0] ?? null));
$('catalogue-validate').addEventListener('click', () => catalogue.validate());
$('catalogue-import').addEventListener('click', () => { if (catalogue.canWrite() && catalogue.state.report?.can_import && window.confirm('Create all validated catalogue products? The server rechecks every row and commits them together.')) catalogue.execute(); });
$('catalogue-reconcile').addEventListener('click', () => catalogue.state.create ? catalogue.reconcileCreate() : catalogue.execute(true));
$('queue-search-form').addEventListener('submit', event => {
  event.preventDefault();
  if (queue.state.screen) location.hash = queueRoute(queue.state.workspace.id, queue.state.screen, { query: $('queue-search').value.trim(), status: $('queue-status').value });
});
$('queue-refresh').addEventListener('click', () => queue.load());
for (const [id, offset] of [['queue-previous', -1], ['queue-next', 1]]) $(id).addEventListener('click', () => {
  const s = queue.state;
  if (!$(id).disabled && s.screen) location.hash = queueRoute(s.workspace.id, s.screen, { query: s.query, status: s.status, page: s.page + offset });
});
$('purchase-open-form').addEventListener('submit', event => { event.preventDefault(); const id = $('purchase-open-id').value.trim().toLowerCase(); if (/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id) && purchase.state.workspace) location.hash = purchaseRoute(purchase.state.workspace.id, id); else purchase.update({ message: 'Enter a valid purchase-order UUID.' }); });
$('purchase-refresh').addEventListener('click', () => purchase.load());
$('purchase-previous').addEventListener('click', () => purchase.load(purchase.state.page - 1));
$('purchase-next').addEventListener('click', () => purchase.load(purchase.state.page + 1));
for (const action of ['submit', 'approve']) $(`purchase-${action}`).addEventListener('click', () => {
  if (purchase.can(action) && window.confirm(`${action === 'approve' ? 'Approve' : 'Submit for review'} ${purchase.state.order.purchase_order_number} for ${purchase.state.order.customer_name}? Inspect the displayed quantities and units first. Pricing and ERP delivery remain separate.`)) purchase.mutate(action);
});
$('purchase-generate').addEventListener('click', () => purchase.mutate('generate'));
$('purchase-download').addEventListener('click', async () => {
  const version = purchase.version, order = purchase.state.orderId;
  const blob = await purchase.download(); if (!blob || version !== purchase.version || order !== purchase.state.orderId) return;
  const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = `order-${purchase.state.orderId}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('documents-open-form').addEventListener('submit', event => { event.preventDefault(); const id = $('documents-order-id').value.trim().toLowerCase(); if (/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id) && documents.state.workspace) location.hash = documentRoute(documents.state.workspace.id, id); else documents.update({ message: 'Enter a valid purchase-order UUID.' }); });
$('customer-search-form').addEventListener('submit', event => { event.preventDefault(); customers.list(1, $('customer-query').value.trim(), $('customer-active').value); });
$('customer-refresh').addEventListener('click', () => customers.list(customers.state.page));
$('customer-previous').addEventListener('click', () => customers.list(customers.state.page - 1));
$('customer-next').addEventListener('click', () => customers.list(customers.state.page + 1));
$('customer-create-form').addEventListener('submit', event => { event.preventDefault(); customers.mutate('account', customers.base(), { code: $('customer-new-code').value, display_name: $('customer-new-name').value, destination_id: $('customer-new-destination').value, requires_location: $('customer-new-location-required').checked }); });
$('customer-edit-form').addEventListener('submit', event => { event.preventDefault(); const account = customers.state.account; if (!account) return; customers.mutate('account', `${customers.base()}${account.id}/`, { display_name: $('customer-edit-name').value, destination_id: $('customer-edit-destination').value, requires_location: $('customer-edit-location-required').checked, is_active: $('customer-edit-active').checked }, { id: account.id, method: 'PATCH', revision: account.revision }); });
$('customer-location-form').addEventListener('submit', event => { event.preventDefault(); const account = customers.state.account; if (!account) return; customers.mutate('location', `${customers.base()}${account.id}/locations/`, { code: $('customer-location-code').value, display_name: $('customer-location-name').value, destination_id: $('customer-location-destination').value }, { customer: account.id }); });
$('customer-alias-form').addEventListener('submit', event => { event.preventDefault(); const account = customers.state.account; if (!account) return; customers.mutate('alias', `${customers.base()}${account.id}/aliases/`, { value: $('customer-alias-value').value, provenance: $('customer-alias-provenance').value }, { customer: account.id }); });
for (const [previous, next, kind] of [['customer-site-previous', 'customer-site-next', 'site'], ['customer-alias-previous', 'customer-alias-next', 'alias'], ['customer-confirm-site-previous', 'customer-confirm-site-next', 'site']]) {
  for (const [id, increment] of [[previous, -1], [next, 1]]) $(id).addEventListener('click', () => { const s = customers.state; if (s.account) customers.openAccount(s.account.id, s.sitePage + (kind === 'site' ? increment : 0), s.aliasPage + (kind === 'alias' ? increment : 0)); });
}
$('customer-import-file').addEventListener('change', event => customers.selectFile(event.target.files[0] ?? null));
$('customer-import-validate').addEventListener('click', () => customers.validateFile());
$('customer-import-create').addEventListener('click', () => { if (customers.state.file && customers.state.report?.valid) customers.mutate('import', `${customers.base()}imports/create/`, {}, { file: customers.state.file }); });
for (const prefix of ['customer', 'customer-confirm']) {
  $(`${prefix}-reconcile`).addEventListener('click', () => customers.reconcile());
  $(`${prefix}-retry`).addEventListener('click', () => customers.send());
}
$('customer-confirm-refresh').addEventListener('click', () => customers.loadStatus());
$('customer-lookup-form').addEventListener('submit', event => { event.preventDefault(); customers.list(1, $('customer-confirm-query').value.trim()); });
$('customer-confirm-exact').addEventListener('click', () => customers.resolve($('customer-confirm-query').value));
$('customer-confirm-previous').addEventListener('click', () => customers.list(customers.state.page - 1));
$('customer-confirm-next').addEventListener('click', () => customers.list(customers.state.page + 1));
$('customer-confirm-preview').addEventListener('click', () => customers.preview($('customer-site-choice').value || null));
$('customer-site-choice').addEventListener('change', () => customers.preview($('customer-site-choice').value || null));
$('customer-confirm-save').addEventListener('click', () => customers.confirm());
$('customer-confirm-cancel').addEventListener('click', () => { if (!customers.state.pending && !customers.state.operation) customers.update({ account: null, locations: [], candidate: null, locationId: null }); });
$('order-customer-refresh').addEventListener('click', () => customers.loadSnapshot());
$('document-file').addEventListener('change', event => documents.select(event.target.files[0] ?? null));
$('document-upload-form').addEventListener('submit', event => { event.preventDefault(); documents.upload(); });
$('documents-refresh').addEventListener('click', () => documents.list(documents.state.page));
$('documents-check').addEventListener('click', async () => { if (documents.state.order === 'incoming') return documents.reconcileUpload(); const workspace = documents.state.workspace?.id; const generation = documents.state.generation; const order = documents.state.order; documents.update({ file: null }); const loaded = await documents.list(); if (loaded && documents.state.workspace?.id === workspace && documents.state.generation === generation && documents.state.order === order) documents.update({ uncertain: false, message: 'Compare listed filenames and sizes before deliberately selecting a file again.' }); });
$('incoming-search-form').addEventListener('submit', event => { event.preventDefault(); if (documents.state.pending) return; documents.update({ query: $('incoming-query').value.trim(), filter: $('incoming-filter').value }); documents.list(); });
$('incoming-link-form').addEventListener('submit', event => { event.preventDefault(); documents.linkSource({ draft_id: $('incoming-drafts').value, customer_name: $('incoming-customer').value, customer_reference: $('incoming-reference').value }); });
$('incoming-link-cancel').addEventListener('click', () => { if (!documents.state.pending && !documents.state.linkOperation) documents.update({ linkSource: null, drafts: [] }); });
$('incoming-link-reconcile').addEventListener('click', () => documents.linkSource());
$('incoming-draft-previous').addEventListener('click', () => documents.chooseLink(documents.state.linkSource, documents.state.draftPage - 1));
$('incoming-draft-next').addEventListener('click', () => documents.chooseLink(documents.state.linkSource, documents.state.draftPage + 1));
$('documents-previous').addEventListener('click', () => documents.list(documents.state.page - 1));
$('documents-next').addEventListener('click', () => documents.list(documents.state.page + 1));
$('extraction-queue').addEventListener('click', () => documents.queueExtraction());
$('extraction-retry').addEventListener('click', () => documents.queueExtraction(true));
$('extraction-refresh').addEventListener('click', () => { if (documents.state.extraction) documents.openExtraction(documents.state.extraction.row, documents.state.extraction.page); });
$('extraction-previous').addEventListener('click', () => documents.openExtraction(documents.state.extraction.row, documents.state.extraction.page - 1));
$('extraction-next').addEventListener('click', () => documents.openExtraction(documents.state.extraction.row, documents.state.extraction.page + 1));
$('review-load-drafts').addEventListener('click', () => extractionReview.listDrafts());
$('review-draft-previous').addEventListener('click', () => extractionReview.listDrafts(extractionReview.state.draftPage - 1));
$('review-draft-next').addEventListener('click', () => extractionReview.listDrafts(extractionReview.state.draftPage + 1));
$('review-open-form').addEventListener('submit', event => { event.preventDefault(); const id = $('review-draft-id').value.trim().toLowerCase(); if (extractionReview.hasUnsaved() && id !== extractionReview.state.draftId) { if (!window.confirm('Discard these unsaved selections before choosing another draft?')) return; extractionReview.discard(); } extractionReview.load(id); });
$('review-previous').addEventListener('click', () => extractionReview.load(extractionReview.state.draftId, extractionReview.state.page - 1));
$('review-next').addEventListener('click', () => extractionReview.load(extractionReview.state.draftId, extractionReview.state.page + 1));
$('review-line-previous').addEventListener('click', () => extractionReview.loadLines(extractionReview.state.linePage - 1));
$('review-line-next').addEventListener('click', () => extractionReview.loadLines(extractionReview.state.linePage + 1));
$('review-refresh').addEventListener('click', () => extractionReview.load(extractionReview.state.draftId, extractionReview.state.page, true));
$('review-accept-comparison').addEventListener('click', () => { if (window.confirm('Use the refreshed draft revision with these kept choices after comparing current target values?')) extractionReview.acceptComparison(); });
$('review-discard').addEventListener('click', () => { if (!extractionReview.hasUnsaved() || window.confirm('Discard these unsaved selections and corrections?')) { extractionReview.discard(); extractionReview.load(extractionReview.state.draftId, extractionReview.state.page); } });
$('review-apply').addEventListener('click', () => { if (extractionReview.canApply() && window.confirm('Apply exactly the selected fields and row mappings shown in the preview? Other lines stay unchanged. Conversion remains a separate action.')) extractionReview.apply(); });
$('review-reconcile').addEventListener('click', () => extractionReview.apply(true));
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const password = $('password').value;
  $('password').value = '';
  await desk.login($('email').value, password);
  await applyRoute();
  if (desk.state.phase === 'login') $('password').focus();
});
$('logout').addEventListener('click', () => { if (discardForNavigation(true)) desk.logout(); });
$('workspace').addEventListener('change', async event => {
  if (!discardForNavigation()) { $('workspace').value = desk.state.workspace?.id ?? ''; return; }
  navigation += 1;
  await desk.selectWorkspace(event.target.value);
  location.hash = desk.state.workspace ? `#/workspaces/${desk.state.workspace.id}/catalogue/` : '';
});
$('more-workspaces').addEventListener('click', () => desk.moreWorkspaces());
$('search-form').addEventListener('submit', event => {
  event.preventDefault(); desk.search($('search').value, $('activity').value);
});
$('activity').addEventListener('change', () => desk.search($('search').value, $('activity').value));
$('previous').addEventListener('click', () => desk.goToPage(desk.state.page - 1));
$('next').addEventListener('click', () => desk.goToPage(desk.state.page + 1));
$('retry').addEventListener('click', () => desk.state.catalogError ? desk.loadCatalogue() : desk.state.retryAction === 'logout' ? desk.logout() : desk.start());
// Revalidate on return from another tab, where selection, auth or access changed.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && desk.state.phase === 'desk' && !desk.state.busy && !customers.hasUnsaved() && !customers.state.file && !documents.state.pending && !documents.state.uncertain && !documents.state.linkOperation && !documents.state.file && !catalogue.state.pending && !catalogue.state.uncertain && !catalogue.state.file && !orders.state.converting && !purchase.state.pending && !editor.state.open && !extractionReview.hasUnsaved() && !extractionReview.state.pending) desk.start().then(applyRoute);
});
window.addEventListener('pageshow', event => { if (event.persisted) desk.start().then(applyRoute); });
window.addEventListener('hashchange', applyRoute);
window.addEventListener('beforeunload', event => { if (customers.hasUnsaved() || documents.state.pending || documents.state.uncertain || documents.state.linkOperation || catalogue.state.pending || catalogue.state.uncertain || purchase.state.pending || editor.state.dirty || editor.state.pending || extractionReview.hasUnsaved() || extractionReview.state.pending || matching.state.pending || matching.state.uncertain) { event.preventDefault(); event.returnValue = ''; } });
$('matching-load').addEventListener('click', () => matching.load());
$('matching-reload').addEventListener('click', () => matching.reload());
$('new-draft').addEventListener('click', () => editor.begin('create'));
$('edit-header').addEventListener('click', () => editor.begin('header'));
$('add-line').addEventListener('click', () => editor.begin('add-line'));
$('editor-form').addEventListener('input', event => { if (event.target.name) editor.change(event.target.name, event.target.value); });
$('editor-form').addEventListener('change', event => { if (event.target.name) editor.change(event.target.name, event.target.value); });
$('editor-form').addEventListener('submit', event => { event.preventDefault(); editor.save(); });
$('editor-discard').addEventListener('click', () => { if (discardForNavigation()) $('page-title').focus(); });
$('draft-editor').addEventListener('cancel', event => { event.preventDefault(); discardForNavigation(); });
$('editor-reload').addEventListener('click', () => { if (window.confirm('Reload server values and discard these unsaved values?')) editor.reload().catch(() => editor.update({ message: 'Unable to reload. Your values are still kept.' })); });
$('attach-search').addEventListener('click', () => editor.catalogue($('attach-query').value));
$('attach-previous').addEventListener('click', () => editor.catalogue(editor.state.catalogQuery, editor.state.catalogPage - 1));
$('attach-next').addEventListener('click', () => editor.catalogue(editor.state.catalogQuery, editor.state.catalogPage + 1));
$('draft-refresh').addEventListener('click', () => orders.state.draftId ? orders.open(orders.state.draftId, true) : orders.list(orders.state.page));
$('draft-previous').addEventListener('click', () => orders.list(orders.state.page - 1));
$('draft-next').addEventListener('click', () => orders.list(orders.state.page + 1));
$('draft-line-previous').addEventListener('click', () => orders.lines(orders.state.linePage - 1));
$('draft-line-next').addEventListener('click', () => orders.lines(orders.state.linePage + 1));
let confirmationContext;
$('convert-draft').addEventListener('click', () => {
  if (!orders.canConvert()) return;
  confirmationContext = orders.version;
  $('conversion-confirm').returnValue = 'cancel';
  $('confirm-description').textContent = `${orders.state.draft.customer_name || 'No customer name'} · ${orders.state.draft.line_count} requested lines. ${orders.state.uncertain ? 'Repeats the same source request and may create the order if no result committed.' : orders.state.draft.status === 'converted' ? 'Retrieves the existing purchase order.' : 'The server will check readiness again.'}`;
  $('conversion-confirm').showModal();
});
$('conversion-confirm').addEventListener('close', async () => {
  if ($('conversion-confirm').returnValue !== 'confirm' || confirmationContext !== orders.version) return;
  await orders.convert();
  if (orders.state.workspace && !orders.state.converting) $('page-title').focus();
});
desk.start().then(applyRoute);
