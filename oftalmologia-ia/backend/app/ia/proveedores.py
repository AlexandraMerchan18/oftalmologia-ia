"""Capa de proveedor LLM desacoplada.

El agente solo conoce el protocolo `ProveedorLLM.completar(...)`. Cambiar de Groq a
Gemini u OpenAI es cambiar LLM_PROVIDER en el .env: los tres exponen la API de
Chat Completions compatible con OpenAI, así que una sola implementación los cubre.

Aquí también se TRADUCEN los errores del SDK a errores de dominio con mensajes
para humanos (timeout, caída, 429, credenciales). Ningún error del SDK sale de este módulo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..config import Config
from ..errores import (
    ConfiguracionIncompleta,
    ErrorAplicacion,
    LimiteDeTasa,
    ProveedorNoDisponible,
    TimeoutIA,
)


class RespuestaInvalidaModelo(ErrorAplicacion):
    """El modelo devolvió una llamada a herramienta mal formada (contrato JSON roto)."""

    codigo = "ia_respuesta_invalida"
    http_status = 502
    mensaje_por_defecto = "La IA devolvió una respuesta con formato inválido."


@dataclass
class LlamadaHerramienta:
    id: str
    nombre: str
    argumentos: str  # JSON crudo tal como lo generó el modelo


@dataclass
class RespuestaLLM:
    contenido: Optional[str]
    llamadas: list[LlamadaHerramienta] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_salida: int = 0
    latencia_ms: float = 0.0
    finalizacion: Optional[str] = None

    def como_mensaje(self) -> dict:
        """Mensaje 'assistant' para reinyectar en el historial de la conversación."""
        mensaje: dict = {"role": "assistant", "content": self.contenido or ""}
        if self.llamadas:
            mensaje["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.nombre, "arguments": c.argumentos}}
                for c in self.llamadas
            ]
        return mensaje


class ProveedorLLM(Protocol):
    nombre: str
    modelo: str
    estilo_esquema: str  # "openai" | "gemini": cómo se expresa un campo opcional en JSON Schema

    def completar(self, mensajes: list[dict], herramientas: Optional[list[dict]], max_tokens: int,
                  timeout_s: float) -> RespuestaLLM: ...

    def costo_usd(self, tokens_entrada: int, tokens_salida: int) -> float: ...


class _ConCosto:
    precio_entrada_mtok: float = 0.0
    precio_salida_mtok: float = 0.0

    def costo_usd(self, tokens_entrada: int, tokens_salida: int) -> float:
        return (tokens_entrada * self.precio_entrada_mtok + tokens_salida * self.precio_salida_mtok) / 1_000_000


class ProveedorOpenAICompatible(_ConCosto):
    """Groq, Gemini (endpoint OpenAI) y OpenAI con el mismo código."""

    def __init__(self, nombre: str, modelo: str, api_key: str, base_url: Optional[str],
                 precio_entrada_mtok: float, precio_salida_mtok: float, temperatura: float,
                 reasoning_effort: str = ""):
        import openai  # import diferido: los tests de lógica pura no necesitan el SDK

        self._openai = openai
        self.nombre, self.modelo = nombre, modelo
        self.precio_entrada_mtok, self.precio_salida_mtok = precio_entrada_mtok, precio_salida_mtok
        self.temperatura, self.reasoning_effort = temperatura, reasoning_effort
        self.estilo_esquema = "gemini" if nombre == "gemini" else "openai"
        # max_retries=1: un único reintento automático (cubre 429/5xx transitorios) sin bucles ciegos.
        self._cliente = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=1)

    def completar(self, mensajes, herramientas, max_tokens, timeout_s) -> RespuestaLLM:
        openai = self._openai
        params: dict = {"model": self.modelo, "messages": mensajes, "temperature": self.temperatura}
        params["max_tokens" if self.nombre == "gemini" else "max_completion_tokens"] = max_tokens
        if herramientas:
            params["tools"] = herramientas
            params["tool_choice"] = "auto"
        if self.reasoning_effort:
            params["reasoning_effort"] = self.reasoning_effort
        inicio = time.perf_counter()
        try:
            r = self._cliente.with_options(timeout=timeout_s).chat.completions.create(**params)
        except openai.APITimeoutError as e:
            raise TimeoutIA(detalle={"proveedor": self.nombre, "timeout_s": round(timeout_s, 1)}) from e
        except openai.RateLimitError as e:
            raise LimiteDeTasa(detalle={"proveedor": self.nombre}) from e
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            raise ConfiguracionIncompleta(
                f"El proveedor {self.nombre} rechazó la llave de API. Revise {self.nombre.upper()}_API_KEY en .env.",
                detalle={"proveedor": self.nombre}) from e
        except openai.BadRequestError as e:
            # Groq responde 400 "tool_use_failed" cuando el modelo genera JSON de herramienta inválido.
            raise RespuestaInvalidaModelo(detalle={"proveedor": self.nombre, "error": str(e)[:300]}) from e
        except openai.NotFoundError as e:
            raise ConfiguracionIncompleta(
                f"El modelo '{self.modelo}' no existe en {self.nombre}. Revise LLM_MODEL en .env.") from e
        except (openai.APIConnectionError, openai.InternalServerError, openai.APIStatusError) as e:
            raise ProveedorNoDisponible(detalle={"proveedor": self.nombre, "error": type(e).__name__}) from e

        latencia = (time.perf_counter() - inicio) * 1000
        opcion = r.choices[0]
        llamadas = [
            LlamadaHerramienta(id=tc.id, nombre=tc.function.name, argumentos=tc.function.arguments or "{}")
            for tc in (opcion.message.tool_calls or [])
        ]
        uso = r.usage
        return RespuestaLLM(
            contenido=opcion.message.content,
            llamadas=llamadas,
            tokens_entrada=getattr(uso, "prompt_tokens", 0) or 0,
            tokens_salida=getattr(uso, "completion_tokens", 0) or 0,
            latencia_ms=latencia,
            finalizacion=opcion.finish_reason,
        )


class InyectorFallas:
    """Permite DEMOSTRAR en vivo el manejo de fallos (timeout, caída, JSON roto) sin desconectar internet.

    Se arma desde el panel de trazas (POST /api/demo/falla) y se consume en la siguiente llamada al LLM.
    Solo funciona si PERMITIR_SIMULAR_FALLAS=true.
    """

    def __init__(self, habilitado: bool):
        self.habilitado = habilitado
        self.proxima: Optional[str] = None

    def armar(self, tipo: Optional[str]) -> None:
        self.proxima = tipo

    def consumir(self) -> Optional[str]:
        tipo, self.proxima = self.proxima, None
        return tipo


class ProveedorConFallas:
    """Envoltorio (patrón decorador) que inyecta un fallo simulado antes de delegar al proveedor real."""

    def __init__(self, real: ProveedorLLM, inyector: InyectorFallas):
        self.real, self.inyector = real, inyector
        self.nombre, self.modelo, self.estilo_esquema = real.nombre, real.modelo, real.estilo_esquema

    def costo_usd(self, tokens_entrada: int, tokens_salida: int) -> float:
        return self.real.costo_usd(tokens_entrada, tokens_salida)

    def completar(self, mensajes, herramientas, max_tokens, timeout_s) -> RespuestaLLM:
        falla = self.inyector.consumir() if self.inyector.habilitado else None
        if falla == "timeout":
            raise TimeoutIA(detalle={"simulado": True})
        if falla == "caida":
            raise ProveedorNoDisponible(detalle={"simulado": True})
        if falla == "limite_tasa":
            raise LimiteDeTasa(detalle={"simulado": True})
        if falla == "json_roto":
            return RespuestaLLM(contenido=None, llamadas=[LlamadaHerramienta("simulada", "enviar_borrador",
                                                                              '{"motivo_consulta": {"valor": ')])
        return self.real.completar(mensajes, herramientas, max_tokens, timeout_s)


def construir_proveedor(config: Config) -> ProveedorLLM:
    perfil = config.perfil_llm
    if config.llm_provider == "mock":
        from .simulado import ProveedorSimulado

        return ProveedorSimulado()
    if not config.api_key_llm:
        return _ProveedorSinLlave(config)
    return ProveedorOpenAICompatible(
        nombre=config.llm_provider,
        modelo=config.modelo_llm,
        api_key=config.api_key_llm,
        base_url=perfil.base_url,
        precio_entrada_mtok=config.llm_precio_entrada_mtok if config.llm_precio_entrada_mtok is not None
        else perfil.precio_entrada_mtok,
        precio_salida_mtok=config.llm_precio_salida_mtok if config.llm_precio_salida_mtok is not None
        else perfil.precio_salida_mtok,
        temperatura=config.llm_temperature,
        reasoning_effort=perfil.reasoning_effort if config.llm_reasoning_effort is None
        else config.llm_reasoning_effort,
    )


class _ProveedorSinLlave(_ConCosto):
    """La app arranca aunque falte la llave; el error aparece, claro, al usar la IA."""

    estilo_esquema = "openai"

    def __init__(self, config: Config):
        self.nombre, self.modelo = config.llm_provider, config.modelo_llm
        self._variable = config.variable_api_key_llm

    def completar(self, *args, **kwargs) -> RespuestaLLM:
        raise ConfiguracionIncompleta(
            f"Falta {self._variable} en el archivo .env (o use LLM_PROVIDER=mock para la demo sin llaves)."
        )
