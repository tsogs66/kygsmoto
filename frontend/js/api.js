// Thin fetch wrapper: attaches the session token and normalises API errors.

const TOKEN_KEY = 'kygs_token';

export const session = {
  get token() { return localStorage.getItem(TOKEN_KEY) || ''; },
  set token(value) {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  },
  user: null,
  permissions: [],
  settings: {},
  can(permission) { return this.permissions.includes(permission); },
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body, options = {}) {
  const headers = {};
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 401 && !options.allowAnonymous) {
    session.token = '';
    window.dispatchEvent(new CustomEvent('kygs:signed-out'));
    throw new ApiError('Your session has ended. Please sign in again.', 401);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (payload && payload.detail) {
        detail = typeof payload.detail === 'string'
          ? payload.detail
          : JSON.stringify(payload.detail);
      }
    } catch { /* Non-JSON error body; keep the status message. */ }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return null;
  return response.json();
}

const qs = (params = {}) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.append(key, value);
  }
  const string = search.toString();
  return string ? `?${string}` : '';
};

export const api = {
  get:   (path, params)  => request('GET', path + qs(params)),
  post:  (path, body)    => request('POST', path, body ?? {}),
  patch: (path, body)    => request('PATCH', path, body ?? {}),
  put:   (path, body)    => request('PUT', path, body ?? {}),
  del:   (path)          => request('DELETE', path),

  login: (username, password) =>
    request('POST', '/api/auth/login', { username, password }, { allowAnonymous: true }),

  // CSV endpoints stream a file, so they need the token on a manual fetch.
  async download(path, params) {
    const response = await fetch(path + qs(params), {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    if (!response.ok) throw new ApiError('Export failed', response.status);

    const blob = await response.blob();
    const disposition = response.headers.get('content-disposition') || '';
    const match = disposition.match(/filename="?([^"]+)"?/);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = match ? match[1] : 'export.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },
};
