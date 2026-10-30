"""Normalización de texto y números dictados en español.

`normalizar` conserva la LONGITUD del texto (reemplaza 1 carácter por 1 carácter),
de modo que una posición encontrada en el texto normalizado sirve para recortar
la cita exacta del texto original. Esto es lo que permite mostrar evidencia literal.
"""
from __future__ import annotations

import re

_TABLA_TILDES = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")

UNIDADES = {"cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
            "seis": 6, "siete": 7, "ocho": 8, "nueve": 9}
ESPECIALES = {"diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
              "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
              "veintiuno": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
              "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
           "ochenta": 80, "noventa": 90}
CENTENAS = {"cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300, "cuatrocientos": 400,
            "quinientos": 500, "seiscientos": 600, "setecientos": 700, "ochocientos": 800,
            "novecientos": 900}


def _alt(d: dict) -> str:
    # Más largos primero para que "veintiuno" gane sobre "veinte".
    return "|".join(sorted(d, key=len, reverse=True))


_UNI, _ESP, _DEC, _CEN = _alt(UNIDADES), _alt(ESPECIALES), _alt(DECENAS), _alt(CENTENAS)
_DEC_COMPUESTA = rf"(?:{_DEC})(?:\s+y\s+(?:{_UNI}))?"
_MENOR_CIEN = rf"(?:{_ESP}|{_DEC_COMPUESTA}|{_UNI})"
NUM_PALABRAS = rf"(?:(?:{_CEN})(?:\s+{_MENOR_CIEN})?|{_MENOR_CIEN})"
NUM_DIGITOS = r"\d{1,3}(?:[.,]\d+)?"
# Número dictado en dígitos o en palabras (sobre texto normalizado).
NUM = rf"(?:(?<![\d/]){NUM_DIGITOS}(?![\d/])|\b{NUM_PALABRAS}\b)"

_TODAS = {**UNIDADES, **ESPECIALES, **DECENAS, **CENTENAS}


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes, MISMA longitud que el original."""
    return texto.lower().translate(_TABLA_TILDES)


def normalizar_para_comparar(texto: str) -> str:
    """Forma canónica para comparar citas: sin tildes, sin puntuación, espacios simples."""
    t = normalizar(texto)
    t = re.sub(r"[.,;:¿?¡!\"'()\[\]«»“”‘’\-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def a_numero(token: str) -> float | None:
    """'15' -> 15.0, '15,5' -> 15.5, 'treinta y cinco' -> 35.0, 'ciento veinte' -> 120.0."""
    t = normalizar(token).strip()
    if re.fullmatch(NUM_DIGITOS, t):
        return float(t.replace(",", "."))
    total = 0
    encontrado = False
    for palabra in t.split():
        if palabra == "y":
            continue
        if palabra not in _TODAS:
            return None
        total += _TODAS[palabra]
        encontrado = True
    return float(total) if encontrado else None


def numeros_en_texto(texto: str) -> set[float]:
    """Todos los números presentes en un texto (dígitos o palabras). Para detectar alucinaciones.

    Una fracción como 20/40 aporta 20 y 40; '2040' (error típico de Whisper) aporta 20 y 40 también.
    """
    t = normalizar(texto)
    numeros: set[float] = set()
    for m in re.finditer(NUM, t):
        n = a_numero(m.group(0))
        if n is not None:
            numeros.add(n)
    for m in re.finditer(r"\b20(\d{2,3})\b", t):
        numeros.update({20.0, float(m.group(1))})
    return numeros


def cita_presente(cita: str, transcripcion: str) -> bool:
    """¿La cita aparece literalmente (salvo tildes, mayúsculas y puntuación) en la transcripción?"""
    c = normalizar_para_comparar(cita)
    return bool(c) and c in normalizar_para_comparar(transcripcion)
