import { useEffect, useState } from "react";
import { request, type RequestProgress } from "./api";
import { normalizeSearch, teamNames, translate } from "./i18n";
import { peruDateTime, peruDay } from "./time";
import { Badge, EmptyState, Icon, LoadingBlock } from "./ui";

interface Props {
  token: string;
  language: string;
  selectedId?: string;
  onSelect: (id?: string) => void;
  onNew: () => void;
}

const emptyFilters = { search: "", status: "", from: "", through: "" };
const requestStatuses = ["requestWaiting", "laneProgress", "done"];

function status(item: RequestProgress) {
  if (item.resuelto_at) return "done";
  if (item.respondido_at) return "laneProgress";
  return "requestWaiting";
}

export function RequesterPanel({ token, language, selectedId, onSelect, onNew }: Props) {
  const [rows, setRows] = useState<RequestProgress[]>([]);
  const [detail, setDetail] = useState<RequestProgress>();
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [filters, setFilters] = useState(emptyFilters);
  const t = (key: string) => translate(language, key);
  const date = (value: string) => peruDateTime(value, language);

  useEffect(() => {
    let active = true;
    setBusy(true);
    setError("");
    async function load() {
      try {
        if (selectedId) {
          const value = await request<RequestProgress>("/api/mis-solicitudes/" + selectedId, token);
          if (active) setDetail(value);
        } else {
          const value = await request<RequestProgress[]>("/api/mis-solicitudes", token);
          if (active) setRows(value);
        }
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : translate(language, "unexpected"));
      } finally {
        if (active) setBusy(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [token, selectedId, version, language]);

  const item = detail?.id === selectedId ? detail : undefined;
  const search = normalizeSearch(filters.search.trim());
  const filtered = rows.filter(row => {
    if (filters.status && status(row) !== filters.status) return false;
    if (search && !normalizeSearch(row.titulo + " " + row.id).includes(search)) return false;
    if (filters.from || filters.through) {
      const received = peruDay(row.recibido_at);
      if (filters.from && received < filters.from) return false;
      if (filters.through && received > filters.through) return false;
    }
    return true;
  });
  const setFilter = (key: keyof typeof emptyFilters, value: string) =>
    setFilters(current => ({ ...current, [key]: value }));

  return <section className="panel case-view" aria-labelledby="module-title" aria-busy={busy}>
    <div className="list-toolbar">
      {selectedId
        ? <button type="button" className="secondary" onClick={() => onSelect()}>{t("backToRequests")}</button>
        : <p className="intro">{t("requestsIntro")}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" className="secondary" disabled={busy} onClick={() => setVersion(value => value + 1)}>{t("refreshRequests")}</button>
        {!selectedId && <button type="button" onClick={onNew}>{t("newReport")}</button>}
      </div>
    </div>
    {error && <p role="alert" className="notice error">{error}</p>}
    {busy && <LoadingBlock label={t("loading")} />}
    {selectedId ? item && <article className="report case-detail">
      <Badge tone={item.resuelto_at ? "success" : "info"}>{t(status(item))}</Badge>
      <h2>{item.titulo}</h2>
      <p className="hint">{t("requestReference")} <code>{item.id}</code></p>
      <p className="description">{item.descripcion}</p>
      <h3>{t("requestProgress")}</h3>
      <ol className="request-timeline">
        {([
          [t("requestReceived"), item.recibido_at, null],
          [t("requestAssigned"), item.asignado_at, null],
          [t("firstResponse"), item.respondido_at, item.vence_respuesta_at],
          [t("resolution"), item.resuelto_at, item.vence_resolucion_at],
        ] as const).map(([label, time, deadline]) => <li key={label} data-complete={Boolean(time)}>
          <Icon name={time ? "check" : "clock"} />
          <div><strong>{label}</strong><p className="hint">{time ? date(time) : t("waiting")}
            {!time && deadline ? " · " + t("deadline") + " " + date(deadline) : ""}</p>
            {label === t("requestAssigned") && item.responsable && <p className="hint">
              {language === "en" ? teamNames[item.responsable] || item.responsable : item.responsable}
            </p>}
          </div>
        </li>)}
      </ol>
    </article> : <>
      {rows.length > 0 && <div className="board-filter-panel request-filters" role="group" aria-label={t("requestFilters")}>
        <div className="request-filter-fields">
          <label>{t("requestSearch")}<input type="search" value={filters.search}
            onChange={event => setFilter("search", event.target.value)} /></label>
          <label>{t("requestStatus")}<select value={filters.status} onChange={event => setFilter("status", event.target.value)}>
            <option value="">{t("all")}</option>
            {requestStatuses.map(value => <option key={value} value={value}>{t(value)}</option>)}
          </select></label>
          <label>{t("requestFrom")}<input type="date" value={filters.from} max={filters.through || undefined}
            onChange={event => setFilter("from", event.target.value)} /></label>
          <label>{t("requestThrough")}<input type="date" value={filters.through} min={filters.from || undefined}
            onChange={event => setFilter("through", event.target.value)} /></label>
        </div>
        <div className="filter-actions request-filter-summary">
          <span className="hint" role="status">{translate(language, "requestFilterCount", filtered.length, rows.length)}</span>
          {Object.values(filters).some(Boolean) && <button type="button" className="ghost" onClick={() => setFilters(emptyFilters)}>
            {t("clearFilters")}
          </button>}
        </div>
      </div>}
      {!busy && !rows.length && !error && <EmptyState>{t("noRequests")}</EmptyState>}
      {rows.length > 0 && !filtered.length && <EmptyState>{t("noMatchingRequests")}</EmptyState>}
      <div className="request-list">{filtered.map(row => <article className="report request-row" key={row.id}>
        <div><h2>{row.titulo}</h2><p className="hint">{translate(language, "receivedOn", date(row.recibido_at))}</p></div>
        <Badge tone={row.resuelto_at ? "success" : "info"}>{t(status(row))}</Badge>
        <button type="button" className="secondary" onClick={() => onSelect(row.id)}
          aria-label={t("viewProgress") + " · " + row.titulo}>{t("viewProgress")}</button>
      </article>)}</div>
    </>}
  </section>;
}
