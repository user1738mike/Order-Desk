import { ApiError } from './api.js';

export class DeskController {
  constructor(api, render = () => {}) {
    this.api = api;
    this.render = render;
    this.epoch = 0;
    this.state = { phase: 'loading', busy: false, message: '', workspaces: [], workspace: null,
      workspacePage: 1, moreWorkspaces: false, items: [], count: 0, page: 1,
      query: '', activity: '', catalogBusy: false, catalogError: false, retryAction: 'start' };
  }

  update(patch) { Object.assign(this.state, patch); this.render(this.state); }

  invalidate() {
    this.epoch += 1;
    this.catalogAbort?.abort();
    this.update({ generation: this.epoch, items: [], count: 0, catalogBusy: false, catalogError: false });
    return this.epoch;
  }

  async start() {
    const epoch = this.invalidate();
    this.update({ phase: 'loading', busy: false, message: '', workspace: null, workspaces: [], retryAction: 'start' });
    try {
      const list = await this.api.request('/api/v1/workspaces/');
      const current = await this.api.request('/api/v1/workspaces/current/');
      if (epoch !== this.epoch) return;
      this.update({ phase: 'desk', workspaces: list.results, workspacePage: 1,
        moreWorkspaces: Boolean(list.next), workspace: current.workspace,
        page: 1, query: '', activity: '', message: list.count ? '' : 'You have no active workspaces. Contact your administrator.' });
      if (current.workspace) await this.loadCatalogue();
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.update({ phase: error instanceof ApiError && error.status === 403 ? 'login' : 'error',
        message: error instanceof ApiError && error.status === 403 ? '' : 'Unable to open your workspace. Try again.' });
    }
  }

  async login(email, password) {
    this.update({ busy: true, message: '' });
    try { await this.api.login(email, password); await this.start(); }
    catch (error) { this.update({ message: error instanceof ApiError ? error.message : 'Unable to sign in. Check your connection and try again.' }); }
    finally { this.update({ busy: false }); }
  }

  async logout() {
    this.invalidate();
    this.update({ busy: true, workspace: null, message: '' });
    try {
      await this.api.logout();
      this.update({ phase: 'login', workspaces: [] });
    } catch {
      // Do not claim logout succeeded if the server did not confirm it.
      this.update({ phase: 'error', retryAction: 'logout', message: 'Sign out was not confirmed. Try again.' });
    } finally { this.update({ busy: false }); }
  }

  async moreWorkspaces() {
    const epoch = this.epoch;
    this.update({ busy: true, message: '' });
    try {
      const page = this.state.workspacePage + 1;
      const list = await this.api.request(`/api/v1/workspaces/?page=${page}`);
      if (epoch !== this.epoch) return;
      this.update({ workspaces: [...this.state.workspaces, ...list.results], workspacePage: page, moreWorkspaces: Boolean(list.next) });
    } catch (error) {
      if (epoch === this.epoch) {
        if (error instanceof ApiError && error.status === 403) await this.start();
        else this.update({ message: 'Unable to load more workspaces. Try again.' });
      }
    } finally { if (epoch === this.epoch) this.update({ busy: false }); }
  }

  async selectWorkspace(id) {
    const epoch = this.invalidate();
    this.update({ workspace: null, busy: true, message: '', page: 1, query: '', activity: '' });
    try {
      // Revalidate session mutations, including another tab's CSRF rotation.
      await this.api.refreshCsrf();
      const data = await this.api.request('/api/v1/workspaces/current/', {
        method: id ? 'PUT' : 'DELETE', ...(id ? { body: { workspace_id: id } } : {}),
      });
      if (epoch !== this.epoch) return;
      this.update({ workspace: data?.workspace ?? null });
      if (data?.workspace) await this.loadCatalogue();
    } catch (error) {
      if (epoch !== this.epoch) return;
      if (error instanceof ApiError && error.status === 403) {
        await this.startWithoutSelection();
        this.update({ message: 'Workspace access changed. Sign in or choose an available workspace.' });
      } else this.update({ message: 'Unable to select that workspace. Try again.' });
    } finally { if (epoch === this.epoch) this.update({ busy: false }); }
  }

  search(query, activity) {
    this.update({ query: query.trim(), activity, page: 1 });
    return this.loadCatalogue();
  }

  goToPage(page) {
    this.update({ page });
    return this.loadCatalogue();
  }

  async loadCatalogue() {
    if (!this.state.workspace) return;
    this.catalogAbort?.abort();
    const abort = new AbortController();
    this.catalogAbort = abort;
    const epoch = this.epoch;
    const { workspace, query, activity, page } = this.state;
    const params = new URLSearchParams({ page: String(page) });
    if (query) params.set('q', query);
    if (activity) params.set('is_active', activity);
    this.update({ items: [], count: 0, catalogBusy: true, catalogError: false, message: '' });
    try {
      const data = await this.api.request(`/api/v1/workspaces/${encodeURIComponent(workspace.id)}/catalog/items/?${params}`, { signal: abort.signal });
      if (epoch !== this.epoch || abort.signal.aborted) return;
      this.update({ items: data.results, count: data.count });
    } catch (error) {
      if (epoch !== this.epoch || abort.signal.aborted) return;
      if (error instanceof ApiError && error.status === 403) {
        // Erase revoked data before discovering whether the session still exists.
        // Never auto-reopen a stale workspace preference after denial.
        await this.startWithoutSelection();
      } else this.update({ catalogError: true, message: error instanceof ApiError ? error.message : 'Unable to load the catalogue. Check your connection and try again.' });
    } finally {
      if (epoch === this.epoch && !abort.signal.aborted) this.update({ catalogBusy: false });
    }
  }

  async startWithoutSelection() {
    const epoch = this.invalidate();
    this.update({ workspace: null, busy: true });
    try {
      const list = await this.api.request('/api/v1/workspaces/');
      if (epoch !== this.epoch) return;
      this.update({ phase: 'desk', workspaces: list.results, workspacePage: 1, moreWorkspaces: Boolean(list.next),
        message: list.count ? 'Workspace access changed. Choose an available workspace.' : 'Workspace access changed. You have no active workspaces. Contact your administrator.' });
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.update({ phase: error instanceof ApiError && error.status === 403 ? 'login' : 'error', workspaces: [], message: 'Your session or workspace is unavailable. Sign in again or retry.' });
    } finally { if (epoch === this.epoch) this.update({ busy: false }); }
  }
}
