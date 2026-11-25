/**
 * Minimal URL sync built on the History API - deliberately not a router.
 *
 * Workspace state lives in the query string so a refresh, a bookmark or a
 * pasted link lands in the same place:
 *
 *   ?tab=projects&project=PRJ-20260803-138101&pane=template-review
 *
 * Query params rather than path segments (`/projects/:code/:pane`) because
 * pretty paths need an SPA rewrite rule on whatever serves the build, and
 * main.jsx derives its auth redirects from `window.location.pathname` -
 * moving the app off "/" would quietly break logout and the recovery
 * links. Swapping to path segments later is a change to readRoute/
 * writeRoute only; nothing that calls useRoute has to know.
 *
 * `view` is intentionally left alone: main.jsx owns it for the
 * unauthenticated screens, and its logout handler clears the whole query
 * string, which resets this module's state for free.
 */
import { useCallback, useEffect, useRef, useState } from "react";

const ROUTE_KEYS = ["tab", "project", "pane", "vendor", "broadcast", "person"];

export function readRoute() {
  const params = new URLSearchParams(window.location.search);
  return {
    tab: params.get("tab") || "",
    project: params.get("project") || "",
    pane: params.get("pane") || "",
    vendor: params.get("vendor") || "",
    broadcast: params.get("broadcast") || "",
    person: params.get("person") || "",
  };
}

// One-time sign-in parameters (PKCE `code`, OAuth errors, recovery `view`)
// must not linger in the address bar after auth has consumed them - but the
// workspace route next to them must survive, or every refresh, bookmark and
// shared link would land on the home tab.
const AUTH_PARAMS = ["code", "state", "error", "error_code", "error_description", "type", "token_hash", "view"];

export function stripAuthParams() {
  const params = new URLSearchParams(window.location.search);
  AUTH_PARAMS.forEach(key => params.delete(key));
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ""}`;
  if (url !== `${window.location.pathname}${window.location.search}${window.location.hash}`) window.history.replaceState({}, "", url);
}

function currentUrl() {
  return `${window.location.pathname}${window.location.search}`;
}

function writeRoute(next, replace) {
  const params = new URLSearchParams(window.location.search);
  ROUTE_KEYS.forEach(key => {
    if (next[key]) params.set(key, next[key]);
    else params.delete(key);
  });
  const query = params.toString();
  const url = `${window.location.pathname}${query ? `?${query}` : ""}`;
  // A no-op navigation would otherwise stack duplicate history entries and
  // make the browser Back button feel broken.
  if (url === currentUrl()) return;
  window.history[replace ? "replaceState" : "pushState"]({}, "", url);
}

export function useRoute() {
  const [route, setRouteState] = useState(readRoute);
  // History is written outside the state updater: React re-invokes updaters
  // under StrictMode, which would push every navigation twice.
  const latest = useRef(route);
  latest.current = route;

  useEffect(() => {
    function sync() {
      const next = readRoute();
      latest.current = next;
      setRouteState(next);
    }
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);

  const setRoute = useCallback((patch, options = {}) => {
    const next = { ...latest.current, ...patch };
    if (ROUTE_KEYS.every(key => next[key] === latest.current[key])) return;
    writeRoute(next, options.replace === true);
    latest.current = next;
    setRouteState(next);
  }, []);

  return [route, setRoute];
}
