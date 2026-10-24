import { ApiError } from './api.js';
import { UUID } from './orders-api.js';

const HEX = /^[0-9a-f]{64}$/;
const STATES = ['exact', 'already_attached', 'inactive', 'no_match', 'empty_sku', 'unsupported_sku', 'ambiguous'];
const ATTACHMENTS = ['none', 'current', 'source_changed', 'inactive', 'snapshot_changed', 'unavailable'];
// Python str.strip uses Unicode whitespace plus the four separator controls;
// JavaScript trim additionally strips BOM and omits NEL/separator controls.
const trimSku = source => source.replace(/^[\p{White_Space}\u001c-\u001f]+|[\p{White_Space}\u001c-\u001f]+$/gu, '');
const boundedSku = source => [...source].slice(0, 4096).join('');
const valid = condition => { if (!condition) throw new Error('Catalogue assessment unavailable. Reload current draft values.'); };

export class MatchingController {
  constructor(client, drafts, render = () => {}, denied = async () => {}) { this.client = client; this.drafts = drafts; this.render = render; this.denied = denied; this.version = 0; this.state = this.empty(); }
  empty() { return { rows: [], revision: null, busy: false, pending: false, blocked: false, uncertain: false, message: '' }; }
  update(patch) { Object.assign(this.state, patch); this.drafts.state.matchingPending = this.state.pending; this.render(this.state); }
  context() {
    const s = this.drafts.state; const key = `${s.generation}/${s.workspace?.id ?? ''}/${s.draftId ?? ''}/${s.revision ?? ''}/${s.linePage}/${s.dirty}`;
    if (key !== this.key) { this.key = key; this.version++; this.abort?.abort(); this.state = this.empty(); this.drafts.state.matchingPending = false; this.render(this.state); }
  }
  usable() { const s = this.drafts.state; return s.workspace && s.draft && s.revision && !s.loading && !s.linesLoading && !s.converting && !s.dirty && !this.state.pending; }
  path() { const s = this.drafts.state; valid(UUID.test(s.workspace?.id) && UUID.test(s.draftId)); return `/api/v1/workspaces/${s.workspace.id}/draft-orders/${s.draftId}/`; }
  live(version, abort) { return version === this.version && !abort.signal.aborted; }
  validate(data) {
    const s = this.drafts.state;
    valid(data && data.id === s.draftId && data.organization_id === s.workspace.id && data.rule_version === 'exact-sku-v1' && data.draft_revision === s.revision && HEX.test(data.draft_revision));
    valid(Number.isSafeInteger(data.count) && data.count >= 0 && Array.isArray(data.results) && data.results.length <= 50);
    const seen = new Set();
    for (const row of data.results) {
      const line = s.lines.find(item => item.id === row.line_id);
      valid(line && !seen.has(row.line_id) && row.position === line.position && row.source_sku === boundedSku(line.requested_sku) && typeof row.source_truncated === 'boolean' && row.normalized_sku === boundedSku(trimSku(line.requested_sku)) && STATES.includes(row.state)); seen.add(row.line_id);
      valid(row.attachment && ATTACHMENTS.includes(row.attachment.state) && row.attachment.id === line.catalogue_item_id);
      valid(row.checks?.unit === 'not_modeled' && row.checks?.pricing === 'not_modeled' && row.checks?.quantity === 'not_assessed');
      const item = row.candidate;
      if (item !== null) valid(UUID.test(item?.id) && item.sku === row.normalized_sku && typeof item.description === 'string' && [...item.description].length <= 4096 && typeof item.description_truncated === 'boolean' && typeof item.is_active === 'boolean' && HEX.test(item.revision));
      valid(!['exact', 'already_attached'].includes(row.state) || item?.is_active === true);
      valid(row.state !== 'inactive' || item?.is_active === false);
    }
    return data;
  }
  async load() {
    if (!this.usable() || this.state.busy || this.state.uncertain) return;
    const version = this.version; const abort = this.abort = new AbortController();
    this.update({ rows: [], revision: null, busy: true, blocked: false, message: 'Assessing exact requested SKUs…' });
    try {
      const data = await this.client.request(`${this.path()}suggestions/?page=${this.drafts.state.linePage}`, { signal: abort.signal });
      if (!this.live(version, abort)) return;
      this.validate(data); this.update({ rows: data.results, revision: data.draft_revision, message: 'Suggestions only. Units and prices were not checked.' });
    } catch (error) {
      if (!this.live(version, abort)) return;
      this.update({ blocked: true, message: error.message }); if (error instanceof ApiError && error.status === 403) await this.denied(false);
    } finally { if (this.live(version, abort)) this.update({ busy: false }); }
  }
  canAccept(row) { const s = this.drafts.state; return this.usable() && !this.state.busy && !this.state.blocked && !this.state.uncertain && this.state.revision === s.revision && ['admin', 'reviewer', 'processor'].includes(s.workspace.role) && s.draft.status === 'draft' && row.state === 'exact' && row.attachment.state === 'none' && row.candidate?.is_active; }
  async accept(row) {
    if (!this.canAccept(row)) return;
    const version = this.version; const abort = this.abort = new AbortController(); const s = this.drafts.state; const draftId = s.draftId;
    this.update({ pending: true, message: 'Confirming the current exact catalogue identity…' });
    try {
      await this.client.refreshCsrf(abort.signal);
      if (!this.live(version, abort)) return;
      const data = await this.client.request(`${this.path()}lines/${row.line_id}/accept-suggestion/`, { method: 'POST', body: { catalogue_item_id: row.candidate.id, rule_version: 'exact-sku-v1', source_sku: row.normalized_sku, catalogue_revision: row.candidate.revision }, revision: this.state.revision, signal: abort.signal });
      if (!this.live(version, abort)) return;
      valid(data.id === row.line_id && data.order_id === draftId && data.organization_id === s.workspace.id && data.catalogue_item_id === row.candidate.id && data.catalogue_sku_snapshot === row.candidate.sku);
      this.update({ pending: false }); await this.drafts.open(draftId, true); this.context(); await this.load();
    } catch (error) {
      if (!this.live(version, abort)) return;
      if (error instanceof ApiError && [409, 412].includes(error.status)) this.update({ blocked: true, message: 'Draft or catalogue changed. Reload and compare current values before accepting again.' });
      else if (error instanceof ApiError && error.status === 403) { this.update({ blocked: true, message: 'Acceptance is not permitted. Access will be rechecked.' }); await this.denied(true); }
      else if (!(error instanceof ApiError) || error.status >= 500) this.update({ uncertain: true, blocked: true, message: 'Attachment outcome is unconfirmed. Reload the draft to check its actual catalogue attachment before another acceptance.' });
      else this.update({ blocked: true, message: error.message });
    } finally { if (this.live(version, abort)) this.update({ pending: false }); }
  }
  async reload() {
    if (this.state.pending || !this.drafts.state.draftId) return;
    const id = this.drafts.state.draftId; await this.drafts.open(id, true); this.context(); this.update({ uncertain: false, blocked: false }); await this.load();
  }
}

const $ = id => document.getElementById(id);
export function renderMatching(controller) {
  const s = controller.state; const draft = controller.drafts.state;
  $('catalogue-suggestions').hidden = !draft.draft;
  $('matching-load').disabled = !controller.usable() || s.busy || s.uncertain;
  $('matching-reload').hidden = !s.blocked && !s.uncertain; $('matching-reload').disabled = s.pending || draft.dirty;
  $('matching-message').textContent = s.message;
  $('matching-results').replaceChildren(...s.rows.map(row => {
    const article = document.createElement('article'); const title = document.createElement('h4'); title.textContent = `Line ${row.position}: ${row.source_sku || 'No requested SKU'}`; article.append(title);
    const evidence = document.createElement('p'); evidence.textContent = `exact-sku-v1 · ${row.state.replaceAll('_', ' ')} · outer whitespace trim; case, punctuation and leading zeros preserved. Current attachment: ${row.attachment.state.replaceAll('_', ' ')}.`; article.append(evidence);
    if (row.candidate) { const item = document.createElement('p'); item.textContent = `${row.candidate.sku} · ${row.candidate.description}${row.candidate.description_truncated ? '…' : ''} · ${row.candidate.is_active ? 'Active' : 'Inactive'} · ${row.candidate.id}`; article.append(item); }
    const checks = document.createElement('p'); checks.textContent = 'Units and prices: not modeled in catalogue. Quantity: not assessed. Manual catalogue selection remains available.'; article.append(checks);
    if (row.state === 'exact' && row.attachment.state === 'none' && ['admin', 'reviewer', 'processor'].includes(draft.workspace?.role)) { const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Accept exact suggestion'; button.dataset.line = row.line_id; button.disabled = !controller.canAccept(row); button.addEventListener('click', () => controller.accept(row)); article.append(button); }
    return article;
  }));
}
