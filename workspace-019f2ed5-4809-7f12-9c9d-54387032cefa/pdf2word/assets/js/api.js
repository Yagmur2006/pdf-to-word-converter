/**
 * api.js
 * ---------------------------------------------------------------
 * Thin wrapper around fetch() for every backend endpoint. Keeping
 * network calls in one module makes it trivial to swap base URLs,
 * add retry logic, or mock the backend during development.
 * ---------------------------------------------------------------
 */

const BASE = 'api';

/** Small helper to normalize the { success, data|error } response envelope. */
async function handle(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error('Unexpected server response.');
  }

  if (!response.ok || !body.success) {
    throw new Error(body.error || 'Something went wrong.');
  }

  return body.data;
}

export async function fetchCsrfToken() {
  const res = await fetch(`${BASE}/csrf.php`, { credentials: 'same-origin' });
  const data = await handle(res);
  return data.csrfToken;
}

export async function uploadFile(file, csrfToken) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${BASE}/upload.php`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-CSRF-Token': csrfToken },
    body: formData,
  });

  return handle(res);
}

export async function fetchStatus(jobId) {
  const res = await fetch(`${BASE}/status.php?jobId=${encodeURIComponent(jobId)}`, {
    credentials: 'same-origin',
  });
  return handle(res);
}

export function downloadUrl(jobId) {
  return `${BASE}/download.php?jobId=${encodeURIComponent(jobId)}`;
}
