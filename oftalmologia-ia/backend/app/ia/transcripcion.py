"""Paso 2: transcripción con Whisper.

Tres implementaciones del mismo protocolo (`Transcriptor.transcribir`):
  - local: faster-whisper (CTranslate2, int8 en CPU). El audio NUNCA sale del servidor.
  - groq:  whisper-large-v3-turbo vía API (más rápido; el audio sale a un tercero).
  - mock:  devuelve un texto fijo (tests).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional, Protocol

from ..config import Config
from ..errores import AudioInvalido, ConfiguracionIncompleta, ProveedorNoDisponible, TimeoutIA
from .prompts import VOCABULARIO_WHISPER


@dataclass
class ResultadoTranscripcion:
    texto: str
    duracion_audio_s: Optional[float]
    modelo: str
    latencia_ms: float


class Transcriptor(Protocol):
    descripcion: str

    def transcribir(self, ruta_audio: str) -> ResultadoTranscripcion: ...


class TranscriptorLocal:
    """faster-whisper. El modelo se carga una sola vez (perezosamente) y se comparte entre peticiones."""

    _modelo = None
    _candado = threading.Lock()

    def __init__(self, nombre_modelo: str, compute_type: str):
        self.nombre_modelo, self.compute_type = nombre_modelo, compute_type
        self.descripcion = f"faster-whisper {nombre_modelo} ({compute_type}, CPU, local)"

    def _cargar(self):
        with self._candado:
            if TranscriptorLocal._modelo is None:
                from faster_whisper import WhisperModel

                TranscriptorLocal._modelo = WhisperModel(self.nombre_modelo, device="cpu",
                                                         compute_type=self.compute_type)
        return TranscriptorLocal._modelo

    def precalentar(self) -> None:
        """Carga el modelo en segundo plano al arrancar: la primera transcripción no espera."""
        threading.Thread(target=self._cargar, daemon=True, name="carga-whisper").start()

    def transcribir(self, ruta_audio: str) -> ResultadoTranscripcion:
        inicio = time.perf_counter()
        modelo = self._cargar()
        try:
            segmentos, info = modelo.transcribe(
                ruta_audio, language="es", initial_prompt=VOCABULARIO_WHISPER,
                vad_filter=True,       # recorta silencios: menos tiempo y menos "alucinaciones" de Whisper
                beam_size=5, temperature=0.0, condition_on_previous_text=False,
            )
            texto = " ".join(s.text.strip() for s in segmentos).strip()
        except Exception as e:  # PyAV/ffmpeg lanzan errores variados ante audio corrupto
            raise AudioInvalido(detalle={"error": type(e).__name__}) from e
        if not texto:
            raise AudioInvalido("No se detectó voz en el audio. Verifique el micrófono o use el modo texto.")
        return ResultadoTranscripcion(texto, round(info.duration, 1), f"faster-whisper/{self.nombre_modelo}",
                                      (time.perf_counter() - inicio) * 1000)


class TranscriptorGroq:
    def __init__(self, api_key: str, modelo: str):
        self.api_key, self.modelo = api_key, modelo
        self.descripcion = f"Groq {modelo} (API)"

    def transcribir(self, ruta_audio: str) -> ResultadoTranscripcion:
        if not self.api_key:  # se valida al usarlo para que la app arranque igual y muestre el error claro
            raise ConfiguracionIncompleta("TRANSCRIPCION_PROVIDER=groq requiere GROQ_API_KEY en .env.")
        import openai

        self._openai = openai
        self._cliente = openai.OpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1",
                                      max_retries=1)
        inicio = time.perf_counter()
        try:
            with open(ruta_audio, "rb") as f:
                r = self._cliente.with_options(timeout=60).audio.transcriptions.create(
                    model=self.modelo, file=f, language="es", prompt=VOCABULARIO_WHISPER,
                    temperature=0.0, response_format="verbose_json")
        except self._openai.APITimeoutError as e:
            raise TimeoutIA("La transcripción tardó demasiado. Reintente o use el modo texto.") from e
        except self._openai.BadRequestError as e:
            raise AudioInvalido(detalle={"error": str(e)[:200]}) from e
        except self._openai.APIError as e:
            raise ProveedorNoDisponible("El servicio de transcripción no está disponible. "
                                        "Use el modo texto o reintente.") from e
        texto = (r.text or "").strip()
        if not texto:
            raise AudioInvalido("No se detectó voz en el audio.")
        return ResultadoTranscripcion(texto, getattr(r, "duration", None), f"groq/{self.modelo}",
                                      (time.perf_counter() - inicio) * 1000)


class TranscriptorSimulado:
    descripcion = "simulado (tests)"
    TEXTO = ("Paciente consulta por visión borrosa de lejos. Agudeza visual sin corrección ojo derecho 20/40, "
             "ojo izquierdo 20/30. Presión intraocular de 15 en ojo derecho y 16 en ojo izquierdo.")

    def transcribir(self, ruta_audio: str) -> ResultadoTranscripcion:
        return ResultadoTranscripcion(self.TEXTO, 12.0, "simulado", 5.0)


def construir_transcriptor(config: Config) -> Transcriptor:
    if config.transcripcion_provider == "groq":
        return TranscriptorGroq(config.groq_api_key, config.whisper_groq_model)
    if config.transcripcion_provider == "mock":
        return TranscriptorSimulado()
    return TranscriptorLocal(config.whisper_model, config.whisper_compute_type)
