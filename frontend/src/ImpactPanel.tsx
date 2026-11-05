import React, { useEffect, useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend, ReferenceLine } from "recharts";
import { request } from "./api";
import { translate } from "./i18n";

interface Period {
  period: string; source: "demo"; report_count: number;
  response_on_time: number; resolution_on_time: number;
  response_pct: number; resolution_pct: number;
  manual_seconds_per_case: number; automated_seconds_per_case: number;
  review_seconds_per_case: number; estimated_hours_saved: number;
}
interface History {
  source: "demo"; is_demo: true; sla_target_pct: number;
  periods: Period[]; measured_baselines: number;
  sla_demo?: DemoSla;
}
type Milestone = "respuesta" | "resolucion";
type DemoResult = { a_tiempo: number; evaluables: number; porcentaje: number };
interface DemoSla {
  source: "demo"; tipo: string; severidad: string; respuesta_min: number; resolucion_min: number;
  meta_mejora_pp: number; meta_cumplida: boolean; mejora_pp: Record<Milestone, number>;
  grupos: Record<"manual" | "asistido", { desde: string; hasta: string } & Record<Milestone, DemoResult>>;
}

export function ImpactPanel({ token, language, onError }: {
  token: string; language: string; onError: (cause: unknown) => void;
}) {
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(false);
  const s = (es: string, en: string) => language === "en" ? en : es;
  const number = (value: number, digits = 1) => new Intl.NumberFormat(language, { maximumFractionDigits: digits }).format(value);

  async function load() {
    setBusy(true);
    try { setHistory(await request<History>("/api/impacto", token)); }
    catch (cause) { onError(cause); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, [token]);

  const periods = history?.periods || [];
  const first = periods[0];
  const comparison = history?.sla_demo;
  const last = periods.at(-1);
  const data = periods.map(row => ({
    ...row,
    label: new Date(row.period + "-01T12:00:00Z").toLocaleDateString(language, { month: "short", year: "2-digit", timeZone: "America/Lima" }),
    manual_minutes: row.manual_seconds_per_case / 60,
    assisted_minutes: (row.automated_seconds_per_case + row.review_seconds_per_case) / 60,
  }));
  const tooltipStyle = { background: "var(--panel)", color: "var(--text)", borderColor: "var(--border)" };

  return <section className="panel" aria-labelledby="impact-title">
    <div className="list-toolbar">
      <div><h2 id="impact-title">{s("Evolución de SLA y triaje", "SLA and triage trends")}</h2>
        <p className="intro">{s("Histórico simulado para presentar la evolución del sistema.", "Simulated history to demonstrate trends in the system.")}</p></div>
      <button disabled={busy} onClick={load}>{s("Actualizar", "Refresh")}</button>
    </div>
    <p className="notice demo-notice"><strong>{s("DEMO · Datos históricos simulados", "DEMO · Simulated historical data")}</strong><br />
      {s("Esta serie ilustra una mejora diseñada para demostración. Sus valores se guardan aparte de los reportes y no acreditan resultados operativos reales.", "This series illustrates improvement designed for demonstration. Its values are stored separately from reports and do not establish real operational results.")}</p>
    {busy && !history && <p role="status">{s("Cargando histórico…", "Loading history…")}</p>}
    {comparison && <section className="sla" aria-labelledby="demo-sla-title">
      <h3 id="demo-sla-title">{s("DEMO · SLA manual frente a asistido", "DEMO · Manual versus assisted SLA")}</h3>
      <p>{translate(language, comparison.tipo)} · {translate(language, comparison.severidad)} · {s("Plazos compartidos", "Shared deadlines")} · {s("Respuesta", "Response")} {number(comparison.respuesta_min / 60)} h · {s("Resolución", "Resolution")} {number(comparison.resolucion_min / 60)} h</p>
      <p className="hint">{s("Meta ilustrativa", "Illustrative target")} · +{number(comparison.meta_mejora_pp)} pp {s("en cada SLA", "for each SLA")} · {comparison.meta_cumplida ? s("Alcanzada en la simulación", "Reached in the simulation") : s("Pendiente en la simulación", "Missed in the simulation")}</p>
      <div className="table-scroll"><table aria-label={s("Comparación de SLA DEMO", "Demo SLA comparison")}>
        <thead><tr><th>SLA</th><th>{s("Manual", "Manual")} · {comparison.grupos.manual.desde.slice(0, 7)}</th><th>{s("Asistido", "Assisted")} · {comparison.grupos.asistido.desde.slice(0, 7)}</th><th>{s("Mejora", "Improvement")}</th></tr></thead>
        <tbody>{(["respuesta", "resolucion"] as const).map(milestone => <tr key={milestone}>
          <th scope="row">{milestone === "respuesta" ? s("Primera respuesta", "First response") : s("Resolución", "Resolution")}</th>
          {(["manual", "asistido"] as const).map(cohort => {
            const result = comparison.grupos[cohort][milestone];
            return <td key={cohort}>{result.a_tiempo}/{result.evaluables} · {number(result.porcentaje)} %</td>;
          })}
          <td>+{number(comparison.mejora_pp[milestone])} pp</td>
        </tr>)}</tbody>
      </table></div>
    </section>}
    {history && !periods.length && <p className="empty">{s("El histórico DEMO aún no ha sido cargado.", "The demo history has not been loaded yet.")}</p>}
    {first && last && <>
      <div className="metrics next">
        <div className="metric"><h3>{s("SLA de respuesta DEMO", "Demo response SLA")}</h3>
          <p className="rate">{number(first.response_pct)} % → {number(last.response_pct)} %</p>
          <p className="hint">{s("Mejora simulada", "Simulated improvement")} · +{number(last.response_pct - first.response_pct)} {s("puntos porcentuales", "percentage points")}</p></div>
        <div className="metric"><h3>{s("SLA de resolución DEMO", "Demo resolution SLA")}</h3>
          <p className="rate">{number(first.resolution_pct)} % → {number(last.resolution_pct)} %</p></div>
        <div className="metric"><h3>{s("Ahorro mensual estimado DEMO", "Demo estimated monthly savings")}</h3>
          <p className="rate">{number(first.estimated_hours_saved)} h → {number(last.estimated_hours_saved)} h</p>
          <p className="hint">{first.report_count} {s("casos por mes en esta simulación", "cases per month in this simulation")}</p></div>
      </div>
      <div className="impact-charts">
        <div><h3>{s("Cumplimiento mensual de plazos", "Monthly deadline compliance")}</h3>
          <p className="hint">{s("Meta ilustrativa", "Illustrative target")} · {history!.sla_target_pct} %</p>
          <div className="chart" role="img" aria-label={s("Gráfico DEMO de SLA mensual", "Demo monthly SLA chart")}>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data} margin={{ top: 12, right: 18, bottom: 0, left: 0 }}>
                <XAxis dataKey="label" tick={{ fill: "var(--text)", fontSize: 11 }} />
                <YAxis domain={[0, 100]} unit="%" tick={{ fill: "var(--text)", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle} /><Legend />
                <ReferenceLine y={history!.sla_target_pct} stroke="var(--muted)" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="response_pct" name={s("Respuesta (%)", "Response (%)")} stroke="var(--chart-1)" strokeWidth={2} isAnimationActive={false} />
                <Line type="monotone" dataKey="resolution_pct" name={s("Resolución (%)", "Resolution (%)")} stroke="var(--chart-3)" strokeWidth={2} strokeDasharray="5 4" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
        <div><h3>{s("Tiempo de triaje por caso", "Triage time per case")}</h3>
          <p className="hint">{s("Ciclo automático más revisión humana, en minutos", "Automated cycle plus human review, in minutes")}</p>
          <div className="chart" role="img" aria-label={s("Gráfico DEMO de tiempo de triaje", "Demo triage time chart")}>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data} margin={{ top: 12, right: 18, bottom: 0, left: 0 }}>
                <XAxis dataKey="label" tick={{ fill: "var(--text)", fontSize: 11 }} />
                <YAxis unit="m" tick={{ fill: "var(--text)", fontSize: 11 }} />
                <Tooltip contentStyle={tooltipStyle} /><Legend />
                <Line type="monotone" dataKey="manual_minutes" name={s("Manual", "Manual")} stroke="var(--chart-3)" strokeWidth={2} strokeDasharray="5 4" isAnimationActive={false} />
                <Line type="monotone" dataKey="assisted_minutes" name={s("Con automatización", "With automation")} stroke="var(--chart-2)" strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
      <details className="sla" open><summary>{s("Datos mensuales y cálculo", "Monthly data and calculation")}</summary>
        <p className="hint">{s("Ahorro estimado = casos × (tiempo manual − ciclo automático − revisión humana). Los tiempos de la tabla son promedios por caso.", "Estimated savings = cases × (manual time − automated cycle − human review). Table times are per-case averages.")}</p>
        <div className="table-scroll"><table>
          <thead><tr>{[s("Mes", "Month"),s("Casos DEMO", "Demo cases"),s("Respuesta a tiempo", "Response on time"),s("Resolución a tiempo", "Resolution on time"),s("Manual (min)", "Manual (min)"),s("Ciclo + revisión (min)", "Cycle + review (min)"),s("Horas estimadas", "Estimated hours")].map(label => <th key={label}>{label}</th>)}</tr></thead>
          <tbody>{data.map(row => <tr key={row.period}>
            <td>{row.period}</td><td>{row.report_count}</td>
            <td>{row.response_on_time}/{row.report_count} · {number(row.response_pct)} %</td>
            <td>{row.resolution_on_time}/{row.report_count} · {number(row.resolution_pct)} %</td>
            <td>{number(row.manual_minutes)}</td><td>{number(row.assisted_minutes)}</td><td>{number(row.estimated_hours_saved, 2)} h</td>
          </tr>)}</tbody>
        </table></div>
      </details>
    </>}
    <div className="sla">
      <h3>{s("Evidencia operacional real", "Real operational evidence")}</h3>
      <p>{s("Líneas base registradas como reales", "Baselines registered as real")} · {history?.measured_baselines ?? "—"}</p>
      <p className="hint">{s("La demostración real de mejora requiere muestras manuales medidas, casos comparables y un periodo representativo. Puedes registrar la línea base en el tablero. Los valores DEMO de esta vista están excluidos de esos registros.", "Demonstrating real improvement requires measured manual samples, comparable cases, and a representative period. You can register a baseline on the board. Demo values in this view are excluded from those records.")}</p>
    </div>
  </section>;
}
