import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { LogoMark } from "./Icons";

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.login(password);
      setPassword("");
      onSuccess();
    } catch (err) {
      const e = err as ApiError;
      setError(e.status === 429 ? `Demasiados intentos. Reintente en ${e.retryAfter ?? 300} s.` : e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login-page">
      <form className="card login-card" onSubmit={submit} noValidate>
        <div className="login-brand">
          <div className="mark"><LogoMark size={28} /></div>
          <div>
            <h1>Panel de administración</h1>
            <p className="page-sub">Votación Electrónica 2026</p>
          </div>
        </div>
        <div className="field">
          <label htmlFor="admin-password">Clave de administrador</label>
          <input id="admin-password" type="password" autoComplete="current-password" autoFocus value={password}
            onChange={(e) => setPassword(e.target.value)} aria-describedby="login-error" />
        </div>
        <p id="login-error" className="form-error" role="alert">{error}</p>
        <button className="btn primary" type="submit" disabled={busy || !password}>{busy ? "Verificando…" : "Ingresar"}</button>
        <p className="login-note">El acceso queda registrado. La clave nunca se almacena en el navegador.</p>
      </form>
    </main>
  );
}
