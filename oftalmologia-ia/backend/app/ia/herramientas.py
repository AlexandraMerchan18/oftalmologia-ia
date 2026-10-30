"""Herramientas propias del agente de extracción.

Las descripciones son PROMPTS: le dicen al modelo cuándo y cómo usar cada herramienta.
Se iteraron contra la suite de eval (ver docs/decisiones.md, sección "Iteración de herramientas").

Cuarto límite del agente — CONFIRMACIÓN HUMANA:
  Cada herramienta declara `requiere_confirmacion_humana`. El bucle del agente se NIEGA a
  ejecutar cualquiera que lo requiera: esas acciones (guardar, aprobar) solo ocurren por
  endpoints que exigen al médico `confirmo_revision=true`. Por diseño, el agente no tiene
  ninguna herramienta con efectos: solo lee la transcripción y propone un borrador.
"""
from __future__ import annotations

import copy
import difflib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import ValidationError

from ..clinica.mediciones import ResultadoMediciones
from ..clinica.normalizacion import cita_presente
from ..clinica.verificador import ResultadoVerificacion, verificar_borrador
from ..esquemas import HistoriaClinica

MAX_ENVIOS_CON_ERRORES = 2  # después de 2 rechazos, el borrador se acepta con alertas para el médico


@dataclass
class ContextoAgente:
    transcripcion: str
    mediciones: ResultadoMediciones
    envios: int = 0
    verificacion: Optional[ResultadoVerificacion] = None
    entregado: bool = False


@dataclass
class Herramienta:
    nombre: str
    descripcion: str
    parametros: dict
    ejecutar: Callable[[ContextoAgente, dict], dict]
    requiere_confirmacion_humana: bool = False

    def definicion(self) -> dict:
        return {"type": "function",
                "function": {"name": self.nombre, "description": self.descripcion, "parameters": self.parametros}}


# --------------------------------------------------------------------------- herramientas
def _obtener_mediciones(ctx: ContextoAgente, _: dict) -> dict:
    datos = ctx.mediciones.como_dict()
    datos["instrucciones"] = (
        "Usa estos valores para agudeza_visual y pio. Copia 'evidencia' tal cual. "
        "Para las mediciones listadas en 'ambiguedades' deja el campo en null."
    )
    return datos


def _verificar_cita(ctx: ContextoAgente, args: dict) -> dict:
    cita = str(args.get("cita", ""))
    if cita_presente(cita, ctx.transcripcion):
        return {"encontrada": True}
    oraciones = [o.strip() for o in re.split(r"(?<=[.;])\s+", ctx.transcripcion) if o.strip()]
    sugerencia = difflib.get_close_matches(cita, oraciones, n=1, cutoff=0.3)
    return {"encontrada": False,
            "sugerencia": sugerencia[0] if sugerencia else None,
            "instrucciones": "Usa un fragmento literal de la transcripción como evidencia, o deja el campo en null."}


def _enviar_borrador(ctx: ContextoAgente, args: dict) -> dict:
    ctx.envios += 1
    try:
        historia = HistoriaClinica.model_validate(args)
    except ValidationError as e:
        errores = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()][:15]
        return {"aceptado": False, "errores_de_esquema": errores,
                "instrucciones": "Corrige estos campos y vuelve a llamar enviar_borrador."}

    verificacion = verificar_borrador(historia, ctx.transcripcion, ctx.mediciones)
    corregibles = verificacion.errores_corregibles_por_llm
    if corregibles and ctx.envios < MAX_ENVIOS_CON_ERRORES:
        ctx.verificacion = verificacion  # se guarda por si se agotan los límites
        return {"aceptado": False,
                "errores": [{"campo": a.campo, "problema": a.mensaje} for a in corregibles],
                "instrucciones": "Corrige la evidencia (debe ser literal) o pon null en esos campos, y reenvía."}
    ctx.verificacion = verificacion
    ctx.entregado = True
    return {"aceptado": True, "alertas_para_el_medico": len(verificacion.alertas)}


# --------------------------------------------------------------------------- esquema JSON
def esquema_para_proveedor(estilo: str = "openai") -> dict:
    """JSON Schema de HistoriaClinica, sin $ref y con opcionales en el dialecto del proveedor.

    - openai/groq:  {"type": ["string", "null"]}
    - gemini:       {"type": "string", "nullable": true}  (Gemini no acepta 'additionalProperties')
    """
    esquema = HistoriaClinica.model_json_schema()
    definiciones = esquema.pop("$defs", {})

    def resolver(nodo: Any) -> Any:
        if isinstance(nodo, dict):
            if "$ref" in nodo:
                return resolver(copy.deepcopy(definiciones[nodo["$ref"].split("/")[-1]]))
            nodo = {k: resolver(v) for k, v in nodo.items() if k not in ("title", "default")}
            if "anyOf" in nodo:
                tipos = [o for o in nodo["anyOf"] if o.get("type") != "null"]
                if len(tipos) == 1 and len(nodo["anyOf"]) == 2:
                    base = {**{k: v for k, v in nodo.items() if k != "anyOf"}, **tipos[0]}
                    if estilo == "gemini":
                        base["nullable"] = True
                    else:
                        base["type"] = [base["type"], "null"]
                    nodo = base
            if estilo == "gemini":
                nodo.pop("additionalProperties", None)
            return nodo
        if isinstance(nodo, list):
            return [resolver(x) for x in nodo]
        return nodo

    return resolver(esquema)


# --------------------------------------------------------------------------- registro
def construir_herramientas(estilo_esquema: str = "openai") -> dict[str, Herramienta]:
    herramientas = [
        Herramienta(
            nombre="obtener_mediciones_oculares",
            descripcion=(
                "Devuelve la agudeza visual (AV) y la presión intraocular (PIO) que un extractor determinista "
                "encontró en el dictado, con ojo (OD/OI), corrección (sc/cc) y la cita literal. "
                "ÚSALA SIEMPRE antes de llenar agudeza_visual y pio: es más confiable que tu lectura para "
                "números y lateralidad. Si una medición aparece en 'ambiguedades', deja ese campo en null; "
                "NO adivines el ojo."
            ),
            parametros={"type": "object", "properties": {}},
            ejecutar=_obtener_mediciones,
        ),
        Herramienta(
            nombre="verificar_cita",
            descripcion=(
                "Comprueba si un fragmento aparece LITERALMENTE en la transcripción. Úsala cuando no estés "
                "seguro de que tu 'evidencia' sea textual. Si no se encuentra, devuelve la oración más "
                "parecida para que la copies. No la uses para cada campo: solo ante la duda."
            ),
            parametros={"type": "object",
                        "properties": {"cita": {"type": "string", "description": "Fragmento a verificar."}},
                        "required": ["cita"]},
            ejecutar=_verificar_cita,
        ),
        Herramienta(
            nombre="enviar_borrador",
            descripcion=(
                "Entrega el borrador FINAL de la historia clínica para revisión del médico. Llámala cuando "
                "tengas todos los campos. Cada campo con valor debe traer 'evidencia' copiada literalmente "
                "de la transcripción; lo no dictado va en null. Si la respuesta trae 'aceptado': false, "
                "corrige exactamente los errores indicados y vuelve a llamarla."
            ),
            parametros=esquema_para_proveedor(estilo_esquema),
            ejecutar=_enviar_borrador,
        ),
    ]
    return {h.nombre: h for h in herramientas}


def ejecutar_herramienta(herramientas: dict[str, Herramienta], nombre: str, argumentos_json: str,
                         ctx: ContextoAgente) -> dict:
    """Punto único de ejecución: aquí se aplican el límite de confirmación y el manejo de JSON roto."""
    herramienta = herramientas.get(nombre)
    if herramienta is None:
        return {"error": f"La herramienta '{nombre}' no existe. Disponibles: {sorted(herramientas)}"}
    if herramienta.requiere_confirmacion_humana:
        return {"error": "Acción reservada al médico: requiere confirmación humana en la pantalla de revisión."}
    try:
        args = json.loads(argumentos_json or "{}")
        if not isinstance(args, dict):
            raise ValueError("los argumentos deben ser un objeto JSON")
    except (json.JSONDecodeError, ValueError) as e:
        return {"error": f"Argumentos JSON inválidos: {e}. Reenvía con JSON válido."}
    return herramienta.ejecutar(ctx, args)
