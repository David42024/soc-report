import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { ApiError, downloadFile, request, stage, selectedReports, readPreference, type Report, type User, type Role, type Metrics, type Triage, type Audit, type Event } from "./api";
import { translate, teamNames } from "./i18n";
import "./styles.css";
import { ChatWidget } from "./ChatWidget";
import { ImpactPanel } from "./ImpactPanel";
import { OperationalImpactPanel } from "./OperationalImpactPanel";
import { DashboardPanel } from "./DashboardPanel";
import { useAuditVisit } from "./navigation";
import { CollaborationPanel, OperationsPanel, ProfilePanel, type Section } from "./OperationsPanels";

const roles: Role[] = ["administrador", "analista", "gestor", "auditor"];

export function App() {
  const [language, setLanguage] = useState(readPreference("language", "es"));
  const [theme, setTheme] = useState(readPreference("theme", "system"));
  const [view, setView] = useState("intake");
  const [section, setSection] = useState<Section>("notificaciones");
  const [focusedReport, setFocusedReport] = useState<Report>();
  const [session, setSession] = useState<{ access_token: string; user: User } | null>(null);
  const [reports, setReports] = useState<Report[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [triage, setTriage] = useState<Triage | null>(null);
  const [filter, setFilter] = useState("todos");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsFactor, setNeedsFactor] = useState(false);
  const [receipt, setReceipt] = useState<Report | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const pending = useRef<{ body: string; key: string }>();
  const refreshSequence = useRef(0);
  const [chatOpen, setChatOpen] = useState(false);
  const token = session?.access_token || "";
  const role = session?.user.role;
  const canRead = Boolean(role && role !== "auditor");
  const canWrite = role === "administrador" || role === "analista";
  const canAudit = role === "administrador" || role === "auditor";
  const canBaseline = role === "administrador" || role === "gestor";
  const canExportReports = role === "administrador" || role === "gestor";
  const activeModule = view === "operations" ? section : view;
  const closeView = useAuditVisit(token, !token && view !== "intake" ? "login" : activeModule);
  const closeChat = useAuditVisit(token, chatOpen ? "chat" : null);
  const t = (key: string, ...values: (string | number)[]) => translate(language, key, ...values);
  const s = (es: string, en: string) => language === "en" ? en : es;
  const team = (name: string | null) => name ? (language === "en" ? teamNames[name] || name : name) : t("noTeam");
  const date = (value: string | null) => value ? new Date(value).toLocaleString(language === "en" ? "en-US" : "es-PE") : "—";
  const roleLabel = (value: Role) => ({ administrador: s("Administrador", "Administrator"), analista: s("Analista", "Analyst"), gestor: s("Gestor", "Manager"), auditor: s("Auditor", "Auditor") })[value];

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("soc-language", language);
      localStorage.setItem("soc-theme", theme);
    } catch { /* Preferences remain usable without browser storage. */ }
  }, [language, theme]);

  function fail(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) {
      refreshSequence.current++;
      setSession(null); setReports([]); setMetrics(null); setTriage(null);
      setFocusedReport(undefined);
    }
    setError(cause instanceof Error ? cause.message : t("unexpected"));
  }

  async function refresh(authToken = token) {
    const sequence = ++refreshSequence.current;
    setBusy(true); setError("");
    try {
      const [items, stats, times] = await Promise.all([
        request<Report[]>("/api/reportes", authToken),
        request<Metrics>("/api/metricas", authToken),
        request<Triage>("/api/triage", authToken),
      ]);
      if (sequence === refreshSequence.current) { setReports(items); setMetrics(stats); setTriage(times); }
    } catch (cause) { if (sequence === refreshSequence.current) fail(cause); }
    finally { if (sequence === refreshSequence.current) setBusy(false); }
  }

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true); setError("");
    try {
      const result = await request<{ access_token: string; user: User }>("/api/auth/login", "", { method: "POST", body: JSON.stringify(data) });
      setNeedsFactor(false);
      setSession(result);
      if (result.user.role === "auditor") setView("audit");
      else { setView("inbox"); await refresh(result.access_token); }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 428) {
        setNeedsFactor(true);
        setError(s("Introduce tu código de segundo factor o un código de recuperación.", "Enter your second factor or a recovery code."));
      } else fail(cause);
    }
    finally { setBusy(false); }
  }

  async function logout() {
    await Promise.all([closeView(), closeChat()]);
    try { await request("/api/auth/logout", token, { method: "POST" }); }
    catch (cause) { fail(cause); return; }
    refreshSequence.current++;
    setSession(null); setReports([]); setMetrics(null); setTriage(null);
    setFocusedReport(undefined); setSection("notificaciones");
    setNotice(""); setError(""); setView("intake");
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const body = JSON.stringify(Object.fromEntries(new FormData(form)));
    if (pending.current?.body !== body) pending.current = { body, key: crypto.randomUUID() };
    setSending(true); setSendError(""); setReceipt(null);
    try {
      const result = await request<Report>("/api/reportes", "", { method: "POST", body, headers: { "Idempotency-Key": pending.current.key } });
      setReceipt(result); pending.current = undefined; form.reset();
      setFilter("todos");
      if (canRead) await refresh();
    } catch (cause) { setSendError(cause instanceof Error ? cause.message : t("unexpected")); }
    finally { setSending(false); }
  }

  async function action(id: string, path: string) {
    const result = await request<Report>(`/api/reportes/${id}/${path}`, token, { method: "POST" });
    setNotice(t(path === "responder" ? "responded" : path === "resolver" ? "resolutionSaved" : result.notificado_at ? "routed" : "stillPending"));
    await refresh();
    if (focusedReport?.id === id) setFocusedReport(result);
  }

  async function openReport(id: string) {
    try {
      setFocusedReport(await request<Report>("/api/reportes/" + id, token));
      setView("inbox");
    } catch (error) { fail(error); }
  }

  async function download(format: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/exportar/${format}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = `soc-reportes.${format}`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { fail(cause); } finally { setBusy(false); }
  }

  const filtered = selectedReports(reports, filter);
  const counts = Object.entries(reports.reduce<Record<string, number>>((result, report) => {
    result[report.tipo] = (result[report.tipo] || 0) + 1; return result;
  }, {})).map(([name, cases]) => ({ name: t(name), cases }));

  return <>
    <header className="site-header"><div className="shell header-layout">
      <div><p className="eyebrow">{t("eyebrow")}</p><h1>SOC Report Router</h1><p>{t("tagline")}</p></div>
      <div className="preferences">
        <label>{t("language")}<select aria-label={t("language")} value={language} onChange={e => setLanguage(e.target.value)}><option value="es">Español</option><option value="en">English</option></select></label>
        <label>{t("theme")}<select aria-label={t("theme")} value={theme} onChange={e => setTheme(e.target.value)}>{["system", "light", "dark"].map(value => <option key={value} value={value}>{t(value)}</option>)}</select></label>
      </div>
    </div></header>
    <main className="shell workspace">
      <nav className="views" aria-label={s("Vistas", "Views")}>
        {[["intake", t("newReport")], ["inbox", t("board")], ...(canRead ? [["dashboard", s("Dashboard e informes", "Dashboard and reports")], ["impact", s("Evolución", "Trends")], ["operations", s("Operaciones", "Operations")]] : []), ...(canAudit ? [["audit", s("Auditoría", "Audit")]] : []), ...(role === "administrador" ? [["users", s("Usuarios", "Users")]] : []), ...(session ? [["profile", s("Mi perfil", "My profile")]] : [])].map(([key, label]) =>
          <button type="button" key={key} aria-pressed={view === key} onClick={() => { setView(key); setError(""); setNotice(""); }}>{label}</button>)}
        {session && <span className="session">{session.user.username} · {roleLabel(session.user.role)} <button type="button" className="secondary" onClick={logout}>{s("Cerrar sesión", "Sign out")}</button></span>}
      </nav>
      {error && <p role="alert" className="notice error">{error}</p>}
      {notice && <p role="status" className="notice">{notice}</p>}
      {view === "intake" && <section className="panel narrow" aria-labelledby="report-heading">
        <h2 id="report-heading">{t("newReport")}</h2><p className="intro">{t("intakeIntro")}</p>
        <form id="report-form" onSubmit={submit}><fieldset disabled={sending}>
          <label htmlFor="titulo">{t("title")}</label><input id="titulo" name="titulo" minLength={5} maxLength={120} placeholder={t("titleExample")} required />
          <label htmlFor="descripcion">{t("description")}</label><textarea id="descripcion" name="descripcion" minLength={15} maxLength={4000} placeholder={t("descriptionExample")} required />
          <p className="hint">{t("descriptionHelp")}</p><button>{t("submit")}</button>
        </fieldset></form>
        <output className="notice" role="status">{sending ? t("sending") : receipt ? `${t("received")} ${receipt.notificado_at ? t("notified", team(receipt.responsable)) : t("routePending")}\nID: ${receipt.id}` : ""}</output>
        {sendError && <p role="alert" className="notice error">{sendError}</p>}
        {receipt && <button className="secondary next" onClick={() => setView("inbox")}>{t("viewBoard")}</button>}
      </section>}
      {view !== "intake" && !session && <section className="panel narrow">
        <h2>{s("Iniciar sesión", "Sign in")}</h2><p className="intro">{s("Ingresa con tu usuario. Los permisos dependen de tu rol.", "Sign in with your account. Your role determines your permissions.")}</p>
        <form onSubmit={login}><label htmlFor="username">{s("Usuario", "Username")}</label><input id="username" name="username" autoComplete="username" required />
          <label htmlFor="password">{s("Contraseña", "Password")}</label><input id="password" name="password" type="password" autoComplete="current-password" required />
          {needsFactor && <><label htmlFor="otp">{s("Código de segundo factor o recuperación", "Second factor or recovery code")}</label>
            <input id="otp" name="otp" autoComplete="one-time-code" minLength={6} maxLength={48} required /></>}
          <button className="next" disabled={busy}>{s("Ingresar", "Sign in")}</button></form>
      </section>}
      {view === "inbox" && canRead && <section className="panel" aria-labelledby="board-heading">
        {focusedReport && <div className="sla">
          <button className="secondary" type="button" onClick={() => setFocusedReport(undefined)}>{s("Cerrar reporte seleccionado", "Close selected report")}</button>
          <ReportCard key={focusedReport.id} report={focusedReport} token={token} language={language} canWrite={canWrite} onAction={action} onError={fail} />
        </div>}
        <div className="list-toolbar"><div><h2 id="board-heading">{t("board")}</h2><p className="hint">{t("count", filtered.length, reports.length, reports.filter(r => stage(r) !== 2).length)}</p></div>
          <div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => refresh()}>{busy ? t("loading") : t("refreshBoard")}</button>
            {canExportReports && ["pdf", "docx", "xlsx"].map(format => <button key={format} className="secondary" disabled={busy} onClick={() => download(format)}>{s("Exportar", "Export")} {format.toUpperCase()}</button>)}</div>
        </div>
        {metrics && <details className="sla"><summary>{t("sla")}</summary><div className="metrics">{[
          ["firstResponse", metrics.respuesta_a_tiempo, metrics.respuesta_evaluable], ["resolution", metrics.resolucion_a_tiempo, metrics.resolucion_evaluable],
        ].map(([label, passed, total]) => <div className="metric" key={String(label)}><h3>{t(String(label))}</h3><p className="rate">{total ? new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: 1 }).format(Number(passed) / Number(total)) : "—"}</p><p>{total ? t("onTimeCount", Number(passed), Number(total)) : t("notEvaluated")}</p></div>)}</div><p className="hint">{t("slaHelp")}</p>
          {counts.length > 0 && <div className="chart" role="img" aria-label={s("Reportes por tipo", "Reports by type")}><ResponsiveContainer width="100%" height={220}><BarChart data={counts}><XAxis dataKey="name" tick={{ fill: "var(--text)", fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fill: "var(--text)" }} /><Tooltip contentStyle={{ background: "var(--panel)", color: "var(--text)" }} /><Bar dataKey="cases" name={s("Casos", "Cases")} fill="var(--accent)" /></BarChart></ResponsiveContainer></div>}
        </details>}
        <div className="list-toolbar"><label>{t("show")} <select aria-label={t("show")} value={filter} onChange={e => setFilter(e.target.value)}>{[["todos", "all"], ["pendientes", "pending"], ["revision", "reviewFilter"], ["resueltos", "resolved"]].map(([value, key]) => <option key={value} value={value}>{t(key)}</option>)}</select></label></div>
        <div className="board">{["laneNew", "laneProgress", "laneDone"].map((label, lane) => {
          const items = filtered.filter(report => stage(report) === lane);
          return <section className="lane" key={label} aria-label={t(label)}><h3>{t(label)} · {items.length}</h3><div className="report-list">{items.map(report =>
            <ReportCard key={report.id} report={report} token={token} language={language} canWrite={canWrite} onAction={action} onError={fail} />
          )}{!items.length && <p className="empty">{t("emptyLane")}</p>}</div></section>;
        })}</div>
        <TriagePanel value={triage} canEdit={canBaseline} language={language} token={token} onRefresh={() => refresh()} onError={fail} />
      </section>}
      {view === "inbox" && session && !canRead && <p className="panel">{s("Tu rol permite consultar la vista Auditoría.", "Your role can access the Audit view.")}</p>}
      {view === "users" && role === "administrador" && <UsersPanel token={token} language={language} onError={fail} />}
      {view === "audit" && canAudit && <AuditPanel token={token} language={language} onError={fail} />}
      {view === "impact" && canRead && <>
        <OperationalImpactPanel token={token} language={language} canManage={canBaseline} onError={fail} />
        <ImpactPanel token={token} language={language} onError={fail} />
      </>}
      {view === "dashboard" && canRead && <DashboardPanel token={token} language={language} canExport={canExportReports} onError={fail} />}
      {view === "operations" && canRead && <OperationsPanel token={token} language={language} onError={fail}
        section={section} setSection={setSection} canWrite={canWrite} admin={role === "administrador"} openReport={openReport} />}
      {view === "profile" && session && <ProfilePanel token={token} language={language} user={session.user} onError={fail}
        onChanged={message => {
          refreshSequence.current++;
          setSession(null); setReports([]); setMetrics(null); setTriage(null); setFocusedReport(undefined); setSection("notificaciones");
          setView("inbox"); setNotice(message ?? s("Contraseña cambiada. Inicia sesión de nuevo.", "Password changed. Sign in again."));
        }} />}
    </main>
    <ChatWidget language={language} onVisibilityChange={setChatOpen} />
  </>;
}

interface CardProps { report: Report; token: string; language: string; canWrite: boolean; onAction: (id: string, action: string) => Promise<void>; onError: (error: unknown) => void }
function ReportCard({ report, token, language, canWrite, onAction, onError }: CardProps) {
  const [collaboration, setCollaboration] = useState(false);
  const [busy, setBusy] = useState(false);
  const [events, setEvents] = useState<Event[] | null>(null);
  const [showAudit, setShowAudit] = useState(false);
  const [seconds, setSeconds] = useState("");
  const t = (key: string, ...values: (string | number)[]) => translate(language, key, ...values);
  const team = report.responsable ? language === "en" ? teamNames[report.responsable] || report.responsable : report.responsable : t("noTeam");
  const date = (value: string | null) => value ? new Date(value).toLocaleString(language === "en" ? "en-US" : "es-PE") : "—";
  async function run(operation: () => Promise<void>) { setBusy(true); try { await operation(); } catch (cause) { onError(cause); } finally { setBusy(false); } }
  const next = report.respondido_at ? report.vence_resolucion_at : report.vence_respuesta_at;
  const late = Boolean(next && Date.parse(next) < Date.now());
  const state = !report.notificado_at ? "needsRouting" : !report.respondido_at ? "needsResponse" : report.resuelto_at ? "done" : "needsResolution";
  return <article className="report">
    <div className="report-heading"><h4>{report.titulo}</h4><span className="badge">{t(state)}</span></div>
    <p>{team} · {t(report.tipo)} · {t("severity", t(report.severidad))}</p><p className="hint">{t("receivedOn", date(report.recibido_at))}</p>
    {report.motivo_revision && <p className="hint review">{t("review", t(report.motivo_revision))}</p>}
    {next && !report.resuelto_at && <p className={late ? "hint late" : "hint"}>{t(report.respondido_at ? "resolution" : "firstResponse")} · {t(late ? "overdue" : "deadline")} {date(next)}</p>}
    {canWrite && <div className="report-footer">
      {!report.notificado_at && <button disabled={busy} onClick={() => run(() => onAction(report.id, "reintentar"))}>{t("retry")}</button>}
      {report.responsable && !report.respondido_at && <button disabled={busy} onClick={() => run(() => onAction(report.id, "responder"))}>{t("respond")}</button>}
      {report.respondido_at && !report.resuelto_at && <button disabled={busy} onClick={() => run(() => onAction(report.id, "resolver"))}>{t("resolve")}</button>}
    </div>}
    <details className="report-details"><summary>{t("details")}</summary>
      <p className="description">{report.descripcion}</p><p className="hint">{t("asset", report.activo_afectado || t("unknown"))}</p>
      <p className="hint">{t("source", t(report.origen))} · ID {report.id}</p>
      <p className="hint">{report.notificado_at ? t("internalNotice", date(report.notificado_at)) : t("noticePending")}</p>
      {(["respuesta", "resolucion"] as const).map((step) => {
        const deadline = step === "respuesta" ? report.vence_respuesta_at : report.vence_resolucion_at;
        const done = step === "respuesta" ? report.respondido_at : report.resuelto_at;
        const missed = deadline && (done ? Date.parse(done) : Date.now()) > Date.parse(deadline);
        return <p className="hint" key={step}>{t(step === "respuesta" ? "firstResponse" : "resolution")} · {t("deadline")} {date(deadline)} · {done ? `${date(done)} (${t(missed ? "late" : "onTime")})` : t(missed ? "pastDue" : "waiting")}</p>;
      })}
      <button className="secondary" aria-expanded={showAudit} disabled={busy} onClick={() => run(async () => {
        if (!showAudit) setEvents(await request<Event[]>(`/api/reportes/${report.id}/bitacora`, token));
        setShowAudit(!showAudit);
      })}>{t(showAudit ? "hideAudit" : "audit")}</button>
      {showAudit && <ul>{events?.map(event => <li key={event.accion}>{date(event.ocurrido_at)} · {t(event.accion === "responder" ? "firstResponse" : event.accion === "resolver" ? "resolution" : event.accion)} · {event.actor} · {event.detalle}</li>)}</ul>}
      {canWrite && report.motivo_revision && report.notificado_at && <form className="next" onSubmit={e => { e.preventDefault(); run(async () => {
        await request(`/api/reportes/${report.id}/triaje`, token, {method:"POST",body:JSON.stringify({seconds:Number(seconds)})}); setSeconds("");
      }); }}>
        <label>{language === "en" ? "Manual review time (seconds)" : "Tiempo de revisión manual (segundos)"}<input type="number" min="0" max="86400" required value={seconds} onChange={e => setSeconds(e.target.value)} /></label><button disabled={busy}>{language === "en" ? "Save review time" : "Guardar tiempo de revisión"}</button>
      </form>}
      <button type="button" className="secondary" aria-expanded={collaboration} onClick={() => setCollaboration(!collaboration)}>
        {language === "en" ? "Collaboration and review" : "Colaboración y revisión"}
      </button>
      {collaboration && <CollaborationPanel report={report} token={token} language={language} canWrite={canWrite} onError={onError} />}
    </details>
  </article>;
}

interface PanelProps { token: string; language: string; onError: (cause: unknown) => void }
function UsersPanel({ token, language, onError }: PanelProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [busy, setBusy] = useState(false);
  const s = (es: string, en: string) => language === "en" ? en : es;
  const labels = language === "en" ? ["Administrator", "Analyst", "Manager", "Auditor"] : ["Administrador", "Analista", "Gestor", "Auditor"];
  async function load() { try { setUsers(await request<User[]>("/api/users", token)); } catch (cause) { onError(cause); } }
  useEffect(() => { load(); }, [token]);
  return <section className="panel"><h2>{s("Usuarios y roles", "Users and roles")}</h2>
    <form className="admin-create grid gap-3 md:grid-cols-4" onSubmit={async e => {
      e.preventDefault(); const form = e.currentTarget; setBusy(true);
      try { await request("/api/users", token, {method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))}); form.reset(); await load(); } catch (cause) { onError(cause); } finally { setBusy(false); }
    }}>
      <label>{s("Usuario", "Username")}<input name="username" pattern="[a-zA-Z0-9_.-]+" required maxLength={80} autoComplete="off" /></label>
      <label>{s("Contraseña inicial", "Initial password")}<input name="password" type="password" minLength={12} maxLength={128} required autoComplete="new-password" /></label>
      <label>{s("Rol", "Role")}<select name="role">{roles.map((role, i) => <option key={role} value={role}>{labels[i]}</option>)}</select></label>
      <button disabled={busy}>{s("Crear usuario", "Create user")}</button>
    </form>
    <div className="grid gap-3 mt-5">{users.map(user => <form key={`${user.id}-${user.role}-${user.active}`} className="user-row" onSubmit={async e => {
      e.preventDefault(); const data = new FormData(e.currentTarget); setBusy(true);
      try { await request(`/api/users/${user.id}`, token, {method:"PUT",body:JSON.stringify({role:data.get("role"),active:data.get("active")==="on",password:data.get("password") || null})}); await load(); } catch (cause) { onError(cause); } finally { setBusy(false); }
    }}>
      <strong>{user.username}</strong><label>{s("Rol", "Role")}<select name="role" defaultValue={user.role}>{roles.map((role, i) => <option key={role} value={role}>{labels[i]}</option>)}</select></label>
      <label>{s("Nueva contraseña opcional", "Optional new password")}<input name="password" type="password" minLength={12} maxLength={128} autoComplete="new-password" /></label>
      <label className="check"><input type="checkbox" name="active" defaultChecked={Boolean(user.active)} />{s("Activo", "Active")}</label>
      <button disabled={busy}>{s("Guardar cambios", "Save changes")}</button>
    </form>)}</div>
  </section>;
}

function AuditPanel({token, language, onError}: PanelProps) {
  const [rows, setRows] = useState<Audit[]>([]);
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(true);
  const [query, setQuery] = useState("");
  const s = (es: string, en: string) => language === "en" ? en : es;
  async function load(append = false) {
    setBusy(true);
    try {
      const cursor = append && rows.length ? `&before=${rows.at(-1)!.id}` : "";
      const page = await request<Audit[]>(`/api/audit?limit=100${cursor}${query && "&" + query}`, token);
      setRows(append ? [...rows, ...page] : page); setMore(page.length === 100);
    } catch(cause) { onError(cause); } finally { setBusy(false); }
  }
  useEffect(() => { load(); }, [token, query]);
  return <section className="panel"><div className="list-toolbar"><div><h2>{s("Auditoría inmutable", "Immutable audit log")}</h2><p className="hint">{s("Entradas, salidas y cambios críticos registrados por el servidor.", "Request entry, exit, and critical changes recorded by the server.")}</p></div><button disabled={busy} onClick={() => load()}>{s("Actualizar", "Refresh")}</button></div>
    <form className="report-filters" onSubmit={event => {
      event.preventDefault();
      const params = new URLSearchParams();
      for (const [key, value] of new FormData(event.currentTarget)) if (value) params.set(key, String(value));
      setQuery(params.toString());
    }}>
      {[
        ["usuario", s("Usuario", "User"), "text"], ["rol", s("Rol", "Role"), "text"],
        ["modulo", s("Módulo", "Module"), "text"], ["accion", s("Acción", "Action"), "text"],
        ["desde", s("Desde", "From"), "date"], ["hasta", s("Hasta", "To"), "date"], ["resultado", "HTTP", "number"],
        ["desenlace", s("Resultado", "Outcome"), "text"],
      ].map(([key, label, type]) => <label key={key}>{label}<input name={key} type={type} min={type === "number" ? 100 : undefined} max={type === "number" ? 599 : undefined} /></label>)}
      <button disabled={busy}>{s("Aplicar", "Apply")}</button>
      <button type="reset" className="secondary" onClick={() => setQuery("")}>{s("Limpiar", "Clear")}</button>
    </form>
    <div className="report-filters">
      {["pdf", "docx", "xlsx"].map(format => <button key={format} type="button" className="secondary" disabled={busy}
        onClick={() => void downloadFile(`/api/audit/exportar/${format}?${query}`, token, "soc-auditoria." + format).catch(onError)}>
        {s("Exportar", "Export")} {format.toUpperCase()}
      </button>)}
    </div>
    <div className="table-scroll"><table><thead><tr>{[s("Fecha", "Date"),s("Usuario", "User"),s("Rol", "Role"),s("Acción", "Action"),s("Módulo", "Module"),"IP",s("Fase", "Phase"),s("Resultado", "Outcome"),"HTTP",s("Solicitud", "Request")].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.id}><td>{new Date(row.occurred_at).toLocaleString(language)}</td><td>{row.user_id}</td><td>{row.role}</td><td>{row.action}</td><td>{row.module}</td><td>{row.ip}</td><td>{row.phase}</td><td>{row.outcome ?? "—"}</td><td>{row.status_code ?? "—"}</td><td>{row.request_id || "—"}</td></tr>)}</tbody></table></div>
    {more && <button className="next" disabled={busy} onClick={() => load(true)}>{s("Cargar anteriores", "Load older entries")}</button>}
  </section>;
}

function TriagePanel({value,canEdit,token,language,onRefresh,onError}: PanelProps & {value:Triage|null; canEdit:boolean; onRefresh:()=>Promise<void>}) {
  const [busy, setBusy] = useState(false);
  const s = (es:string,en:string) => language === "en" ? en : es;
  return <details className="sla"><summary>{s("Tiempo de triaje y ahorro estimado", "Triage time and estimated savings")}</summary>
    <p className="hint">{s("La estimación compara muestras manuales con el tiempo de ciclo automático y la revisión humana registrada. Una cifra negativa indica más tiempo consumido.", "The estimate compares manual samples with automated cycle time and recorded human review. A negative value means more time was used.")}</p>
    {value && <div className="metrics">
      <div className="metric">{s("Ciclo medio", "Average cycle")}<p className="rate">{value.average_cycle_seconds?.toFixed(1) ?? "—"} s</p></div>
      <div className="metric">{s("Ahorro estimado", "Estimated savings")}<p className="rate">{value.estimated_hours_saved?.toFixed(3) ?? "—"} h</p></div>
      <div className="metric">{s("Casos comparables", "Comparable cases")}<p className="rate">{value.comparable_reports}</p><p>{s("Revisiones sin medir", "Unmeasured reviews")} · {value.pending_review_measurements}</p></div>
    </div>}
    <p className="hint">{value?.baseline ? `${value.baseline.label} · ${value.baseline.sample_count} ${s("muestras", "samples")} · ${value.baseline.average_seconds.toFixed(1)} s` : s("Registra una línea base manual para calcular el ahorro.", "Record a manual baseline to estimate savings.")}</p>
    {Boolean(value?.demo_comparisons || value?.baseline?.is_demo) && <p className="review">{s("Incluye muestras de demostración. Presenta esta estimación como ilustrativa.", "Includes demo samples. Present this estimate as illustrative.")}</p>}
    {canEdit && <form className="next" onSubmit={async e => {
      e.preventDefault(); const form=e.currentTarget; const data=new FormData(form); setBusy(true);
      try { await request("/api/triage/baselines",token,{method:"POST",body:JSON.stringify({label:data.get("label"),seconds:String(data.get("seconds")).split(/[\s,;]+/).filter(Boolean).map(Number),is_demo:data.get("is_demo")==="on"})}); form.reset(); await onRefresh(); } catch(cause) { onError(cause); } finally { setBusy(false); }
    }}>
      <label>{s("Nombre de la medición", "Measurement name")}<input name="label" minLength={5} maxLength={150} required /></label>
      <label>{s("Tiempos manuales en segundos, separados por coma. Mínimo 3.", "Manual times in seconds, comma separated. At least 3.")}<input name="seconds" required placeholder="120, 135, 110" /></label>
      <label className="check"><input name="is_demo" type="checkbox" />{s("Datos de demostración", "Demo data")}</label><button disabled={busy}>{s("Registrar línea base", "Record baseline")}</button>
    </form>}
  </details>;
}

if (document.getElementById("root")) createRoot(document.getElementById("root")!).render(<App />);
