// The dashboard API (src/gstagent/dashboard.py). Case ids contain "|" and "/", so they are always encoded.
const id = (caseId) => encodeURIComponent(caseId);

async function call(path, options) {
  const r = await fetch(path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${r.status})`);
  return body;
}

export const getCases = () => call('/api/cases');
export const getClients = () => call('/api/clients');
export const getCase = (caseId) => call(`/api/cases/${id(caseId)}`);
export const post = (path, body) =>
  call(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) });
export const caseAction = (caseId, action, body) => post(`/api/cases/${id(caseId)}/${action}`, body);
