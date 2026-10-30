"""Paso 7: explicación para el paciente, generada SOLO a partir de la historia aprobada.

Flujo con red de seguridad:
  LLM -> guarda determinista -> (si viola) 1 reintento con la violación explicada -> (si vuelve a violar
  o el proveedor falla) plantilla determinista. El médico siempre edita y aprueba al final (paso 8).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from ..clinica.guardas import AVISO_PACIENTE, violaciones_explicacion
from ..errores import ErrorAplicacion
from ..esquemas import HistoriaClinica
from ..trazas import EventoTraza, RegistrarTraza, sin_trazas
from .prompts import CORRECCION_EXPLICACION, SISTEMA_EXPLICACION, USUARIO_EXPLICACION
from .proveedores import ProveedorLLM
from .simulado import explicacion_plantilla

PASO_EXPLICACION = 7


@dataclass
class ResultadoExplicacion:
    texto: str
    metodo: Literal["llm", "llm_corregida", "plantilla"]
    violaciones_detectadas: list[str] = field(default_factory=list)
    aviso: str = ""


def texto_de_historia(historia: HistoriaClinica) -> str:
    """Todo el contenido aprobado como texto plano (base de la guarda: qué se puede mencionar)."""
    return json.dumps(historia.model_dump(exclude_none=True), ensure_ascii=False)


def _datos_para_llm(historia: HistoriaClinica) -> str:
    """Solo valores (sin evidencias) para no inflar el prompt."""
    def limpiar(nodo):
        if isinstance(nodo, dict):
            return {k: limpiar(v) for k, v in nodo.items() if k != "evidencia" and v not in (None, {}, "")}
        return nodo
    return json.dumps(limpiar(historia.model_dump()), ensure_ascii=False, indent=1)


def generar_explicacion(historia: HistoriaClinica, proveedor: ProveedorLLM, timeout_s: float = 30.0,
                        registrar: RegistrarTraza = sin_trazas) -> ResultadoExplicacion:
    base = texto_de_historia(historia)
    mensajes = [{"role": "system", "content": SISTEMA_EXPLICACION},
                {"role": "user", "content": USUARIO_EXPLICACION.format(historia_json=_datos_para_llm(historia))}]
    todas_violaciones: list[str] = []

    for intento in (1, 2):
        try:
            r = proveedor.completar(mensajes, None, max_tokens=900, timeout_s=timeout_s)
        except ErrorAplicacion as e:
            registrar(EventoTraza(PASO_EXPLICACION, "error", f"explicacion_llm_{intento}", ok=False,
                                  detalle={"codigo": e.codigo, "accion": "se usa plantilla determinista"}))
            break
        texto = (r.contenido or "").strip()
        violaciones = violaciones_explicacion(texto, base) if texto else ["respuesta vacía"]
        registrar(EventoTraza(
            PASO_EXPLICACION, "llm", f"explicacion_llm_{intento}", latencia_ms=r.latencia_ms,
            tokens_entrada=r.tokens_entrada, tokens_salida=r.tokens_salida,
            costo_usd=proveedor.costo_usd(r.tokens_entrada, r.tokens_salida),
            detalle={"modelo": proveedor.modelo, "palabras": len(texto.split())}))
        registrar(EventoTraza(PASO_EXPLICACION, "seguridad", f"guarda_no_diagnostico_{intento}",
                              ok=not violaciones, detalle={"violaciones": violaciones}))
        if not violaciones:
            return ResultadoExplicacion(texto, "llm" if intento == 1 else "llm_corregida",
                                        todas_violaciones, AVISO_PACIENTE)
        todas_violaciones += violaciones
        mensajes += [{"role": "assistant", "content": texto},
                     {"role": "user", "content": CORRECCION_EXPLICACION.format(violaciones="; ".join(violaciones))}]

    texto = explicacion_plantilla(historia)
    registrar(EventoTraza(PASO_EXPLICACION, "seguridad", "plantilla_determinista",
                          detalle={"motivo": "violaciones o fallo del proveedor", "violaciones": todas_violaciones}))
    return ResultadoExplicacion(texto, "plantilla", todas_violaciones, AVISO_PACIENTE)
