"""Configuración central leída de variables de entorno (ver .env.example).

Toda la configuración entra por aquí: ningún otro módulo lee os.environ.
Así el profesor (o un test) puede saber exactamente qué variables existen.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class PerfilProveedor:
    """Valores por defecto de cada proveedor LLM (todos exponen API compatible con OpenAI)."""

    base_url: str | None
    modelo: str
    precio_entrada_mtok: float  # USD por 1M tokens de entrada
    precio_salida_mtok: float   # USD por 1M tokens de salida
    reasoning_effort: str       # "" = no enviar el parámetro


PERFILES_LLM: dict[str, PerfilProveedor] = {
    # Groq: gpt-oss-120b es el modelo grande de autoservicio (Llama 3.3 70B pasó a Enterprise).
    "groq": PerfilProveedor("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", 0.15, 0.60, "low"),
    # Gemini vía su endpoint compatible con OpenAI. "none" desactiva el "thinking" en 2.5 Flash.
    "gemini": PerfilProveedor(
        "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash", 0.30, 2.50, "none"
    ),
    "openai": PerfilProveedor(None, "gpt-4o-mini", 0.15, 0.60, ""),
    # Proveedor simulado y determinista: sin red, sin llaves. Para tests, eval de humo y demo offline.
    "mock": PerfilProveedor(None, "simulado-determinista", 0.0, 0.0, ""),
}


class Config(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # --- Base de datos ---
    database_url: str = "sqlite:///./oftalmologia_dev.db"

    # --- LLM ---
    llm_provider: str = "groq"  # groq | gemini | openai | mock
    llm_model: str = ""         # vacío = modelo por defecto del proveedor
    groq_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    llm_temperature: float = 0.0
    llm_reasoning_effort: str | None = None  # None = usar el del perfil
    llm_precio_entrada_mtok: float | None = None
    llm_precio_salida_mtok: float | None = None
    llm_timeout_s: float = 30.0

    # --- Límites del agente (los 4 límites activos de la rúbrica) ---
    agente_max_iteraciones: int = 5         # 1. iteraciones
    agente_timeout_s: float = 60.0          # 2. timeout total del bucle
    agente_max_tokens_totales: int = 20000  # 3. presupuesto de tokens por consulta
    llm_max_tokens_respuesta: int = 4096
    # 4. confirmación humana: no es configurable a propósito (ver app/ia/herramientas.py).

    # --- Transcripción ---
    transcripcion_provider: str = "local"  # local (faster-whisper) | groq | mock
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_groq_model: str = "whisper-large-v3-turbo"
    max_audio_mb: int = 25

    # --- Demo de manejo de fallos (panel de trazas -> "Simular fallo") ---
    permitir_simular_fallas: bool = True

    # --- HTTP ---
    cors_origins: str = "http://localhost:8080,http://localhost:5173"

    @property
    def perfil_llm(self) -> PerfilProveedor:
        if self.llm_provider not in PERFILES_LLM:
            raise ValueError(
                f"LLM_PROVIDER='{self.llm_provider}' no es válido. Use uno de: {', '.join(PERFILES_LLM)}"
            )
        return PERFILES_LLM[self.llm_provider]

    @property
    def modelo_llm(self) -> str:
        return self.llm_model or self.perfil_llm.modelo

    @property
    def api_key_llm(self) -> str:
        return {
            "groq": self.groq_api_key,
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
        }.get(self.llm_provider, "no-requerida")

    @property
    def variable_api_key_llm(self) -> str:
        return f"{self.llm_provider.upper()}_API_KEY"

    @property
    def lista_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def obtener_config() -> Config:
    return Config()
