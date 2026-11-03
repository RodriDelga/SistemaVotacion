import { useCallback, useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";
import { Login } from "./components/Login";
import { Shell, NAV } from "./components/Shell";
import { Banner } from "./components/Bits";
import { setTimeZone } from "./lib/format";
import { Overview } from "./pages/Overview";
import { Results } from "./pages/Results";
import { Reports } from "./pages/Reports";
import { Placeholder } from "./pages/Placeholder";
import type { Meta } from "./types";

function useHashRoute(): string {
  const read = () => (window.location.hash.replace(/^#/, "") || "/");
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

type Phase = "checking" | "anon" | "authed";

export default function App() {
  const [phase, setPhase] = useState<Phase>("checking");
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const route = useHashRoute();

  const loadMeta = useCallback(async () => {
    try {
      const data = await api.meta();
      setTimeZone(data.timezone);
      setMeta(data);
      setMetaError(null);
      setPhase("authed");
    } catch (error) {
      setMetaError((error as Error).message);
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => { setMeta(null); setPhase("anon"); });
    const controller = new AbortController();
    api.me(controller.signal)
      .then((auth) => (auth.authenticated ? loadMeta() : setPhase("anon")))
      .catch((error) => { if ((error as Error).name !== "AbortError") setPhase("anon"); });
    return () => { controller.abort(); setUnauthorizedHandler(null); };
  }, [loadMeta]);

  useEffect(() => { if (meta) document.title = `${meta.title} · Panel`; }, [meta]);

  const logout = async () => {
    try { await api.logout(); } catch { /* la cookie expira sola */ }
    setMeta(null);
    setPhase("anon");
  };

  if (phase === "checking") return <div className="login-page" aria-busy="true" />;
  if (phase === "anon") return <Login onSuccess={() => void loadMeta()} />;
  if (!meta) {
    return <div className="login-page"><div className="card login-card"><Banner kind="warn">{metaError ?? "Cargando…"}</Banner></div></div>;
  }

  const pollMs = Math.max(2, meta.pollSeconds) * 1000;
  const known = NAV.some((n) => n.path === route);
  const current = known ? route : "/";
  return (
    <Shell title={meta.title} route={current} onLogout={logout}>
      {current === "/" && <Overview pollMs={pollMs} />}
      {current === "/resultados" && <Results meta={meta} pollMs={pollMs} />}
      {current === "/reportes" && <Reports meta={meta} pollMs={pollMs} />}
      {["/participacion", "/dispositivo", "/configuracion"].includes(current) && (
        <Placeholder title={NAV.find((n) => n.path === current)!.label} />
      )}
    </Shell>
  );
}
