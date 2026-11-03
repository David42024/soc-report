import { FormEvent, useEffect, useState } from "react";
import { request } from "./api";
import { translate } from "./i18n";

type Study = { id: string; nombre: string; muestreo: string; tipo: string; severidad: string;
  manual_desde: string; manual_hasta: string; asistido_desde: string; asistido_hasta: string;
  minimo_por_grupo: number; respuesta_min: number; resolucion_min: number; meta_mejora_pp: number };
type Milestone = { a_tiempo: number; evaluables: number; porcentaje: number | null };
type Group = { muestra: number; segundos_activos_total: number; segundos_activos_media: number | null;
  respuesta: Milestone; resolucion: Milestone };
type Detail = { criterios: Study; grupos: Record<"manual" | "asistido", Group>; periodo_completo: boolean;
  criterios_previos_al_periodo_asistido: boolean;
  mejora_sla_pp: { respuesta: number; resolucion: number } | null; meta_sla_cumplida: boolean | null;
  ahorro_estimado_horas_muestras_reales: number | null };
const path = "/api/estudios-impacto";
const types = ["phishing", "malware", "acceso_no_autorizado", "ddos", "fuga_datos", "vulnerabilidad", "uso_indebido", "incidente_fisico", "fraude", "otro"];
const severities = ["critica", "alta", "media", "baja"];

export function OperationalImpactPanel({ token, language, canManage, onError }: {
  token: string; language: string; canManage: boolean; onError: (error: unknown) => void;
}) {
  const [studies, setStudies] = useState<Study[]>([]);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail>();
  const [mode, setMode] = useState("manual");
  const [busy, setBusy] = useState(false);
  const s = (es: string, en: string) => language === "es" ? es : en;
  const number = new Intl.NumberFormat(language, { maximumFractionDigits: 2 });
  const fmt = (value: number | null) => value === null ? "—" : number.format(value);

  useEffect(() => {
    let active = true;
    request<Study[]>(path, token).then(list => { if (active) setStudies(list); })
      .catch(error => { if (active) onError(error); });
    return () => { active = false; };
  }, [token]);

  useEffect(() => {
    let active = true;
    setDetail(undefined);
    if (selected) request<Detail>(`${path}/${selected}`, token).then(result => { if (active) setDetail(result); })
      .catch(error => { if (active) onError(error); });
    return () => { active = false; };
  }, [token, selected]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = Object.fromEntries(new FormData(form));
    const body = { ...fields, minimo_por_grupo: Number(fields.minimo_por_grupo), respuesta_min: Number(fields.respuesta_min),
      resolucion_min: Number(fields.resolucion_min), meta_mejora_pp: Number(fields.meta_mejora_pp) };
    setBusy(true);
    try {
      const result = await request<{ id: string }>(path, token, { method: "POST", body: JSON.stringify(body) });
      setStudies(await request<Study[]>(path, token)); setSelected(result.id); form.reset();
    } catch (error) { onError(error); }
    finally { setBusy(false); }
  }

  async function record(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const date = (name: string) => fields.get(name) ? `${fields.get(name)}:00-05:00` : null;
    const source = mode === "manual" ? { referencia: fields.get("referencia"), recibido_at: date("recibido_at"),
      respondido_at: date("respondido_at"), resuelto_at: date("resuelto_at") } : { reporte_id: fields.get("reporte_id") };
    setBusy(true);
    try {
      await request(`${path}/${selected}/observaciones`, token, { method: "POST", body: JSON.stringify({ ...source,
        modalidad: mode, segundos_activos: Number(fields.get("segundos_activos")), caso_real: fields.has("caso_real") }) });
      setDetail(await request<Detail>(`${path}/${selected}`, token)); form.reset();
    } catch (error) { onError(error); }
    finally { setBusy(false); }
  }

  return <section className="panel" aria-labelledby="operational-impact">
    <h2 id="operational-impact">{s("Estudios de impacto operacional", "Operational impact studies")}</h2>
    <p className="hint">{s("Registra casos operativos y mide tiempo humano activo. Los plazos se calculan con los mismos criterios en ambos grupos. El histórico DEMO se presenta aparte.", "Record operational cases and measure active human time. Both groups use the same deadline criteria. DEMO history is shown separately.")}</p>
    {canManage && <details className="sla"><summary>{s("Definir un estudio", "Define a study")}</summary>
      <form className="report-filters" onSubmit={create}>
        <label>{s("Nombre", "Name")}<input name="nombre" minLength={5} maxLength={100} required /></label>
        <label>{s("Criterio de muestreo", "Sampling criteria")}<textarea name="muestreo" minLength={15} maxLength={500} required /></label>
        <label>{s("Tipo", "Type")}<select name="tipo">{types.map(type => <option key={type} value={type}>{translate(language, type)}</option>)}</select></label>
        <label>{s("Severidad", "Severity")}<select name="severidad">{severities.map(value => <option key={value} value={value}>{translate(language, value)}</option>)}</select></label>
        <label>{s("Manual desde", "Manual from")}<input name="manual_desde" type="date" required /></label>
        <label>{s("Manual hasta", "Manual through")}<input name="manual_hasta" type="date" required /></label>
        <label>{s("Asistido desde", "Assisted from")}<input name="asistido_desde" type="date" required /></label>
        <label>{s("Asistido hasta", "Assisted through")}<input name="asistido_hasta" type="date" required /></label>
        <label>{s("Mínimo por grupo", "Minimum per group")}<input name="minimo_por_grupo" type="number" min={3} max={10000} required /></label>
        <label>{s("Plazo de respuesta (min)", "Response deadline (min)")}<input name="respuesta_min" type="number" min={1} max={525600} required /></label>
        <label>{s("Plazo de resolución (min)", "Resolution deadline (min)")}<input name="resolucion_min" type="number" min={1} max={525600} required /></label>
        <label>{s("Mejora mínima de cada SLA (pp)", "Minimum improvement per SLA (pp)")}<input name="meta_mejora_pp" type="number" min={0} max={100} step="any" required /></label>
        <button disabled={busy}>{s("Guardar estudio", "Save study")}</button>
      </form>
    </details>}
    <label>{s("Estudio", "Study")}<select value={selected} disabled={busy} onChange={event => setSelected(event.target.value)}>
      <option value="">{s("Selecciona un estudio", "Choose a study")}</option>
      {studies.map(item => <option key={item.id} value={item.id}>{item.nombre}</option>)}
    </select></label>
    {detail && <>
      <p>{detail.criterios.muestreo}</p>
      {!detail.criterios_previos_al_periodo_asistido && <p className="hint">{s("Estudio retrospectivo. Los criterios se registraron tras iniciar el periodo asistido.", "Retrospective study. Criteria were recorded after the assisted period started.")}</p>}
      <p>{s("Mínimo por grupo", "Minimum per group")} {detail.criterios.minimo_por_grupo} · {s("Meta SLA", "SLA target")} {detail.criterios.meta_mejora_pp} pp</p>
      <div className="table-scroll"><table><thead><tr>
        <th>{s("Grupo", "Group")}</th><th>{s("Muestra", "Sample")}</th><th>{s("Tiempo activo medio (s)", "Average active time (s)")}</th>
        <th>{s("SLA de respuesta", "Response SLA")}</th><th>{s("SLA de resolución", "Resolution SLA")}</th>
      </tr></thead><tbody>{(["manual", "asistido"] as const).map(key => {
        const group = detail.grupos[key];
        return <tr key={key}><td>{key === "manual" ? s("Manual", "Manual") : s("Asistido", "Assisted")}</td><td>{group.muestra}</td>
          <td>{fmt(group.segundos_activos_media)}</td>{([group.respuesta, group.resolucion]).map((milestone, index) =>
            <td key={index}>{milestone.a_tiempo}/{milestone.evaluables} · {fmt(milestone.porcentaje)} %</td>)}</tr>;
      })}</tbody></table></div>
      {detail.mejora_sla_pp ? <p>{s("Diferencia de SLA en puntos porcentuales", "SLA difference in percentage points")} · {s("Respuesta", "Response")} {fmt(detail.mejora_sla_pp.respuesta)} · {s("Resolución", "Resolution")} {fmt(detail.mejora_sla_pp.resolucion)} · {detail.meta_sla_cumplida ? s("Meta alcanzada", "Target reached") : s("Meta pendiente", "Target missed")}</p>
        : <p>{s("Comparación de SLA pendiente de periodo o muestra suficiente.", "SLA comparison needs a complete period and sufficient sample.")}</p>}
      <p>{s("Ahorro estimado con muestras reales", "Estimated savings based on real observations")} · {fmt(detail.ahorro_estimado_horas_muestras_reales)} h</p>
      <details className="sla"><summary>{s("Registrar observación real", "Record real observation")}</summary>
        <form className="report-filters" onSubmit={record}>
          <label>{s("Grupo", "Group")}<select value={mode} onChange={event => setMode(event.target.value)}>
            <option value="manual">Manual</option><option value="asistido">{s("Asistido", "Assisted")}</option>
          </select></label>
          {mode === "manual" ? <>
            <p className="hint">{s("Registra el caso manual cuando sus hitos estén documentados o sus plazos hayan vencido.", "Record manual cases once their milestones are documented or their deadlines have elapsed.")}</p>
            <label>{s("Referencia externa", "External reference")}<input name="referencia" pattern="[A-Za-z0-9_.-]+" minLength={3} maxLength={80} required /></label>
            <label>{s("Recepción (Lima)", "Intake (Lima)")}<input name="recibido_at" type="datetime-local" required /></label>
            <label>{s("Respuesta (Lima)", "Response (Lima)")}<input name="respondido_at" type="datetime-local" /></label>
            <label>{s("Resolución (Lima)", "Resolution (Lima)")}<input name="resuelto_at" type="datetime-local" /></label>
          </> : <label>{s("ID del reporte operativo", "Operational report ID")}<input name="reporte_id" required /></label>}
          <label>{s("Segundos de trabajo humano activo", "Seconds of active human work")}<input name="segundos_activos" type="number" min={0.01} max={86400} step="any" required /></label>
          <label className="check"><input name="caso_real" type="checkbox" required />{s("Confirmo que corresponde a un caso real y al criterio de muestreo", "I confirm this is a real case that meets the sampling criteria")}</label>
          <button disabled={busy}>{s("Registrar observación", "Record observation")}</button>
        </form>
      </details>
    </>}
  </section>;
}
