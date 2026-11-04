import { FormEvent, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { downloadFile, request } from "./api";
import { translate } from "./i18n";
import { Badge, KpiCard, LoadingBlock } from "./ui";

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
const chartColors: Record<string, string> = {
  sin_asignar: "var(--muted)", por_atender: "var(--warning)", en_atencion: "var(--info)", resuelto: "var(--success)",
  critica: "var(--critical)", alta: "var(--danger)", media: "var(--warning)", baja: "var(--info)",
};
const tick = { fill: "var(--muted)", fontSize: 12 };
const tooltip = { background: "var(--raised)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "var(--radius)" };

export function DashboardPanel({ token, language, canExport, onError }: Props) {
  const [data, setData] = useState<Dashboard>();
  const [teams, setTeams] = useState<string[]>([]);
  const [query, setQuery] = useState("");
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

  async function exportTo(kind: string, format: string) {
    try { await downloadFile("/api/informes/" + kind + "/" + format + query, token, "soc-" + kind + "." + format); }
    catch (error) { onError(error); }
  }
  const filters = Object.fromEntries(new URLSearchParams(query));

  return <section className="panel" aria-labelledby="module-title">
    <p className="hint">{s("Los indicadores y las descargas usan todos los registros del filtro. Las fechas corresponden a la recepción en Lima.", "Metrics and downloads use every matching record. Dates refer to intake in Lima.")}</p>
    <form className="report-filters dashboard-filters" onSubmit={filter}>
      <label>{s("Desde", "From")}<input type="date" name="desde" /></label>
      <label>{s("Hasta", "To")}<input type="date" name="hasta" /></label>
      <label>{s("Tipo", "Type")}<select name="tipo" aria-label={s("Tipo", "Type")}><option value="">{s("Todos", "All")}</option>
        {["phishing", "malware", "acceso_no_autorizado", "ddos", "fuga_datos", "vulnerabilidad", "uso_indebido", "incidente_fisico", "fraude", "otro"].map(value => <option key={value} value={value}>{label(value)}</option>)}
      </select></label>
      <label>{s("Severidad", "Severity")}<select name="severidad" aria-label={s("Severidad", "Severity")}><option value="">{s("Todas", "All")}</option>
        {["critica", "alta", "media", "baja"].map(value => <option key={value} value={value}>{label(value)}</option>)}
      </select></label>
      <label>{s("Equipo", "Team")}<select name="equipo" aria-label={s("Equipo", "Team")}><option value="">{s("Todos", "All")}</option>
        {teams.map(team => <option key={team}>{team}</option>)}
      </select></label>
      <div className="filter-actions"><button disabled={busy}>{s("Aplicar", "Apply")}</button>
        <button type="reset" className="secondary" onClick={() => setQuery("")}>{s("Limpiar", "Clear")}</button></div>
    </form>
    {query && <div className="chip-row" aria-label={s("Filtros aplicados", "Applied filters")}>
      {([["desde", "Desde", "From"], ["hasta", "Hasta", "To"], ["tipo", "Tipo", "Type"],
        ["severidad", "Severidad", "Severity"], ["equipo", "Equipo", "Team"]]).map(([key, es, en]) => filters[key] &&
        <Badge key={key} tone="info">{s(es, en)} · {label(filters[key])}</Badge>)}
    </div>}
    {busy && <LoadingBlock label={s("Cargando indicadores…", "Loading metrics…")} />}
    {data && <div aria-busy={busy}>
      <div className="metrics dashboard-metrics">
        <KpiCard title={s("Reportes", "Reports")} value={number.format(data.total)} icon="report">
          {data.demo > 0 && <Badge tone="demo">{data.demo} DEMO</Badge>}</KpiCard>
        {(["respuesta", "resolucion"] as const).map(key => {
          const total = data.sla[key + "_evaluable"] || 0;
          const onTime = data.sla[key + "_a_tiempo"] || 0;
          const tone = total ? onTime === total ? "success" : "warning" : "neutral";
          return <KpiCard key={key} title={key === "respuesta" ? s("SLA de respuesta", "Response SLA") : s("SLA de resolución", "Resolution SLA")}
            icon="clock" tone={tone} value={percent(total ? onTime / total : null)}>
            {onTime}/{total} {s("evaluables", "eligible")}
          </KpiCard>;
        })}
        {Object.entries({ clasificacion: s("Clasificación", "Classification"), respuesta: s("Primera respuesta", "First response"), resolucion: s("Resolución", "Resolution") }).map(([key, heading]) => {
          const timing = data.tiempos[key];
          return <KpiCard key={key} title={heading} icon="pulse" tone="neutral"
            value={timing ? number.format(timing.segundos / 60) + " min" : "—"}>
            {timing?.muestra || 0} {s("casos con hito", "completed milestones")}
          </KpiCard>;
        })}
      </div>
      <div className="impact-charts">
        {([[s("Por estado", "By status"), data.estados], [s("Por tipo", "By type"), data.tipos],
          [s("Por severidad", "By severity"), data.severidades],
          [s("Carga por equipo (abiertos)", "Team workload (open)"), Object.fromEntries(data.equipos.map(team => [team.nombre, team.abiertos]))]] as [string, Counts][]).map(([heading, counts]) => <div key={heading} className="chart-card">
          <h3>{heading}</h3>
          {Object.keys(counts).length > 0 && <ResponsiveContainer width="100%" height={Math.max(212, Object.keys(counts).length * 31)} minWidth={0}>
            <BarChart layout="vertical" margin={{ top: 12, right: 42, bottom: 0, left: 0 }}
              data={Object.entries(counts).map(([key, total]) => ({ nombre: label(key), total }))}>
              <CartesianGrid horizontal={false} stroke="var(--border)" strokeDasharray="3 4" />
              <XAxis type="number" allowDecimals={false} tick={tick} />
              <YAxis type="category" dataKey="nombre" width={142} tick={tick} tickLine={false} />
              <Tooltip contentStyle={tooltip} cursor={{ fill: "var(--subtle)" }} />
              <Bar dataKey="total" name={s("Reportes", "Reports")} barSize={16} radius={[0, 4, 4, 0]} isAnimationActive={false}>
                {Object.keys(counts).map((key, index) => <Cell key={key} fill={chartColors[key] || `var(--chart-${index % 8 + 1})`} />)}
                <LabelList dataKey="total" position="right" fill="var(--text)" fontSize={12} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>}
          {Object.keys(counts).length ? <ul className="chart-summary">{Object.entries(counts).map(([key, value]) =>
            <li key={key}>{label(key)} <strong>{number.format(value)}</strong></li>)}</ul> : <p className="empty">{s("Sin datos para estos filtros.", "No data for these filters.")}</p>}
        </div>)}
        <div><h3>{s("Tendencia mensual", "Monthly trend")}</h3>
          {data.mensual.length > 0 && <ResponsiveContainer width="100%" height={220}><LineChart data={data.mensual}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 4" />
            <XAxis dataKey="mes" tick={tick} /><YAxis allowDecimals={false} tick={tick} width={42} />
            <Tooltip contentStyle={tooltip} />
            <Line type="monotone" dataKey="total" name={s("Reportes", "Reports")} stroke="var(--chart-1)" strokeWidth={2} isAnimationActive={false} />
          </LineChart></ResponsiveContainer>}
        </div>
        <div><h3>{s("SLA mensual", "Monthly SLA")}</h3>
          {data.mensual.length > 0 && <ResponsiveContainer width="100%" height={220}><LineChart data={data.mensual.map(row => ({
            mes: row.mes,
            respuesta: row.respuesta_evaluable ? 100 * (row.respuesta_a_tiempo || 0) / row.respuesta_evaluable : null,
            resolucion: row.resolucion_evaluable ? 100 * (row.resolucion_a_tiempo || 0) / row.resolucion_evaluable : null,
          }))}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 4" />
            <XAxis dataKey="mes" tick={tick} /><YAxis domain={[0, 100]} unit="%" tick={tick} width={44} />
            <Tooltip contentStyle={tooltip} /><Legend />
            <Line dataKey="respuesta" name={s("Respuesta", "Response")} stroke="var(--chart-1)" strokeWidth={2} isAnimationActive={false} />
            <Line dataKey="resolucion" name={s("Resolución", "Resolution")} stroke="var(--chart-3)" strokeDasharray="5 4" strokeWidth={2} isAnimationActive={false} />
          </LineChart></ResponsiveContainer>}
        </div>
        <div><h3>{s("Precisión en casos revisados", "Accuracy on reviewed cases")}</h3>
          <p className="hint">{s("Coincidencia de tipo, severidad y activo entre la clasificación inicial y la revisión humana.", "Agreement on type, severity and asset between the initial classification and human review.")}</p>
          <ul className="chart-summary">{data.clasificador.map(row => <li key={`${row.origen}-${row.demo}`}>{label(row.origen)} {row.demo && <Badge tone="demo">DEMO</Badge>} · {percent(row.precision)} ({row.aciertos}/{row.validados})</li>)}</ul>
        </div>
      </div>
    </div>}
    {canExport && <div className="sla">
      <h3>{s("Descargar informe filtrado", "Download filtered report")}</h3>
      <p className="hint">{s("Los archivos usan el filtro aplicado. SLA próximo incluye las siguientes cuatro horas.", "Files use the applied filters. Due SLA includes the next four hours.")}</p>
      <div className="export-cards">
        {reports.map(([kind, es, en]) => <article key={kind} className="export-card">
          <h4>{s(es, en)}</h4><div className="filter-actions">
            {["pdf", "docx", "xlsx"].map(format => <button type="button" className="secondary" disabled={busy} key={format}
              aria-label={s(es, en) + " " + format.toUpperCase()} onClick={() => exportTo(kind, format)}>{format.toUpperCase()}</button>)}
          </div>
        </article>)}
      </div>
    </div>}
  </section>;
}
