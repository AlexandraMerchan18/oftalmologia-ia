"""Máquina de estados de la consulta: hace cumplir el orden de los 8 pasos en el servidor.

    CREADA --(2 transcribir)--> TRANSCRITA --(3-4 extraer)--> BORRADOR
      --(5-6 revisar y guardar)--> GUARDADA --(7 explicar)--> EXPLICACION_GENERADA --(8 aprobar)--> APROBADA

La historia GUARDADA es inmutable: después del paso 6 solo cambia la explicación.
"""
from __future__ import annotations

from .errores import TransicionInvalida

CREADA, TRANSCRITA, BORRADOR = "CREADA", "TRANSCRITA", "BORRADOR"
GUARDADA, EXPLICACION_GENERADA, APROBADA = "GUARDADA", "EXPLICACION_GENERADA", "APROBADA"

TRANSICIONES: dict[str, tuple[set[str], str]] = {
    # acción: (estados desde los que se permite, estado resultante)
    "transcribir": ({CREADA, TRANSCRITA, BORRADOR}, TRANSCRITA),
    "extraer": ({TRANSCRITA, BORRADOR}, BORRADOR),
    "guardar": ({BORRADOR}, GUARDADA),
    "explicar": ({GUARDADA, EXPLICACION_GENERADA}, EXPLICACION_GENERADA),
    "aprobar": ({EXPLICACION_GENERADA}, APROBADA),
}

PASO_DE_ESTADO = {CREADA: 1, TRANSCRITA: 2, BORRADOR: 5, GUARDADA: 7, EXPLICACION_GENERADA: 8, APROBADA: 8}


def siguiente_estado(estado_actual: str, accion: str) -> str:
    permitidos, destino = TRANSICIONES[accion]
    if estado_actual not in permitidos:
        raise TransicionInvalida(
            f"No se puede '{accion}' una consulta en estado {estado_actual}. "
            f"Estados válidos: {', '.join(sorted(permitidos))}.",
            detalle={"estado_actual": estado_actual, "accion": accion},
        )
    return destino
