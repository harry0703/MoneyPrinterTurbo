// Client for /api/v1/motion. MoneyPrinterTurbo can require its own server access key (app.api_key in
// config.toml); when it does, the studio asks for it once per tab and sends it as x-api-key.
// That server key is not the AI provider key, which lives only in React state.
const SERVER_KEY = 'motion.serverKey';

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export const serverKey = {
  get: () => sessionStorage.getItem(SERVER_KEY) || '',
  set: (value) => (value ? sessionStorage.setItem(SERVER_KEY, value) : sessionStorage.removeItem(SERVER_KEY)),
};

async function request(path, { method = 'GET', body, raw = false } = {}) {
  const headers = {};
  if (serverKey.get()) headers['x-api-key'] = serverKey.get();
  let payload = body;
  if (body && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(`/api/v1/motion${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "Can't reach the MoneyPrinterTurbo server. Check that python main.py is running.");
  }
  if (res.ok && raw) return res;
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, json.message || `The server answered ${res.status}.`);
  return json.data;
}

const blobUrl = async (path) => URL.createObjectURL(await (await request(path, { raw: true })).blob());

export const api = {
  options: () => request('/options'),
  upload: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('/characters', { method: 'POST', body: form });
  },
  characterUrl: (id) => blobUrl(`/characters/${id}`),
  createJob: (body) => request('/jobs', { method: 'POST', body }),
  job: (id) => request(`/jobs/${id}`),
  cancel: (id) => request(`/jobs/${id}/cancel`, { method: 'POST' }),
  videoUrl: (id) => blobUrl(`/jobs/${id}/video`),
};

// Clipboard needs a secure origin; over plain http on a LAN address, fall back to a hidden textarea.
export async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
  document.body.append(area);
  area.select();
  document.execCommand('copy');
  area.remove();
}
