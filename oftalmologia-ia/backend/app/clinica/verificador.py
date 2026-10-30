"""Verificador del borrador del LLM: la capa determinista que decide qué se le advierte al médico.

Reglas (todas en código, ninguna depende del LLM):
  R1. Cita literal: todo valor debe traer `evidencia` presente en la transcripción.
  R2. Números: ningún número del valor puede faltar en la transcripción (anti-alucinación).
  R3. AV/PIO: se contrastan con el extractor determinista (mediciones.py):
        - coinciden            -> OK
        - el LLM omitió        -> se completa con el determinista + advertencia
        - discrepan            -> CONFLICTO bloqueante, se propone el valor determinista
        - solo el LLM lo halló -> la cita debe nombrar ese ojo; si no, LATERALIDAD bloqueante
  R4. Impresión diagnóstica: no puede contener términos diagnósticos ausentes del dictado.
  R5. Inyección: si el dictado contiene órdenes para la IA ("ignora las instrucciones..."), se alerta.
Una alerta "bloqueante" impide guardar hasta que el médico la marque como revisada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, Optional

from ..esquemas import Alerta, Campo, HistoriaClinica
from .guardas import terminos_diagnosticos_en
from .mediciones import RE_LATERALIDAD, ResultadoMediciones
from .normalizacion import cita_presente, normalizar, numeros_en_texto

NOMBRE_OJO = {"od": "ojo derecho (OD)", "oi": "ojo izquierdo (OI)"}

# R5. Texto dictado (o colado en la transcripción) que intenta dar órdenes a la IA.
RE_INYECCION = re.compile(
    r"ignor(?:a|e|ar)\s+(?:las\s+|todas\s+las\s+|tus\s+)?instrucciones|olvid(?:a|e)\s+(?:las|tus)\s+instrucciones"
    r"|instrucciones\s+anteriores|system\s+prompt|eres\s+un\s+(?:modelo|asistente)|actua\s+como"
)


@dataclass
class ResultadoVerificacion:
    historia: HistoriaClinica
    alertas: list[Alerta] = field(default_factory=list)

    @property
    def errores_corregibles_por_llm(self) -> list[Alerta]:
        """Errores que el agente puede y debe corregir antes de entregar (citas y números inventados)."""
        return [a for a in self.alertas if a.tipo in ("sin_evidencia", "posible_alucinacion")]

    @property
    def bloqueantes(self) -> list[Alerta]:
        return [a for a in self.alertas if a.bloqueante]


def _campos_texto(h: HistoriaClinica) -> Iterator[tuple[str, Campo]]:
    yield "motivo_consulta", h.motivo_consulta
    yield "antecedentes", h.antecedentes
    for ojo in ("od", "oi"):
        yield f"biomicroscopia.{ojo}", getattr(h.biomicroscopia, ojo)
        yield f"fondo_de_ojo.{ojo}", getattr(h.fondo_de_ojo, ojo)
    yield "impresion_diagnostica", h.impresion_diagnostica
    yield "plan", h.plan


def _ojos_en(cita: str) -> set[str]:
    ojos = set()
    for m in RE_LATERALIDAD.finditer(normalizar(cita)):
        if m.group("OD"):
            ojos.add("od")
        elif m.group("OI"):
            ojos.add("oi")
        else:
            ojos.update({"od", "oi"})
    return ojos


def _es_bilateral(cita: str) -> bool:
    return bool(re.search(r"(?<!\w)(?:ambos\s+ojos|ao|ou|bilateral(?:mente)?)(?!\w)", normalizar(cita)))


def _fmt(v: Optional[float | str]) -> Optional[str]:
    if v is None:
        return None
    return f"{v:g}" if isinstance(v, float) else str(v)


def verificar_borrador(
    historia: HistoriaClinica, transcripcion: str, mediciones: ResultadoMediciones
) -> ResultadoVerificacion:
    h = historia.model_copy(deep=True)
    alertas: list[Alerta] = []
    numeros_dictados = numeros_en_texto(transcripcion)

    def alerta(campo: str, tipo: str, bloqueante: bool, mensaje: str, **extra) -> None:
        # id estable (el frontend lo usa para marcar la alerta como revisada) y único
        base = ident = f"{tipo}:{campo}"
        n = 2
        while any(a.id == ident for a in alertas):
            ident, n = f"{base}#{n}", n + 1
        alertas.append(Alerta(id=ident, campo=campo, tipo=tipo, bloqueante=bloqueante, mensaje=mensaje, **extra))

    # ---- R1 + R2 + R4: campos de texto libre -------------------------------
    for ruta, campo in _campos_texto(h):
        if not campo.valor:
            continue
        if not campo.evidencia or not cita_presente(campo.evidencia, transcripcion):
            alerta(ruta, "sin_evidencia", True,
                   "El valor no tiene una cita literal que aparezca en el dictado.",
                   valor_llm=campo.valor, evidencia=campo.evidencia)
        inventados = numeros_en_texto(campo.valor) - numeros_dictados
        if inventados:
            alerta(ruta, "posible_alucinacion", True,
                   f"Contiene números que no aparecen en el dictado: {sorted(_fmt(n) for n in inventados)}",
                   valor_llm=campo.valor)
        if ruta == "impresion_diagnostica":
            nuevos = terminos_diagnosticos_en(campo.valor) - terminos_diagnosticos_en(transcripcion)
            if nuevos:
                alerta(ruta, "posible_alucinacion", True,
                       f"Menciona diagnósticos que el médico no dictó: {sorted(nuevos)}. La IA no diagnostica.",
                       valor_llm=campo.valor)

    # ---- R5: posible inyección de instrucciones en el dictado ---------------
    inyeccion = RE_INYECCION.search(normalizar(transcripcion))
    if inyeccion:
        alerta("general", "posible_alucinacion", True,
               "El dictado contiene una frase que parece una instrucción dirigida a la IA "
               f"(«{transcripcion[inyeccion.start():inyeccion.end()]}»). Verifique que ningún campo la haya obedecido.",
               evidencia=transcripcion[inyeccion.start():inyeccion.end()])
        for ruta, campo in _campos_texto(h):
            texto_campo = normalizar(f"{campo.valor or ''} {campo.evidencia or ''}")
            if campo.valor and RE_INYECCION.search(texto_campo):
                alerta(ruta, "posible_alucinacion", True,
                       "Este campo proviene de la frase con instrucciones para la IA, no de un hallazgo clínico.",
                       valor_llm=campo.valor)

    # ---- R3: agudeza visual ------------------------------------------------
    for ojo in ("od", "oi"):
        for corr, nombre_corr in (("sc", "sin_correccion"), ("cc", "con_correccion")):
            ruta = f"agudeza_visual.{ojo}.{nombre_corr}"
            campo = getattr(getattr(h.agudeza_visual, ojo), nombre_corr)
            det = mediciones.buscar("AV", ojo.upper(), corr)
            _contrastar(alerta, ruta, ojo, campo, "valor", campo.valor, det,
                        mediciones.ambiguedades_de("AV", corr), transcripcion)

    # ---- R3: presión intraocular -------------------------------------------
    for ojo in ("od", "oi"):
        ruta = f"pio.{ojo}"
        campo = getattr(h.pio, ojo)
        det = mediciones.buscar("PIO", ojo.upper())
        _contrastar(alerta, ruta, ojo, campo, "valor_mmhg", campo.valor_mmhg, det,
                    mediciones.ambiguedades_de("PIO"), transcripcion)

    return ResultadoVerificacion(historia=h, alertas=alertas)


def _iguales(a, b) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def _contrastar(alerta, ruta, ojo, campo, atributo, valor_llm, det, ambiguedades, transcripcion) -> None:
    valor_det = None
    if det is not None:
        valor_det = det.valor_num if atributo == "valor_mmhg" else det.valor

    if det is not None and valor_llm is None:
        setattr(campo, atributo, valor_det)
        campo.evidencia = det.evidencia
        alerta(ruta, "completado_determinista", False,
               f"El LLM omitió este dato; se completó con el extractor determinista ({_fmt(valor_det)}).",
               valor_determinista=_fmt(valor_det), evidencia=det.evidencia)
    elif det is not None and not _iguales(valor_llm, valor_det):
        alerta(ruta, "conflicto", True,
               f"La IA propuso {_fmt(valor_llm)} y el extractor determinista {_fmt(valor_det)} "
               f"para {NOMBRE_OJO[ojo]}. Se precargó el valor determinista: confirme cuál es correcto.",
               valor_llm=_fmt(valor_llm), valor_determinista=_fmt(valor_det), evidencia=det.evidencia)
        setattr(campo, atributo, valor_det)
        campo.evidencia = det.evidencia
    elif det is None and valor_llm is not None:
        cita = campo.evidencia or ""
        if not cita or not cita_presente(cita, transcripcion):
            alerta(ruta, "sin_evidencia", True, "Dato crítico sin cita literal verificable.",
                   valor_llm=_fmt(valor_llm), evidencia=cita)
        elif ojo not in _ojos_en(cita) or (len(_ojos_en(cita)) > 1 and not _es_bilateral(cita)):
            alerta(ruta, "lateralidad", True,
                   f"La cita no permite confirmar que el valor corresponde al {NOMBRE_OJO[ojo]}.",
                   valor_llm=_fmt(valor_llm), evidencia=cita)
        else:
            alerta(ruta, "solo_llm", True,
                   "Solo la IA encontró este dato crítico (el extractor determinista no). Verifíquelo.",
                   valor_llm=_fmt(valor_llm), evidencia=cita)
        if ambiguedades:
            alerta(ruta + ".ambigua", "ambigua", True,
                   "El dictado de esta medición es ambiguo: " + "; ".join(a.motivo for a in ambiguedades),
                   valor_llm=_fmt(valor_llm), evidencia=ambiguedades[0].evidencia)
    elif det is None and valor_llm is None and ambiguedades:
        alerta(ruta, "ambigua", True,
               "Se dictó una medición pero no se pudo asignar el ojo con certeza: "
               + "; ".join(a.motivo for a in ambiguedades) + ". Diligéncielo manualmente.",
               evidencia=ambiguedades[0].evidencia)

    if atributo == "valor_mmhg":
        v = getattr(campo, atributo)
        if v is not None and not (5 <= v <= 60):
            alerta(ruta, "fuera_de_rango", True, f"PIO de {v:g} mmHg fuera del rango esperado (5–60).",
                   valor_llm=_fmt(valor_llm))
