import { ApiClient } from './api.js';
import { DeskController } from './controller.js';
import { OrdersApi, parseRoute } from './orders-api.js';
import { DraftController } from './orders-controller.js';
import { draftRoute, renderDrafts } from './orders-view.js';

const $ = id => document.getElementById(id);
const client = new ApiClient();
let desk;
const orders = new DraftController(new OrdersApi(client), renderOrders, recheckAccess);
function renderOrders(state) {
  const route = parseRoute(location.hash);
  renderDrafts(state, desk?.state.phase === 'desk' && Boolean(state.workspace) && route.screen === 'drafts' && route.workspace === state.workspace.id, orders.canConvert());
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
      await orders.open(draftId, true);
      return;
    } catch {
      if (orders.state.generation !== generation || orders.version !== version) return;
    }
  }
  await desk.startWithoutSelection();
}
let navigation = 0;
async function applyRoute() {
  const version = ++navigation;
  const route = parseRoute(location.hash);
  if (desk.state.phase !== 'desk') return;
  if (route.workspace && route.workspace !== desk.state.workspace?.id) {
    await desk.selectWorkspace(route.workspace);
    if (version !== navigation || desk.state.workspace?.id !== route.workspace) return;
  }
  render(desk.state);
  if (route.screen === 'drafts' && orders.state.workspace) {
    if (route.draft) await orders.open(route.draft); else await orders.list();
    if (version === navigation) $('page-title').focus();
  }
}
function render(state) {
  const route = parseRoute(location.hash);
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
  $('drafts-tab').href = state.workspace ? draftRoute(state.workspace.id) : '#';
  $('catalogue-tab').setAttribute('aria-current', route.screen === 'catalogue' ? 'page' : 'false');
  $('drafts-tab').setAttribute('aria-current', route.screen === 'drafts' ? 'page' : 'false');
  $('route-missing').hidden = route.screen !== 'missing';
  $('breadcrumb').textContent = route.screen === 'drafts' ? 'WORKSPACE / DRAFT ORDERS' : 'WORKSPACE / CATALOGUE';
  $('page-title').textContent = route.screen === 'drafts' ? route.draft ? 'Draft review' : 'Draft orders' : 'Product catalogue';
  $('page-subtitle').textContent = route.screen === 'drafts' ? 'Inspect manual requests and their readiness for internal conversion.' : 'Browse your workspace’s products and catalogue status.';
  $('catalogue').setAttribute('aria-busy', String(state.catalogBusy));
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
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const password = $('password').value;
  $('password').value = '';
  await desk.login($('email').value, password);
  await applyRoute();
  if (desk.state.phase === 'login') $('password').focus();
});
$('logout').addEventListener('click', () => desk.logout());
$('workspace').addEventListener('change', async event => {
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
  if (!document.hidden && desk.state.phase === 'desk' && !desk.state.busy && !orders.state.converting) desk.start().then(applyRoute);
});
window.addEventListener('pageshow', event => { if (event.persisted) desk.start().then(applyRoute); });
window.addEventListener('hashchange', applyRoute);
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
