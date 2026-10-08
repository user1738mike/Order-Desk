import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiError } from '../assets/desk/api.js';

const reply = (data, status = 200) => ({ status, ok: status < 400, json: async () => data });
test('login uses cookie credentials, bootstrap CSRF then rotated token for selection', async () => {
  const calls = [];
  const api = new ApiClient(async (url, options) => {
    calls.push({ url, ...options });
    return reply(url.endsWith('csrf/') ? { csrf_token: 'before' } : url.endsWith('login/') ? { csrf_token: 'rotated' } : { workspace: null });
  });
  await api.login('member@example.test', '  preserve whitespace  ');
  await api.request('/api/v1/workspaces/current/', { method: 'PUT', body: { workspace_id: 'a' } });
  assert.equal(calls[1].headers['X-CSRFToken'], 'before');
  assert.equal(calls[2].headers['X-CSRFToken'], 'rotated');
  assert.equal(JSON.parse(calls[1].body).password, '  preserve whitespace  ');
  for (const call of calls) {
    assert.equal(call.credentials, 'same-origin');
    assert.equal(call.cache, 'no-store');
    assert.equal(call.redirect, 'error');
  }
});
test('logout refreshes CSRF and drops in-memory token after 204', async () => {
  const calls = [];
  const api = new ApiClient(async (url, options) => {
    calls.push({ url, ...options });
    return url.endsWith('csrf/') ? reply({ csrf_token: 'fresh' }) : reply(null, 204);
  });
  api.csrf = 'stale';
  await api.logout();
  assert.equal(calls[1].headers['X-CSRFToken'], 'fresh');
  assert.equal(api.csrf, null);
});
test('structured API errors retain status and helpful field messages', async () => {
  const api = new ApiClient(async () => reply({ email: ['Invalid email.'] }, 400));
  await assert.rejects(api.request('/api/v1/workspaces/'), error => error instanceof ApiError && error.status === 400 && error.message === 'email: Invalid email.');
});
test('untrusted paths never receive cookies or CSRF', async () => {
  const api = new ApiClient(() => assert.fail('fetch must not run'));
  for (const path of ['https://other.test/api/v1/', '//other.test/api/v1/', '/api/v1/\\other']) {
    await assert.rejects(api.request(path), /Invalid API path/);
  }
});
