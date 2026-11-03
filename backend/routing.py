"""Versioned routing configuration. Existing reports retain their assigned version."""
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .classifier import Tipo, Severidad
from .config import ROOT

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
DEFAULT_RULES = json.loads((ROOT / "integrations" / "reglas.json").read_text(encoding="utf-8"))


class SlaRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    respuesta_min: int = Field(gt=0, le=525600, strict=True)
    resolucion_min: int = Field(gt=0, le=525600, strict=True)

    @model_validator(mode="after")
    def order(self):
        if self.respuesta_min > self.resolucion_min:
            raise ValueError("El plazo de respuesta debe preceder al de resolución.")
        return self


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equipos: dict[Tipo, Name]
    equipo_revision: Name
    sla: dict[Severidad, SlaRule]
    umbral: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def coverage(self):
        if self.equipos.keys() != DEFAULT_RULES["equipos"].keys() or self.sla.keys() != DEFAULT_RULES["sla"].keys():
            raise ValueError("Configura todas las categorías y severidades.")
        return self


class PolicyUpdate(Policy):
    version_anterior: str | None


def policy_record(execute, report_id=None):
    if report_id is None:
        row = execute("SELECT * FROM routing_versions ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
    else:
        row = execute("""SELECT v.* FROM routing_versions v JOIN report_routing_versions p ON p.version_id=v.id
                         WHERE p.report_id=%s""", (report_id,)).fetchone()
    if not row:
        return {"id": None, "configuration": {**DEFAULT_RULES, "umbral": 0.75}}
    return {**row, "configuration": json.loads(row["configuration"])}


def routing_policy(db, report_id=None):
    with db.session() as execute:
        return policy_record(execute, report_id)
