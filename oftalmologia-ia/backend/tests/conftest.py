import pytest


@pytest.fixture
def cliente():
    """API completa con SQLite en memoria, LLM simulado y Whisper simulado: sin red, sin llaves."""
    from fastapi.testclient import TestClient

    from app.config import Config
    from app.main import crear_app

    config = Config(database_url="sqlite://", llm_provider="mock", transcripcion_provider="mock",
                    permitir_simular_fallas=True)
    with TestClient(crear_app(config), raise_server_exceptions=False) as c:
        yield c
