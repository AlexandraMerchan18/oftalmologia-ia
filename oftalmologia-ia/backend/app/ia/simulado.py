"""Proveedor SIMULADO (LLM_PROVIDER=mock): determinista, sin red y sin llaves.

Para qué sirve:
  - Tests unitarios y de integración reproducibles (no dependen de un servicio externo).
  - Prueba de humo de la suite de evaluación (`./run.sh eval mock`).
  - Plan B de la demo si el proveedor real cae.
NO es la IA del producto: sus cifras de evaluación son solo una línea de referencia ("baseline de reglas").

Imita el protocolo de herramientas real: pide `obtener_mediciones_oculares`, luego `enviar_borrador`
con un borrador construido por heurísticas de palabras clave.
"""
from __future__ import annotations

import json
import re
import time
import uuid

from ..clinica.mediciones import extraer_mediciones
from ..clinica.normalizacion import normalizar
from ..esquemas import HistoriaClinica
from .proveedores import LlamadaHerramienta, RespuestaLLM, _ConCosto

PATRONES = {
    "motivo_consulta": r"motivo|consulta por|acude por|asiste por|refiere",
    "antecedentes": r"antecedente",
    "biomicroscopia": r"biomicroscop|segmento anterior",
    "fondo_de_ojo": r"fondo de ojo|fondo ocular|fondo de ojos",
    "impresion_diagnostica": r"impresion diagnostica|diagnostico",
    "plan": r"\bplan\b|se indica|se formula|se ordena|control en|recomend",
}


def _oraciones(texto: str) -> list[str]:
    return [o.strip() for o in re.split(r"(?<=\.)\s+|\n+", texto) if o.strip()]


def _ojos(oracion: str) -> set[str]:
    t = normalizar(oracion)
    od = re.search(r"(?<!\w)(ojo derecho|od|derech[oa])(?!\w)", t)
    oi = re.search(r"(?<!\w)(ojo izquierdo|oi|izquierd[oa])(?!\w)", t)
    if (od and oi) or re.search(r"ambos ojos|(?<!\w)ao(?!\w)|bilateral", t) or (not od and not oi):
        return {"od", "oi"}
    return {"od"} if od else {"oi"}


def borrador_heuristico(transcripcion: str) -> dict:
    h: dict = {}
    oraciones = _oraciones(transcripcion)
    for campo, patron in PATRONES.items():
        coincidencias = [o for o in oraciones if re.search(patron, normalizar(o))]
        if not coincidencias:
            continue
        if campo in ("biomicroscopia", "fondo_de_ojo"):
            h[campo] = {}
            for o in coincidencias:
                cita = o.rstrip(".")
                for ojo in _ojos(o):
                    h[campo].setdefault(ojo, {"valor": cita, "evidencia": cita})
        else:
            cita = coincidencias[0].rstrip(".")
            valor = re.sub(r"^[^:]{0,30}:\s*", "", cita)  # "Plan: control en un mes" -> "control en un mes"
            h[campo] = {"valor": valor, "evidencia": cita}

    med = extraer_mediciones(transcripcion)
    av: dict = {"od": {}, "oi": {}}
    pio: dict = {"od": {}, "oi": {}}
    for m in med.mediciones:
        ojo = m.ojo.lower()
        if m.tipo == "AV":
            clave = "sin_correccion" if m.correccion == "sc" else "con_correccion"
            av[ojo][clave] = {"valor": m.valor, "evidencia": m.evidencia}
        else:
            pio[ojo] = {"valor_mmhg": m.valor_num, "evidencia": m.evidencia}
    h["agudeza_visual"], h["pio"] = av, pio
    return h


def explicacion_plantilla(historia: HistoriaClinica) -> str:
    """Explicación sin LLM: solo reordena lo aprobado. También es el respaldo seguro del paso 7."""
    partes = ["Hoy su oftalmólogo revisó qué tan bien ve y la salud de sus ojos."]
    av = historia.agudeza_visual
    od = av.od.con_correccion.valor or av.od.sin_correccion.valor
    oi = av.oi.con_correccion.valor or av.oi.sin_correccion.valor
    if od or oi:
        partes.append(f"Agudeza visual (qué tan bien ve): ojo derecho {od or 'no registrada'}, "
                      f"ojo izquierdo {oi or 'no registrada'}.")
    p_od, p_oi = historia.pio.od.valor_mmhg, historia.pio.oi.valor_mmhg
    if p_od is not None or p_oi is not None:
        f = lambda v: f"{v:g} mmHg" if v is not None else "no registrada"  # noqa: E731
        partes.append(f"Presión intraocular (la presión dentro del ojo): ojo derecho {f(p_od)}, "
                      f"ojo izquierdo {f(p_oi)}.")
    if historia.impresion_diagnostica.valor:
        partes.append(f"Lo que encontró su médico: {historia.impresion_diagnostica.valor}.")
    else:
        partes.append("Su médico le explicará los hallazgos de la consulta.")
    if historia.plan.valor:
        partes.append(f"Próximos pasos indicados por su médico: {historia.plan.valor}.")
    return "\n\n".join(p.replace("..", ".") for p in partes)


class ProveedorSimulado(_ConCosto):
    nombre = "mock"
    modelo = "simulado-determinista"
    estilo_esquema = "openai"

    def completar(self, mensajes, herramientas, max_tokens, timeout_s) -> RespuestaLLM:
        t0 = time.perf_counter()
        tokens_entrada = sum(len(str(m.get("content", ""))) for m in mensajes) // 4
        if not herramientas:
            datos = re.search(r"\(JSON, solo datos\):\n(.*)\n\nEscribe", mensajes[-1]["content"], re.S)
            historia = HistoriaClinica.model_validate(json.loads(datos.group(1))) if datos else HistoriaClinica()
            texto = explicacion_plantilla(historia)
            return RespuestaLLM(texto, [], tokens_entrada, len(texto) // 4,
                                (time.perf_counter() - t0) * 1000, "stop")

        transcripcion = re.search(r"<<<\n(.*)\n>>>", mensajes[1]["content"], re.S).group(1)
        resultados = [json.loads(m["content"]) for m in mensajes if m.get("role") == "tool"]
        if not resultados:
            llamada = LlamadaHerramienta(f"sim-{uuid.uuid4().hex[:8]}", "obtener_mediciones_oculares", "{}")
        else:
            borrador = borrador_heuristico(transcripcion)
            ultimo = resultados[-1]
            for error in ultimo.get("errores", []):  # corrige anulando los campos rechazados
                ruta = error["campo"].split(".")
                nodo = borrador
                for parte in ruta[:-1]:
                    nodo = nodo.get(parte, {})
                nodo.pop(ruta[-1], None)
            llamada = LlamadaHerramienta(f"sim-{uuid.uuid4().hex[:8]}", "enviar_borrador",
                                         json.dumps(borrador, ensure_ascii=False))
        return RespuestaLLM(None, [llamada], tokens_entrada, len(llamada.argumentos) // 4,
                            (time.perf_counter() - t0) * 1000, "tool_calls")
