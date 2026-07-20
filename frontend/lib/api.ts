import { supabase } from "./supabase";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`API ${status}: ${body}`);
    this.status = status;
    this.body = body;
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) throw new Error("Not signed in");
  return { Authorization: `Bearer ${session.access_token}` };
}

export async function apiGet<T>(path: string): Promise<T> {
  const headers = await authHeader();
  const r = await fetch(`${API_BASE}${path}`, { headers });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return (await r.json()) as T;
}

// Unauthenticated POST — for the public access-request intake, which runs on the
// logged-out landing page where there's no session to attach a bearer to.
export async function apiPostPublic<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return (await r.json()) as T;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const headers = await authHeader();
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return (await r.json()) as T;
}

// Multipart upload (e.g. a custom image). Does NOT set Content-Type — the
// browser fills in the multipart boundary itself when the body is FormData.
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const headers = await authHeader();
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return (await r.json()) as T;
}

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  const headers = await authHeader();
  const r = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { ...headers, "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  return (await r.json()) as T;
}

export async function apiDelete<T = void>(path: string): Promise<T | null> {
  const headers = await authHeader();
  const r = await fetch(`${API_BASE}${path}`, { method: "DELETE", headers });
  if (!r.ok) throw new ApiError(r.status, await r.text());
  if (r.status === 204) return null;
  return (await r.json()) as T;
}
