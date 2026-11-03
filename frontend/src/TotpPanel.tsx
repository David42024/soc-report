import { FormEvent, useEffect, useState } from "react";
import { request } from "./api";

interface Props {
  token: string;
  language: string;
  onError: (error: unknown) => void;
  onChanged: (notice: string) => void;
}

export function TotpPanel({ token, language, onError, onChanged }: Props) {
  const [status, setStatus] = useState<{ activo: boolean; disponible: boolean }>();
  const [secret, setSecret] = useState("");
  const [recovery, setRecovery] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const s = (es: string, en: string) => language === "es" ? es : en;
  const root = "/api/auth/totp";

  useEffect(() => {
    let active = true;
    request<{ activo: boolean; disponible: boolean }>(root, token)
      .then(value => { if (active) setStatus(value); })
      .catch(error => { if (active) onError(error); });
    return () => { active = false; };
  }, [token]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    const action = status?.activo ? "desactivar" : secret ? "activar" : "preparar";
    setBusy(true);
    try {
      if (action === "preparar") {
        const result = await request<{ secret: string }>(root + "/preparar", token, { method: "POST", body: JSON.stringify(data) });
        form.reset(); setSecret(result.secret);
      } else if (action === "activar") {
        const result = await request<{ codigos_recuperacion: string[] }>(root + "/activar", token, { method: "POST", body: JSON.stringify(data) });
        form.reset(); setSecret(""); setRecovery(result.codigos_recuperacion);
      } else {
        await request(root + "/desactivar", token, { method: "POST", body: JSON.stringify(data) });
        onChanged(s("Segundo factor desactivado. Inicia sesión de nuevo.", "Two-factor authentication disabled. Sign in again."));
      }
    } catch (error) { onError(error); }
    finally { setBusy(false); }
  }

  return <section className="sla">
    <h3>{s("Segundo factor (TOTP)", "Two-factor authentication (TOTP)")}</h3>
    {recovery.length > 0 ? <>
      <p>{s("Guarda los códigos en un lugar seguro. Cada uno funciona una sola vez. Si usas la aplicación de autenticación para ingresar ahora, espera al siguiente código.", "Store these codes safely. Each works once. If you sign in with your authenticator now, wait for its next code.")}</p>
      <ul>{recovery.map(code => <li key={code}><code>{code}</code></li>)}</ul>
      <button type="button" onClick={() => onChanged(s("Segundo factor activado. Inicia sesión de nuevo.", "Two-factor authentication enabled. Sign in again."))}>{s("Guardé los códigos", "I saved the codes")}</button>
    </> : status?.disponible ? <form key={secret ? "activation" : "password"} onSubmit={submit}>
      <p>{status.activo ? s("Activado", "Enabled") : s("Desactivado", "Disabled")}</p>
      {secret ? <>
        <p>{s("Agrega esta clave en tu aplicación de autenticación como una cuenta basada en tiempo. Vence en diez minutos.", "Add this key to your authenticator as a time-based account. It expires in ten minutes.")}</p>
        <p><code>{secret}</code></p>
      </> : <label>{s("Contraseña actual", "Current password")}<input name="password" type="password" autoComplete="current-password" maxLength={128} required /></label>}
      {(secret || status.activo) && <label>{status.activo ? s("Código o recuperación", "Code or recovery code") : s("Código de seis dígitos", "Six-digit code")}
        <input name="code" autoComplete="one-time-code" minLength={6} maxLength={status.activo ? 48 : 6} required />
      </label>}
      <button disabled={busy}>{status.activo ? s("Desactivar", "Disable") : secret ? s("Activar", "Enable") : s("Preparar segundo factor", "Set up two-factor authentication")}</button>
      {secret && <button type="button" className="secondary" disabled={busy} onClick={() => setSecret("")}>{s("Volver", "Back")}</button>}
    </form> : status && <p>{s("El segundo factor requiere la clave de cifrado del servidor.", "Two-factor authentication requires the server encryption key.")}</p>}
  </section>;
}
