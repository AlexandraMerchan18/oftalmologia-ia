"""Endpoints HTTP. Solo traducen JSON <-> ServicioConsultas; no contienen lógica de negocio.

Los endpoints son síncronos (def, no async def): FastAPI los ejecuta en un pool de hilos,
lo cual es correcto para Whisper (CPU) y para el SDK de OpenAI en modo síncrono.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..ejemplos import EJEMPLOS
from ..errores import AudioInvalido, ErrorValidacion
from ..esquemas import AprobacionFinal, CrearConsulta, RevisionMedica, TranscripcionManual
from ..ia.prompts import PROMPT_VERSION
from ..servicios import ServicioConsultas, Servicios, resumen_trazas

router = APIRouter(prefix="/api")

EXTENSIONES_AUDIO = {".webm", ".ogg", ".oga", ".wav", ".mp3", ".m4a", ".mp4", ".flac", ".aac"}


# ---------------------------------------------------------------- dependencias
def obtener_servicios(request: Request) -> Servicios:
    return request.app.state.servicios


def obtener_sesion(request: Request):
    sesion: Session = request.app.state.fabrica_sesiones()
    try:
        yield sesion
    finally:
        sesion.close()


def servicio(sesion: Session = Depends(obtener_sesion),
             servicios: Servicios = Depends(obtener_servicios)) -> ServicioConsultas:
    return ServicioConsultas(sesion, servicios)


# ---------------------------------------------------------------- modelos de salida
class ConsultaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    paciente_ref: str
    medico: str
    estado: str
    transcripcion: Optional[str] = None
    fuente_transcripcion: Optional[str] = None
    duracion_audio_s: Optional[float] = None
    borrador: Optional[dict] = None
    alertas: Optional[list] = None
    resumen_extraccion: Optional[dict] = None
    historia_final: Optional[dict] = None
    campos_corregidos: Optional[list] = None
    revisado_por: Optional[str] = None
    revisado_en: Optional[datetime] = None
    explicacion_borrador: Optional[str] = None
    explicacion_metodo: Optional[str] = None
    explicacion_final: Optional[str] = None
    aprobado_por: Optional[str] = None
    aprobado_en: Optional[datetime] = None
    creado_en: datetime
    actualizado_en: datetime


class ConsultaResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    paciente_ref: str
    medico: str
    estado: str
    creado_en: datetime


class TrazaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    paso: int
    tipo: str
    nombre: str
    ok: bool
    detalle: Optional[dict] = None
    latencia_ms: Optional[float] = None
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None
    costo_usd: Optional[float] = None
    creado_en: datetime


class SimularFalla(BaseModel):
    tipo: Optional[Literal["timeout", "caida", "json_roto", "limite_tasa"]] = None


# ---------------------------------------------------------------- sistema
@router.get("/salud")
def salud(request: Request, servicios: Servicios = Depends(obtener_servicios)) -> dict[str, Any]:
    c = servicios.config
    try:
        with request.app.state.fabrica_sesiones() as s:
            s.execute(text("SELECT 1"))
        bd = "ok"
    except Exception:  # noqa: BLE001
        bd = "sin conexión"
    return {
        "estado": "ok" if bd == "ok" else "degradado",
        "base_datos": bd,
        "llm": {"proveedor": c.llm_provider, "modelo": servicios.llm.modelo,
                "llave_configurada": c.llm_provider == "mock" or bool(c.api_key_llm)},
        "transcripcion": servicios.transcriptor.descripcion,
        "prompt_version": PROMPT_VERSION,
        "limites_agente": {"max_iteraciones": c.agente_max_iteraciones, "timeout_s": c.agente_timeout_s,
                           "max_tokens_totales": c.agente_max_tokens_totales,
                           "confirmacion_humana": "obligatoria (pasos 5 y 8)"},
        "simular_fallas": c.permitir_simular_fallas,
    }


@router.get("/ejemplos")
def ejemplos() -> list[dict]:
    return EJEMPLOS


@router.post("/demo/falla")
def simular_falla(datos: SimularFalla, servicios: Servicios = Depends(obtener_servicios)) -> dict:
    if not servicios.inyector.habilitado:
        raise ErrorValidacion("La simulación de fallos está deshabilitada (PERMITIR_SIMULAR_FALLAS=false).")
    servicios.inyector.armar(datos.tipo)
    return {"proxima_falla": datos.tipo}


# ---------------------------------------------------------------- consultas
@router.get("/consultas", response_model=list[ConsultaResumen])
def listar(svc: ServicioConsultas = Depends(servicio)):
    return svc.listar()


@router.post("/consultas", response_model=ConsultaSalida, status_code=201)
def crear(datos: CrearConsulta, svc: ServicioConsultas = Depends(servicio)):
    """Paso 1: abre la consulta (el dictado se graba en el navegador)."""
    return svc.crear(datos)


@router.get("/consultas/{consulta_id}", response_model=ConsultaSalida)
def obtener(consulta_id: str, svc: ServicioConsultas = Depends(servicio)):
    return svc.obtener(consulta_id)


@router.post("/consultas/{consulta_id}/audio", response_model=ConsultaSalida)
def subir_audio(consulta_id: str, audio: UploadFile = File(...), svc: ServicioConsultas = Depends(servicio),
                servicios: Servicios = Depends(obtener_servicios)):
    """Paso 2: transcribe con Whisper. El audio se borra apenas termina (no se conserva)."""
    extension = os.path.splitext(audio.filename or "")[1].lower() or ".webm"
    tipo = (audio.content_type or "").split(";")[0]
    if extension not in EXTENSIONES_AUDIO and not tipo.startswith(("audio/", "video/webm")):
        raise AudioInvalido(f"Formato no soportado ({extension or tipo}). Use webm, wav, mp3, m4a u ogg.")
    limite = servicios.config.max_audio_mb * 1024 * 1024
    ruta, total = None, 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
            ruta = tmp.name
            while bloque := audio.file.read(1024 * 1024):
                total += len(bloque)
                if total > limite:
                    raise AudioInvalido(f"El audio supera {servicios.config.max_audio_mb} MB.")
                tmp.write(bloque)
        if total == 0:
            raise AudioInvalido("El archivo de audio está vacío.")
        return svc.transcribir_audio(consulta_id, ruta, total)
    finally:
        if ruta and os.path.exists(ruta):
            os.remove(ruta)


@router.put("/consultas/{consulta_id}/transcripcion", response_model=ConsultaSalida)
def fijar_transcripcion(consulta_id: str, datos: TranscripcionManual, svc: ServicioConsultas = Depends(servicio)):
    """Paso 2 (alternativo): dictado escrito o corrección de lo que transcribió Whisper."""
    return svc.fijar_transcripcion(consulta_id, datos.texto)


@router.post("/consultas/{consulta_id}/extraccion", response_model=ConsultaSalida)
def extraer(consulta_id: str, svc: ServicioConsultas = Depends(servicio)):
    """Pasos 3 y 4: agente LLM + verificación determinista -> borrador con alertas."""
    return svc.extraer(consulta_id)


@router.post("/consultas/{consulta_id}/revision", response_model=ConsultaSalida)
def revisar(consulta_id: str, datos: RevisionMedica, svc: ServicioConsultas = Depends(servicio)):
    """Pasos 5 y 6: revisión médica obligatoria y guardado."""
    return svc.guardar_revision(consulta_id, datos)


@router.post("/consultas/{consulta_id}/explicacion", response_model=ConsultaSalida)
def explicar(consulta_id: str, svc: ServicioConsultas = Depends(servicio)):
    """Paso 7: explicación para el paciente (solo con la historia ya guardada)."""
    return svc.explicar(consulta_id)


@router.post("/consultas/{consulta_id}/aprobacion", response_model=ConsultaSalida)
def aprobar(consulta_id: str, datos: AprobacionFinal, svc: ServicioConsultas = Depends(servicio)):
    """Paso 8: aprobación final del médico."""
    return svc.aprobar(consulta_id, datos)


@router.get("/consultas/{consulta_id}/trazas")
def trazas(consulta_id: str, svc: ServicioConsultas = Depends(servicio)) -> dict:
    filas = svc.trazas(consulta_id)
    return {"resumen": resumen_trazas(filas), "trazas": [TrazaSalida.model_validate(t).model_dump() for t in filas]}
