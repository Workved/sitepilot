import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client";
import { authApi } from "./api/authApi";
import { LoginPage } from "./features/auth/LoginPage";
import { Dashboard } from "./features/dashboard/Dashboard";
import { stripAuthParams } from "./lib/route";
import "./styles.css";

function initialAuthError() {
  // Google/Supabase OAuth failures redirect back with #error=...&error_code=...
  // in the hash rather than throwing where our own code could catch them.
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  if (!params.get("error")) return "";
  return params.get("error_description")?.replaceAll("+", " ") || "Sign-in with Google failed. Try again, or contact your administrator.";
}

function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(initialAuthError);
  // Local-only "sign in as any local test account" shortcut - the backend
  // reports whether it's actually reachable (gated to a local Supabase
  // stack; always false against a real deployment), so this never shows
  // up as an option outside local dev.
  const [devLoginEnabled, setDevLoginEnabled] = useState(false);

  async function loadPortalIdentity(session) {
    if (!session) { setUser(null); return; }
    setUser(await api("/api/me"));
  }

  useEffect(() => {
    authApi.provider().then(info => setDevLoginEnabled(Boolean(info?.dev_login_enabled))).catch(() => {});
  }, []);

  useEffect(() => {
    let active = true;

    function handleSessionExpired(event) {
      if (!active) return;
      setUser(null);
      setLoading(false);
      setError(event.detail?.message || "Your session expired. Sign in again to continue.");
      window.history.replaceState({}, "", window.location.pathname);
    }

    window.addEventListener("siteops:session-expired", handleSessionExpired);

    async function initializeAuth() {
      try {
        const { data: { session } } = await authApi.getSession();
        if (!active) return;
        await loadPortalIdentity(session);
        if (session) stripAuthParams();
      } catch (caught) {
        if (!active) return;
        setError(caught.message);
      } finally {
        if (active) setLoading(false);
      }
    }
    initializeAuth();
    const { data: { subscription } } = authApi.onAuthStateChange((event) => {
      if (event === "SIGNED_OUT") setUser(null);
    });
    return () => {
      active = false;
      window.removeEventListener("siteops:session-expired", handleSessionExpired);
      subscription.unsubscribe();
    };
  }, []);

  async function loginWithGoogle() {
    setError("");
    try {
      await authApi.signInWithGoogle();
      // Redirects to Google on success - execution stops here. initializeAuth
      // picks the resulting session back up on return (detectSessionInUrl
      // handles the OAuth code exchange automatically).
    } catch (caught) {
      setError(caught.message);
    }
  }

  async function loginWithPassword(email, password) {
    setError("");
    try {
      const session = await authApi.signInWithPassword(email, password);
      await loadPortalIdentity(session);
    } catch (caught) {
      setError(caught.message);
    }
  }

  async function loginAsDev(email) {
    setError("");
    try {
      const session = await authApi.devLogin(email);
      const { error: sessionError } = await authApi.setSession(session);
      if (sessionError) throw new Error(sessionError.message);
      await loadPortalIdentity(session);
    } catch (caught) {
      setError(caught.message);
    }
  }

  async function logout() {
    await authApi.logout().catch(() => {});
    setUser(null);
  }

  if (loading && !user) return <main className="grid min-h-screen place-items-center bg-canvas text-sm text-slate-500">Opening secure workspace…</main>;
  if (!user) return <LoginPage onGoogle={loginWithGoogle} onPassword={loginWithPassword} error={error} devLoginEnabled={devLoginEnabled} onDevLogin={loginAsDev}/>;
  return <Dashboard initialUser={user} onLogout={logout}/>;
}

createRoot(document.getElementById("root")).render(<App/>);
