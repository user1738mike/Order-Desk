export class ApiError extends Error {
  constructor(status, details) {
    const messages = Object.entries(details ?? {}).flatMap(([key, value]) =>
      (Array.isArray(value) ? value : [value]).map(message =>
        `${key === 'detail' || key === 'non_field_errors' ? '' : `${key}: `}${message}`));
    super(messages.join(' ') || 'The request could not be completed.');
    this.status = status;
    this.details = details;
  }
}

export class ApiClient {
  constructor(fetcher = globalThis.fetch.bind(globalThis)) {
    this.fetcher = fetcher;
    this.csrf = null;
  }

  async request(path, { method = 'GET', body, signal, withStatus = false } = {}) {
    // Accept only relative API paths. Never follow server pagination URLs.
    if (!path.startsWith('/api/v1/') || path.includes('\\')) throw new Error('Invalid API path.');
    const headers = { Accept: 'application/json' };
    if (method !== 'GET') {
      if (!this.csrf) await this.refreshCsrf(signal);
      headers['X-CSRFToken'] = this.csrf;
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await this.fetcher(path, {
      method, headers, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      signal, ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(response.status, data);
    return withStatus ? { data, status: response.status } : data;
  }

  async refreshCsrf(signal) {
    const data = await this.request('/api/v1/auth/csrf/', { signal });
    this.csrf = data.csrf_token;
  }

  async login(email, password) {
    // Fetch before every attempt, including after logout or another tab's login.
    await this.refreshCsrf();
    const data = await this.request('/api/v1/auth/login/', { method: 'POST', body: { email, password } });
    this.csrf = data.csrf_token;
  }

  async logout() {
    await this.refreshCsrf();
    await this.request('/api/v1/auth/logout/', { method: 'POST' });
    this.csrf = null;
  }
}
