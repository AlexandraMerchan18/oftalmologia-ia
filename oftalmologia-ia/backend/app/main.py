"""Punto de entrada FastAPI: configuración, ciclo de vida y manejo global de errores.

Contrato de errores (lo que ve el frontend, NUNCA un stack trace):
    {"error": {"codigo": "ia_timeout", "mensaje": "...", "detalle": {...}, "traza_id": "a1b2c3d4"}}
El stack trace completo queda solo en los logs del servidor, enlazado por `traza_id`.
"""
from __future__ import annotations

import logging
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from .api.rutas import router
from .config import Config, obtener_config
from .db import crear_motor, inicializar_bd
from .errores import ErrorAplicacion
from .servicios import Servicios, construir_servicios

logger = logging.getLogger("oftalmologia")

NOMBRES_CAMPOS = {"paciente_ref": "identificador del paciente", "medico": "médico", "texto": "dictado",
                  "explicacion_final": "explicación", "confirmo_revision": "confirmación de revisión"}


def configurar_logging() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _error(status: int, codigo: str, mensaje: str, detalle: Optional[dict] = None,
           traza_id: Optional[str] = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "codigo": codigo, "mensaje": mensaje, "detalle": detalle or {}, "traza_id": traza_id or _nuevo_id()}})


def _nuevo_id() -> str:
    return uuid.uuid4().hex[:8]


def crear_app(config: Optional[Config] = None, servicios: Optional[Servicios] = None) -> FastAPI:
    config = config or obtener_config()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        configurar_logging()
        motor = crear_motor(config.database_url)
        inicializar_bd(motor)
        app.state.fabrica_sesiones = sessionmaker(motor, expire_on_commit=False)
        app.state.servicios = servicios or construir_servicios(config)
        if hasattr(app.state.servicios.transcriptor, "precalentar"):
            app.state.servicios.transcriptor.precalentar()
        logger.info("Listo. LLM=%s/%s | Transcripción=%s", config.llm_provider,
                    app.state.servicios.llm.modelo, app.state.servicios.transcriptor.descripcion)
        yield
        motor.dispose()

    app = FastAPI(title="Oftalmología + IA — Historia clínica asistida", version="1.0.0", lifespan=ciclo_de_vida)
    app.add_middleware(CORSMiddleware, allow_origins=config.lista_cors, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)

    @app.exception_handler(ErrorAplicacion)
    async def manejar_error_aplicacion(request: Request, exc: ErrorAplicacion):
        traza_id = _nuevo_id()
        logger.warning("[%s] %s %s -> %s: %s %s", traza_id, request.method, request.url.path, exc.codigo,
                       exc.mensaje, exc.detalle)
        return _error(exc.http_status, exc.codigo, exc.mensaje, exc.detalle, traza_id)

    @app.exception_handler(RequestValidationError)
    async def manejar_validacion(request: Request, exc: RequestValidationError):
        campos = []
        for err in exc.errors():
            ruta = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            nombre = NOMBRES_CAMPOS.get(ruta[-1], ".".join(ruta)) if ruta else "solicitud"
            campos.append({"campo": ".".join(ruta), "mensaje": f"{nombre}: {err.get('msg', 'valor inválido')}"})
        mensaje = "Revise los datos: " + "; ".join(c["mensaje"] for c in campos[:3])
        return _error(422, "validacion", mensaje, {"campos": campos})

    @app.exception_handler(Exception)
    async def manejar_inesperado(request: Request, exc: Exception):
        traza_id = _nuevo_id()
        logger.exception("[%s] Error no controlado en %s %s", traza_id, request.method, request.url.path)
        return _error(500, "error_interno",
                      f"Ocurrió un error inesperado. Reporte el código {traza_id} al equipo técnico.",
                      traza_id=traza_id)

    return app


app = crear_app()
