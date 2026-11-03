const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

const root = join(__dirname, "..");
const read = (file) => readFileSync(join(root, file), "utf8");
const workflow = JSON.parse(read("integrations/n8n/assign_report.json"));
const rules = JSON.parse(read("integrations/reglas.json"));
const routeCode = workflow.nodes.find((node) => node.type === "n8n-nodes-base.code").parameters.jsCode;

function route({ type = "phishing", severity = "media", review = false } = {}) {
  const input = { report_id: "sample", tipo: type, severidad: severity, revision: review, reglas: rules };
  const result = runInNewContext(`(() => { ${routeCode}\n })()`, { $input: { first: () => ({ json: input }) } });
  return JSON.parse(JSON.stringify(result))[0].json;
}

test("n8n aplica cada equipo y los cuatro plazos", () => {
  for (const [type, team] of Object.entries(rules.equipos)) {
    for (const [severity, deadlines] of Object.entries(rules.sla)) {
      assert.deepEqual(route({ type, severity }), { report_id: "sample", asignacion: { responsable: team, ...deadlines } });
    }
  }
});

test("n8n deriva a triaje y rechaza contextos sin regla", () => {
  assert.equal(route({ review: true }).asignacion.responsable, "Triaje SOC");
  assert.throws(() => route({ type: "inexistente" }), /No existe una regla/);
  assert.throws(() => route({ severity: "inexistente" }), /No existe una regla/);
});

