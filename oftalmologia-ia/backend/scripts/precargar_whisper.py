"""Descarga el modelo de Whisper DURANTE el build de la imagen.

Así la primera transcripción en la demo no espera una descarga de ~460 MB (modelo "small").
Uso: python scripts/precargar_whisper.py small
"""
import sys

from faster_whisper import WhisperModel

modelo = sys.argv[1] if len(sys.argv) > 1 else "small"
print(f"Descargando y verificando faster-whisper '{modelo}' (int8, CPU)...", flush=True)
WhisperModel(modelo, device="cpu", compute_type="int8")
print("Modelo listo.", flush=True)
