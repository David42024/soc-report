import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./main";
import type { Report } from "./api";
import { peruDateTime, peruDay } from "./time";

const report: Report = {
  id: "test-report", titulo: "Correo falso de soporte", descripcion: "Descripción del incidente",
  tipo: "phishing", severidad: "media", activo_afectado: "correo corporativo", origen: "demo",
  motivo_revision: null, responsable: "Seguridad de correo", recibido_at: "2026-11-03T10:00:00Z",
  notificado_at: "2026-11-03T10:00:01Z", vence_respuesta_at: "2026-11-03T14:00:00Z",
  vence_resolucion_at: "2026-11-04T10:00:00Z", respondido_at: null, resuelto_at: null,
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status,headers:{"Content-Type":"application/json"}});
const apiFetch = vi.fn<typeof fetch>();
const auditFetch = vi.fn<typeof fetch>();
beforeEach(() => {
  localStorage.clear();
  apiFetch.mockReset();
  auditFetch.mockReset().mockImplementation(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", (path: RequestInfo | URL, options?: RequestInit) =>
    path === "/api/audit/visitas" ? auditFetch(path, options) : apiFetch(path, options));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("aplica la fecha y hora de Lima aunque el instante venga en UTC", () => {
  const timestamp = "2026-11-05T04:30:00Z";
  expect(peruDay(timestamp)).toBe("2026-11-04");
  expect(peruDateTime(timestamp, "en", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })).toBe("23:30");
});

it("permite mostrar y ocultar la contraseña sin perder el valor", async () => {
  const user = userEvent.setup(); render(<App />);
  const password = screen.getByLabelText("Contraseña");
  await user.type(password, "solo-prueba-visual");
  expect(password.getAttribute("type")).toBe("password");
  await user.click(screen.getByRole("button", {name: "Mostrar contraseña"}));
  expect(password.getAttribute("type")).toBe("text");
  await user.click(screen.getByRole("button", {name: "Ocultar contraseña"}));
  expect(password.getAttribute("type")).toBe("password");
  expect((password as HTMLInputElement).value).toBe("solo-prueba-visual");
  expect(apiFetch).not.toHaveBeenCalled();
});

it("recuerda el tema y cambia los textos del formulario al inglés", async () => {
  const user = userEvent.setup(); render(<App />);
  await user.click(within(screen.getByRole("radiogroup", {name: "Tema"})).getByRole("radio", {name: "Oscuro"}));
  await user.click(within(screen.getByRole("radiogroup", {name: "Idioma"})).getByRole("radio", {name: "English"}));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("soc-language")).toBe("en");
  expect(screen.getByRole("heading", {name: "Sign in"})).toBeDefined();
  expect(screen.queryByRole("navigation", {name: "Modules"})).toBeNull();
  await user.click(screen.getByRole("button", {name: "Report without signing in"}));
  expect(screen.getByLabelText("Title")).toBeDefined();
  expect(screen.getByRole("button",{name:"Submit report"})).toBeDefined();
});

it("conserva la clave de idempotencia al repetir un envío fallido", async () => {
  const user = userEvent.setup();
  apiFetch.mockResolvedValueOnce(json({detail:"Prueba de fallo"},503)).mockResolvedValueOnce(json(report,201));
  render(<App />);
  await user.click(screen.getByRole("button", {name: "Reportar sin iniciar sesión"}));
  await user.type(screen.getByLabelText("Título"), report.titulo);
  await user.type(screen.getByLabelText("Descripción"), report.descripcion);
  await user.click(screen.getByRole("button",{name:"Enviar reporte"}));
  await screen.findByRole("alert");
  await user.click(screen.getByRole("button",{name:"Enviar reporte"}));
  await screen.findByText(/ID: test-report/);
  const calls = apiFetch.mock.calls;
  expect(new Headers(calls[0][1]?.headers).get("Idempotency-Key")).toBe(new Headers(calls[1][1]?.headers).get("Idempotency-Key"));
  expect(screen.getByRole("status").textContent).toContain("test-report");
  await user.click(screen.getByRole("button", {name: "Volver a iniciar sesión"}));
  expect(screen.getByLabelText("Usuario")).toBeDefined();
});

it.each(["gestor", "analista"])("%s ve los casos con los controles de su rol", async (role) => {
  const user = userEvent.setup();
  apiFetch.mockImplementation(async (path) => {
    if (path === "/api/auth/login") return json({access_token:"test-token",user:{id:role,username:role,role,active:1}});
    if (path === "/api/reportes") return json([report]);
    if (path === "/api/metricas") return json({total:1,respuesta_evaluable:0,resolucion_evaluable:0});
    if (path === "/api/triage") return json({baseline:null,comparable_reports:0,estimated_hours_saved:null});
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"),role);
  await user.type(screen.getByLabelText("Contraseña"),"password");
  await user.click(screen.getByRole("button",{name:"Ingresar"}));
  await screen.findByText(report.titulo);
  expect(screen.getByRole("region",{name:"Por atender"})).toBeDefined();
  expect(screen.getByRole("region",{name:"En atención"})).toBeDefined();
  expect(screen.getByRole("region",{name:"Resueltos"})).toBeDefined();
  expect(Boolean(screen.queryByText("Exportar", { selector: "summary" }))).toBe(role === "gestor");
  await user.click(screen.getByRole("button", { name: "Ver detalle · " + report.titulo }));
  expect(Boolean(screen.queryByRole("button",{name:"Registrar primera respuesta"}))).toBe(role === "analista");
  expect(screen.getByText(report.descripcion)).toBeDefined();
});

it("pagina por columna y conserva los filtros al volver del detalle", async () => {
  const user = userEvent.setup();
  const reports = Array.from({ length: 6 }, (_, i) => ({
    ...report, id: "case-" + i, titulo: "Incidente " + (i + 1), severidad: i < 5 ? "media" : "alta",
  }));
  apiFetch.mockImplementation(async path => {
    if (path === "/api/auth/login") return json({ access_token: "test-token", user: { id: "analista", username: "analista", role: "analista", active: 1 } });
    if (path === "/api/reportes") return json(reports);
    if (path === "/api/metricas" || path === "/api/triage") return json({});
    return json([]);
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"), "analista");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
  await screen.findByText("Incidente 1");
  const lane = screen.getByRole("region", { name: "Por atender" });
  expect(within(lane).getAllByRole("article")).toHaveLength(4);
  await user.click(within(lane).getByRole("button", { name: "Siguiente" }));
  expect(within(lane).getAllByRole("article")).toHaveLength(2);
  await user.selectOptions(screen.getByRole("combobox", { name: "Severidad" }), "alta");
  await user.type(screen.getByRole("searchbox", { name: "Buscar por título o ID" }), "case-5");
  expect(within(lane).getAllByRole("article")).toHaveLength(1);
  expect(within(lane).queryByText(report.descripcion)).toBeNull();
  await user.click(within(lane).getByRole("button", { name: "Ver detalle · Incidente 6" }));
  expect(screen.getByText(report.descripcion)).toBeDefined();
  await user.click(screen.getByRole("button", { name: "Volver al tablero" }));
  expect(screen.getByText("1 de 6 reportes recientes")).toBeDefined();
});

it("ubica el mismo caso tras cada hito aunque cambie de página o quede fuera del filtro", async () => {
  const user = userEvent.setup();
  let target = { ...report, id: "target-case", titulo: "Alerta repetida" };
  const attending = Array.from({ length: 5 }, (_, index) => ({
    ...target, id: "other-" + index, respondido_at: "2026-11-03T11:00:00Z",
  }));
  apiFetch.mockImplementation(async (path, options) => {
    if (path === "/api/auth/login") return json({ access_token: "test-token", user: { id: "analista", username: "analista", role: "analista", active: 1 } });
    if (path === "/api/reportes") return json([...attending, target]);
    if (path === "/api/metricas" || path === "/api/triage") return json({});
    if (options?.method === "POST" && path === "/api/reportes/target-case/responder") {
      target = { ...target, respondido_at: "2026-11-03T12:00:00Z" };
      return json(target);
    }
    if (options?.method === "POST" && path === "/api/reportes/target-case/resolver") {
      target = { ...target, resuelto_at: "2026-11-03T13:00:00Z" };
      return json(target);
    }
    return json([]);
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"), "analista");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
  const pending = await screen.findByRole("region", { name: "Por atender" });
  const details = await within(pending).findByRole("button", { name: "Ver detalle · Alerta repetida" });
  const attendingLane = screen.getByRole("region", { name: "En atención" });
  await user.click(within(attendingLane).getByRole("button", { name: "En atención 5" }));
  await user.click(details);
  await user.click(screen.getByRole("button", { name: "Registrar primera respuesta" }));
  await screen.findByRole("button", { name: "Marcar resuelto" });
  await user.click(screen.getByRole("button", { name: "Volver al tablero" }));

  const movedLane = screen.getByRole("region", { name: "En atención" });
  expect(within(movedLane).getByRole("button", { name: "En atención 6" }).getAttribute("aria-expanded")).toBe("true");
  expect(within(movedLane).getByText("2 / 2")).toBeDefined();
  const moved = within(movedLane).getByText("target-c").closest("article");
  expect(moved?.getAttribute("data-located")).toBe("true");

  await user.selectOptions(screen.getByLabelText("Estado"), "1");
  await user.click(screen.getByRole("button", { name: "Continuar seguimiento" }));
  await user.click(screen.getByRole("button", { name: "Marcar resuelto" }));
  await screen.findByText("Reporte marcado como resuelto.");
  await user.click(screen.getByRole("button", { name: "Volver al tablero" }));
  const resolvedLane = screen.getByRole("region", { name: "Resueltos" });
  expect(within(resolvedLane).getByText("target-c").closest("article")?.getAttribute("data-located")).toBe("true");
  expect(within(resolvedLane).getByText("Caso visible para seguimiento. Queda fuera de los filtros actuales.")).toBeDefined();
  expect((screen.getByLabelText("Estado") as HTMLSelectElement).value).toBe("1");
});

it("filtra la muestra del seeder y pliega cada columna de forma independiente", async () => {
  const user = userEvent.setup();
  const recent = [
    { ...report, id: "seed-1", titulo: "[DEMO] SOC-01 · Caso pendiente" },
    { ...report, id: "seed-2", titulo: "[DEMO] SOC-02 · Caso en atención", respondido_at: report.notificado_at },
    { ...report, id: "seed-3", titulo: "[DEMO] SOC-03 · Caso resuelto", respondido_at: report.notificado_at, resuelto_at: report.notificado_at },
    { ...report, id: "older-demo", titulo: "[DEMO] 1 Correo falso de soporte" },
  ];
  apiFetch.mockImplementation(async path => {
    if (path === "/api/auth/login") return json({ access_token: "test-token", user: { id: "analista", username: "analista", role: "analista", active: 1 } });
    if (path === "/api/reportes") return json(recent);
    if (path === "/api/metricas" || path === "/api/triage") return json({});
    return json([]);
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"), "analista");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
  await screen.findByText(recent[3].titulo);
  const sample = screen.getByRole("button", { name: "Muestra del seeder" });
  await user.click(sample);
  expect(sample.getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByText(recent[3].titulo)).toBeNull();
  expect(screen.getByText("3 de 4 reportes recientes")).toBeDefined();

  const lanes = ["Por atender", "En atención", "Resueltos"].map(name => screen.getByRole("region", { name }));
  for (const lane of lanes) {
    const toggle = within(lane).getByRole("button", { name: /^(Por atender|En atención|Resueltos) 1$/ });
    await user.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(within(lane).queryByRole("article")).toBeNull();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    await user.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(within(lane).getByRole("article")).toBeDefined();
  }
});

it("el solicitante envía con su sesión y actualiza los hitos de su propia solicitud", async () => {
  const user = userEvent.setup();
  const progress = { ...report, asignado_at: report.notificado_at };
  let submitted = false;
  let readAt: string | null = null;
  apiFetch.mockImplementation(async (path, options) => {
    if (path === "/api/auth/login") return json({ access_token: "requester-token", user: { id: "owner", username: "persona", role: "solicitante", active: 1 } });
    if (path === "/api/mis-solicitudes") return json(submitted ? [progress] : []);
    if (path === "/api/reportes" && options?.method === "POST") {
      submitted = true;
      expect(new Headers(options.headers).get("Authorization")).toBe("Bearer requester-token");
      return json(report, 201);
    }
    if (path === "/api/mis-solicitudes/test-report") return json(progress);
    if (String(path).startsWith("/api/mis-solicitudes/notificaciones")) return json(submitted ? [{
      report_id: report.id, titulo: report.titulo, responsable: report.responsable, accion: "asignado",
      ocurrido_at: report.notificado_at, read_at: readAt,
    }] : []);
    if (path === "/api/mis-solicitudes/test-report/notificaciones/asignado/leida" && options?.method === "PUT") {
      readAt = report.notificado_at;
      return new Response(null, { status: 204 });
    }
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"), "persona");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
  await screen.findByText("Aún no has enviado reportes con esta cuenta.");
  expect(screen.queryByRole("button", { name: "Tablero del operador" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Dashboard e informes" })).toBeNull();
  await user.click(within(screen.getByRole("main")).getByRole("button", { name: "Nuevo reporte" }));
  await user.type(screen.getByLabelText("Título"), report.titulo);
  await user.type(screen.getByLabelText("Descripción"), report.descripcion);
  await user.click(screen.getByRole("button", { name: "Enviar reporte" }));
  await user.click(await screen.findByRole("button", { name: "Ver progreso" }));
  await screen.findByText("En espera de atención");
  expect(screen.queryByRole("button", { name: "Ver bitácora" })).toBeNull();
  progress.respondido_at = "2026-11-03T11:00:00Z";
  await user.click(screen.getByRole("button", { name: "Actualizar estado" }));
  await screen.findByText("En atención");
  progress.resuelto_at = "2026-11-03T12:00:00Z";
  await user.click(screen.getByRole("button", { name: "Actualizar estado" }));
  await screen.findByText("Resuelto");
  await user.click(await screen.findByRole("button", { name: "Notificaciones · 1 sin leer" }));
  await screen.findByText("Equipo asignado ·");
  await user.click(screen.getByRole("button", { name: "Marcar leída" }));
  await screen.findByRole("button", { name: "Notificaciones · 0 sin leer" });
  await user.click(screen.getByRole("button", { name: "Ver progreso" }));
  await screen.findByText("Resuelto");
});

it("combina los filtros de mis solicitudes y los conserva al volver del detalle", async () => {
  const user = userEvent.setup();
  const first = { ...report, id: "case-a", titulo: "Intrusión en portal", recibido_at: "2026-11-05T04:30:00Z", asignado_at: null };
  const second = { ...first, id: "case-b", titulo: "Intrusión descartada", recibido_at: "2026-11-05T05:30:00Z",
    respondido_at: "2026-11-05T06:00:00Z", resuelto_at: "2026-11-05T07:00:00Z" };
  apiFetch.mockImplementation(async path => {
    if (path === "/api/auth/login") return json({ access_token: "requester-token", user: { id: "owner", username: "persona", role: "solicitante", active: 1 } });
    if (path === "/api/mis-solicitudes") return json([first, second]);
    if (path === "/api/mis-solicitudes/case-a") return json(first);
    if (String(path).startsWith("/api/mis-solicitudes/notificaciones")) return json([]);
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"), "persona");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
  await screen.findByText("2 de 2 solicitudes");

  const search = screen.getByRole("searchbox", { name: "Buscar por título o referencia" });
  await user.type(search, "intrusion");
  await user.selectOptions(screen.getByLabelText("Estado"), "done");
  expect(screen.queryByRole("heading", { name: first.titulo })).toBeNull();
  expect(screen.getByRole("heading", { name: second.titulo })).toBeDefined();
  fireEvent.change(screen.getByLabelText("Recibido hasta"), { target: { value: "2026-11-04" } });
  expect(screen.getByText("No hay solicitudes que coincidan con los filtros.")).toBeDefined();
  await user.selectOptions(screen.getByLabelText("Estado"), "");
  await user.clear(search);
  await user.type(search, first.id);
  await user.click(screen.getByRole("button", { name: "Ver progreso · " + first.titulo }));
  await screen.findByText("Progreso de la solicitud");
  await user.click(screen.getByRole("button", { name: "Volver a mis solicitudes" }));
  expect(screen.getByText("1 de 2 solicitudes")).toBeDefined();
  expect((screen.getByLabelText("Recibido hasta") as HTMLInputElement).value).toBe("2026-11-04");
  await user.click(screen.getByRole("button", { name: "Limpiar filtros" }));
  expect(screen.getByText("2 de 2 solicitudes")).toBeDefined();
});

it("el gestor abre el dashboard, aplica filtros y registra el cambio de módulo", async () => {
  const user = userEvent.setup();
  const result = { total: 120, demo: 3, estados: {}, tipos: {}, severidades: {}, sla: {},
    mensual: [], tiempos: {}, equipos: [], clasificador: [] };
  apiFetch.mockImplementation(async path => {
    if (path === "/api/auth/login") return json({access_token:"test-token",user:{id:"manager",username:"gestor",role:"gestor",active:1}});
    if (path === "/api/reportes") return json([]);
    if (path === "/api/metricas") return json({total:120,respuesta_evaluable:0,resolucion_evaluable:0});
    if (path === "/api/triage") return json({baseline:null,comparable_reports:0,estimated_hours_saved:null});
    if (path === "/api/dashboard") return json(result);
    if (path === "/api/dashboard?tipo=malware") return json({ ...result, total: 7, demo: 0 });
    if (path === "/api/activos") return json([]);
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"),"gestor");
  await user.type(screen.getByLabelText("Contraseña"),"password");
  await user.click(screen.getByRole("button",{name:"Ingresar"}));
  const sidebar = await screen.findByRole("complementary", {name: "Área de trabajo"});
  const dashboardButton = within(sidebar).getByRole("button",{name:"Dashboard e informes"});
  await user.click(dashboardButton);
  expect(dashboardButton.getAttribute("aria-current")).toBe("page");
  await screen.findByText("120");
  expect(screen.getByText("3 DEMO")).toBeDefined();
  await user.selectOptions(screen.getByLabelText("Tipo"), "malware");
  await user.click(screen.getByRole("button", { name: "Aplicar" }));
  await screen.findByText("7");
  const visits = auditFetch.mock.calls.map(([, options]) => JSON.parse(String(options?.body)));
  expect(visits.some(row => row.modulo === "login")).toBe(true);
  const inbox = visits.find(row => row.modulo === "inbox");
  const dashboard = visits.find(row => row.modulo === "dashboard");
  expect(inbox.id).toBe(dashboard.id);
  expect(inbox.secuencia).toBeLessThan(dashboard.secuencia);
  expect(screen.queryByRole("button",{name:"Usuarios"})).toBeNull();
  const operations = within(sidebar).getByRole("navigation", {name: "Operaciones"});
  await user.click(within(operations).getByRole("button", {name: "Activos"}));
  await screen.findByRole("heading", {name: "Activos"});
  expect(within(operations).queryByRole("button", {name: "Reglas y SLA"})).toBeNull();
});

it.each([204, 401])("permite pasar de auditor a gestor tras cerrar sesión (HTTP %s)", async logoutStatus => {
  const user = userEvent.setup();
  apiFetch.mockImplementation(async (path, options) => {
    if (path === "/api/auth/login") {
      const role = JSON.parse(String(options?.body)).username;
      return json({ access_token: role + "-token", user: { id: role, username: role, role, active: 1 } });
    }
    if (path === "/api/auth/logout") {
      expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer auditor-token");
      return new Response(null, { status: logoutStatus });
    }
    if (path === "/api/reportes" || String(path).startsWith("/api/audit?")) return json([]);
    if (path === "/api/metricas") return json({ total: 0 });
    if (path === "/api/triage") return json({ baseline: null });
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"), "auditor");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
  expect(await screen.findByRole("heading", { name: "Auditoría" })).toBeDefined();
  expect(screen.queryByRole("button", { name: "Dashboard e informes" })).toBeNull();
  await user.click(screen.getByRole("button", {name: "Menú de usuario"}));
  await user.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  await user.type(await screen.findByLabelText("Usuario"), "gestor");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
  expect(await screen.findByRole("button", { name: "Dashboard e informes" })).toBeDefined();
});

it("el menú de usuario muestra avisos, persiste el tema y cierra con Escape o clic fuera", async () => {
  const user = userEvent.setup();
  apiFetch.mockImplementation(async path => {
    if (path === "/api/auth/login") return json({access_token:"test-token",user:{id:"manager",username:"gestor",role:"gestor",active:1}});
    if (path === "/api/reportes") return json([]);
    if (path === "/api/metricas") return json({total:0});
    if (path === "/api/triage") return json({baseline:null});
    if (String(path).startsWith("/api/notificaciones")) return json([{read_at:null},{read_at:"2026-11-03"}]);
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"), "gestor");
  await user.type(screen.getByLabelText("Contraseña"), "password");
  await user.click(screen.getByRole("button", {name:"Ingresar"}));
  await screen.findByRole("button", {name:"Notificaciones · 1 sin leer"});
  const trigger = screen.getByRole("button", {name:"Menú de usuario"});
  await user.click(trigger);
  const dialog = screen.getByRole("dialog", {name:"Tu cuenta"});
  const light = within(dialog).getByRole("radio", {name:"Claro"});
  await user.click(light);
  await user.click(within(dialog).getByRole("radio", {name:"Oscuro"}));
  expect(localStorage.getItem("soc-theme")).toBe("dark");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", {name:"Tu cuenta"})).toBeNull();
  expect(document.activeElement).toBe(trigger);
  await user.click(trigger);
  await user.click(screen.getByRole("heading", {name:"Tablero del operador"}));
  expect(screen.queryByRole("dialog", {name:"Tu cuenta"})).toBeNull();
});

it("solicita el segundo factor y lo envía con el siguiente intento", async () => {
  const user = userEvent.setup();
  apiFetch.mockImplementation(async (path, options) => {
    if (path === "/api/auth/login") {
      const data = JSON.parse(String(options?.body));
      if (!data.otp) return json({ detail: "Factor requerido" }, 428);
      expect(data.otp).toBe("123456");
      return json({access_token:"test-token",user:{id:"audit",username:"auditor",role:"auditor",active:1}});
    }
    if (typeof path === "string" && path.startsWith("/api/audit?")) return json([]);
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"),"auditor");
  await user.type(screen.getByLabelText("Contraseña"),"password");
  await user.click(screen.getByRole("button",{name:"Ingresar"}));
  await user.type(await screen.findByLabelText("Código de segundo factor o recuperación"),"123456");
  await user.click(screen.getByRole("button",{name:"Ingresar"}));
  await screen.findByRole("heading", { name:"Auditoría" });
});

it("el chat flotante llama a la API y muestra el proveedor de la respuesta", async () => {
  const user = userEvent.setup(); render(<App />);
  apiFetch.mockResolvedValue(json({reply:"SLA es el plazo de atención.",provider:"Groq"}));
  await user.click(screen.getByRole("button",{name:"Asistente SOC"}));
  expect(screen.getByRole("dialog")).toBeDefined();
  await user.type(screen.getByLabelText("Tu pregunta"),"¿Qué es el SLA?");
  await user.click(screen.getByRole("button",{name:"Enviar"}));
  await waitFor(() => expect(screen.getByRole("log").textContent).toContain("SLA es el plazo"));
  expect(screen.getByRole("log").textContent).toContain("Groq");
  expect(apiFetch.mock.calls[0][0]).toBe("/api/chat");
  await user.click(screen.getByRole("button",{name:"Cerrar chat"}));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("el chat envía con Enter, conserva Shift+Enter y mantiene la conversación al minimizar", async () => {
  const user = userEvent.setup();
  let reply!: (response: Response) => void;
  apiFetch.mockImplementationOnce(() => new Promise<Response>(resolve => { reply = resolve; }));
  render(<App />);
  const launcher = screen.getByRole("button", {name: "Asistente SOC"});
  await user.click(launcher);
  const input = screen.getByLabelText("Tu pregunta");
  await user.type(input, "Primera línea");
  await user.keyboard("{Shift>}{Enter}{/Shift}");
  await user.type(input, "Segunda línea");
  expect(apiFetch).not.toHaveBeenCalled();
  await user.keyboard("{Enter}");
  expect(apiFetch).toHaveBeenCalledTimes(1);
  const body = JSON.parse(String(apiFetch.mock.calls[0][1]?.body));
  expect(body).toEqual({language:"es", messages:[{role:"user",content:"Primera línea\nSegunda línea"}]});
  expect(screen.getByText("Preparando respuesta…")).toBeDefined();
  reply(json({reply:"Consulta recibida.",provider:"Groq"}));
  await screen.findByText("Consulta recibida.");
  await user.click(screen.getByRole("button", {name:"Minimizar chat"}));
  await waitFor(() => expect(document.activeElement).toBe(launcher));
  await user.click(launcher);
  expect(screen.getByText("Consulta recibida.")).toBeDefined();
  await user.keyboard("{Escape}");
  await waitFor(() => expect(document.activeElement).toBe(launcher));
});

it("el chat conserva el contexto y muestra el respaldo Gemini", async () => {
  const user = userEvent.setup(); render(<App />);
  apiFetch.mockResolvedValueOnce(json({reply:"Primera respuesta.",provider:"Groq"}))
    .mockResolvedValueOnce(json({reply:"Seguimiento con contexto.",provider:"Gemini"}));
  await user.click(screen.getByRole("button",{name:"Asistente SOC"}));
  await user.type(screen.getByLabelText("Tu pregunta"),"¿Cómo reporto?");
  await user.click(screen.getByRole("button",{name:"Enviar"}));
  await screen.findByText("Primera respuesta.");
  await user.type(screen.getByLabelText("Tu pregunta"),"¿Y después?");
  await user.click(screen.getByRole("button",{name:"Enviar"}));
  await screen.findByText("Seguimiento con contexto.");
  const body=JSON.parse(String(apiFetch.mock.calls[1][1]?.body));
  expect(body.messages.map((message: {role:string})=>message.role)).toEqual(["user","assistant","user"]);
  expect(body.messages[1].content).toBe("Primera respuesta.");
  expect(screen.getByRole("log").textContent).toContain("Gemini · respaldo");
});

it("un fallo permite reintentar sin duplicar la pregunta", async () => {
  const user = userEvent.setup(); render(<App />);
  apiFetch.mockResolvedValueOnce(json({detail:"No disponible"},503))
    .mockResolvedValueOnce(json({reply:"Respuesta recuperada.",provider:"Gemini"}));
  await user.click(screen.getByRole("button",{name:"Asistente SOC"}));
  await user.type(screen.getByLabelText("Tu pregunta"),"Pregunta de prueba");
  await user.click(screen.getByRole("button",{name:"Enviar"}));
  await screen.findByRole("alert");
  await user.click(screen.getByRole("button",{name:"Reintentar"}));
  await screen.findByText("Respuesta recuperada.");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getAllByText("Pregunta de prueba")).toHaveLength(1);
  expect(apiFetch.mock.calls[0][1]?.body).toBe(apiFetch.mock.calls[1][1]?.body);
});

it("presenta Markdown como negritas, listas, enlaces y código", async () => {
  const user = userEvent.setup();
  const reply = [
    "Una vez dentro, podrás:",
    "- Crear un nuevo informe desde la vista **Nuevo informe**.\n- Ver casos en el **Tablero de operador**.",
    "1. Guardar\n2. Consultar",
    "Usa `/health` para comprobar la API.",
    "```powershell\nGet-Date\n```",
    "[Documentación](https://example.com/docs)",
  ].join("\n\n");
  apiFetch.mockResolvedValue(json({reply,provider:"Groq"}));
  render(<App />);
  await user.click(screen.getByRole("button",{name:"Asistente SOC"}));
  await user.type(screen.getByLabelText("Tu pregunta"),"¿Qué puedo hacer?");
  await user.click(screen.getByRole("button",{name:"Enviar"}));
  const bold = await screen.findByText("Nuevo informe");
  expect(bold.tagName).toBe("STRONG");
  const markdown = bold.closest(".chat-markdown") as HTMLElement;
  expect(within(markdown).getAllByRole("list")).toHaveLength(2);
  expect(within(markdown).getAllByRole("listitem")).toHaveLength(4);
  expect(within(markdown).getByText("/health").tagName).toBe("CODE");
  expect(markdown.querySelector("pre code")?.textContent).toContain("Get-Date");
  const link = within(markdown).getByRole("link",{name:"Documentación"});
  expect(link.getAttribute("href")).toBe("https://example.com/docs");
  expect(link.getAttribute("rel")).toContain("noopener");
  expect(markdown.textContent).not.toContain("**");
});

it("el Markdown descarta HTML activo y URLs ejecutables", async () => {
  const user = userEvent.setup();
  apiFetch.mockResolvedValue(json({
    reply:'**Texto válido**\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">\n\n[peligroso](javascript:alert(1))\n\n![Imagen](https://example.com/tracker.png)',
    provider:"Gemini",
  }));
  render(<App />);
  await user.click(screen.getByRole("button",{name:"Asistente SOC"}));
  await user.type(screen.getByLabelText("Tu pregunta"),"Prueba de formato");
  await user.click(screen.getByRole("button",{name:"Enviar"}));
  await screen.findByText("Texto válido");
  const log = screen.getByRole("log");
  expect(log.querySelector("script, img, iframe")).toBeNull();
  for (const link of log.querySelectorAll("a")) {
    expect(link.getAttribute("href") || "").not.toMatch(/^(javascript|data|vbscript):/i);
  }
});

it("muestra la evolución histórica identificada como DEMO y mantiene el ámbito real separado", async () => {
  const user = userEvent.setup();
  apiFetch.mockImplementation(async (path) => {
    if (path === "/api/auth/login") return json({access_token:"test-token",user:{id:"manager",username:"gestor",role:"gestor",active:1}});
    if (path === "/api/reportes") return json([]);
    if (path === "/api/metricas") return json({total:0,respuesta_evaluable:0,resolucion_evaluable:0});
    if (path === "/api/triage") return json({baseline:null,comparable_reports:0,estimated_hours_saved:null});
    if (path === "/api/estudios-impacto") return json([]);
    if (path === "/api/impacto") return json({
      source:"demo",is_demo:true,sla_target_pct:90,measured_baselines:0,
      sla_demo: {source:"demo", tipo:"phishing", severidad:"media", respuesta_min:240, resolucion_min:1440,
        meta_mejora_pp:15, meta_cumplida:true, mejora_pp:{respuesta:30,resolucion:30}, grupos:{
          manual:{desde:"2026-09-01",hasta:"2026-09-30",respuesta:{a_tiempo:26,evaluables:40,porcentaje:65},resolucion:{a_tiempo:24,evaluables:40,porcentaje:60}},
          asistido:{desde:"2026-10-01",hasta:"2026-10-31",respuesta:{a_tiempo:38,evaluables:40,porcentaje:95},resolucion:{a_tiempo:36,evaluables:40,porcentaje:90}},
        }},
      periods:[
        {period:"2026-05",source:"demo",report_count:40,response_on_time:22,resolution_on_time:20,response_pct:55,resolution_pct:50,manual_seconds_per_case:900,automated_seconds_per_case:720,review_seconds_per_case:90,estimated_hours_saved:1},
        {period:"2026-10",source:"demo",report_count:40,response_on_time:38,resolution_on_time:37,response_pct:95,resolution_pct:92.5,manual_seconds_per_case:900,automated_seconds_per_case:120,review_seconds_per_case:30,estimated_hours_saved:8.333},
      ],
    });
    throw new Error(String(path));
  });
  render(<App />);
  await user.type(screen.getByLabelText("Usuario"),"gestor");
  await user.type(screen.getByLabelText("Contraseña"),"password");
  await user.click(screen.getByRole("button",{name:"Ingresar"}));
  await user.click(await screen.findByRole("button",{name:"Evolución"}));
  await screen.findByText("DEMO · Datos históricos simulados");
  await screen.findByText("2026-05");
  expect(screen.getByText("2026-10")).toBeDefined();
  expect(screen.getByText(/55 % → 95 %/)).toBeDefined();
  expect(screen.getByText("Evidencia operacional real")).toBeDefined();
  expect(screen.getByText(/no acreditan resultados operativos reales/)).toBeDefined();
  const comparison = screen.getByRole("table", { name: "Comparación de SLA DEMO" });
  expect(within(comparison).getByText("26/40 · 65 %")).toBeDefined();
  expect(within(comparison).getByText("36/40 · 90 %")).toBeDefined();
  expect(within(comparison).getAllByText("+30 pp")).toHaveLength(2);
  expect(screen.getByText(/Alcanzada en la simulación/)).toBeDefined();
});
