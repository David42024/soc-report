"""Labeled synthetic symptoms for a technical test of the 5×3 protocol."""
from src.data.models import content_hash
from src.training.partition import Case, Partition, build_partition
from src.training.settings import TrainingSettings

SYMPTOMS = {
    "phishing": ("Correo de suplantación", "La persona recibió un mensaje falso con un enlace y una solicitud de credenciales."),
    "malware": ("Detección de software malicioso", "El sistema detectó archivos cifrados y actividad de software malicioso en un equipo."),
    "acceso_no_autorizado": ("Acceso fuera de política", "Una cuenta abrió una sesión desconocida y la revisión confirmó un acceso sin permiso."),
    "uso_indebido": ("Uso de un recurso fuera de horario", "Una cuenta autorizada usó recursos institucionales para un fin personal fuera de política."),
}


def technical_cases(groups_per_class: int) -> tuple[Case, ...]:
    """Create identifiable fixture reports with two related records per group."""
    return tuple(
        Case(key=content_hash(["fixture", label, group, member]), group=content_hash(["fixture", label, group]),
             title=title, description=f"{description} Referencia sintética campaña{group:03d} reporte{member}.", label=label)
        for label, (title, description) in SYMPTOMS.items() for group in range(groups_per_class) for member in range(2)
    )


def demo_partition(policy: TrainingSettings, seed: int) -> Partition:
    """Return the technical split, dropping its sealed rows at construction."""
    cases = technical_cases(policy.demo_groups_per_class)
    digest = content_hash([case.model_dump() for case in cases])
    return build_partition(cases, policy, seed, digest)
