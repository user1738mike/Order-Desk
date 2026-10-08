import { ApiError } from './api.js';
import { validateReasons } from './orders-api.js';

export class DraftController {
  constructor(api, render = () => {}, denied = async () => {}) {
    this.api = api; this.render = render; this.denied = denied; this.version = 0;
    this.state = this.empty();
  }
  empty() {
    return { workspace: null, generation: null, draftId: null, rows: [], count: 0, page: 1,
      draft: null, lines: [], lineCount: 0, linePage: 1, review: null, readiness: null,
      errors: {}, loading: false, linesLoading: false, converting: false,
      result: null, uncertain: false, conflict: [], assessedAt: null, message: '', revision: null, dirty: false };
  }
  update(patch) { Object.assign(this.state, patch); this.render(this.state); }
  cancel() { this.version += 1; this.abort?.abort(); this.lineAbort?.abort(); }
  context(workspace, generation) {
    if (workspace?.id === this.state.workspace?.id && generation === this.state.generation) {
      this.state.workspace = workspace;
      return;
    }
    this.cancel(); this.state = { ...this.empty(), workspace, generation }; this.render(this.state);
  }
  live(version, abort) { return version === this.version && !abort.signal.aborted; }
  error(error) { return error instanceof ApiError && error.status === 404 ? 'Draft not found or unavailable in this workspace.' : error.message || 'Unable to load this panel. Try again.'; }
  async list(number = 1) {
    if (!this.state.workspace) return;
    this.cancel(); const version = this.version; const abort = this.abort = new AbortController();
    this.update({ draftId: null, draft: null, rows: [], count: 0, page: number, loading: true, errors: {}, result: null, uncertain: false, readiness: null, lines: [], review: null, converting: false, message: '' });
    try {
      const data = await this.api.list(this.state.workspace.id, number, abort.signal);
      if (this.live(version, abort)) this.update({ rows: data.results, count: data.count });
    } catch (error) {
      if (!this.live(version, abort)) return;
      if (error instanceof ApiError && error.status === 403) await this.denied(false);
      else this.update({ errors: { list: this.error(error) } });
    } finally { if (this.live(version, abort)) this.update({ loading: false }); }
  }
  async open(id, preserveOutcome = false) {
    if (!this.state.workspace) return;
    const { result, uncertain, conflict, message } = this.state;
    this.cancel(); const version = this.version; const abort = this.abort = new AbortController();
    this.update({ draftId: id, draft: null, lines: [], review: null, readiness: null, assessedAt: null,
      errors: {}, loading: true, linePage: 1, lineCount: 0, rows: [], converting: false, revision: null,
      result: preserveOutcome ? result : null, uncertain: preserveOutcome && uncertain,
      conflict: preserveOutcome ? conflict : [], message: preserveOutcome ? message : '' });
    const workspace = this.state.workspace.id;
    try {
      let before;
      try { before = await this.api.revision(workspace, id, abort.signal); }
      catch (error) {
        if (error instanceof ApiError && [403, 404].includes(error.status)) throw error;
        if (!this.live(version, abort)) return;
        this.update({ errors: { revision: 'Draft revision unavailable. Refresh before editing or converting.' } });
      }
      if (!this.live(version, abort)) return;
      const draft = await this.api.detail(workspace, id, abort.signal);
      if (!this.live(version, abort)) return;
      this.update({ draft });
      await Promise.all(['review', 'readiness', 'lines'].map(async panel => {
        try {
          const data = panel === 'lines' ? await this.api.lines(workspace, id, 1, abort.signal) : await this.api[panel](workspace, id, abort.signal);
          if (!this.live(version, abort)) return;
          this.update(panel === 'lines' ? { lines: data.results, lineCount: data.count } : panel === 'readiness' ? { readiness: data, assessedAt: new Date().toISOString() } : { review: data });
        } catch (error) {
          if (!this.live(version, abort)) return;
          if (error instanceof ApiError && error.status === 403) { this.cancel(); this.update({ draft: null, lines: [], readiness: null, review: null }); await this.denied(false); }
          else this.update({ errors: { ...this.state.errors, [panel]: this.error(error) } });
        }
      }));
      if (!this.live(version, abort)) return;
      const after = await this.api.revision(workspace, id, abort.signal);
      if (!this.live(version, abort)) return;
      if (before === after) this.update({ revision: after });
      else this.update({ errors: { ...this.state.errors, revision: 'The draft changed while loading. Refresh before editing or converting.' } });
    } catch (error) {
      if (!this.live(version, abort)) return;
      if (error instanceof ApiError && error.status === 403) await this.denied(false);
      else this.update({ errors: { ...this.state.errors, [this.state.draft ? 'revision' : 'detail']: this.error(error) } });
    } finally { if (this.live(version, abort)) this.update({ loading: false }); }
  }
  async lines(number) {
    if (!this.state.draft) return;
    this.lineAbort?.abort(); const abort = this.lineAbort = new AbortController(); const version = this.version;
    this.update({ lines: [], linePage: number, linesLoading: true, errors: { ...this.state.errors, lines: null } });
    try {
      const data = await this.api.lines(this.state.workspace.id, this.state.draftId, number, abort.signal);
      if (this.live(version, abort)) this.update({ lines: data.results, lineCount: data.count });
    } catch (error) {
      if (!this.live(version, abort)) return;
      if (error instanceof ApiError && error.status === 403) await this.denied(false);
      else this.update({ errors: { ...this.state.errors, lines: this.error(error) } });
    } finally { if (this.live(version, abort)) this.update({ linesLoading: false }); }
  }
  canConvert() {
    const s = this.state;
    return Boolean(s.workspace?.role === 'admin' && s.draft && s.revision && !s.dirty && !s.loading && !s.linesLoading && !s.converting &&
      (s.draft.status === 'converted' || s.uncertain || (s.readiness?.ready_to_convert && s.review && !s.errors.lines && s.draft.line_count === s.readiness.line_count)));
  }
  async convert() {
    if (!this.canConvert()) return;
    const version = this.version; const abort = this.abort; const workspace = this.state.workspace.id; const id = this.state.draftId;
    this.update({ converting: true, message: '', conflict: [] });
    try {
      const result = await this.api.convert(workspace, id, abort.signal, this.state.revision);
      if (!this.live(version, abort)) return;
      this.update({ result, uncertain: false, message: result.replayed ? 'Existing internal purchase order confirmed.' : 'Internal purchase order created.' });
      await this.open(id, true);
    } catch (error) {
      if (!this.live(version, abort)) return;
      if (error instanceof ApiError && error.status === 403) {
        this.update({ message: 'Conversion is not permitted. Workspace access and role will be rechecked.' });
        await this.denied(true);
      } else if (error instanceof ApiError && [409, 412].includes(error.status)) {
        let conflict = [];
        try { conflict = validateReasons(error.details?.blocking_reasons ?? []); } catch {}
        this.update({ conflict, uncertain: false, message: error.details?.detail === 'purchase_order_number_conflict' ? 'The reserved purchase-order number conflicts with another order. Contact your administrator.' : 'The draft changed or is not ready. Review the refreshed blockers.' });
        await this.open(id, true);
      } else if (!(error instanceof ApiError) || error.status >= 500) {
        this.update({ uncertain: true, message: 'Conversion outcome is unconfirmed. Check the result using the same repeat-safe request; it may create the order if no result was committed.' });
      } else this.update({ message: this.error(error) });
    } finally { if (this.live(version, abort)) this.update({ converting: false }); }
  }
}
