"""Fictional SOC exercises for the small local seed."""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DemoCase:
    number: int
    title: str
    asset: str
    description: str
    stage: Literal["por_atender", "en_atencion", "resuelto"]
    note: str
    evidence: tuple[str, str] | None = None

    def payload(self):
        return {
            "titulo": f"[DEMO] SOC-{self.number:02d} · {self.title}",
            "descripcion": f"{self.description}\n\nActivo: {self.asset}",
        }


CASES = (
    DemoCase(1, "Suplantación de soporte en el buzón de Finanzas", "buzón compartido FIN-CORREO",
        "Detección · Tres personas recibieron un correo falso de soporte con un enlace para renovar su clave antes del cierre de nómina.\n\n"
        "Alcance · El equipo de correo confirmó la entrega a tres buzones. Una persona abrió el mensaje y reportó que no ingresó credenciales.\n\n"
        "Evidencia · El remitente y el enlace apuntan al dominio de laboratorio soporte.example.test. Se conservó la cabecera del mensaje.\n\n"
        "Siguiente paso · Buscar el mismo remitente en el resto de los buzones y comprobar si hubo clics.",
        "por_atender", "Pendiente de primera atención. Priorizar la búsqueda de mensajes iguales y confirmar el alcance de la entrega."),
    DemoCase(2, "Troyano bloqueado en una estación de Contabilidad", "estación FIN-WS17",
        "Detección · El EDR puso en cuarentena un troyano al intentar ejecutarse desde la carpeta de descargas.\n\n"
        "Impacto · La alerta se limita a FIN-WS17. La persona puede continuar desde un equipo de reemplazo.\n\n"
        "Evidencia · La consola registró el archivo en cuarentena y su proceso padre. Se conserva el extracto del laboratorio.\n\n"
        "Contención · La estación permanece aislada mientras se revisa el origen de la descarga y si hay el mismo indicador en otros equipos.",
        "en_atencion", "Primera atención registrada. Estación aislada y análisis de alcance en curso.",
        ("SOC-02-alerta-edr.txt", "Evidencia de laboratorio\nEquipo: FIN-WS17\nDetección: troyano\nAcción EDR: cuarentena\nContención: aislamiento del equipo\n")),
    DemoCase(3, "Inicio de sesión no autorizado en una cuenta de compras", "cuenta de compras LAB-COMPRAS",
        "Detección · La persona titular informó un inicio de sesión desconocido. El equipo confirmó acceso no autorizado a la cuenta de compras.\n\n"
        "Impacto · Se revisaron los registros de la cuenta y las órdenes recientes. La revisión quedó acotada a esa cuenta.\n\n"
        "Respuesta · Se revocaron las sesiones activas, se restableció la contraseña y se verificó el segundo factor con la persona titular.\n\n"
        "Cierre · Se confirmó el acceso legítimo y se revisó el registro posterior a la revocación.",
        "resuelto", "Cierre validado con la persona titular. Sesiones revocadas y segundo factor verificado."),
    DemoCase(4, "Panel administrativo expuesto en el portal de inventario", "portal INV-STAGE",
        "Detección · El escáner interno encontró una vulnerabilidad de configuración en el entorno de pruebas de inventario. El panel administrativo responde desde un segmento que debería estar excluido.\n\n"
        "Impacto · La exposición está confirmada. El alcance de las funciones accesibles sigue pendiente de revisión.\n\n"
        "Evidencia · Se guardó la matriz de accesos esperados y el resultado de una comprobación desde el segmento invitado.\n\n"
        "Siguiente paso · Validar la restricción con el equipo del portal y aplicar el control de red acordado.",
        "por_atender", "Pendiente de primera atención. El hallazgo incluye los segmentos esperado y observado para reproducirlo."),
    DemoCase(5, "Alerta de posible fuga de datos en almacenamiento de RR. HH.", "repositorio HR-DOCS-LAB",
        "Detección · El control de datos alertó por una exportación fuera del horario habitual desde un repositorio de RR. HH.\n\n"
        "Impacto · La exportación podría incluir documentos restringidos. El contenido y los destinatarios están por confirmar.\n\n"
        "Evidencia · El registro de acceso identifica el recurso, la cuenta de servicio y la hora de la transferencia. El extracto contiene identificadores ficticios.\n\n"
        "Contención · Se suspendió el vínculo de descarga y se está verificando si existía un cambio autorizado.",
        "en_atencion", "Se comunicó la alerta al responsable del repositorio. Queda validar el alcance de la posible fuga.",
        ("SOC-05-extracto-control-datos.txt", "Evidencia de laboratorio\nRecurso: HR-DOCS-LAB\nEvento: exportación fuera de horario\nAcción: vínculo de descarga suspendido\nAlcance: pendiente de validación\n")),
    DemoCase(6, "Fraude por cambio de cuenta bancaria de un proveedor", "cola de pagos PAGOS-LAB",
        "Detección · Compras recibió una solicitud de cambio de cuenta bancaria justo antes de un pago. El canal habitual del proveedor confirmó que la solicitud era un intento de fraude.\n\n"
        "Impacto · Se retuvo el pago antes de ejecutarlo y se verificó que el dato de destino registrado no hubiera cambiado.\n\n"
        "Evidencia · Se conservó la solicitud de cambio y el registro de la confirmación por el canal habitual del proveedor.\n\n"
        "Cierre · Se anuló la solicitud y se documentó la verificación de doble control con Tesorería.",
        "resuelto", "Tesorería confirmó el cierre. Pago retenido y solicitud de cambio rechazada."),
)
