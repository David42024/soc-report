import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BarChart, Bar, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { ApiError, downloadFile, request, stage, selectedReports, readPreference, type Report, type User, type Role, type Metrics, type Triage, type Audit, type Event } from "./api";
import { translate, teamNames } from "./i18n";
import "./styles.css";
import { ChatWidget } from "./ChatWidget";
import { ImpactPanel } from "./ImpactPanel";
import { OperationalImpactPanel } from "./OperationalImpactPanel";
import { DashboardPanel } from "./DashboardPanel";
import { useAuditVisit } from "./navigation";
import { CollaborationPanel, OperationsPanel, ProfilePanel, type Section } from "./OperationsPanels";
import { Avatar, Badge, Button, DataTable, EmptyState, ExportMenu, Icon, KpiCard, LoadingBlock, type IconName, type Tone } from "./ui";
import { Preferences } from "./Preferences";
import { WorkspaceHeader } from "./WorkspaceHeader";

const roles: Role[] = ["administrador", "analista", "gestor", "auditor"];
type View = "login" | "intake" | "inbox" | "dashboard" | "impact" | "operations" | "audit" | "users" | "profile";
const severityTone: Record<string, Tone> = { critica: "critical", alta: "high", media: "medium", baja: "low" };
const laneTones = ["warning", "info", "success"] as const;
const laneIcons = ["clock", "pulse", "check"] as const;

export function App() {
  const [language, setLanguage] = useState(readPreference("language", "es"));
  const [theme, setTheme] = useState(readPreference("theme", "system"));
  const [view, setView] = useState<View>("login");
  const [menuOpen, setMenuOpen] = useState(false);
  const sidebarMenu = useRef<HTMLDivElement>(null);
  const menuToggle = useRef<HTMLButtonElement>(null);
  const workspace = useRef<HTMLElement>(null);
  const [sidebarCompact, setSidebarCompact] = useState(false);
  const [passwordVisible, setPasswordVisible] = useState(false);
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
  const [signingOut, setSigningOut] = useState(false);
  const [needsFactor, setNeedsFactor] = useState(false);
  const [receipt, setReceipt] = useState<Report | null>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const pending = useRef<{ body: string; key: string }>();
  const refreshSequence = useRef(0);
  const [chatOpen, setChatOpen] = useState(false);
  const [noticeVersion, setNoticeVersion] = useState(0);
  const token = session?.access_token || "";
  const role = session?.user.role;
  const canRead = Boolean(role && role !== "auditor");
  const canWrite = role === "administrador" || role === "analista";
  const canAudit = role === "administrador" || role === "auditor";
  const canBaseline = role === "administrador" || role === "gestor";
  const canExportReports = role === "administrador" || role === "gestor";
  const activeModule = view === "operations" ? section : view;
  const closeView = useAuditVisit(token, activeModule);
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

  useEffect(() => {
    if (menuOpen) sidebarMenu.current?.querySelector<HTMLButtonElement>("nav button")?.focus();
  }, [menuOpen]);

  useEffect(() => {
    if (workspace.current) {
      workspace.current.scrollTop = 0;
      if (token) workspace.current.focus({ preventScroll: true });
    }
  }, [view, section, token]);

  function returnToSignIn() {
    refreshSequence.current++;
    setSession(null); setReports([]); setMetrics(null); setTriage(null);
    setFocusedReport(undefined); setSection("notificaciones");
    setBusy(false); setNeedsFactor(false);
    setPasswordVisible(false);
    setMenuOpen(false);
    setNotice(""); setError(""); setView("login");
  }

  function navigate(next: View) {
    setView(next); setMenuOpen(false); setError(""); setNotice("");
    setPasswordVisible(false);
  }

  function fail(cause: unknown, authToken = token) {
    if (authToken && cause instanceof ApiError && cause.status === 401) returnToSignIn();
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
    } catch (cause) { if (sequence === refreshSequence.current) fail(cause, authToken); }
    finally { if (sequence === refreshSequence.current) setBusy(false); }
  }

  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true); setError("");
    try {
      const result = await request<{ access_token: string; user: User }>("/api/auth/login", "", { method: "POST", body: JSON.stringify(data) });
      setNeedsFactor(false);
      setPasswordVisible(false);
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
    setSigningOut(true);
    setError("");
    try {
      await Promise.all([closeView(), closeChat()]);
      await request("/api/auth/logout", token, { method: "POST" });
      returnToSignIn();
    } catch (cause) {
      fail(cause);
    } finally {
      setSigningOut(false);
    }
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

  const modules: [View, string, IconName][] = [["intake", t("newReport"), "report"]];
  if (canRead) modules.push(["inbox", t("board"), "board"], ["dashboard", s("Dashboard e informes", "Dashboard and reports"), "chart"],
    ["impact", s("Evolución", "Trends"), "trend"]);
  const administration: [View, string, IconName][] = [];
  if (canAudit) administration.push(["audit", s("Auditoría", "Audit"), "audit"]);
  if (role === "administrador") administration.push(["users", s("Usuarios", "Users"), "users"]);
  const profile: [View, string, IconName][] = [["profile", s("Mi perfil", "My profile"), "user"]];
  const operations: [Section, string, IconName][] = [["notificaciones", s("Notificaciones", "Notifications"), "bell"],
    ["activos", s("Activos", "Assets"), "assets"], ["equipos", s("Equipos", "Teams"), "users"], ["salud", s("Salud de servicios", "Service health"), "pulse"]];
  if (canWrite) operations.push(["revision", s("Revisión humana", "Human review"), "search"]);
  if (role === "administrador") operations.push(["reglas", s("Reglas y SLA", "Rules and SLA"), "rules"]);
  const page = view === "operations" ? operations.find(([key]) => key === section) :
    [...modules, ...administration, ...profile].find(([key]) => key === view);
  const navigation = (label: string, items: [View, string, IconName][]) => <nav className="views" aria-label={label}>
    <p className="sidebar-group">{label}</p>
    {items.map(([key, title, icon]) => <button type="button" key={key} aria-current={view === key ? "page" : undefined}
      aria-label={title} title={title} onClick={() => navigate(key)}><Icon name={icon} /><span className="nav-label">{title}</span></button>)}
  </nav>;

  return <>
    {!session && <header className="site-header"><div className="shell header-layout">
      <div className="brand-lockup"><Icon name="shield" /><p>SOC Report Router</p></div>
      <Preferences compact language={language} theme={theme} onLanguage={setLanguage} onTheme={setTheme} />
    </div></header>}
    <div className={session ? "app-layout" + (sidebarCompact ? " is-compact" : "") + (chatOpen ? " has-chat" : "") : undefined}>
    {session && <aside className="sidebar" aria-label={s("Área de trabajo", "Workspace")}
      onKeyDown={event => { if (event.key === "Escape" && menuOpen) { setMenuOpen(false); menuToggle.current?.focus(); } }}>
      <div className="sidebar-header">
        <p className="brand-lockup" aria-label="SOC Report Router"><Icon name="shield" /><span className="nav-label">SOC Report Router</span></p>
        <button type="button" className="ghost sidebar-collapse" aria-expanded={!sidebarCompact} aria-controls="sidebar-menu"
          aria-label={sidebarCompact ? s("Ampliar menú lateral", "Expand sidebar") : s("Compactar menú lateral", "Collapse sidebar")}
          onClick={() => setSidebarCompact(!sidebarCompact)}><Icon name="collapse" /></button>
      </div>
      <div id="sidebar-menu" ref={sidebarMenu} className={menuOpen ? "sidebar-menu is-open" : "sidebar-menu"}>
        {navigation(s("Principal", "Main"), modules)}
        {canRead && <nav className="views" aria-label={s("Operaciones", "Operations")}>
          <p className="sidebar-group">{s("Operaciones", "Operations")}</p>
          {operations.map(([key, label, icon]) => <button type="button" key={key} aria-label={label} title={label}
            aria-current={view === "operations" && section === key ? "page" : undefined}
            onClick={() => { setSection(key); navigate("operations"); }}><Icon name={icon} /><span className="nav-label">{label}</span></button>)}
        </nav>}
        {administration.length > 0 && navigation(s("Administración", "Administration"), administration)}
        <div className="session">
          <div className="account-card"><Avatar name={session.user.username} />
            <div className="nav-label"><strong>{session.user.username}</strong><p>{roleLabel(session.user.role)}</p></div></div>
        </div>
      </div>
    </aside>}
    <div className={session ? "workspace-column" : undefined}>
      {session && page && <WorkspaceHeader title={page[1]} icon={page[2]} user={session.user} roleLabel={roleLabel(session.user.role)}
        token={token} language={language} theme={theme} onLanguage={setLanguage} onTheme={setTheme} signingOut={signingOut}
        onLogout={logout} onProfile={() => navigate("profile")} activeModule={activeModule} noticeVersion={noticeVersion}
        onNotifications={() => { setSection("notificaciones"); navigate("operations"); }}
        menuOpen={menuOpen} onMenu={() => setMenuOpen(!menuOpen)} menuButtonRef={menuToggle} />}
    <main ref={workspace} tabIndex={-1} className={session ? "workspace" : "shell public-workspace"}>
      {error && view !== "login" && <p role="alert" className="notice error">{error}</p>}
      {notice && <p role="status" className="notice">{notice}</p>}
      {view === "intake" && <section className="panel narrow" aria-labelledby={session ? "module-title" : "report-heading"}>
        {!session && <h2 id="report-heading">{t("newReport")}</h2>}<p className="intro">{t("intakeIntro")}</p>
        <form id="report-form" onSubmit={submit}><fieldset disabled={sending}>
          <label htmlFor="titulo">{t("title")}</label><input id="titulo" name="titulo" minLength={5} maxLength={120} placeholder={t("titleExample")} required />
          <label htmlFor="descripcion">{t("description")}</label><textarea id="descripcion" name="descripcion" minLength={15} maxLength={4000} placeholder={t("descriptionExample")} required />
          <p className="hint">{t("descriptionHelp")}</p><button>{t("submit")}</button>
        </fieldset></form>
        <output className="notice" role="status">{sending ? t("sending") : receipt ? `${t("received")} ${receipt.notificado_at ? t("notified", team(receipt.responsable)) : t("routePending")}\nID: ${receipt.id}` : ""}</output>
        {sendError && <p role="alert" className="notice error">{sendError}</p>}
        {!session && <button type="button" className="secondary next" onClick={() => navigate("login")}>{s("Volver a iniciar sesión", "Back to sign in")}</button>}
        {receipt && canRead && <button type="button" className="secondary next" onClick={() => navigate("inbox")}>{t("viewBoard")}</button>}
      </section>}
      {view === "login" && !session && <div className="access-grid">
        <aside className="access-brand">
          <div className="brand-emblem"><Icon name="shield" /></div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <p className="access-title">SOC Report Router</p>
          <p>{t("tagline")}</p>
        </aside>
        <section className="panel login-panel" aria-labelledby="login-title">
        <h2 id="login-title">{s("Iniciar sesión", "Sign in")}</h2><p className="intro">{s("Accede a tu área de trabajo con tu cuenta SOC.", "Use your SOC account to access your workspace.")}</p>
        {error && <p role="alert" className="notice error login-error">{error}</p>}
        <form onSubmit={login}><label htmlFor="username">{s("Usuario", "Username")}</label><input id="username" name="username" autoComplete="username" required />
          <label className="next" htmlFor="password">{s("Contraseña", "Password")}</label>
          <div className="password-field"><input id="password" name="password" type={passwordVisible ? "text" : "password"} autoComplete="current-password" required />
            <button type="button" className="ghost" aria-label={passwordVisible ? s("Ocultar contraseña", "Hide password") : s("Mostrar contraseña", "Show password")}
              onClick={() => setPasswordVisible(!passwordVisible)}><Icon name={passwordVisible ? "eyeOff" : "eye"} /></button>
          </div>
          {needsFactor && <><label htmlFor="otp">{s("Código de segundo factor o recuperación", "Second factor or recovery code")}</label>
            <input id="otp" name="otp" autoComplete="one-time-code" minLength={6} maxLength={48} required /></>}
          <Button type="submit" className="next" disabled={busy}>{busy ? s("Ingresando…", "Signing in…") : s("Ingresar", "Sign in")}</Button></form>
        <div className="public-report-link">
          <p className="hint">{s("¿Necesitas reportar un incidente?", "Need to report an incident?")}</p>
          <button type="button" className="secondary" disabled={busy} onClick={() => navigate("intake")}>{s("Reportar sin iniciar sesión", "Report without signing in")}</button>
        </div>
        </section>
      </div>}
      {view === "inbox" && canRead && <section className="panel" aria-labelledby="module-title">
        {focusedReport && <div className="sla">
          <button className="secondary" type="button" onClick={() => setFocusedReport(undefined)}>{s("Cerrar reporte seleccionado", "Close selected report")}</button>
          <ReportCard key={focusedReport.id} report={focusedReport} token={token} language={language} canWrite={canWrite} onAction={action} onError={fail} />
        </div>}
        <div className="list-toolbar"><div><p className="hint">{t("count", filtered.length, reports.length, reports.filter(r => stage(r) !== 2).length)}</p></div>
          <div className="flex flex-wrap gap-2"><button className="secondary" disabled={busy} onClick={() => refresh()}>{busy ? t("loading") : t("refreshBoard")}</button>
            {canExportReports && <ExportMenu label={s("Exportar", "Export")} disabled={busy} onSelect={download} />}</div>
        </div>
        {metrics && <section className="sla" aria-label={t("sla")}><h3>{t("sla")}</h3><div className="metrics">{[
          ["firstResponse", metrics.respuesta_a_tiempo, metrics.respuesta_evaluable], ["resolution", metrics.resolucion_a_tiempo, metrics.resolucion_evaluable],
        ].map(([label, passed, total]) => <KpiCard key={String(label)} title={t(String(label))} icon="clock"
          value={total ? new Intl.NumberFormat(language, { style: "percent", maximumFractionDigits: 1 }).format(Number(passed) / Number(total)) : "—"}>
          {total ? t("onTimeCount", Number(passed), Number(total)) : t("notEvaluated")}</KpiCard>)}</div><p className="hint">{t("slaHelp")}</p>
          {counts.length > 0 && <details className="next"><summary>{s("Reportes por tipo", "Reports by type")}</summary><div className="chart" role="img" aria-label={s("Reportes por tipo", "Reports by type")}><ResponsiveContainer width="100%" height={220}><BarChart data={counts}><XAxis dataKey="name" tick={{ fill: "var(--text)", fontSize: 12 }} /><YAxis allowDecimals={false} tick={{ fill: "var(--text)" }} /><Tooltip contentStyle={{ background: "var(--panel)", color: "var(--text)" }} /><Bar dataKey="cases" name={s("Casos", "Cases")} isAnimationActive={false}>{counts.map(({ name }, index) => <Cell key={name} fill={`var(--chart-${index % 8 + 1})`} />)}</Bar></BarChart></ResponsiveContainer></div></details>}
        </section>}
        <div className="list-toolbar"><label>{t("show")} <select aria-label={t("show")} value={filter} onChange={e => setFilter(e.target.value)}>{[["todos", "all"], ["pendientes", "pending"], ["revision", "reviewFilter"], ["resueltos", "resolved"]].map(([value, key]) => <option key={value} value={value}>{t(key)}</option>)}</select></label></div>
        {busy && !metrics && <LoadingBlock label={t("loading")} />}
        <div className="board" aria-busy={busy}>{["laneNew", "laneProgress", "laneDone"].map((label, lane) => {
          const items = filtered.filter(report => stage(report) === lane);
          return <section className="lane" key={label} aria-label={t(label)} data-tone={laneTones[lane]}>
            <h3 className="lane-header"><Icon name={laneIcons[lane]} />{t(label)}<span>{items.length}</span></h3><div className="report-list">{items.map(report =>
            <ReportCard key={report.id} report={report} token={token} language={language} canWrite={canWrite} onAction={action} onError={fail} />
          )}{!items.length && !busy && <EmptyState>{t("emptyLane")}</EmptyState>}</div></section>;
        })}</div>
        <TriagePanel value={triage} canEdit={canBaseline} language={language} token={token} onRefresh={() => refresh()} onError={fail} />
      </section>}
      {view === "users" && role === "administrador" && <UsersPanel token={token} language={language} onError={fail} />}
      {view === "audit" && canAudit && <AuditPanel token={token} language={language} onError={fail} />}
      {view === "impact" && canRead && <>
        <OperationalImpactPanel token={token} language={language} canManage={canBaseline} onError={fail} />
        <ImpactPanel token={token} language={language} onError={fail} />
      </>}
      {view === "dashboard" && canRead && <DashboardPanel token={token} language={language} canExport={canExportReports} onError={fail} />}
      {view === "operations" && canRead && <OperationsPanel token={token} language={language} onError={fail}
        section={section} canWrite={canWrite} admin={role === "administrador"} openReport={openReport}
        onNotificationsChanged={() => setNoticeVersion(version => version + 1)} />}
      {view === "profile" && session && <ProfilePanel token={token} language={language} user={session.user} onError={fail}
        onChanged={message => {
          returnToSignIn();
          setNotice(message ?? s("Contraseña cambiada. Inicia sesión de nuevo.", "Password changed. Sign in again."));
        }} />}
    </main>
    </div>
    </div>
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
  const remainingMinutes = next ? (Date.parse(next) - Date.now()) / 60000 : 0;
  const late = remainingMinutes < 0;
  const dueSoon = !late && remainingMinutes <= 240;
  const relative = new Intl.RelativeTimeFormat(language, { style: "short" });
  const delta = Math.trunc(remainingMinutes);
  const relativeDeadline = Math.abs(delta) >= 60 ? relative.format(Math.trunc(delta / 60), "hour") : relative.format(delta, "minute");
  const state = !report.notificado_at ? "needsRouting" : !report.respondido_at ? "needsResponse" : report.resuelto_at ? "done" : "needsResolution";
  const severity = severityTone[report.severidad] || "neutral";
  return <article className="report" data-tone={severity}>
    <div className="report-heading"><h4>{report.titulo}</h4></div>
    <div className="chip-row"><Badge tone={laneTones[stage(report)]} icon={laneIcons[stage(report)]}>{t(state)}</Badge>
      <Badge tone={severity} icon={severity === "critical" || severity === "high" ? "warning" : "info"}>{t("severity", t(report.severidad))}</Badge>
      <Badge>{t(report.tipo)}</Badge>
      {(report.titulo.startsWith("[DEMO]") || report.origen === "demo") && <Badge tone="demo">DEMO</Badge>}
    </div>
    <p>{team}</p><p className="hint">{t("receivedOn", date(report.recibido_at))}</p>
    {report.motivo_revision && <p className="hint review">{t("review", t(report.motivo_revision))}</p>}
    {next && !report.resuelto_at && <div className="chip-row">
      <Badge tone={late ? "danger" : dueSoon ? "warning" : "success"} icon={late ? "warning" : "clock"}>
        {t(late ? "slaLate" : dueSoon ? "slaSoon" : "slaOnTrack")} · {relativeDeadline}
      </Badge>
      <p className="hint">{t(report.respondido_at ? "resolution" : "firstResponse")} · {t(late ? "overdue" : "deadline")} {date(next)}</p>
    </div>}
    {canWrite && <div className="report-footer">
      {!report.notificado_at && <button disabled={busy} onClick={() => run(() => onAction(report.id, "reintentar"))}>{t("retry")}</button>}
      {report.responsable && !report.respondido_at && <button disabled={busy} onClick={() => run(() => onAction(report.id, "responder"))}>{t("respond")}</button>}
      {report.respondido_at && !report.resuelto_at && <button disabled={busy} onClick={() => run(() => onAction(report.id, "resolver"))}>{t("resolve")}</button>}
    </div>}
    <details className="report-details"><summary>{t("details")}</summary>
      <p className="description">{report.descripcion}</p><p className="hint">{t("asset", report.activo_afectado || t("unknown"))}</p>
      <p className="hint">{t("source", t(report.origen))} · ID <code>{report.id}</code></p>
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
  const [loading, setLoading] = useState(true);
  const s = (es: string, en: string) => language === "en" ? en : es;
  const labels = language === "en" ? ["Administrator", "Analyst", "Manager", "Auditor"] : ["Administrador", "Analista", "Gestor", "Auditor"];
  async function load() {
    setLoading(true);
    try { setUsers(await request<User[]>("/api/users", token)); }
    catch (cause) { onError(cause); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [token]);
  return <section className="panel" aria-labelledby="module-title">
    <form className="admin-create grid gap-3 md:grid-cols-4" onSubmit={async e => {
      e.preventDefault(); const form = e.currentTarget; setBusy(true);
      try { await request("/api/users", token, {method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(form)))}); form.reset(); await load(); } catch (cause) { onError(cause); } finally { setBusy(false); }
    }}>
      <label>{s("Usuario", "Username")}<input name="username" pattern="[a-zA-Z0-9_.-]+" required maxLength={80} autoComplete="off" /></label>
      <label>{s("Contraseña inicial", "Initial password")}<input name="password" type="password" minLength={12} maxLength={128} required autoComplete="new-password" /></label>
      <label>{s("Rol", "Role")}<select name="role">{roles.map((role, i) => <option key={role} value={role}>{labels[i]}</option>)}</select></label>
      <button disabled={busy}>{s("Crear usuario", "Create user")}</button>
    </form>
    {loading && <LoadingBlock label={s("Cargando usuarios…", "Loading users…")} />}
    {!loading && !users.length && <p className="empty next">{s("No hay usuarios para mostrar.", "No users to display.")}</p>}
    <div className="grid gap-3 mt-5">{users.map(user => <form key={`${user.id}-${user.role}-${user.active}`} className="user-row" onSubmit={async e => {
      e.preventDefault(); const data = new FormData(e.currentTarget); setBusy(true);
      try { await request(`/api/users/${user.id}`, token, {method:"PUT",body:JSON.stringify({role:data.get("role"),active:data.get("active")==="on",password:data.get("password") || null})}); await load(); } catch (cause) { onError(cause); } finally { setBusy(false); }
    }}>
      <div className="user-identity"><strong>{user.username}</strong><Badge tone={user.role === "administrador" ? "info" : "neutral"}>{labels[roles.indexOf(user.role)]}</Badge></div>
      <label>{s("Rol", "Role")}<select name="role" defaultValue={user.role}>{roles.map((role, i) => <option key={role} value={role}>{labels[i]}</option>)}</select></label>
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
  const phaseTones: Record<string, Tone> = { entry: "info", exit: "success", rejected: "danger" };
  const outcomeTones: Record<string, Tone> = { iniciado: "info", completado: "success", rechazado: "danger", error: "danger", expirado: "warning" };
  async function load(append = false) {
    setBusy(true);
    try {
      const cursor = append && rows.length ? `&before=${rows.at(-1)!.id}` : "";
      const page = await request<Audit[]>(`/api/audit?limit=100${cursor}${query && "&" + query}`, token);
      setRows(append ? [...rows, ...page] : page); setMore(page.length === 100);
    } catch(cause) { onError(cause); } finally { setBusy(false); }
  }
  useEffect(() => { load(); }, [token, query]);
  return <section className="panel" aria-labelledby="module-title"><div className="list-toolbar"><div><p className="hint">{s("Entradas, salidas y cambios críticos registrados por el servidor.", "Request entry, exit, and critical changes recorded by the server.")}</p></div><button disabled={busy} onClick={() => load()}>{s("Actualizar", "Refresh")}</button></div>
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
    <div className="filter-actions"><ExportMenu label={s("Exportar", "Export")} disabled={busy} onSelect={format =>
      void downloadFile(`/api/audit/exportar/${format}?${query}`, token, "soc-auditoria." + format).catch(onError)} /></div>
    {busy && !rows.length && <LoadingBlock label={s("Cargando auditoría…", "Loading audit log…")} />}
    {!busy && !rows.length && <EmptyState>{s("No hay registros para estos filtros.", "No entries match these filters.")}</EmptyState>}
    {rows.length > 0 && <DataTable className="audit-table" label={s("Registros de auditoría", "Audit entries")}><table><thead><tr>{[s("Fecha", "Date"),s("Usuario", "User"),s("Rol", "Role"),s("Acción", "Action"),s("Módulo", "Module"),"IP",s("Fase", "Phase"),s("Resultado", "Outcome"),"HTTP",s("Solicitud", "Request")].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.id}>
      <td className="timestamp">{new Date(row.occurred_at).toLocaleString(language)}</td><td className="identifier">{row.user_id}</td>
      <td><Badge tone={row.role === "administrador" ? "info" : "neutral"}>{row.role}</Badge></td>
      <td>{row.action}</td><td>{row.module}</td><td>{row.ip}</td>
      <td><Badge tone={phaseTones[row.phase]}>{row.phase}</Badge></td>
      <td>{row.outcome ? <Badge tone={outcomeTones[row.outcome]}>{row.outcome}</Badge> : "—"}</td>
      <td>{row.status_code ?? "—"}</td><td className="identifier">{row.request_id || "—"}</td>
    </tr>)}</tbody></table></DataTable>}
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
