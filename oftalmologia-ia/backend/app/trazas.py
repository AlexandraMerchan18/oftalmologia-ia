"""Evento de traza: la unidad de observabilidad del sistema.

Cada llamada al LLM, cada herramienta ejecutada, cada transcripción y cada fallo
genera un EventoTraza. El servicio los persiste en la tabla `trazas` y el
frontend los muestra en vivo (panel "Trazas"). Los módulos de IA no conocen la BD:
solo reciben una función `registrar(evento)`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal, Optional

logger = logging.getLogger("oftalmologia.trazas")

TipoTraza = Literal["whisper", "llm", "herramienta", "limite", "validacion", "seguridad", "estado", "error"]


@dataclass
class EventoTraza:
    paso: int                  # 1..8 según el flujo del producto
    tipo: TipoTraza
    nombre: str
    ok: bool = True
    detalle: dict[str, Any] = field(default_factory=dict)
    latencia_ms: Optional[float] = None
    tokens_entrada: Optional[int] = None
    tokens_salida: Optional[int] = None
    costo_usd: Optional[float] = None


RegistrarTraza = Callable[[EventoTraza], None]


def registrar_en_log(evento: EventoTraza) -> None:
    """Además de la BD, cada evento sale por stdout en JSON (visible con `docker compose logs`)."""
    logger.info(json.dumps({"traza": asdict(evento)}, ensure_ascii=False, default=str))


def sin_trazas(_: EventoTraza) -> None:  # útil en tests y en la evaluación
    return None


def recortar(valor: Any, limite: int = 1500) -> Any:
    """Evita trazas gigantes: recorta textos y JSON largos."""
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str)
    return valor if len(texto) <= limite else texto[:limite] + f"… (+{len(texto) - limite} caracteres)"
