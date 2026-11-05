import { useEffect, useRef, useState, type ReactNode } from "react";
import { nextDeadline, reportState, stage, type Report } from "./api";
import { normalizeSearch, teamNames, translate } from "./i18n";
import { peruDateTime, peruDay } from "./time";
import { Badge, EmptyState, Icon, LoadingBlock, type Tone } from "./ui";

const lanes = [
  { label: "laneNew", tone: "warning", icon: "clock" },
  { label: "laneProgress", tone: "info", icon: "pulse" },
  { label: "laneDone", tone: "success", icon: "check" },
] as const;
const pageSize = 4;
const fourHours = 4 * 60 * 60 * 1000;
const sampleTitle = /^\[DEMO\] SOC-\d{2} · /;
const emptyFilters = { search: "", status: "", severity: "", type: "", team: "", deadline: "", from: "", to: "", sample: "" };
type Filter = keyof typeof emptyFilters;
export const severityTone: Record<string, Tone> = { critica: "critical", alta: "high", media: "medium", baja: "low" };

function matches(report: Report, filters: typeof emptyFilters, search: string, now: number) {
  if (filters.sample && !sampleTitle.test(report.titulo)) return false;
  const lane = stage(report);
  if (filters.status === "open" && lane === 2) return false;
  if (filters.status === "review" && !report.motivo_revision) return false;
  if (["0", "1", "2"].includes(filters.status) && String(lane) !== filters.status) return false;
  if (filters.severity && filters.severity !== report.severidad) return false;
  if (filters.type && filters.type !== report.tipo) return false;
  if (filters.team && filters.team !== (report.responsable || "unassigned")) return false;
  if (search && !normalizeSearch(report.titulo + " " + report.id).includes(search)) return false;
  if (filters.from || filters.to) {
    const received = peruDay(report.recibido_at);
    if (filters.from && received < filters.from) return false;
    if (filters.to && received > filters.to) return false;
  }
  const deadline = nextDeadline(report);
  const remaining = deadline ? Date.parse(deadline) - now : NaN;
  if (filters.deadline === "late" && !(remaining < 0)) return false;
  if (filters.deadline === "soon" && !(remaining >= 0 && remaining <= fourHours)) return false;
  return true;
}

function cardTitle(report: Report) {
  return sampleTitle.test(report.titulo) ? report.titulo.slice("[DEMO] ".length) : report.titulo;
}

interface Props {
  reports: Report[];
  language: string;
  busy: boolean;
  tools: ReactNode;
  summary: ReactNode;
  detail?: { reportId: string; onBack: () => void; content: ReactNode };
  lastUpdatedCase?: Report;
  onSelect: (report: Report) => void;
}

export function ReportBoard({ reports, language, busy, tools, summary, detail, lastUpdatedCase, onSelect }: Props) {
  const [filters, setFilters] = useState(emptyFilters);
  const [pages, setPages] = useState([0, 0, 0]);
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [location, setLocation] = useState<{ id: string }>();
  const locatedCard = useRef<HTMLElement>(null);
  const t = (key: string) => translate(language, key);
  const s = (es: string, en: string) => language === "en" ? en : es;
  const now = Date.now();
  const search = normalizeSearch(filters.search.trim());
  const filtered = reports.filter(report => matches(report, filters, search, now));
  const tracked = lastUpdatedCase && (reports.find(report => report.id === lastUpdatedCase.id) ?? lastUpdatedCase);
  const extra = tracked && location?.id === tracked.id && !filtered.some(report => report.id === tracked.id) ? tracked : undefined;
  const boardReports = extra ? [extra, ...filtered] : filtered;
  const showingDetail = Boolean(detail);
  useEffect(() => {
    if (!location || showingDetail) return;
    const frame = window.requestAnimationFrame(() => {
      const card = locatedCard.current;
      card?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      card?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [location, showingDetail]);
  const teams = [...new Set(reports.map(report => report.responsable || "unassigned"))].sort();
  const types = [...new Set(reports.map(report => report.tipo))].sort();
  const teamName = (team: string | null) => !team || team === "unassigned" ? t("noTeam") : language === "en" ? teamNames[team] || team : team;
  const setFilter = (key: Filter, value: string) => {
    setFilters(current => ({ ...current, [key]: value }));
    setPages([0, 0, 0]);
    setLocation(undefined);
  };
  const select = (key: Filter, label: string, options: [string, string][]) =>
    <label>{label}<select value={filters[key]} onChange={event => setFilter(key, event.target.value)}>
      {options.map(([value, text]) => <option value={value} key={value}>{text}</option>)}
    </select></label>;

  function locate(report: Report) {
    setCollapsed(current => current.filter(label => label !== lanes[stage(report)].label));
    setLocation({ id: report.id });
  }

  if (detail) return <section className="panel case-view" aria-labelledby="module-title">
    <button className="secondary" type="button" onClick={() => {
      if (tracked && detail.reportId === tracked.id) locate(tracked);
      detail.onBack();
    }}>{t("backToBoard")}</button>
    {detail.content}
  </section>;

  return <section className="panel" aria-labelledby="module-title">
    {tracked && <aside className="board-follow-up" aria-label={t("lastUpdatedCase")}>
      <div><p className="hint">{t("lastUpdatedCase")}</p><strong>{cardTitle(tracked)}</strong>
        <p className="hint">{t(lanes[stage(tracked)].label)} · {t("requestReference")} <code title={tracked.id}>{tracked.id.slice(0, 8)}</code></p>
      </div>
      <div className="filter-actions">
        <button type="button" className="secondary" onClick={() => locate(tracked)}>{t("locateCase")}</button>
        <button type="button" onClick={() => onSelect(tracked)}>{t("continueCase")}</button>
      </div>
    </aside>}
    <div className="board-filter-panel">
      <div className="board-filter-primary">
        <label>{s("Buscar por título o ID", "Search by title or ID")}
          <input type="search" value={filters.search} onChange={event => setFilter("search", event.target.value)}
            placeholder={s("Ej. Correo falso de soporte", "E.g. Fake support email")} />
        </label>
        {select("status", s("Estado", "Status"), [
          ["", t("all")], ["open", t("pending")], ["0", t("laneNew")], ["1", t("laneProgress")],
          ["2", t("laneDone")], ["review", t("reviewFilter")],
        ])}
        {select("severity", s("Severidad", "Severity"), [
          ["", s("Todas", "All")], ...["critica", "alta", "media", "baja"].map((value): [string, string] => [value, t(value)]),
        ])}
      </div>
      <details className="board-extra-filters">
        <summary>{s("Más filtros", "More filters")}</summary>
        <div className="board-filter-fields">
          {select("type", s("Tipo", "Type"), [["", t("all")], ...types.map((value): [string, string] => [value, t(value)])])}
          {select("team", s("Equipo", "Team"), [["", t("all")], ...teams.map((value): [string, string] => [value, teamName(value)])])}
          {select("deadline", s("Plazo", "Deadline"), [["", t("all")], ["late", t("slaLate")], ["soon", t("slaSoon")]])}
          <label>{s("Desde", "From")}<input type="date" value={filters.from} max={filters.to || undefined}
            onChange={event => setFilter("from", event.target.value)} /></label>
          <label>{s("Hasta", "To")}<input type="date" value={filters.to} min={filters.from || undefined}
            onChange={event => setFilter("to", event.target.value)} /></label>
        </div>
      </details>
      <div className="board-filter-actions">
        <button className="secondary" type="button" aria-pressed={Boolean(filters.sample)}
          onClick={() => setFilter("sample", filters.sample ? "" : "curated")}>
          {s("Muestra del seeder", "Seeded sample")}
        </button>
        {Object.values(filters).some(Boolean) && <button className="ghost" type="button" onClick={() => {
          setFilters(emptyFilters); setPages([0, 0, 0]); setLocation(undefined);
        }}>{s("Limpiar filtros", "Clear filters")}</button>}
      </div>
    </div>
    <div className="list-toolbar">
      <div>
        <p className="hint" role="status">{translate(language, "boardCount", filtered.length, reports.length)}</p>
        <p className="hint">{s("Hasta cuatro por columna. La bandeja abarca los 100 reportes más recientes.", "Up to four per column. The board covers the 100 most recent reports.")}</p>
      </div>
      <div className="flex flex-wrap gap-2">{tools}</div>
    </div>
    {busy && !reports.length && <LoadingBlock label={t("loading")} />}
    <div className="board" aria-busy={busy}>{lanes.map(({ label, tone, icon }, lane) => {
      const items = boardReports.filter(report => stage(report) === lane);
      const lastPage = Math.max(0, Math.ceil(items.length / pageSize) - 1);
      const locatedIndex = location ? items.findIndex(report => report.id === location.id) : -1;
      const page = locatedIndex >= 0 ? Math.floor(locatedIndex / pageSize) : Math.min(pages[lane], lastPage);
      const showPage = (index: number) => {
        setPages(current => current.map((value, column) => column === lane ? index : value));
        if (locatedIndex >= 0) setLocation(undefined);
      };
      const expanded = !collapsed.includes(label);
      const contentId = `board-${label}`;
      return <section className="lane" key={label} aria-label={t(label)} data-tone={tone}>
        <h2 className="lane-heading">
          <button type="button" className="lane-header" aria-expanded={expanded} aria-controls={contentId}
            onClick={() => setCollapsed(current => current.includes(label) ? current.filter(item => item !== label) : [...current, label])}>
            <Icon name={icon} />{t(label)}<span className="lane-count">{items.length}</span>
            <span className="lane-caret" aria-hidden="true" />
          </button>
        </h2>
        <div className="lane-content" id={contentId} hidden={!expanded}>
        <div className="report-list">{items.slice(page * pageSize, (page + 1) * pageSize).map(report => {
          const deadline = nextDeadline(report);
          const remaining = deadline ? Date.parse(deadline) - now : null;
          const step = t(report.respondido_at ? "resolution" : "firstResponse");
          const title = cardTitle(report);
          const located = location?.id === report.id;
          return <article className="report board-card" key={report.id} data-tone={severityTone[report.severidad] || "neutral"}
            data-located={located || undefined} ref={located ? locatedCard : undefined} tabIndex={located ? -1 : undefined}>
            <h3>{title}</h3>
            <p className="hint">{teamName(report.responsable)} · {t(report.tipo)}</p>
            <p className="hint">{t("requestReference")} <code title={report.id}>{report.id.slice(0, 8)}</code></p>
            {extra?.id === report.id && <p className="hint">{t("locatedOutsideFilters")}</p>}
            <div className="chip-row">
              <Badge tone={severityTone[report.severidad] || "neutral"}>{translate(language, "severity", t(report.severidad))}</Badge>
              {report.motivo_revision && <Badge tone="warning">{s("Revisión", "Review")}</Badge>}
              {(report.titulo.startsWith("[DEMO]") || report.origen === "demo") && <Badge tone="demo">DEMO</Badge>}
            </div>
            {deadline && remaining !== null
              ? <p className={remaining < 0 ? "hint late" : "hint"}>{step} · {remaining < 0 ? t("slaLate") : peruDateTime(deadline, language,
                { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</p>
              : <p className="hint">{t(reportState(report))}</p>}
            <button className="secondary" type="button" onClick={() => onSelect(report)}
              aria-label={t("details") + " · " + title}>{t("details")}</button>
          </article>;
        })}{!items.length && !busy && <EmptyState>{t("emptyLane")}</EmptyState>}</div>
        {lastPage > 0 && <nav className="board-pagination" aria-label={s("Páginas", "Pages") + " · " + t(label)}>
          <button className="secondary" type="button" disabled={page === 0} onClick={() => showPage(page - 1)}>{s("Anterior", "Previous")}</button>
          <span className="hint">{page + 1} / {lastPage + 1}</span>
          <button className="secondary" type="button" disabled={page === lastPage} onClick={() => showPage(page + 1)}>{s("Siguiente", "Next")}</button>
        </nav>}
        </div>
      </section>;
    })}</div>
    {summary}
  </section>;
}
