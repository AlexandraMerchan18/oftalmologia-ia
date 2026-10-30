"""Conexión a la base de datos y modelos ORM (SQLAlchemy 2.0).

PostgreSQL en Docker (JSONB para historia/alertas); SQLite en memoria para los tests.
Las tablas se crean al arrancar (create_all). Para un MVP académico esto reemplaza a un
sistema de migraciones; en producción se usaría Alembic (ver docs/decisiones.md).
"""
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("oftalmologia.db")
JSONFlexible = JSON().with_variant(JSONB(), "postgresql")


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Consulta(Base):
    __tablename__ = "consultas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    paciente_ref: Mapped[str] = mapped_column(String(64), index=True)
    medico: Mapped[str] = mapped_column(String(120))
    estado: Mapped[str] = mapped_column(String(32), index=True, default="CREADA")
    # Pasos 1-2
    transcripcion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fuente_transcripcion: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # audio | texto
    duracion_audio_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Pasos 3-4
    borrador: Mapped[Optional[dict]] = mapped_column(JSONFlexible, nullable=True)
    alertas: Mapped[Optional[list]] = mapped_column(JSONFlexible, nullable=True)
    resumen_extraccion: Mapped[Optional[dict]] = mapped_column(JSONFlexible, nullable=True)
    # Pasos 5-6
    historia_final: Mapped[Optional[dict]] = mapped_column(JSONFlexible, nullable=True)
    campos_corregidos: Mapped[Optional[list]] = mapped_column(JSONFlexible, nullable=True)
    revisado_por: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    revisado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Pasos 7-8
    explicacion_borrador: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explicacion_metodo: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    explicacion_final: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    aprobado_por: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    aprobado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)

    trazas: Mapped[list["Traza"]] = relationship(back_populates="consulta", cascade="all, delete-orphan",
                                                 order_by="Traza.id")


class Traza(Base):
    __tablename__ = "trazas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consulta_id: Mapped[str] = mapped_column(ForeignKey("consultas.id"), index=True)
    paso: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(80))
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detalle: Mapped[Optional[dict]] = mapped_column(JSONFlexible, nullable=True)
    latencia_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tokens_entrada: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_salida: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    costo_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    consulta: Mapped[Consulta] = relationship(back_populates="trazas")


def crear_motor(url: str) -> Engine:
    if url.startswith("sqlite"):
        argumentos: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            argumentos["poolclass"] = StaticPool  # una sola conexión compartida: la BD en memoria persiste
        return create_engine(url, **argumentos)
    return create_engine(url, pool_pre_ping=True)


def inicializar_bd(motor: Engine, intentos: int = 10) -> None:
    """Crea las tablas. Reintenta porque Postgres puede tardar unos segundos en aceptar conexiones."""
    for intento in range(1, intentos + 1):
        try:
            with motor.connect() as conexion:
                conexion.execute(text("SELECT 1"))
            Base.metadata.create_all(motor)
            return
        except Exception as e:  # noqa: BLE001 - se reintenta cualquier error de conexión
            if intento == intentos:
                raise
            logger.warning("Base de datos no disponible (intento %s/%s): %s", intento, intentos, type(e).__name__)
            time.sleep(2)
