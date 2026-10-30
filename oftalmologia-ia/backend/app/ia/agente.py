"""Agente de extracción (pasos 3 y 4): bucle de herramientas con CUATRO límites activos.

  1. Iteraciones máximas  -> AGENTE_MAX_ITERACIONES (cada llamada al LLM es una iteración)
  2. Timeout total        -> AGENTE_TIMEOUT_S (reloj de pared de todo el bucle; además, timeout por llamada)
  3. Presupuesto de tokens-> AGENTE_MAX_TOKENS_TOTALES (entrada + salida acumulados)
  4. Confirmación humana  -> herramientas con efectos no se ejecutan (ver herramientas.py) y el
                             resultado es SIEMPRE un borrador: guardar exige al médico (paso 5).

Si un límite se alcanza sin borrador aceptado, el agente NO falla en silencio: devuelve un borrador
parcial con lo que el extractor determinista sí encontró y una alerta bloqueante "extraccion_parcial".
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Literal

from ..clinica.mediciones import extraer_mediciones
from ..clinica.verificador import ResultadoVerificacion, verificar_borrador
from ..errores import ErrorAplicacion
from ..esquemas import Alerta, HistoriaClinica
from ..trazas import EventoTraza, RegistrarTraza, recortar, sin_trazas
from .herramientas import ContextoAgente, construir_herramientas, ejecutar_herramienta
from .prompts import (
    PROMPT_VERSION,
    RECORDATORIO_JSON_INVALIDO,
    RECORDATORIO_SIN_HERRAMIENTA,
    SISTEMA_EXTRACCION,
    USUARIO_EXTRACCION,
)
from .proveedores import ProveedorLLM, RespuestaInvalidaModelo

PASO_EXTRACCION = 3
MIN_TOKENS_PARA_LLAMAR = 600  # si quedan menos, no vale la pena otra llamada


@dataclass(frozen=True)
class LimitesAgente:
    max_iteraciones: int = 5
    timeout_s: float = 60.0
    max_tokens_totales: int = 20000
    max_tokens_respuesta: int = 4096
    timeout_llamada_s: float = 30.0


@dataclass
class ResultadoAgente:
    historia: HistoriaClinica
    alertas: list[Alerta]
    estado: Literal["completo", "parcial"]
    motivo_parada: str
    iteraciones: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    latencia_ms: float = 0.0
    herramientas_usadas: list[str] = field(default_factory=list)


def ejecutar_agente(transcripcion: str, proveedor: ProveedorLLM, limites: LimitesAgente,
                    registrar: RegistrarTraza = sin_trazas) -> ResultadoAgente:
    inicio = time.monotonic()
    mediciones = extraer_mediciones(transcripcion)
    registrar(EventoTraza(PASO_EXTRACCION, "herramienta", "extractor_determinista", detalle={
        "mediciones": len(mediciones.mediciones), "ambiguedades": len(mediciones.ambiguedades),
        "resultado": recortar(mediciones.como_dict())}))

    ctx = ContextoAgente(transcripcion=transcripcion, mediciones=mediciones)
    herramientas = construir_herramientas(proveedor.estilo_esquema)
    definiciones = [h.definicion() for h in herramientas.values()]
    mensajes: list[dict] = [
        {"role": "system", "content": SISTEMA_EXTRACCION},
        {"role": "user", "content": USUARIO_EXTRACCION.format(transcripcion=transcripcion)},
    ]
    r = ResultadoAgente(historia=HistoriaClinica(), alertas=[], estado="parcial", motivo_parada="")

    def parar(motivo: str, detalle: dict) -> None:
        r.motivo_parada = motivo
        registrar(EventoTraza(PASO_EXTRACCION, "limite", motivo, ok=False, detalle=detalle))

    while True:
        transcurrido = time.monotonic() - inicio
        restante = limites.timeout_s - transcurrido
        # ---- Límite 1: iteraciones ----
        if r.iteraciones >= limites.max_iteraciones:
            parar("max_iteraciones", {"limite": limites.max_iteraciones})
            break
        # ---- Límite 2: timeout total ----
        if restante <= 1.0:
            parar("timeout_agente", {"limite_s": limites.timeout_s, "transcurrido_s": round(transcurrido, 1)})
            break
        # ---- Límite 3: presupuesto de tokens ----
        usados = r.tokens_entrada + r.tokens_salida
        disponibles = limites.max_tokens_totales - usados
        if disponibles < MIN_TOKENS_PARA_LLAMAR:
            parar("presupuesto_tokens", {"limite": limites.max_tokens_totales, "usados": usados})
            break

        r.iteraciones += 1
        try:
            respuesta = proveedor.completar(
                mensajes, definiciones,
                max_tokens=min(limites.max_tokens_respuesta, disponibles),
                timeout_s=min(limites.timeout_llamada_s, restante),
            )
        except RespuestaInvalidaModelo as e:
            registrar(EventoTraza(PASO_EXTRACCION, "llm", f"llamada_{r.iteraciones}", ok=False,
                                  detalle={"error": e.codigo, **e.detalle}))
            mensajes.append({"role": "user", "content": RECORDATORIO_JSON_INVALIDO})
            continue
        except ErrorAplicacion as e:
            registrar(EventoTraza(PASO_EXTRACCION, "error", f"llamada_{r.iteraciones}", ok=False,
                                  detalle={"codigo": e.codigo, **e.detalle}))
            if ctx.verificacion is not None:   # ya hay un borrador válido: se entrega con sus alertas
                parar("error_proveedor_con_borrador", {"codigo": e.codigo})
                break
            raise

        r.tokens_entrada += respuesta.tokens_entrada
        r.tokens_salida += respuesta.tokens_salida
        costo = proveedor.costo_usd(respuesta.tokens_entrada, respuesta.tokens_salida)
        r.costo_usd += costo
        registrar(EventoTraza(
            PASO_EXTRACCION, "llm", f"llamada_{r.iteraciones}", latencia_ms=respuesta.latencia_ms,
            tokens_entrada=respuesta.tokens_entrada, tokens_salida=respuesta.tokens_salida, costo_usd=costo,
            detalle={"modelo": proveedor.modelo, "proveedor": proveedor.nombre, "prompt": PROMPT_VERSION,
                     "finalizacion": respuesta.finalizacion,
                     "herramientas_pedidas": [c.nombre for c in respuesta.llamadas],
                     "texto": recortar(respuesta.contenido or "", 300)}))

        mensajes.append(respuesta.como_mensaje())
        if not respuesta.llamadas:
            mensajes.append({"role": "user", "content": RECORDATORIO_SIN_HERRAMIENTA})
            continue

        for llamada in respuesta.llamadas:
            t0 = time.perf_counter()
            resultado = ejecutar_herramienta(herramientas, llamada.nombre, llamada.argumentos, ctx)
            r.herramientas_usadas.append(llamada.nombre)
            registrar(EventoTraza(
                PASO_EXTRACCION, "herramienta", llamada.nombre,
                ok="error" not in resultado and resultado.get("aceptado", True) is not False,
                latencia_ms=(time.perf_counter() - t0) * 1000,
                detalle={"argumentos": recortar(llamada.argumentos, 800), "resultado": recortar(resultado, 800)}))
            mensajes.append({"role": "tool", "tool_call_id": llamada.id,
                             "content": json.dumps(resultado, ensure_ascii=False)})
        if ctx.entregado:
            r.estado, r.motivo_parada = "completo", "borrador_entregado"
            break

    r.latencia_ms = (time.monotonic() - inicio) * 1000
    verificacion = ctx.verificacion or _borrador_determinista(transcripcion, mediciones)
    r.historia, r.alertas = verificacion.historia, list(verificacion.alertas)
    if r.estado != "completo":
        r.alertas.insert(0, Alerta(
            id="extraccion_parcial:general", campo="general", tipo="extraccion_parcial", bloqueante=True,
            mensaje=(f"La IA no completó la extracción ({r.motivo_parada}). Se precargó lo que el extractor "
                     "determinista encontró; complete y verifique los demás campos manualmente.")))
    return r


def _borrador_determinista(transcripcion, mediciones) -> ResultadoVerificacion:
    """Borrador vacío pasado por el verificador: queda con AV/PIO deterministas y sus alertas."""
    return verificar_borrador(HistoriaClinica(), transcripcion, mediciones)
