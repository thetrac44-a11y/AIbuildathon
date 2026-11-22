const API_BASE = (import.meta.env?.VITE_API_BASE_URL as string | undefined) || '/api';

export const TOKEN_STORAGE_KEY = 'hr_copilot_access_token';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage errors in restricted environments
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(options.headers || {});
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (!(options.body instanceof FormData) && options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const url = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
  const resp = await fetch(url, { ...options, headers });

  if (!resp.ok) {
    let detail = `Lỗi hệ thống (${resp.status})`;
    try {
      const errJson = await resp.json();
      if (typeof errJson?.detail === 'string') {
        detail = errJson.detail;
      } else if (Array.isArray(errJson?.detail) && errJson.detail[0]?.msg) {
        detail = errJson.detail[0].msg;
      }
    } catch {
      // Fallback to default message
    }
    throw new ApiError(detail, resp.status);
  }

  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

export async function apiDownload(path: string, fallbackFilename: string): Promise<void> {
  const token = getStoredToken();
  const headers = new Headers();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  const url = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
  const resp = await fetch(url, { headers });
  if (!resp.ok) {
    let detail = `Không thể tải tệp (${resp.status})`;
    try {
      const errJson = await resp.json();
      if (errJson?.detail) detail = errJson.detail;
    } catch {
      // ignore
    }
    throw new ApiError(detail, resp.status);
  }
  const blob = await resp.blob();
  const disposition = resp.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/i);
  const filename = match ? match[1] : fallbackFilename;

  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}
