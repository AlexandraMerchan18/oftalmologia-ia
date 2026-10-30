"""Errores de dominio con mensaje apto para el usuario.

Regla: el frontend NUNCA recibe un stack trace. Cada error tiene un código estable
(para que el frontend decida qué mostrar) y un mensaje en español claro.
"""
from __future__ import annotations


class ErrorAplicacion(Exception):
    codigo = "error_interno"
    http_status = 500
    mensaje_por_defecto = "Ocurrió un error inesperado. Intente de nuevo."

    def __init__(self, mensaje: str | None = None, detalle: dict | None = None):
        self.mensaje = mensaje or self.mensaje_por_defecto
        self.detalle = detalle or {}
        super().__init__(self.mensaje)


# --- Fallo 1: timeout -------------------------------------------------------
class TimeoutIA(ErrorAplicacion):
    codigo = "ia_timeout"
    http_status = 504
    mensaje_por_defecto = (
        "El servicio de IA tardó demasiado en responder. Su dictado está guardado: "
        "puede reintentar la extracción o diligenciar la historia manualmente."
    )


# --- Fallo 2: caída / indisponibilidad de la API ---------------------------
class ProveedorNoDisponible(ErrorAplicacion):
    codigo = "ia_no_disponible"
    http_status = 503
    mensaje_por_defecto = (
        "El proveedor de IA no está disponible en este momento. Su dictado está guardado; "
        "reintente en unos minutos."
    )


class LimiteDeTasa(ErrorAplicacion):
    codigo = "ia_limite_tasa"
    http_status = 429
    mensaje_por_defecto = "El proveedor de IA está recibiendo demasiadas solicitudes (429). Espere unos segundos y reintente."


class ConfiguracionIncompleta(ErrorAplicacion):
    codigo = "configuracion_incompleta"
    http_status = 503
    mensaje_por_defecto = "Falta configurar la llave del proveedor de IA en el archivo .env."


# --- Fallo 3: validación ----------------------------------------------------
class ErrorValidacion(ErrorAplicacion):
    codigo = "validacion"
    http_status = 422
    mensaje_por_defecto = "Los datos enviados no son válidos."


class AudioInvalido(ErrorAplicacion):
    codigo = "audio_invalido"
    http_status = 400
    mensaje_por_defecto = "No se pudo procesar el audio. Verifique el archivo o use el modo texto."


class TransicionInvalida(ErrorAplicacion):
    codigo = "transicion_invalida"
    http_status = 409
    mensaje_por_defecto = "Esta acción no está permitida en el estado actual de la consulta."


class NoEncontrado(ErrorAplicacion):
    codigo = "no_encontrado"
    http_status = 404
    mensaje_por_defecto = "La consulta solicitada no existe."
