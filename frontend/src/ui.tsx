import { useEffect, useRef, type RefObject, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";

const paths = {
  shield: "M12 22s7-3 7-10V5l-7-3-7 3v7c0 7 7 10 7 10ZM9 12l2 2 4-4",
  report: "M14 2H6v20h12V6l-4-4ZM14 2v5h5M9 12h6m-6 4h6",
  board: "M3 4h18v16H3zM9 4v16m6-16v16",
  chart: "M3 3v18h18M7 16v-5m5 5V7m5 9v-8",
  trend: "m3 17 6-6 4 3 7-9m-5 0h5v5",
  audit: "M6 3h12v18H6zM9 7h6m-6 5h6m-6 5h4",
  users: "M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2m14-6a4 4 0 0 1 4 4v2M13 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm4-3a3 3 0 0 1 0 6",
  user: "M20 21v-2a5 5 0 0 0-5-5H9a5 5 0 0 0-5 5v2m12-14a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  bell: "M5 10a7 7 0 0 1 14 0v5l2 3H3l2-3zm4 11h6",
  assets: "M3 4h18v13H3zm5 17h8m-4-4v4",
  pulse: "M2 12h5l3-7 4 14 3-7h5",
  search: "m21 21-5-5m2-5a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z",
  rules: "M5 3v18m7-18v18m7-18v18M2 8h6m1 7h6m1-8h6",
  menu: "M4 6h16M4 12h16M4 18h16",
  collapse: "M3 4h18v16H3zm5 0v16m8-11-3 3 3 3",
  eye: "M2 12s4-6 10-6 10 6 10 6-4 6-10 6-10-6-10-6Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  eyeOff: "m3 3 18 18M10 6l2-.1c6 0 10 6.1 10 6.1a16 16 0 0 1-3 3.2M6 8a16 16 0 0 0-4 4s4 6 10 6c1.3 0 2.5-.3 3.6-.7",
  clock: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Zm-10-5v5l3 2",
  warning: "M12 3 2 20h20L12 3Zm0 6v5m0 3v.1",
  check: "m5 12 4 4L19 6",
  info: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Zm-10 0v5m0-10v.1",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5",
  settings: "M4 6h16M4 12h16M4 18h16M8 4v4m8 2v4m-6 2v4",
  sun: "M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5m-3 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  moon: "M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z",
  logout: "M9 3H4v18h5m5-14 5 5-5 5m-5-5h10",
  close: "m6 6 12 12M6 18 18 6",
  minimize: "M5 12h14",
  send: "m3 3 18 9-18 9 4-9-4-9Zm4 9h14",
  chat: "M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-6 4V6a2 2 0 0 1 2-2ZM7 9h10m-10 4h7",
} as const;

export type IconName = keyof typeof paths;
export type Tone = "neutral" | "info" | "warning" | "danger" | "success" | "demo" | "critical" | "high" | "medium" | "low";

export function Button({ variant = "primary", className = "", type = "button", ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" }) {
  return <button {...props} type={type} className={`${variant === "primary" ? "" : variant} ${className}`.trim()} />;
}

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={`metric ${className}`.trim()} />;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function DataTable({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <div className={`table-scroll ${className}`.trim()} tabIndex={0} role="region" aria-label={label}>{children}</div>;
}

export function Avatar({ name }: { name: string }) {
  return <span className="avatar" aria-hidden="true">{name.slice(0, 2).toUpperCase()}</span>;
}

export function Popover({ id, label, anchor, onClose, children }: {
  id: string; label: string; anchor: RefObject<HTMLButtonElement>;
  onClose: () => void; children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("button, input:checked, input, a")?.focus();
    function outside(event: PointerEvent) {
      if (!panel.current?.contains(event.target as Node) && !anchor.current?.contains(event.target as Node)) onClose();
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") { event.stopPropagation(); onClose(); anchor.current?.focus(); }
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [anchor, onClose]);
  return <div ref={panel} id={id} className="popover" role="dialog" aria-label={label}>{children}</div>;
}

export function Icon({ name }: { name: IconName }) {
  return <svg className="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

export function Badge({ children, tone = "neutral", icon }: { children: ReactNode; tone?: Tone; icon?: IconName }) {
  return <span className="badge" data-tone={tone}>{icon && <Icon name={icon} />}{children}</span>;
}

export function KpiCard({ title, value, icon, children, tone = "info" }: {
  title: string; value: ReactNode; icon: IconName; children?: ReactNode; tone?: Tone;
}) {
  return <Card className="kpi" data-tone={tone}>
    <div className="kpi-heading"><span className="kpi-icon"><Icon name={icon} /></span><h3>{title}</h3></div>
    <p className="rate">{value}</p>{children && <div className="kpi-context">{children}</div>}
  </Card>;
}

export function LoadingBlock({ label }: { label: string }) {
  return <div className="loading-block" role="status"><span>{label}</span><div aria-hidden="true" /></div>;
}

export function ExportMenu({ label, disabled, onSelect }: {
  label: string; disabled: boolean; onSelect: (format: string) => void;
}) {
  const menu = useRef<HTMLDetailsElement>(null);
  return <details className="export-menu" ref={menu}><summary><Icon name="download" />{label}</summary>
    <div>{["pdf", "docx", "xlsx"].map(format => <Button variant="ghost" key={format} disabled={disabled}
      onClick={() => { if (menu.current) menu.current.open = false; onSelect(format); }}>
      {label} {format.toUpperCase()}
    </Button>)}</div>
  </details>;
}
