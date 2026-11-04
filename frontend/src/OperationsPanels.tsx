import { FormEvent, useEffect, useState } from "react";
import { downloadFile, request, type Report, type User } from "./api";
import { translate } from "./i18n";
import { TotpPanel } from "./TotpPanel";
import { Badge, DataTable, EmptyState, LoadingBlock, type Tone } from "./ui";

interface Props { token: string; language: string; onError: (error: unknown) => void }
interface Asset { id: string; nombre: string; descripcion: string; activo: number }
interface Team { nombre: string; contacto: string; disponible: number | null; abiertos: number }
interface Notice { report_id: string; titulo: string; responsable: string; ocurrido_at: string; read_at: string | null }
interface Health { estado: string; servicios: Record<string, string>;
  proveedores?: Record<string, { estado: string; verificado_at: string | null; vigente: boolean; motivo?: string | null }> }
export type Section = "activos" | "equipos" | "revision" | "notificaciones" | "reglas" | "salud";
type ReviewReport = Pick<Report, "id" | "titulo" | "descripcion" | "tipo" | "severidad" | "activo_afectado" | "motivo_revision">;
const types = ["phishing", "malware", "acceso_no_autorizado", "ddos", "fuga_datos", "vulnerabilidad", "uso_indebido", "incidente_fisico", "fraude", "otro"];
const severities = ["critica", "alta", "media", "baja"];
interface Policy { equipos: Record<string, string>; equipo_revision: string; sla: Record<string, { respuesta_min: number; resolucion_min: number }>; umbral: number }
interface Version { id: string | null; configuration: Policy }
interface RuleData { actual: Version; versiones: { id: string; created_by: string; created_at: string }[] }

export function ProfilePanel({ token, language, onError, onChanged, user }: Props & { user: User; onChanged: (notice?: string) => void }) {
  const [busy, setBusy] = useState(false);
  const s = (es: string, en: string) => language === "es" ? es : en;
  async function change(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (data.nueva !== data.confirmacion) {
      onError(new Error(s("Las contraseñas nuevas deben coincidir.", "The new passwords must match.")));
      return;
    }
    setBusy(true);
    try {
      await request("/api/auth/password", token, { method: "POST", body: JSON.stringify({ actual: data.actual, nueva: data.nueva }) });
      onChanged();
    } catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  return <section className="panel narrow" aria-labelledby="module-title">
    <p>{user.username} · {user.role}</p>
    <form className="next" onSubmit={change}>
      <h3>{s("Cambiar contraseña", "Change password")}</h3>
      <label>{s("Contraseña actual", "Current password")}<input name="actual" type="password" autoComplete="current-password" maxLength={128} required /></label>
      <label>{s("Nueva contraseña", "New password")}<input name="nueva" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label>
      <label>{s("Confirmar contraseña", "Confirm password")}<input name="confirmacion" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label>
      <p className="hint">{s("El cambio cierra tus sesiones.", "Changing your password signs out your sessions.")}</p>
      <button disabled={busy}>{s("Guardar contraseña", "Save password")}</button>
    </form>
    <TotpPanel token={token} language={language} onError={onError} onChanged={onChanged} />
  </section>;
}

export function OperationsPanel(props: Props & { section: Section; canWrite: boolean; admin: boolean; openReport: (id: string) => void; onNotificationsChanged: () => void }) {
  const { section, canWrite, admin } = props;
  return <section className="panel" aria-labelledby="module-title">
    {section === "activos" && <AssetsPanel {...props} />}
    {section === "equipos" && <TeamsPanel {...props} />}
    {section === "revision" && canWrite && <ReviewPanel {...props} />}
    {section === "notificaciones" && <NotificationsPanel {...props} />}
    {section === "reglas" && admin && <RulesPanel {...props} />}
    {section === "salud" && <HealthPanel {...props} />}
  </section>;
}

function useModule<T>(path: string, { token, onError }: Props) {
  const [data, setData] = useState<T>();
  const [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true);
    try { setData(await request<T>(path, token)); }
    catch (error) { onError(error); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [path, token]);
  async function save(path: string, method: "PUT" | "POST", body?: unknown) {
    setBusy(true);
    try {
      await request(path, token, { method, body: body ? JSON.stringify(body) : undefined });
      await load();
      return true;
    } catch (error) { onError(error); return false; }
    finally { setBusy(false); }
  }
  return { data, busy, load, save };
}

function AssetsPanel(props: Props & { canWrite: boolean }) {
  const { language, canWrite } = props;
  const s = (es: string, en: string) => language === "es" ? es : en;
  const { data, busy, save } = useModule<Asset[]>("/api/activos", props);
  const [editing, setEditing] = useState<Asset>();
  return <div>
    {busy && !data && <LoadingBlock label={s("Cargando activos…", "Loading assets…")} />}
    {data?.length === 0 && <p className="empty next">{s("No hay activos registrados.", "No assets are registered.")}</p>}
    <DataTable label={s("Activos registrados", "Registered assets")}><table><thead><tr><th>{s("Nombre", "Name")}</th><th>{s("Descripción", "Description")}</th><th>{s("Estado", "Status")}</th>{canWrite && <th>{s("Acción", "Action")}</th>}</tr></thead>
      <tbody>{data?.map(item => <tr key={item.id}><td>{item.nombre}</td><td>{item.descripcion}</td><td><Badge tone={item.activo ? "success" : "neutral"}>{item.activo ? s("Activo", "Active") : s("Inactivo", "Inactive")}</Badge></td>
        {canWrite && <td><button className="secondary" onClick={() => setEditing(item)}>{s("Editar", "Edit")}</button></td>}</tr>)}</tbody></table></DataTable>
    {canWrite && <form key={editing?.id || "new"} className="report-filters" onSubmit={async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      if (await save("/api/activos/" + (editing?.id || crypto.randomUUID()), "PUT", {
        nombre: fields.get("nombre"), descripcion: fields.get("descripcion"), activo: fields.has("activo"),
      })) { form.reset(); setEditing(undefined); }
    }}>
      <label>{s("Nombre", "Name")}<input name="nombre" defaultValue={editing?.nombre} maxLength={120} required /></label>
      <label>{s("Descripción", "Description")}<input name="descripcion" defaultValue={editing?.descripcion} maxLength={500} /></label>
      <label className="check"><input type="checkbox" name="activo" defaultChecked={editing ? Boolean(editing.activo) : true} />{s("Activo", "Active")}</label>
      <button disabled={busy}>{editing ? s("Guardar", "Save") : s("Registrar activo", "Add asset")}</button>
      {editing && <button type="button" className="secondary" onClick={() => setEditing(undefined)}>{s("Cancelar", "Cancel")}</button>}
    </form>}
  </div>;
}

function TeamsPanel(props: Props & { admin: boolean }) {
  const { language, admin } = props;
  const s = (es: string, en: string) => language === "es" ? es : en;
  const { data, busy, save } = useModule<Team[]>("/api/equipos", props);
  const [editing, setEditing] = useState<Team>();
  return <div>
    <p className="hint">{s("La disponibilidad es informativa. Las asignaciones se deciden con la versión de reglas vigente al recibir cada caso.", "Availability is informational. Assignments follow the policy in effect when each case was received.")}</p>
    {busy && !data && <LoadingBlock label={s("Cargando equipos…", "Loading teams…")} />}
    {data?.length === 0 && <p className="empty next">{s("No hay equipos registrados.", "No teams are registered.")}</p>}
    <DataTable label={s("Equipos registrados", "Registered teams")}><table><thead><tr><th>{s("Equipo", "Team")}</th><th>{s("Responsable o contacto", "Owner or contact")}</th>
      <th>{s("Disponibilidad", "Availability")}</th><th>{s("Casos abiertos", "Open cases")}</th>{admin && <th>{s("Acción", "Action")}</th>}</tr></thead>
      <tbody>{data?.map(item => <tr key={item.nombre}><td>{item.nombre}</td><td>{item.contacto || "—"}</td>
        <td>{item.disponible === null ? "—" : <Badge tone={item.disponible ? "success" : "warning"}>{item.disponible ? s("Disponible", "Available") : s("No disponible", "Unavailable")}</Badge>}</td><td>{item.abiertos}</td>
        {admin && <td><button className="secondary" onClick={() => setEditing(item)}>{s("Editar", "Edit")}</button></td>}</tr>)}</tbody></table></DataTable>
    {admin && <form key={editing?.nombre || "new"} className="report-filters" onSubmit={async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fields = new FormData(form);
      if (await save("/api/equipos", "PUT", { nombre: fields.get("nombre"), contacto: fields.get("contacto"), disponible: fields.has("disponible") })) {
        form.reset(); setEditing(undefined);
      }
    }}>
      <label>{s("Equipo", "Team")}<input name="nombre" defaultValue={editing?.nombre} readOnly={Boolean(editing)} maxLength={120} required /></label>
      <label>{s("Contacto", "Contact")}<input name="contacto" defaultValue={editing?.contacto} maxLength={120} /></label>
      <label className="check"><input type="checkbox" name="disponible" defaultChecked={editing?.disponible !== 0} />{s("Disponible", "Available")}</label>
      <button disabled={busy}>{s("Guardar equipo", "Save team")}</button>
      {editing && <button type="button" className="secondary" onClick={() => setEditing(undefined)}>{s("Cancelar", "Cancel")}</button>}
    </form>}
  </div>;
}

function ReviewForm({ report, language, disabled, onSave }: {
  report: ReviewReport; language: string; disabled: boolean;
  onSave: (value: { tipo: string; severidad: string; activo_afectado: string | null; seconds: number | null }) => Promise<unknown>;
}) {
  const s = (es: string, en: string) => language === "es" ? es : en;
  return <form className="report-filters" onSubmit={event => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const seconds = data.get("seconds");
    void onSave({
      tipo: String(data.get("tipo")), severidad: String(data.get("severidad")),
      activo_afectado: String(data.get("activo_afectado")).trim() || null,
      seconds: seconds === "" ? null : Number(seconds),
    });
  }}>
    <label>{s("Tipo validado", "Validated type")}<select name="tipo" defaultValue={report.tipo}>
      {types.map(type => <option key={type} value={type}>{translate(language, type)}</option>)}
    </select></label>
    <label>{s("Severidad validada", "Validated severity")}<select name="severidad" defaultValue={report.severidad}>
      {severities.map(type => <option key={type} value={type}>{translate(language, type)}</option>)}
    </select></label>
    <label>{s("Activo validado", "Validated asset")}<input name="activo_afectado" maxLength={160} defaultValue={report.activo_afectado || ""} /></label>
    <label>{s("Tiempo de revisión en segundos", "Review time in seconds")}<input name="seconds" type="number" min={0} max={86400} step="any" /></label>
    <button disabled={disabled}>{s("Guardar revisión", "Save review")}</button>
  </form>;
}

function ReviewPanel(props: Props) {
  const { language } = props;
  const s = (es: string, en: string) => language === "es" ? es : en;
  const { data, busy, load, save } = useModule<ReviewReport[]>("/api/revision", props);
  return <div><div className="list-toolbar">
    <button type="button" className="secondary" disabled={busy} onClick={load}>{s("Actualizar", "Refresh")}</button></div>
    {busy && !data && <LoadingBlock label={s("Cargando casos…", "Loading cases…")} />}
    {data?.length === 0 && <EmptyState>{s("No hay casos en revisión.", "No cases pending review.")}</EmptyState>}
    {data?.map(report => <details key={report.id} className="sla"><summary>{report.titulo}</summary>
      <p className="description">{report.descripcion}</p><p className="hint">{report.motivo_revision}</p>
      <ReviewForm report={report} language={language} disabled={busy} onSave={body => save("/api/reportes/" + report.id + "/revision", "PUT", body)} />
    </details>)}
  </div>;
}

function NotificationsPanel(props: Props & { openReport: (id: string) => void; onNotificationsChanged: () => void }) {
  const { language, openReport } = props;
  const s = (es: string, en: string) => language === "es" ? es : en;
  const { data, busy, load, save } = useModule<Notice[]>("/api/notificaciones", props);
  return <div><div className="list-toolbar">
    <button type="button" className="secondary" disabled={busy} onClick={load}>{s("Actualizar", "Refresh")}</button></div>
    {busy && !data && <LoadingBlock label={s("Cargando notificaciones…", "Loading notifications…")} />}
    {data?.length === 0 && <EmptyState>{s("Todavía no hay notificaciones.", "There are no notifications yet.")}</EmptyState>}
    <div className="report-list">{data?.map(item => <article className="report" data-tone={item.read_at ? "neutral" : "info"} key={item.report_id}>
      <h4>{item.titulo}</h4><p>{item.responsable} · {new Date(item.ocurrido_at).toLocaleString(language)}</p>
      <div className="report-footer">
        <button type="button" className="secondary" onClick={() => openReport(item.report_id)}>{s("Ver reporte", "View report")}</button>
        {item.read_at ? <Badge tone="success" icon="check">{s("Leída", "Read")}</Badge> : <button type="button" disabled={busy}
          onClick={async () => { if (await save("/api/notificaciones/" + item.report_id + "/leida", "PUT")) props.onNotificationsChanged(); }}>{s("Marcar leída", "Mark read")}</button>}
      </div>
    </article>)}</div>
  </div>;
}

function RulesPanel(props: Props) {
  const { language, token, onError } = props;
  const s = (es: string, en: string) => language === "es" ? es : en;
  const { data, busy, save } = useModule<RuleData>("/api/reglas", props);
  const { data: teams } = useModule<Team[]>("/api/equipos", props);
  const [draft, setDraft] = useState<Version>();
  const [notice, setNotice] = useState("");
  const version = draft || data?.actual;
  if (!version || !data || !teams) return <p role="status">{s("Cargando reglas…", "Loading rules…")}</p>;
  const options = teams.map(team => <option key={team.nombre}>{team.nombre}</option>);
  return <div>
    <p className="hint">{s("Publicar crea una versión para nuevos reportes. El historial permite cargar versiones anteriores como borrador.", "Publishing creates a version for new reports. History can load an older version as a draft.")}</p>
    <form key={version.id || "default"} onSubmit={async event => {
      event.preventDefault();
      const fields = new FormData(event.currentTarget);
      const configuration = {
        equipos: Object.fromEntries(types.map(type => [type, fields.get("equipo_" + type)])),
        equipo_revision: fields.get("equipo_revision"),
        sla: Object.fromEntries(severities.map(level => [level, { respuesta_min: Number(fields.get(level + "_respuesta")), resolucion_min: Number(fields.get(level + "_resolucion")) }])),
        umbral: Number(fields.get("umbral")), version_anterior: data.actual.id,
      };
      if (await save("/api/reglas", "POST", configuration)) {
        setDraft(undefined); setNotice(s("Versión publicada.", "Version published."));
      }
    }}>
      <div className="report-filters">
        {types.map(type => <label key={type}>{translate(language, type)}<select name={"equipo_" + type} defaultValue={version.configuration.equipos[type]}>{options}</select></label>)}
        <label>{s("Equipo de revisión", "Review team")}<select name="equipo_revision" defaultValue={version.configuration.equipo_revision}>{options}</select></label>
      </div>
      <div className="report-filters">
        {severities.map(level => <fieldset className="sla" key={level}>
          <legend>{translate(language, level)}</legend>
          <label>{s("Respuesta en minutos", "Response in minutes")}<input required min={1} max={525600} type="number" name={level + "_respuesta"} defaultValue={version.configuration.sla[level].respuesta_min} /></label>
          <label>{s("Resolución en minutos", "Resolution in minutes")}<input required min={1} max={525600} type="number" name={level + "_resolucion"} defaultValue={version.configuration.sla[level].resolucion_min} /></label>
        </fieldset>)}
        <label>{s("Umbral del clasificador", "Classifier threshold")}<input required min={0} max={1} step="any" type="number" name="umbral" defaultValue={version.configuration.umbral} /></label>
      </div>
      <button disabled={busy}>{s("Publicar versión", "Publish version")}</button>
      {notice && <p role="status">{notice}</p>}
    </form>
    <details className="sla"><summary>{s("Historial de versiones", "Version history")}</summary>
      <ul>{data.versiones.map(item => <li key={item.id}>{new Date(item.created_at).toLocaleString(language)} · {item.id}{" "}
        <button className="secondary" type="button" onClick={async () => {
          try { setDraft(await request<Version>("/api/reglas/" + item.id, token)); setNotice(""); }
          catch (error) { onError(error); }
        }}>{s("Cargar como borrador", "Load as draft")}</button>
      </li>)}</ul>
      {draft && <button type="button" className="secondary" onClick={() => setDraft(undefined)}>{s("Volver a la versión activa", "Back to active version")}</button>}
    </details>
  </div>;
}

function HealthPanel(props: Props & { admin: boolean }) {
  const { language, admin, token, onError } = props;
  const s = (es: string, en: string) => language === "es" ? es : en;
  const { data, busy, load } = useModule<Health>("/health?detalle=true", { ...props, token: "" });
  const [checking, setChecking] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date>();
  useEffect(() => { if (data) setCheckedAt(new Date()); }, [data]);
  const statusTone = (status: string): Tone => status === "ok" ? "success" : status === "error" ? "danger" : "neutral";
  async function checkCloud() {
    setChecking(true);
    try { await request("/api/salud/proveedores", token, { method: "POST" }); await load(); }
    catch (error) { onError(error); }
    finally { setChecking(false); }
  }
  return <div><div className="list-toolbar">
    <button disabled={busy} onClick={load}>{s("Comprobar", "Check")}</button></div>
    {busy && !data && <LoadingBlock label={s("Comprobando servicios…", "Checking services…")} />}
    {data && <div className="health-cards">{Object.entries(data.servicios).map(([name, status]) => <article className="health-card" key={name}>
      <h4>{name}</h4><Badge tone={statusTone(status)} icon={status === "ok" ? "check" : "info"}>{status}</Badge>
      {checkedAt && <p className="hint">{s("Consulta", "Checked")} · {checkedAt.toLocaleString(language)}</p>}
    </article>)}</div>}
    <h4>{s("Proveedores cloud", "Cloud providers")}</h4>
    {data?.proveedores && <div className="health-cards">{Object.entries(data.proveedores).map(([name, check]) => <article className="health-card" key={name}>
      <h4>{name}</h4><Badge tone={statusTone(check.estado)} icon={check.estado === "ok" ? "check" : "info"}>{check.estado}</Badge>
      {check.verificado_at && <p className="hint">{new Date(check.verificado_at).toLocaleString(language)}</p>}
      {check.motivo && <p className="hint">{check.motivo}</p>}
      {check.verificado_at && !check.vigente && <Badge tone="warning">{s("resultado anterior", "stale result")}</Badge>}
    </article>)}</div>}
    {admin && <button disabled={checking} onClick={checkCloud}>{s("Probar Groq y Gemini", "Check Groq and Gemini")}</button>}
  </div>;
}

interface Collaboration {
  comentarios: { id: string; contenido: string; author: string; created_at: string }[];
  adjuntos: { id: string; nombre: string; tamano: number }[];
  revision: { tipo: string; severidad: string; activo_afectado: string | null } | null;
}

export function CollaborationPanel(props: Props & { report: ReviewReport; canWrite: boolean }) {
  const { token, language, report, canWrite, onError } = props;
  const s = (es: string, en: string) => language === "es" ? es : en;
  const root = "/api/reportes/" + report.id;
  const { data, busy, save } = useModule<Collaboration>(root + "/colaboracion", props);
  return <div className="next"><h4>{s("Comentarios y adjuntos", "Comments and attachments")}</h4>
    <ul>{data?.comentarios.map(item => <li key={item.id}><strong>{item.author}</strong> · {item.contenido}</li>)}</ul>
    <ul>{data?.adjuntos.map(item => <li key={item.id}><button className="secondary" type="button"
      onClick={() => void downloadFile(root + "/adjuntos/" + item.id, token, item.nombre).catch(onError)}>{item.nombre}</button> · {item.tamano} B</li>)}</ul>
    {canWrite && <>
      <form onSubmit={async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const value = new FormData(form).get("contenido");
        if (await save(root + "/comentarios", "POST", { contenido: value })) form.reset();
      }}>
        <label>{s("Comentario", "Comment")}<textarea name="contenido" maxLength={2000} required /></label>
        <button disabled={busy}>{s("Comentar", "Comment")}</button>
      </form>
      <form className="next" onSubmit={event => {
        event.preventDefault();
        const form = event.currentTarget;
        const file = new FormData(form).get("archivo");
        if (!(file instanceof File) || file.size < 1 || file.size > 2 * 1024 * 1024) {
          onError(new Error(s("Selecciona un archivo de hasta 2 MiB.", "Choose a file up to 2 MiB.")));
          return;
        }
        const reader = new FileReader();
        reader.onerror = () => onError(new Error(s("No se pudo leer el archivo.", "The file could not be read.")));
        reader.onload = async () => {
          if (await save(root + "/adjuntos", "POST", { nombre: file.name, base64: String(reader.result).split(",")[1] })) form.reset();
        };
        reader.readAsDataURL(file);
      }}>
        <label>{s("Adjunto de hasta 2 MiB", "Attachment up to 2 MiB")}<input type="file" name="archivo" required /></label>
        <button disabled={busy}>{s("Adjuntar", "Attach")}</button>
      </form>
    </>}
    <h4 className="next">{s("Revisión de clasificación", "Classification review")}</h4>
    {data?.revision && <p>{translate(language, data.revision.tipo)} · {translate(language, data.revision.severidad)} · {data.revision.activo_afectado || "—"}</p>}
    {canWrite && data && <ReviewForm report={{ ...report, ...data.revision }} language={language} disabled={busy}
      onSave={body => save(root + "/revision", "PUT", body)} />}
  </div>;
}
