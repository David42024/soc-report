"""Reproducible synthetic data, kept separate from the real VCDB reserve."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from src.data.models import Annotation, DataInventory, DataRecord, DataSource, HoldoutState, SEVERITIES, TARGETS, TYPES, content_hash
from src.utils.config import AnalyticsSettings
from src.utils.errors import DatasetError
from src.utils.privacy import load_policy

SOURCE_ID = "soc_synthetic_demo"
VERSION = "soc-synthetic-v1"
SCENARIOS = {
    "phishing": ("Correo de suplantación", "Un mensaje falso solicitó credenciales mediante un enlace sospechoso.", "CORREO"),
    "malware": ("Software malicioso", "El equipo detectó software malicioso y archivos cifrados en un entorno de laboratorio.", "EQUIPO"),
    "acceso_no_autorizado": ("Acceso sin autorización", "Una cuenta abrió una sesión sin permiso en un servicio del laboratorio.", "CUENTA"),
    "ddos": ("Denegación de servicio", "Un aumento distribuido de tráfico impidió acceder al servicio simulado.", "SERVICIO"),
    "fuga_datos": ("Exposición de datos ficticios", "Un repositorio permitió descargar documentos ficticios fuera del grupo autorizado.", "REPOSITORIO"),
    "vulnerabilidad": ("Debilidad de configuración", "La revisión encontró una vulnerabilidad en la configuración del portal simulado.", "PORTAL"),
    "uso_indebido": ("Uso fuera de política", "Una cuenta autorizada utilizó recursos del laboratorio para una finalidad no permitida.", "RECURSO"),
    "incidente_fisico": ("Incidente físico", "Se simuló la pérdida de un dispositivo y la interrupción de su custodia física.", "DISPOSITIVO"),
    "fraude": ("Operación fraudulenta simulada", "Una solicitud alteró el destino de un pago ficticio en la cola del laboratorio.", "PAGOS"),
    "otro": ("Evento pendiente de categorización", "Se registró una anomalía simulada que no pertenece a las otras categorías del ejercicio.", "SISTEMA"),
}


def demo_path(settings: AnalyticsSettings) -> Path:
    return settings.path(Path(settings.runs_dir) / settings.data.directory / "demostracion" / f"{VERSION}-{settings.seed}.json")


def is_demo(inventory: DataInventory) -> bool:
    return len(inventory.sources) == 1 and inventory.sources[0].id == SOURCE_ID and all(
        record.nature == "sintetica" for record in inventory.records())


def generated_cases(seed: int) -> list[dict]:
    """Cover all ten types and four severities with 480 development and 160 test cases."""
    cases = []
    for kind in TYPES:
        title, description, asset = SCENARIOS[kind]
        for severity in SEVERITIES:
            for member in range(16):
                identifier = f"SYN-{kind}-{severity}-{member + 1:02d}"
                group = content_hash([VERSION, seed, identifier])
                cases.append({
                    "id": identifier, "grupo": group, "naturaleza": "sintetica",
                    "particion": "reservado" if member < 4 else "desarrollo",
                    "titulo": "[SINTÉTICO] " + title,
                    "descripcion": f"Escenario artificial {identifier}. {description} "
                        f"La severidad {severity} es un supuesto del ejercicio; no describe un incidente real.",
                    "tipo": kind, "severidad": severity, "activo_afectado": f"DEMO-{asset}-{member % 4 + 1:02d}",
                    "procedencia_etiquetas": "simulacion",
                })
    return cases


def demo_inventory(settings: AnalyticsSettings, *, create: bool = False) -> DataInventory:
    path = demo_path(settings)
    cases = generated_cases(settings.seed)
    document = {"version": VERSION, "seed": settings.seed, "synthetic": True,
                "human_reviewed": False, "cases": cases}
    payload = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    try:
        if not path.is_file() and create:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation preserves any previously published data.
            try:
                with path.open("xb") as handle:
                    handle.write(payload)
            except FileExistsError:
                pass
        if path.read_bytes() != payload:
            raise DatasetError("La demostración no coincide con su generador y semilla. Conserva el archivo para revisar los cambios.")
        info = path.stat()
    except OSError:
        raise DatasetError("No se pudo leer la demostración. Una cuenta Administrador o Analista puede crearla desde Datos del SOC.") from None
    records = tuple(DataRecord(
        key=content_hash([SOURCE_ID, row["id"]]), source_id=SOURCE_ID, incident_id=row["id"],
        base_sha256=content_hash(row), source_label="Demostración SOC sintética", nature="sintetica",
        partition=row["particion"], origin=VERSION, title=row["titulo"], description=row["descripcion"],
        text_sha256=sha256(row["descripcion"].encode()).hexdigest(), group=row["grupo"],
        links=("grupo:" + row["grupo"], "incidente:" + content_hash([SOURCE_ID, row["id"]])),
        labels={field: Annotation((row[field],), "simulacion") for field in TARGETS},
        categories={"preparación": "generada", "revisión humana": "no aplicable: dato sintético"},
        review_state="simulado", notes="Caso artificial con etiquetas generadas; no aporta una referencia humana.",
    ) for row in cases)
    digest = sha256(payload).hexdigest()
    source = DataSource(id=SOURCE_ID, name="Demostración SOC sintética", format="JSON sintético",
        location=path.relative_to(settings.root).as_posix(), provenance="Generador local reproducible; sin proveedores cloud.",
        limitation="Casos artificiales. Las etiquetas son supuestos y no acreditan desempeño real ni revisión humana.",
        revision=f"{VERSION} · semilla {settings.seed}", status="disponible", sha256=digest,
        columns=tuple(cases[0]), original_columns=tuple(cases[0]), records=records)
    return DataInventory(sources=(source,), holdout=HoldoutState(160, 0, "generado_sintetico", digest),
        privacy_sha256=load_policy().digest, input_fingerprint=(("__synthetic_demo__", info.st_mtime_ns, info.st_size),))


def demo_summary(inventory: DataInventory) -> dict:
    records = inventory.records()
    reserved = tuple(row for row in records if row.partition == "reservado")
    return {"synthetic": True, "version": VERSION, "human_reviewed": False,
        "total_cases": len(records), "development_cases": len(records) - len(reserved), "reserved_cases": len(reserved),
        "complete_by_target": {field: sum(bool(row.label(field).values) for row in records) for field in TARGETS},
        "reserved_counts_by_target": {field: dict(Counter(row.label(field).values[0] for row in reserved)) for field in TARGETS},
        "ready_by_target": {field: bool(reserved) and all(row.label(field).values for row in reserved) for field in TARGETS}}
