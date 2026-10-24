import { ApiError } from './api.js';
import { UUID, blockers } from './orders-api.js';

const SHA = /^[0-9a-f]{64}$/;
const valid = value => { if (!value) throw new Error('Customer response unavailable. Refresh before continuing.'); };
export const customerRoute = workspace => `#/workspaces/${workspace}/customers/`;

export class CustomerController {
  constructor(client, render = () => {}, denied = async () => {}, saved = async () => {}) {
    this.client = client; this.render = render; this.denied = denied; this.saved = saved;
    this.version = 0; this.epoch = 0; this.state = this.empty();
  }
  empty() { return { workspace: null, generation: null, mode: null, draftId: null, orderId: null,
    rows: [], count: 0, page: 1, query: '', active: 'true', account: null,
    locations: [], siteCount: 0, sitePage: 1, aliases: [], aliasCount: 0, aliasPage: 1,
    locationId: null, candidate: null, status: null, revision: null, snapshot: null,
    file: null, report: null, retirementReasons: {}, busy: false, pending: false,
    operation: null, completed: null, message: '' }; }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  context(workspace, generation, mode = null, id = null) {
    const key = `${generation}/${workspace?.id ?? ''}/${workspace?.role ?? ''}/${mode}/${id}`;
    if (key === this.key) return;
    this.key = key; this.epoch++; this.version++; this.abort?.abort();
    this.state = { ...this.empty(), workspace, generation, mode, draftId: mode === 'draft' ? id : null, orderId: mode === 'snapshot' ? id : null };
    this.render(this.state);
  }
  base() { valid(UUID.test(this.state.workspace?.id)); return `/api/v1/workspaces/${this.state.workspace.id}/customers/`; }
  confirmationPath() { valid(UUID.test(this.state.draftId)); return `${this.base()}drafts/${this.state.draftId}/confirmation/`; }
  live(version, abort) { return version === this.version && !abort.signal.aborted; }
  canWrite() { return this.state.workspace?.role === 'admin' && !this.state.pending && !this.state.busy && !this.state.operation; }
  hasUnsaved() { return Boolean(this.state.operation || this.state.pending || (this.state.mode === 'draft' && this.state.account)); }
  observeRevision(revision) {
    if (this.state.mode !== 'draft' || !revision || this.state.revision === revision) return;
    this.state.revision = revision;
    if (!this.state.pending && !this.state.operation && !this.state.busy) this.loadStatus();
  }
  validateRecord(row, kind = 'account', customer = null) {
    valid(row && UUID.test(row.id) && row.organization_id === this.state.workspace.id && typeof row.is_active === 'boolean' && SHA.test(row.revision));
    if (kind !== 'account') valid(row.customer_id === customer);
    if (kind === 'alias') valid(typeof row.value === 'string' && typeof row.provenance === 'string' && UUID.test(row.approved_by_id));
    else valid(typeof row.code === 'string' && typeof row.display_name === 'string' && typeof row.destination_id === 'string');
    return row;
  }
  validatePage(data, kind = 'account', customer = null) {
    valid(data && Number.isSafeInteger(data.count) && data.count >= 0 && Array.isArray(data.results) && data.results.length <= 50);
    data.results.forEach(row => this.validateRecord(row, kind, customer)); return data;
  }
  validateStatus(data) {
    valid(data?.draft_id === this.state.draftId && data.organization_id === this.state.workspace.id && ['draft', 'converted'].includes(data.draft_status));
    valid(typeof data.required === 'boolean' && typeof data.confirmed === 'boolean' && SHA.test(data.draft_revision) && Array.isArray(data.blockers) && data.blockers.every(code => Object.hasOwn(blockers, code)));
    valid(typeof data.requested?.customer_name === 'string' && typeof data.requested.customer_reference === 'string');
    if (data.decision) valid(UUID.test(data.decision.id) && data.decision.draft_id === this.state.draftId && data.decision.organization_id === this.state.workspace.id && UUID.test(data.decision.customer_id) && data.decision.snapshot?.account?.id === data.decision.customer_id);
    valid(!data.confirmed || Boolean(data.decision));
    if (data.candidate) valid(SHA.test(data.candidate.reference_revision) && UUID.test(data.candidate.snapshot?.account?.id) && typeof data.candidate.snapshot.account.code === 'string' && typeof data.candidate.snapshot.account.display_name === 'string');
    return data;
  }
  async read(action) {
    if (!this.state.workspace || this.state.pending || this.state.operation) return false;
    this.abort?.abort(); const abort = this.abort = new AbortController(), version = ++this.version;
    this.update({ busy: true, message: '' });
    try { const patch = await action(abort.signal); if (!this.live(version, abort)) return false; this.update(patch); return true; }
    catch (error) { if (this.live(version, abort)) { this.update({ message: error.message }); if (error.status === 403) { this.context(null, null); await this.denied(); } } return false; }
    finally { if (this.live(version, abort)) this.update({ busy: false }); }
  }
  async list(page = 1, query = this.state.query, active = this.state.active) {
    return this.read(async signal => {
      const params = new URLSearchParams({ page, q: query, active: this.state.mode === 'draft' ? 'true' : active });
      const data = this.validatePage(await this.client.request(`${this.base()}?${params}`, { signal }));
      return { rows: data.results, count: data.count, page, query, active };
    });
  }
  async resolve(identifier) {
    return this.read(async signal => {
      const data = await this.client.request(`${this.base()}resolve/?${new URLSearchParams({ identifier })}`, { signal });
      valid(data?.requires_confirmation === true && Array.isArray(data.matches) && data.matches.length <= 2);
      const rows = data.matches.map(match => this.validateRecord(match.account));
      return { rows, count: rows.length, page: 1, query: identifier,
        message: rows.length ? 'Exact approved identifier evidence. Deliberately choose and confirm the account.' : 'No approved exact match. Search the directory; a display name or email domain does not confirm identity.' };
    });
  }
  async openAccount(id, sitePage = 1, aliasPage = 1) {
    valid(UUID.test(id));
    return this.read(async signal => {
      const path = `${this.base()}${id}/`;
      const [account, locations, aliases] = await Promise.all([
        this.client.request(path, { signal }), this.client.request(`${path}locations/?page=${sitePage}`, { signal }),
        this.state.mode === 'directory' ? this.client.request(`${path}aliases/?page=${aliasPage}`, { signal }) : Promise.resolve({ count: 0, results: [] }),
      ]);
      this.validateRecord(account); this.validatePage(locations, 'location', id); this.validatePage(aliases, 'alias', id);
      return { account, locations: locations.results, siteCount: locations.count, sitePage,
        aliases: aliases.results, aliasCount: aliases.count, aliasPage, locationId: null, candidate: null };
    });
  }
  async loadStatus() {
    if (this.state.mode !== 'draft') return;
    return this.read(async signal => {
      const status = this.validateStatus(await this.client.request(this.confirmationPath(), { signal }));
      return { status, candidate: null };
    });
  }
  async preview(locationId = null) {
    const account = this.state.account; if (!account || this.state.mode !== 'draft') return;
    return this.read(async signal => {
      const params = new URLSearchParams({ customer_id: account.id }); if (locationId) params.set('location_id', locationId);
      const status = this.validateStatus(await this.client.request(`${this.confirmationPath()}?${params}`, { signal }));
      valid(status.candidate.snapshot.account.id === account.id && (status.candidate.snapshot.location?.id ?? null) === locationId);
      return { status, candidate: status.candidate, locationId };
    });
  }
  async loadSnapshot() {
    if (this.state.mode !== 'snapshot') return;
    return this.read(async signal => {
      const data = await this.client.request(`${this.base()}orders/${this.state.orderId}/snapshot/`, { signal });
      valid(data?.order_id === this.state.orderId && data.organization_id === this.state.workspace.id);
      if (data.snapshot) valid(UUID.test(data.snapshot.id) && UUID.test(data.snapshot.decision_id) && UUID.test(data.snapshot.payload?.account?.id));
      return { snapshot: data };
    });
  }
  selectFile(file) {
    if (!this.canWrite()) return;
    const good = file && file.size > 0 && file.size <= 1048576 && /\.csv$/i.test(file.name);
    this.update({ file: good ? file : null, report: null, message: file && !good ? 'Choose a nonempty UTF-8 CSV, up to 1 MiB.' : '' });
  }
  validateReport(data) {
    valid(data?.organization_id === this.state.workspace.id && typeof data.valid === 'boolean' && Number.isSafeInteger(data.rows) && data.rows > 0 && data.rows <= 1000 && Number.isSafeInteger(data.error_count) && Array.isArray(data.errors) && data.errors.length <= 100 && data.valid === (data.error_count === 0));
    return data;
  }
  async validateFile() {
    if (!this.canWrite() || !this.state.file) return;
    const file = this.state.file;
    return this.read(async signal => {
      await this.client.refreshCsrf(signal);
      if (signal.aborted) return {};
      const form = new FormData(); form.append('file', file, file.name);
      try { return { report: this.validateReport(await this.client.request(`${this.base()}imports/validate/`, { method: 'POST', body: form, signal })) }; }
      catch (error) { if (error instanceof ApiError && error.status === 400 && error.details?.errors) return { report: this.validateReport(error.details) }; throw error; }
    });
  }
  async mutate(kind, path, body, { id = null, customer = null, file = null, method = 'POST', revision = null } = {}) {
    const confirmation = kind === 'confirmation';
    if (this.state.pending || this.state.busy || this.state.operation || (confirmation ? !this.canConfirm() : !this.canWrite())) return;
    const operation = { kind, path, body: structuredClone(body), id, customer, file, method, revision,
      key: confirmation ? body.operation_key : crypto.randomUUID(), workspace: this.state.workspace.id };
    this.update({ operation }); await this.send(operation);
  }
  canConfirm() { return ['admin', 'reviewer', 'processor'].includes(this.state.workspace?.role) && this.state.status?.draft_status === 'draft' && Boolean(this.state.candidate) && !this.state.busy && !this.state.pending && !this.state.operation; }
  async confirm() {
    if (!this.canConfirm()) return;
    const data = { operation_key: crypto.randomUUID(), customer_id: this.state.account.id,
      location_id: this.state.locationId, reference_revision: this.state.candidate.reference_revision,
      expected_draft_revision: this.state.status.draft_revision };
    await this.mutate('confirmation', this.confirmationPath(), data, { id: this.state.draftId });
  }
  async send(operation = this.state.operation) {
    if (!operation || this.state.pending || this.state.busy || operation.workspace !== this.state.workspace?.id) return;
    const version = this.version, epoch = this.epoch, abort = this.abort = new AbortController();
    this.update({ pending: true, message: 'Saving the deliberate reference decision…' });
    try {
      await this.client.refreshCsrf(abort.signal); if (!this.live(version, abort)) return;
      let body = operation.body;
      if (operation.file) { body = new FormData(); body.append('file', operation.file, operation.file.name); }
      const data = await this.client.request(operation.path, { method: operation.method, body, signal: abort.signal, idempotencyKey: operation.key, revision: operation.revision });
      if (!this.live(version, abort)) return;
      if (operation.kind === 'confirmation') valid(UUID.test(data?.id) && data.organization_id === operation.workspace && data.draft_id === operation.id && data.customer_id === operation.body.customer_id);
      else if (operation.kind === 'import') { this.validateReport(data); valid(data.operation_key === operation.key); }
      else { this.validateRecord(data, operation.kind, operation.customer); valid(data.operation_key === operation.key && (!operation.id || data.id === operation.id)); }
      const accountId = operation.kind === 'account' ? data.id : this.state.account?.id;
      this.update({ pending: false, operation: null, candidate: null, completed: operation,
        ...(operation.file ? { file: null, report: null } : {}) });
      if (operation.kind === 'confirmation') { this.update({ account: null, locations: [], locationId: null }); await this.saved(this.state.draftId); if (epoch === this.epoch) await this.loadStatus(); }
      else { await this.list(); if (epoch === this.epoch && accountId) await this.openAccount(accountId); }
      if (epoch === this.epoch) this.update({ message: operation.kind === 'import' ? `${data.replayed ? data.original_created : data.created} customer records recorded. The directory uses the selected state filter.` : 'Saved. Review the current recorded state; material reference changes require renewed draft confirmation.' });
    } catch (error) {
      if (!this.live(version, abort)) return;
      const uncertain = !(error instanceof ApiError) || error.status >= 500;
      if (!uncertain) this.update({ operation: null, candidate: null });
      if (operation.kind === 'import' && error.status === 400 && error.details?.errors) this.update({ report: this.validateReport(error.details) });
      this.update({ message: uncertain ? 'Outcome unconfirmed. Reconcile the saved operation or retry its identical request; do not start another write.' : operation.kind === 'import' && error.details?.errors ? 'Import rejected. Correct the listed record errors before creating accounts.' : error.message });
      if (error.status === 403) { this.context(null, null); await this.denied(); }
    } finally { if (this.live(version, abort)) this.update({ pending: false }); }
  }
  async reconcile() {
    const operation = this.state.operation;
    if (!operation || this.state.pending || this.state.busy) return;
    if (operation.kind === 'confirmation') return this.send(operation);
    const version = this.version, epoch = this.epoch, abort = this.abort = new AbortController();
    this.update({ pending: true });
    try {
      const data = await this.client.request(`${this.base()}operations/${operation.key}/`, { signal: abort.signal });
      if (!this.live(version, abort)) return;
      const expectedKind = operation.kind === 'import' ? 'account.import' : `${operation.kind}.${operation.id ? 'update' : 'create'}`;
      valid(data?.operation_key === operation.key && data.organization_id === operation.workspace && data.status === 'committed' && data.kind === expectedKind && data.response?.operation_key === operation.key);
      this.update({ pending: false, operation: null, completed: operation, ...(operation.file ? { file: null, report: null } : {}) });
      const id = this.state.account?.id; await this.list(); if (epoch === this.epoch && id) await this.openAccount(id);
      if (epoch === this.epoch) this.update({ message: 'Original operation confirmed by its durable receipt. Current data is refreshed separately.' });
    } catch (error) { if (this.live(version, abort)) { this.update({ message: error.status === 404 ? 'No committed receipt found yet. Retry only the identical saved request.' : error.message }); if (error.status === 403) { this.context(null, null); await this.denied(); } } }
    finally { if (this.live(version, abort)) this.update({ pending: false }); }
  }
}

const $ = id => document.getElementById(id);
const node = (tag, text = '') => { const result = document.createElement(tag); result.textContent = text; return result; };
const button = (text, disabled, click) => { const result = node('button', text); result.type = 'button'; result.disabled = disabled; result.addEventListener('click', click); return result; };
let displayedContext, displayedAccount, completedKey;
export function renderCustomers(controller) {
  const s = controller.state, directory = Boolean(s.workspace) && s.mode === 'directory', draft = Boolean(s.workspace) && s.mode === 'draft', snapshot = Boolean(s.workspace) && s.mode === 'snapshot';
  $('customers-screen').hidden = !directory; $('customer-confirmation').hidden = !draft; $('order-customer-snapshot').hidden = !snapshot;
  const key = `${s.generation}/${s.workspace?.id}/${s.mode}/${s.draftId}/${s.orderId}`;
  if (key !== displayedContext) {
    displayedContext = key; displayedAccount = null; completedKey = null;
    for (const id of ['customer-create-form', 'customer-edit-form', 'customer-location-form', 'customer-alias-form', 'customer-search-form', 'customer-lookup-form']) $(id).reset();
    $('customer-import-file').value = ''; $('customer-confirm-query').value = '';
  }
  const locked = s.pending || s.busy || Boolean(s.operation), admin = s.workspace?.role === 'admin';
  for (const root of ['customer-create-form', 'customer-edit-form', 'customer-location-form', 'customer-alias-form']) for (const field of $(root).elements) field.disabled = locked || !admin;
  $('customer-create-panel').hidden = !admin; $('customer-edit-form').hidden = !admin;
  $('customer-location-form').hidden = !admin; $('customer-alias-form').hidden = !admin;
  $('customer-details').hidden = !s.account || !directory;
  $('customer-message').textContent = s.message; $('customer-confirm-message').textContent = s.message;
  for (const prefix of ['customer', 'customer-confirm']) {
    $(`${prefix}-reconcile`).hidden = !s.operation; $(`${prefix}-retry`).hidden = !s.operation;
    $(`${prefix}-reconcile`).disabled = locked && (s.pending || s.busy); $(`${prefix}-retry`).disabled = s.pending || s.busy;
    $(`${prefix}-operation`).textContent = s.operation ? `Unconfirmed operation ${s.operation.key}` : '';
  }
  $('customer-refresh').disabled = locked; $('customer-search-button').disabled = locked;
  $('customer-rows').replaceChildren(...s.rows.map(account => {
    const row = document.createElement('tr');
    for (const value of [account.code, account.display_name, account.destination_id || 'Not provided', account.is_active ? 'Active' : 'Inactive']) row.append(node('td', value));
    const action = node('td'); action.append(button('Open account', locked, () => controller.openAccount(account.id))); row.append(action); return row;
  }));
  $('customer-page').textContent = `Page ${s.page} · ${s.count} accounts`;
  $('customer-previous').disabled = locked || s.page <= 1; $('customer-next').disabled = locked || s.page * 50 >= s.count;
  const account = s.account;
  if (account && directory) {
    $('customer-detail-heading').textContent = `${account.code} · ${account.display_name}`;
    const version = `${account.id}/${account.updated_at}`;
    if (version !== displayedAccount) {
      displayedAccount = version;
      $('customer-edit-name').value = account.display_name; $('customer-edit-destination').value = account.destination_id;
      $('customer-edit-location-required').checked = account.requires_location; $('customer-edit-active').checked = account.is_active;
    }
  }
  $('customer-location-rows').replaceChildren(...s.locations.map(site => {
    const row = node('tr'); for (const value of [site.code, site.display_name, site.destination_id || 'Not provided', site.is_active ? 'Active' : 'Inactive']) row.append(node('td', value));
    const action = node('td'); action.append(button(site.is_active ? 'Deactivate' : 'Reactivate', locked || !admin,
      () => controller.mutate('location', `${controller.base()}${site.customer_id}/locations/${site.id}/`, { is_active: !site.is_active }, { id: site.id, customer: site.customer_id, method: 'PATCH', revision: site.revision })));
    row.append(action); return row;
  }));
  $('customer-site-page').textContent = `Location page ${s.sitePage} · ${s.siteCount} locations`;
  $('customer-site-previous').disabled = locked || s.sitePage <= 1; $('customer-site-next').disabled = locked || s.sitePage * 50 >= s.siteCount;
  $('customer-alias-rows').replaceChildren(...s.aliases.map(alias => {
    const item = node('li'); item.append(node('p', `${alias.value} · ${alias.is_active ? 'Approved' : 'Retired'} · source: ${alias.provenance} · approved by ${alias.approved_by_id} at ${alias.approved_at}${alias.retirement_reason ? ` · withdrawal: ${alias.retirement_reason}` : ''}`));
    if (alias.is_active && admin) {
      const label = node('label', 'Withdrawal reason'); const input = document.createElement('input'); input.maxLength = 500; input.value = s.retirementReasons[alias.id] ?? ''; input.disabled = locked;
      input.addEventListener('input', () => { s.retirementReasons[alias.id] = input.value; }); label.append(input); item.append(label,
        button('Retire this approval', locked, () => controller.mutate('alias', `${controller.base()}${alias.customer_id}/aliases/${alias.id}/retire/`, { retirement_reason: input.value }, { id: alias.id, customer: alias.customer_id, revision: alias.revision })));
    } return item;
  }));
  $('customer-alias-page').textContent = `Alias page ${s.aliasPage} · ${s.aliasCount} approvals`;
  $('customer-alias-previous').disabled = locked || s.aliasPage <= 1; $('customer-alias-next').disabled = locked || s.aliasPage * 50 >= s.aliasCount;
  $('customer-import-file').disabled = locked || !admin; if (!s.file) $('customer-import-file').value = '';
  $('customer-import-validate').disabled = !s.file || locked || !admin;
  $('customer-import-create').disabled = !s.file || !s.report?.valid || locked || !admin;
  $('customer-import-summary').textContent = s.report ? `${s.report.rows} records · ${s.report.error_count} errors · ${s.report.created} created${s.report.valid ? ' · validation ready' : ' · correct every error before import'}` : '';
  $('customer-import-errors').replaceChildren(...(s.report?.errors ?? []).map(error => node('li', `Record ${error.row}, ${error.field}: ${error.message}`)));
  if (s.completed && completedKey !== s.completed.key) {
    completedKey = s.completed.key;
    const form = { account: 'customer-create-form', location: 'customer-location-form', alias: 'customer-alias-form' }[s.completed.kind];
    if (!s.completed.id && form) $(form).reset();
  }
  const status = s.status;
  $('customer-confirm-state').textContent = !status ? 'Load the current saved customer decision.' : status.confirmed ? 'Customer account confirmed. Commercial checks and destination acceptance remain not checked.' : status.required ? 'Blocking: this incoming order requires a confirmed customer account.' : 'No confirmed account recorded. Legacy structural readiness does not establish customer-specific handoff readiness.';
  $('customer-confirm-current').textContent = status?.decision ? `Recorded: ${status.decision.snapshot.account.code} · ${status.decision.snapshot.account.display_name} · destination ${status.decision.snapshot.account.destination_id || 'not provided'} · ${status.decision.snapshot.location ? `site ${status.decision.snapshot.location.code}` : 'no delivery site'} · confirmed by ${status.decision.actor_id} at ${status.decision.created_at}` : '';
  $('customer-confirm-blockers').replaceChildren(...(status?.blockers ?? []).map(code => node('li', blockers[code]?.[0] ?? code)));
  $('customer-confirm-refresh').disabled = locked;
  $('customer-confirm-controls').hidden = status?.draft_status === 'converted' || !['admin', 'reviewer', 'processor'].includes(s.workspace?.role);
  $('customer-confirm-search').disabled = locked; $('customer-confirm-exact').disabled = locked;
  $('customer-confirm-accounts').replaceChildren(...s.rows.filter(row => row.is_active).map(row => button(`${row.code} · ${row.display_name} · destination ${row.destination_id || 'not provided'}`, locked, () => controller.openAccount(row.id))));
  $('customer-confirm-account-page').textContent = `Account page ${s.page} · ${s.count} matches`;
  $('customer-confirm-previous').disabled = locked || s.page <= 1; $('customer-confirm-next').disabled = locked || s.page * 50 >= s.count;
  $('customer-confirm-selection').hidden = !account || !draft;
  $('customer-confirm-selected').textContent = account ? `Proposed account: ${account.code} · ${account.display_name}` : '';
  $('customer-site-choice').replaceChildren(new Option('No site selected', ''), ...s.locations.map(site => { const option = new Option(`${site.code} · ${site.display_name} · ${site.destination_id || 'destination not provided'}${site.is_active ? '' : ' · inactive'}`, site.id); option.disabled = !site.is_active; return option; }));
  $('customer-site-choice').value = s.locationId ?? ''; $('customer-site-choice').disabled = locked;
  $('customer-confirm-site-page').textContent = `Location page ${s.sitePage} · ${s.siteCount} locations`;
  $('customer-confirm-site-previous').disabled = locked || s.sitePage <= 1; $('customer-confirm-site-next').disabled = locked || s.sitePage * 50 >= s.siteCount;
  $('customer-confirm-preview').disabled = locked || !account; $('customer-confirm-save').disabled = !controller.canConfirm(); $('customer-confirm-cancel').disabled = locked;
  $('customer-confirm-proposal').textContent = s.candidate ? `Preview of saved request: ${status.requested.customer_name || '(unresolved)'} / ${status.requested.customer_reference || '(no reference)'}. Confirming applies customer name “${s.candidate.snapshot.account.display_name}” and account ${s.candidate.snapshot.account.code}${s.candidate.snapshot.location ? ` / site ${s.candidate.snapshot.location.code}` : ''}. Original text is retained in the decision history.` : 'Selection is proposed only. Preview current reference data before confirming.';
  const frozen = s.snapshot?.snapshot;
  $('order-customer-message').textContent = s.message; $('order-customer-refresh').disabled = locked;
  $('order-customer-summary').textContent = !s.snapshot ? 'Loading recorded customer snapshot…' : frozen ? `Frozen account ${frozen.payload.account.code} · ${frozen.payload.account.display_name} · destination ${frozen.payload.account.destination_id || 'not provided'} · ${frozen.payload.location ? `site ${frozen.payload.location.code} / ${frozen.payload.location.destination_id || 'destination not provided'}` : 'no delivery site'}. Original requested name: ${frozen.payload.source_requested?.customer_name ?? frozen.payload.requested.customer_name}. Destination acceptance remains not checked.` : 'No confirmed customer snapshot exists for this legacy order. Generic CSV does not establish destination compatibility.';
}
