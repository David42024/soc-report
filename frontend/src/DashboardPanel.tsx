import { FormEvent, useEffect, useState } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { downloadFile, request } from "./api";
import { translate } from "./i18n";

type Counts = Record<string, number>;
interface Dashboard {
  total: number;
  demo: number;
  estados: Counts;
  tipos: Counts;
  severidades: Counts;
  sla: Counts;
  mensual: { mes: string; total: number; respuesta_a_tiempo?: number; respuesta_evaluable?: number;
    resolucion_a_tiempo?: number; resolucion_evaluable?: number }[];
  tiempos: Record<string, { segundos: number; muestra: number }>;
  equipos: { nombre: string; total: number; abiertos: number }[];
  clasificador: { origen: string; demo: boolean; total: number; revision: number; validados: number; aciertos: number; precision: number | null }[];
}
interface Props {
  token: string;
  language: string;
  canExport: boolean;
  onError: (error: unknown) => void;
}
const reports = [
  ["cola", "Cola operativa", "Work queue"], ["sla", "SLA próximos o vencidos", "Due or overdue SLA"],
  ["pendientes", "Asignaciones pendientes", "Pending assignments"], ["mensual", "Cumplimiento mensual", "Monthly compliance"],
  ["tendencia", "Tendencia de incidentes", "Incident trends"], ["clasificador", "Desempeño del clasificador", "Classifier performance"],
  ["equipos", "Carga por equipo", "Team workload"],
];
const stateLabels: Record<string, [string, string]> = {
  sin_asignar: ["Sin asignar", "Unassigned"], por_atender: ["Por atender", "Awaiting response"],
  en_atencion: ["En atención", "In progress"], resuelto: ["Resuelto", "Resolved"],
};

export function DashboardPanel({ token, language, canExport, onError }: Props) {
  const [data, setData] = useState<Dashboard>();
  const [teams, setTeams] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("cola");
  const [busy, setBusy] = useState(true);
  const s = (es: string, en: string) => language === "es" ? es : en;
  const label = (key: string) => stateLabels[key]?.[language === "es" ? 0 : 1] ?? translate(language, key);
  const number = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
  const percent = (ratio: number | null) => ratio === null ? "—" : number.format(ratio * 100) + " %";

  useEffect(() => {
    let active = true;
    setBusy(true);
    request<Dashboard>("/api/dashboard" + query, token).then(result => {
      if (!active) return;
      setData(result);
      if (!query) setTeams(result.equipos.map(team => team.nombre));
    }).catch(error => { if (active) onError(error); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [query, token]);

  function filter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    for (const [key, value] of new FormData(event.currentTarget)) {
      if (value) params.set(key, String(value));
    }
    setQuery(params.size ? "?" + params : "");
  }

  async function exportTo(format: string) {
    try { await downloadFile("/api/informes/" + kind + "/" + format + query, token, "soc-" + kind + "." + format); }
    catch (error) { onError(error); }
  }

  return <section className="panel" aria-labelledby="dashboard-title">
    <h2 id="dashboard-title">{s("Dashboard e informes", "Dashboard and reports")}</h2>
    <p className="hint">{s("Los indicadores y las descargas usan todos los registros del filtro. Las fechas corresponden a la recepción en Lima.", "Metrics and downloads use every matching record. Dates refer to intake in Lima.")}</p>
    <form className="report-filters" onSubmit={filter}>
      <label>{s("Desde", "From")}<input type="date" name="desde" /></label>
      <label>{s("Hasta", "To")}<input type="date" name="hasta" /></label>
      <label>{s("Tipo", "Type")}<select name="tipo"><option value="">{s("Todos", "All")}</option>
        {["phishing", "malware", "acceso_no_autorizado", "ddos", "fuga_datos", "vulnerabilidad", "uso_indebido", "incidente_fisico", "fraude", "otro"].map(value => <option key={value} value={value}>{label(value)}</option>)}
      </select></label>
      <label>{s("Severidad", "Severity")}<select name="severidad"><option value="">{s("Todas", "All")}</option>
        {["critica", "alta", "media", "baja"].map(value => <option key={value} value={value}>{label(value)}</option>)}
      </select></label>
      <label>{s("Equipo", "Team")}<select name="equipo"><option value="">{s("Todos", "All")}</option>
        {teams.map(team => <option key={team}>{team}</option>)}
      </select></label>
      <button disabled={busy}>{s("Aplicar", "Apply")}</button>
      <button type="reset" className="secondary" onClick={() => setQuery("")}>{s("Limpiar", "Clear")}</button>
    </form>
    {busy && <p role="status">{s("Cargando indicadores…", "Loading metrics…")}</p>}
    {data && !busy && <>
      <div className="metrics">
        <div className="metric"><h3>{s("Reportes", "Reports")}</h3><p className="rate">{data.total}</p>
          {data.demo > 0 && <p>{data.demo} DEMO</p>}</div>
        {(["respuesta", "resolucion"] as const).map(key => {
          const total = data.sla[key + "_evaluable"] || 0;
          const onTime = data.sla[key + "_a_tiempo"] || 0;
          return <div key={key} className="metric">
            <h3>{key === "respuesta" ? s("SLA de respuesta", "Response SLA") : s("SLA de resolución", "Resolution SLA")}</h3>
            <p className="rate">{percent(total ? onTime / total : null)}</p><p>{onTime}/{total} {s("evaluables", "eligible")}</p>
          </div>;
        })}
        {Object.entries({ clasificacion: s("Clasificación", "Classification"), respuesta: s("Primera respuesta", "First response"), resolucion: s("Resolución", "Resolution") }).map(([key, heading]) => {
          const timing = data.tiempos[key];
          return <div className="metric" key={key}><h3>{heading}</h3><p className="rate">{timing ? number.format(timing.segundos / 60) + " min" : "—"}</p>
            <p>{timing?.muestra || 0} {s("casos con hito", "completed milestones")}</p></div>;
        })}
      </div>
      <div className="impact-charts">
        {([[s("Por estado", "By status"), data.estados], [s("Por tipo", "By type"), data.tipos],
          [s("Por severidad", "By severity"), data.severidades],
          [s("Carga por equipo (abiertos)", "Team workload (open)"), Object.fromEntries(data.equipos.map(team => [team.nombre, team.abiertos]))]] as [string, Counts][]).map(([heading, counts]) => <div key={heading}>
          <h3>{heading}</h3>
          {Object.keys(counts).length > 0 && <ResponsiveContainer width="100%" height={Math.max(140, Object.keys(counts).length * 33)}>
            <BarChart layout="vertical" data={Object.entries(counts).map(([key, total]) => ({ nombre: label(key), total }))}>
              <XAxis type="number" allowDecimals={false} tick={{ fill: "var(--text)" }} />
              <YAxis type="category" dataKey="nombre" width={145} tick={{ fill: "var(--text)", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "var(--panel)", color: "var(--text)" }} />
              <Bar dataKey="total" fill="var(--accent)" />
            </BarChart>
          </ResponsiveContainer>}
          <p className="hint">{Object.entries(counts).map(([key, value]) => label(key) + " · " + value).join(" / ") || "—"}</p>
        </div>)}
        <div><h3>{s("Tendencia mensual", "Monthly trend")}</h3>
          {data.mensual.length > 0 && <ResponsiveContainer width="100%" height={220}><LineChart data={data.mensual}>
            <XAxis dataKey="mes" tick={{ fill: "var(--text)" }} /><YAxis allowDecimals={false} tick={{ fill: "var(--text)" }} />
            <Tooltip contentStyle={{ background: "var(--panel)", color: "var(--text)" }} />
            <Line type="monotone" dataKey="total" stroke="var(--accent)" />
          </LineChart></ResponsiveContainer>}
        </div>
        <div><h3>{s("SLA mensual", "Monthly SLA")}</h3>
          {data.mensual.length > 0 && <ResponsiveContainer width="100%" height={220}><LineChart data={data.mensual.map(row => ({
            mes: row.mes,
            respuesta: row.respuesta_evaluable ? 100 * (row.respuesta_a_tiempo || 0) / row.respuesta_evaluable : null,
            resolucion: row.resolucion_evaluable ? 100 * (row.resolucion_a_tiempo || 0) / row.resolucion_evaluable : null,
          }))}>
            <XAxis dataKey="mes" tick={{ fill: "var(--text)" }} /><YAxis domain={[0, 100]} unit="%" tick={{ fill: "var(--text)" }} />
            <Tooltip contentStyle={{ background: "var(--panel)", color: "var(--text)" }} />
            <Line dataKey="respuesta" name={s("Respuesta", "Response")} stroke="var(--accent)" />
            <Line dataKey="resolucion" name={s("Resolución", "Resolution")} stroke="#b66138" />
          </LineChart></ResponsiveContainer>}
        </div>
        <div><h3>{s("Precisión en casos revisados", "Accuracy on reviewed cases")}</h3>
          <p className="hint">{s("Coincidencia de tipo, severidad y activo entre la clasificación inicial y la revisión humana.", "Agreement on type, severity and asset between the initial classification and human review.")}</p>
          <ul>{data.clasificador.map(row => <li key={`${row.origen}-${row.demo}`}>{label(row.origen)}{row.demo ? " · DEMO" : ""} · {percent(row.precision)} ({row.aciertos}/{row.validados})</li>)}</ul>
        </div>
      </div>
    </>}
    {canExport && <div className="sla">
      <h3>{s("Descargar informe filtrado", "Download filtered report")}</h3>
      <p className="hint">{s("Los archivos usan el filtro aplicado. SLA próximo incluye las siguientes cuatro horas.", "Files use the applied filters. Due SLA includes the next four hours.")}</p>
      <div className="report-filters">
        <label>{s("Informe", "Report")}<select value={kind} onChange={event => setKind(event.target.value)}>
          {reports.map(([value, es, en]) => <option value={value} key={value}>{s(es, en)}</option>)}
        </select></label>
        {["pdf", "docx", "xlsx"].map(format => <button className="secondary" disabled={busy} key={format} onClick={() => exportTo(format)}>{format.toUpperCase()}</button>)}
      </div>
    </div>}
  </section>;
}
