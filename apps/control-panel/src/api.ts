import axios from 'axios';

// The API (INF-12: api.whatsapp.mesiri.ai since 14 Oct 2026). VITE_API_URL
// overrides it, the same setting the dashboard build uses.
const BASE_URL = import.meta.env.VITE_API_URL || 'https://api.whatsapp.mesiri.ai';
const TOKEN_KEY = 'mesiri_token';

export const api = axios.create({ baseURL: BASE_URL });

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// The real security-relevant behavior: a token that exists in localStorage
// is not proof of a valid session (it may be expired, malformed, or belong
// to a non-platform-admin user). Any 401/403 from the backend — the actual
// authorization boundary — clears the stale token and bounces to /login.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 || error.response?.status === 403) {
      clearToken();
      const loginPath = `${import.meta.env.BASE_URL}login`;
      if (window.location.pathname !== loginPath) {
        window.location.href = loginPath;
      }
    }
    return Promise.reject(error);
  }
);

export interface Me {
  user_id: string;
  org_id: string;
  role: string;
  name: string;
  org_name: string;
  is_platform_admin: boolean;
}

export async function login(email: string, password: string): Promise<void> {
  const res = await api.post('/auth/login', { email, password });
  setToken(res.data.access_token);
}

export async function fetchMe(): Promise<Me> {
  const res = await api.get<Me>('/auth/me');
  return res.data;
}
