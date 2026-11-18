import { supabase, supabaseConfigured } from "../lib/supabase";
import { api } from "./client";

function ensureConfigured() {
  if (!supabaseConfigured) throw new Error("Supabase Auth is not configured for this build.");
}

export const authApi = {
  async signInWithGoogle() {
    ensureConfigured();
    // Pinned rather than window.location.origin - otherwise this would send
    // the post-login bounce back to whatever origin triggered it (e.g.
    // localhost, if triggered during local dev against prod).
    const redirectTo = `${import.meta.env.VITE_FRONTEND_URL || window.location.origin}/`;
    const { error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo } });
    if (error) throw new Error(error.message);
  },
  // Email + password set by an Admin (backend PUT /api/users/{id}/password);
  // the password lives in Supabase Auth only.
  async signInWithPassword(email, password) {
    ensureConfigured();
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error(error.message === "Invalid login credentials" ? "That email and password don't match. Check them, or ask your Admin to reset your password." : error.message);
    return data.session;
  },
  async logout() {
    ensureConfigured();
    const { error } = await supabase.auth.signOut();
    if (error) throw new Error(error.message);
  },
  getSession: () => supabase.auth.getSession(),
  onAuthStateChange: callback => supabase.auth.onAuthStateChange(callback),
  provider: () => api("/api/auth/provider"),
  // Local-dev-only shortcut (backend/app/routes/auth.py dev_login, gated
  // off outside a local Supabase stack) - mints a real session for any
  // email without going through Google, then hands it to setSession below
  // exactly like a real OAuth callback would.
  devLogin: email => api("/api/auth/dev-login", { method: "POST", body: JSON.stringify({ email }) }),
  setSession: session => supabase.auth.setSession({ access_token: session.access_token, refresh_token: session.refresh_token }),
};
