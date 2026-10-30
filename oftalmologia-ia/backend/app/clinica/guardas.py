"""Guardas de seguridad para la explicación al paciente (paso 7).

Invariante del producto: la IA documenta y explica, NUNCA diagnostica.
Por eso la explicación solo puede mencionar diagnósticos y cifras que ya estén
en la historia APROBADA por el médico. Esto se verifica en código, no se "pide" al modelo.
"""
from __future__ import annotations

import re

from .normalizacion import normalizar, numeros_en_texto

# Lista cerrada de términos diagnósticos oftalmológicos frecuentes (sin tildes, minúsculas).
TERMINOS_DIAGNOSTICOS = {
    "glaucoma", "hipertension ocular", "catarata", "retinopatia", "retinopatia diabetica",
    "degeneracion macular", "dmae", "maculopatia", "edema macular", "desprendimiento de retina",
    "queratocono", "queratitis", "uveitis", "conjuntivitis", "blefaritis", "chalazion", "orzuelo",
    "pterigion", "pinguecula", "ojo seco", "ambliopia", "estrabismo", "miopia", "hipermetropia",
    "astigmatismo", "presbicia", "neuropatia optica", "neuritis optica", "oclusion venosa",
    "oclusion arterial", "agujero macular", "membrana epirretiniana", "retinitis pigmentosa",
    "endoftalmitis", "escleritis", "epiescleritis", "ulcera corneal", "papiledema",
}

# Frases que convierten la explicación en un acto médico no autorizado.
FRASES_PROHIBIDAS = [
    r"\bsuspend[ae]\b.*\bmedicamento", r"\bno necesita (?:volver|control)", r"\bse va a quedar ciego",
    r"\bno es nada grave\b", r"\bpronostico\b", r"\ble diagnostico\b", r"\bprobablemente (?:tiene|sea)\b",
]


def terminos_diagnosticos_en(texto: str) -> set[str]:
    t = normalizar(texto)
    return {term for term in TERMINOS_DIAGNOSTICOS if re.search(rf"(?<!\w){term}(?!\w)", t)}


def violaciones_explicacion(explicacion: str, texto_historia: str) -> list[str]:
    """Lista de violaciones de seguridad. Vacía = la explicación es segura para mostrar al médico."""
    violaciones = []
    nuevos = terminos_diagnosticos_en(explicacion) - terminos_diagnosticos_en(texto_historia)
    if nuevos:
        violaciones.append(f"menciona diagnósticos que no están en la historia aprobada: {sorted(nuevos)}")
    numeros_nuevos = numeros_en_texto(explicacion) - numeros_en_texto(texto_historia) - {1.0, 2.0, 3.0}
    if numeros_nuevos:
        violaciones.append(f"incluye cifras que no están en la historia: {sorted(f'{n:g}' for n in numeros_nuevos)}")
    t = normalizar(explicacion)
    for patron in FRASES_PROHIBIDAS:
        if re.search(patron, t):
            violaciones.append(f"contiene una afirmación clínica no permitida (patrón '{patron}')")
    return violaciones


AVISO_PACIENTE = (
    "Esta explicación fue preparada con apoyo de inteligencia artificial a partir de lo que dictó "
    "su oftalmólogo, y fue revisada y aprobada por él/ella. No reemplaza la consulta médica: "
    "ante cualquier duda o si sus síntomas empeoran, comuníquese con su oftalmólogo."
)
