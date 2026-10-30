"""Extractor DETERMINISTA de Agudeza Visual (AV) y Presión Intraocular (PIO).

Por qué existe: los datos numéricos críticos y su lateralidad (OD/OI) no deben depender
solo de un LLM. Este módulo los extrae con reglas auditables y sirve como:
  1. herramienta del agente (`obtener_mediciones_oculares`), y
  2. verificador independiente del borrador del LLM (ver verificador.py).

Principio de diseño: ante la duda, NO asignar. Si la lateralidad no se puede
determinar con certeza, se reporta una ambigüedad y el médico decide.

Estrategia de lateralidad ("consenso de dos lecturas"):
  - Lectura A, "valor-luego-ojo":   "PIO de 15 en ojo derecho y 17 en ojo izquierdo"
  - Lectura B, "ojo-luego-valor":   "PIO ojo derecho 15, ojo izquierdo 17"
  Se calcula cada lectura sobre el mismo segmento. Si solo una es coherente, se usa.
  Si ambas son coherentes pero discrepan, el segmento se marca AMBIGUO.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

from .normalizacion import NUM, NUM_PALABRAS, a_numero, normalizar

Ojo = Literal["OD", "OI"]
Correccion = Literal["sc", "cc"]

_L, _R = r"(?<!\w)", r"(?!\w)"

RE_LATERALIDAD = re.compile(
    rf"(?P<OD>{_L}(?:ojo\s+derecho|o\.d\.?|od|derech[oa]){_R})"
    rf"|(?P<OI>{_L}(?:ojo\s+izquierdo|o\.i\.?|oi|os|izquierd[oa]){_R})"
    rf"|(?P<AO>{_L}(?:ambos\s+ojos|a\.o\.?|ao|ou|bilateral(?:mente)?){_R})"
)
RE_CLAVE_AV = re.compile(rf"{_L}(?:agudezas?\s+visual(?:es)?|agudeza|avsc|avcc|av){_R}")
RE_CLAVE_PIO = re.compile(
    rf"{_L}(?:presion(?:es)?\s+intraocular(?:es)?|pio|tonometria|presion\s+ocular|tension\s+ocular"
    rf"|presiones|presion(?!\s+arterial)){_R}"
)
RE_TERMINADOR = re.compile(
    rf"{_L}(?:biomicroscopia|segmento\s+anterior|fondo\s+de\s+ojo|fondo\s+ocular|excavacion|papila|retina"
    rf"|macula|cornea|cristalino|diagnostico|impresion|plan|refraccion|queratometria|paquimetria|motivo"
    rf"|antecedentes?|formula|se\s+indica|control){_R}"
    r"|\.(?=\s|$)|\n"
)
RE_CORRECCION = re.compile(
    rf"(?P<sc>{_L}(?:sin\s+correccion|sin\s+(?:sus\s+)?(?:lentes|gafas|anteojos)|s\.c\.?|sc){_R})"
    rf"|(?P<cc>{_L}(?:con\s+(?:su\s+)?correccion|con\s+(?:sus\s+)?(?:lentes|gafas|anteojos)|c\.c\.?|cc){_R})"
    rf"|(?P<ae>{_L}(?:con\s+)?(?:agujero\s+)?estenopeico{_R})"
)

DENOMINADORES_SNELLEN = {10, 12, 13, 15, 16, 20, 25, 30, 32, 40, 50, 60, 63, 70, 80, 100, 125, 150, 160,
                         200, 250, 300, 400, 500, 600, 800}

_AV_VALORES = [
    # (regex, tipo)
    (re.compile(r"(?<![\d/])(\d{1,2})\s*(?:/|sobre)\s*(\d{2,3})(?![\d/])"), "snellen"),
    (re.compile(r"(?<![\d/])(20)\s+(\d{2,3})(?![\d/])"), "snellen_espacio"),
    (re.compile(r"(?<![\d/])20(\d{2,3})(?![\d/])"), "snellen_pegado"),
    (re.compile(rf"\bveinte\s+(?:sobre\s+)?({NUM_PALABRAS})\b"), "snellen_palabras"),
    (re.compile(r"\bno\s+percibe\s+luz\b|\bnpl\b"), "no percibe luz"),
    (re.compile(r"\bpercepcion\s+de\s+luz\b|\bpercibe\s+luz\b"), "percepcion de luz"),
    (re.compile(r"\bmovimiento\s+de\s+manos\b"), "movimiento de manos"),
    (re.compile(rf"\bcuenta\s+dedos(?:\s+a\s+(?:\d+|una?|{NUM_PALABRAS})\s+(?:metros?|centimetros?|cm|m)\b)?"),
     "cuenta dedos"),
]
RE_PIO_VALOR = re.compile(NUM)
RE_UNIDAD_NO_PIO = re.compile(r"^\s*(?:anos|meses|dias|semanas|horas|minutos|%|am|pm|de\s+la\s+manana)")


@dataclass
class Medicion:
    tipo: Literal["AV", "PIO"]
    ojo: Ojo
    correccion: Optional[Correccion]
    valor: str
    evidencia: str
    notas: list[str] = field(default_factory=list)

    @property
    def valor_num(self) -> Optional[float]:
        return float(self.valor) if self.tipo == "PIO" else None


@dataclass
class Ambiguedad:
    tipo: Literal["AV", "PIO"]
    correccion: Optional[Correccion]
    evidencia: str
    motivo: str


@dataclass
class ResultadoMediciones:
    mediciones: list[Medicion] = field(default_factory=list)
    ambiguedades: list[Ambiguedad] = field(default_factory=list)

    def buscar(self, tipo: str, ojo: str, correccion: Optional[str] = None) -> Optional[Medicion]:
        for m in self.mediciones:
            if m.tipo == tipo and m.ojo == ojo and (tipo == "PIO" or m.correccion == correccion):
                return m
        return None

    def ambiguedades_de(self, tipo: str, correccion: Optional[str] = None) -> list[Ambiguedad]:
        return [a for a in self.ambiguedades
                if a.tipo == tipo and (tipo == "PIO" or a.correccion in (correccion, None))]

    def como_dict(self) -> dict:
        return {
            "mediciones": [asdict(m) for m in self.mediciones],
            "ambiguedades": [asdict(a) for a in self.ambiguedades],
        }


# --- Elementos ordenados dentro de un segmento ------------------------------
@dataclass
class _Item:
    inicio: int
    fin: int
    clase: Literal["lat", "val"]
    ojo: Optional[str] = None      # OD | OI | AO (si clase == lat)
    valor: Optional[str] = None    # (si clase == val)
    nota: Optional[str] = None


def _lateralidades(norm: str, ini: int, fin: int) -> list[_Item]:
    items = []
    for m in RE_LATERALIDAD.finditer(norm, ini, fin):
        ojo = next(k for k in ("OD", "OI", "AO") if m.group(k))
        items.append(_Item(m.start(), m.end(), "lat", ojo=ojo))
    return items


def _valores_av(norm: str, ini: int, fin: int) -> list[_Item]:
    encontrados: list[_Item] = []
    for regex, tipo in _AV_VALORES:
        for m in regex.finditer(norm, ini, fin):
            if any(not (m.end() <= e.inicio or m.start() >= e.fin) for e in encontrados):
                continue  # se solapa con un valor ya reconocido
            nota = None
            if tipo.startswith("snellen"):
                if tipo == "snellen_pegado":
                    num, den = 20, int(m.group(1))
                    nota = f"normalizado desde '{m.group(0)}'"
                elif tipo == "snellen_palabras":
                    num, den = 20, int(a_numero(m.group(1)) or 0)
                else:
                    num, den = int(m.group(1)), int(m.group(2))
                if num not in (20, 6) and tipo != "snellen":
                    continue
                if den not in DENOMINADORES_SNELLEN:
                    nota = (nota + "; " if nota else "") + f"denominador {den} no estándar"
                valor = f"{num}/{den}"
            else:
                valor = m.group(0) if tipo == "cuenta dedos" else tipo
            encontrados.append(_Item(m.start(), m.end(), "val", valor=valor, nota=nota))
    return encontrados


def _valores_pio(norm: str, ini: int, fin: int) -> list[_Item]:
    items = []
    for m in RE_PIO_VALOR.finditer(norm, ini, fin):
        if RE_UNIDAD_NO_PIO.match(norm[m.end():m.end() + 20]) or norm[:m.start()].endswith("a las "):
            continue  # "3 meses", "a las 10": no son presiones
        n = a_numero(m.group(0))
        if n is None:
            continue
        nota = None if 5 <= n <= 60 else f"valor {n:g} mmHg fuera del rango esperado"
        items.append(_Item(m.start(), m.end(), "val", valor=f"{n:g}", nota=nota))
    return items


def _asignar(items: list[_Item]) -> tuple[Optional[dict[int, str]], str]:
    """Devuelve {indice_valor: ojo} o None si es ambiguo, junto con el motivo."""
    items = sorted(items, key=lambda i: i.inicio)
    valores = [k for k, it in enumerate(items) if it.clase == "val"]
    if not valores:
        return {}, ""
    if not any(it.clase == "lat" for it in items):
        return None, "no se dictó el ojo (OD/OI) para este valor"

    # Lectura A: valor -> ojo siguiente (antes del próximo valor)
    lectura_a: Optional[dict[int, str]] = {}
    for k in valores:
        siguiente = items[k + 1] if k + 1 < len(items) else None
        if siguiente is None or siguiente.clase != "lat":
            lectura_a = None
            break
        lectura_a[k] = siguiente.ojo

    # Lectura B: ojo -> valores siguientes
    lectura_b: Optional[dict[int, str]] = {}
    ultimo = None
    for k, it in enumerate(items):
        if it.clase == "lat":
            ultimo = it.ojo
        elif ultimo is None:
            lectura_b = None
            break
        else:
            lectura_b[k] = ultimo

    def coherente(lectura):
        if lectura is None:
            return False
        por_ojo: dict[str, set] = {}
        for k, ojo in lectura.items():
            for o in (("OD", "OI") if ojo == "AO" else (ojo,)):
                por_ojo.setdefault(o, set()).add(items[k].valor)
        return all(len(v) == 1 for v in por_ojo.values())

    a_ok, b_ok = coherente(lectura_a), coherente(lectura_b)
    if a_ok and b_ok:
        if lectura_a == lectura_b:
            return lectura_a, ""
        return None, "el orden de ojos y valores admite dos lecturas distintas"
    if a_ok:
        return lectura_a, ""
    if b_ok:
        return lectura_b, ""
    return None, "no fue posible emparejar cada valor con un único ojo"


def _inicio_oracion(norm: str, pos: int) -> int:
    candidatos = [norm.rfind(". ", 0, pos), norm.rfind("\n", 0, pos)]
    inicio = max(candidatos)
    return 0 if inicio < 0 else inicio + 1


def _lateralidad_previa(norm: str, pos: int) -> Optional[_Item]:
    """Último ojo mencionado en la misma oración antes de `pos` (máx. 80 caracteres)."""
    ini = max(_inicio_oracion(norm, pos), pos - 80)
    previas = _lateralidades(norm, ini, pos)
    return previas[-1] if previas else None


def _fin_segmento(norm: str, desde: int) -> int:
    candidatos = [len(norm)]
    for regex in (RE_TERMINADOR, RE_CLAVE_AV, RE_CLAVE_PIO):
        m = regex.search(norm, desde)
        if m:
            candidatos.append(m.start())
    return min(candidatos)


class _Acumulador:
    def __init__(self, original: str):
        self.original = original
        self.res = ResultadoMediciones()
        self._indice: dict[tuple, Medicion] = {}
        self._conflictivas: set[tuple] = set()

    def cita(self, ini: int, fin: int) -> str:
        return self.original[ini:fin].strip(" ,;:")

    def agregar(self, tipo, ojo, correccion, item: _Item, marcador: _Item, notas: list[str]):
        clave = (tipo, ojo, correccion)
        ini, fin = min(item.inicio, marcador.inicio), max(item.fin, marcador.fin)
        notas = notas + ([item.nota] if item.nota else [])
        if clave in self._conflictivas:
            return
        previa = self._indice.get(clave)
        if previa is None:
            med = Medicion(tipo, ojo, correccion, item.valor, self.cita(ini, fin), notas)
            self._indice[clave] = med
            self.res.mediciones.append(med)
        elif previa.valor != item.valor:
            self.res.mediciones.remove(previa)
            self._conflictivas.add(clave)
            self.res.ambiguedades.append(Ambiguedad(
                tipo, correccion, f"{previa.evidencia} … {self.cita(ini, fin)}",
                f"se dictaron dos valores distintos para {ojo}: {previa.valor} y {item.valor}"))

    def ambiguo(self, tipo, correccion, ini, fin, motivo):
        self.res.ambiguedades.append(Ambiguedad(tipo, correccion, self.cita(ini, fin), motivo))


def _procesar_subsegmento(acc: _Acumulador, norm: str, tipo: str, correccion, ini: int, fin: int,
                          previa: Optional[_Item], notas: list[str]):
    valores = _valores_av(norm, ini, fin) if tipo == "AV" else _valores_pio(norm, ini, fin)
    if not valores:
        return
    lats = _lateralidades(norm, ini, fin)
    items = sorted(([previa] if previa else []) + lats + valores, key=lambda i: i.inicio)
    asignacion, motivo = _asignar(items)
    ini_cita = min(it.inicio for it in items)
    if asignacion is None:
        acc.ambiguo(tipo, correccion, ini_cita, max(v.fin for v in valores), motivo)
        return
    for k, ojo in asignacion.items():
        valor = items[k]
        # marcador usado: el lateral más cercano con ese ojo (para recortar la cita)
        marcadores = [it for it in items if it.clase == "lat" and it.ojo == ojo]
        marcador = min(marcadores, key=lambda m: abs(m.inicio - valor.inicio))
        for o in (("OD", "OI") if ojo == "AO" else (ojo,)):
            acc.agregar(tipo, o, correccion, valor, marcador, notas)


def extraer_mediciones(transcripcion: str) -> ResultadoMediciones:
    norm = normalizar(transcripcion)
    acc = _Acumulador(transcripcion)

    # ---------------- Agudeza visual ----------------
    for clave in RE_CLAVE_AV.finditer(norm):
        fin = _fin_segmento(norm, clave.end())
        previa = _lateralidad_previa(norm, clave.start())
        # Divide el segmento por marcadores de corrección -> [(correccion, inicio, fin)]
        subsegmentos: list[tuple[Optional[str], int, int]] = []
        corr_actual = {"avsc": "sc", "avcc": "cc"}.get(clave.group(0))
        inicio_actual = clave.end()
        for m in RE_CORRECCION.finditer(norm, clave.end(), fin):
            subsegmentos.append((corr_actual, inicio_actual, m.start()))
            corr_actual = next(k for k in ("sc", "cc", "ae") if m.group(k))
            inicio_actual = m.end()
        subsegmentos.append((corr_actual, inicio_actual, fin))

        # Corrección dictada al FINAL ("20/20 en ambos ojos con corrección"):
        # si un subsegmento sin corrección tiene valores y el siguiente no, hereda la corrección.
        for idx in range(len(subsegmentos) - 1):
            corr, a, b = subsegmentos[idx]
            corr_sig, a2, b2 = subsegmentos[idx + 1]
            if corr is None and _valores_av(norm, a, b) and not _valores_av(norm, a2, b2):
                subsegmentos[idx] = (corr_sig, a, b)

        # El ojo mencionado antes de "agudeza visual" ("Ojo derecho: AV sc 20/40 y cc 20/20")
        # se hereda a los subsegmentos SOLO mientras ninguno dicte su propio ojo.
        contexto_ojo = previa
        for corr, a, b in subsegmentos:
            if corr == "ae":
                continue  # agujero estenopeico: no es un campo de la historia en este MVP
            notas = []
            if corr is None:
                corr = "sc"
                notas.append("corrección no especificada: se asumió sin corrección")
            tiene_ojos = bool(_lateralidades(norm, a, b))
            _procesar_subsegmento(acc, norm, "AV", corr, a, b, contexto_ojo, notas)
            if tiene_ojos:
                contexto_ojo = None

    # ---------------- Presión intraocular ----------------
    for clave in RE_CLAVE_PIO.finditer(norm):
        fin = _fin_segmento(norm, clave.end())
        previa = _lateralidad_previa(norm, clave.start())
        _procesar_subsegmento(acc, norm, "PIO", None, clave.end(), fin, previa, [])

    return acc.res
