import { supabase } from "../lib/supabase";

const API_BASE = import.meta.env.VITE_API_BASE || (window.location.protocol + "//" + window.location.hostname + ":8000");

export class ApiError extends Error {
  constructor(message, status, details = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export function assetUrl(path) {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  return API_BASE + path;
}

async function request(path, options, allowRefresh) {
  const { authFailure = "redirect", ...fetchOptions } = options;
  const headers = { ...(fetchOptions.headers || {}) };
  if (!(fetchOptions.body instanceof FormData)) headers["Content-Type"] = "application/json";

  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) headers.Authorization = "Bearer " + session.access_token;

  let response = await fetch(API_BASE + path, { ...fetchOptions, headers });

  if (response.status === 401 && authFailure !== "preserve" && allowRefresh) {
    const { data, error } = await supabase.auth.refreshSession();
    if (!error && data.session?.access_token) {
      headers.Authorization = "Bearer " + data.session.access_token;
      response = await fetch(API_BASE + path, { ...fetchOptions, headers });
    }
  }

  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : null; }
  catch { data = { message: text }; }

  if (!response.ok) {
    // FastAPI request-validation errors arrive as a list of {msg, ...}.
    const detail = Array.isArray(data?.detail)
      ? data.detail.map(item => String(item?.msg || "").replace(/^Value error, /, "")).filter(Boolean).join(" ")
      : data?.detail;
    const message = detail || data?.message || "Something went wrong";
    if (response.status === 401 && authFailure !== "preserve") {
      await supabase.auth.signOut({ scope: "local" }).catch(() => {});
      window.dispatchEvent(new CustomEvent("siteops:session-expired", {
        detail: { message: "Your session expired. Sign in again to continue." },
      }));
    }
    throw new ApiError(message, response.status, data);
  }
  return data;
}

export function api(path, options = {}) {
  return request(path, options, true);
}

// Evidence downloads require the same Bearer auth as every other route (no
// query-string token fallback - see backend/app/auth.py's current_user), so
// a plain <a href> can't reach them. Fetch as an authenticated blob instead
// and let the caller trigger a browser download from it.
export async function fetchBinary(path) {
  const { data: { session } } = await supabase.auth.getSession();
  const headers = session?.access_token ? { Authorization: "Bearer " + session.access_token } : {};
  const response = await fetch(API_BASE + path, { headers });
  if (!response.ok) {
    let message = "Something went wrong";
    try { message = (await response.json())?.detail || message; } catch { /* non-JSON error body */ }
    throw new ApiError(message, response.status);
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  return { blob: await response.blob(), filename: match?.[1] || "evidence" };
}