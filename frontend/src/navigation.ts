import { useEffect, useRef } from "react";
import { request } from "./api";

type Visit = {
  id: string;
  token: string;
  sequence: number;
  module: string | null;
  pending: Promise<void>;
};

function publish(visit: Visit, module: string | null, immediate = false) {
  const body = JSON.stringify({ id: visit.id, secuencia: ++visit.sequence, modulo: module });
  const send = () => request<void>("/api/audit/visitas", visit.token, { method: "POST", body, keepalive: true }).catch(() => undefined);
  if (immediate) return send();
  visit.pending = visit.pending.then(send);
  return visit.pending;
}

export function useAuditVisit(token: string, module: string | null) {
  const current = useRef<Visit>();

  useEffect(() => {
    const visit: Visit = { id: crypto.randomUUID(), token, sequence: 0, module: null, pending: Promise.resolve() };
    current.current = visit;
    function pageExit() {
      if (visit.module) void publish(visit, null, true);
    }
    function renew() {
      if (visit.module) void publish(visit, visit.module);
    }
    const heartbeat = window.setInterval(renew, 60_000);
    window.addEventListener("pagehide", pageExit);
    window.addEventListener("pageshow", renew);
    return () => {
      window.clearInterval(heartbeat);
      window.removeEventListener("pagehide", pageExit);
      window.removeEventListener("pageshow", renew);
      if (visit.module) void publish(visit, null);
    };
  }, [token]);

  useEffect(() => {
    const visit = current.current;
    if (!visit || visit.module === module) return;
    visit.module = module;
    void publish(visit, module);
  }, [token, module]);

  return () => {
    const visit = current.current;
    if (!visit?.module) return Promise.resolve();
    visit.module = null;
    return publish(visit, null);
  };
}
