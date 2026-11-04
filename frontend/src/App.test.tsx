import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, cleanup, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./main";
import type { Report } from "./api";

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
  expect(Boolean(screen.queryByRole("button",{name:"Registrar primera respuesta"}))).toBe(role === "analista");
  expect(Boolean(screen.queryByText("Exportar", { selector: "summary" }))).toBe(role === "gestor");
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
