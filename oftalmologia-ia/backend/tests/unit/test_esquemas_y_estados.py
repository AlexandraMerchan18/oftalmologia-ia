import pytest
from pydantic import ValidationError

from app import estados
from app.errores import TransicionInvalida
from app.esquemas import Campo, CampoAV, CampoPIO, HistoriaClinica


@pytest.mark.parametrize("entrada, esperado", [("20/40", "20/40"), ("20 / 200", "20/200"),
                                               ("Cuenta dedos a 1 metro", "cuenta dedos a 1 metro"),
                                               ("", None), ("no dictado", None)])
def test_agudeza_visual_formatos_validos(entrada, esperado):
    assert CampoAV(valor=entrada).valor == esperado


@pytest.mark.parametrize("entrada", ["buena", "20/", "normal"])
def test_agudeza_visual_formato_invalido(entrada):
    with pytest.raises(ValidationError):
        CampoAV(valor=entrada)


def test_pio_acepta_texto_con_unidades_y_rechaza_rangos_imposibles():
    assert CampoPIO(valor_mmhg="15,5 mmHg").valor_mmhg == 15.5
    with pytest.raises(ValidationError):
        CampoPIO(valor_mmhg=150)


def test_vacios_se_normalizan_a_null():
    assert Campo(valor="  ", evidencia="N/A").valor is None


def test_campos_extra_se_rechazan():
    with pytest.raises(ValidationError):
        HistoriaClinica.model_validate({"diagnostico_sugerido_por_ia": {"valor": "x"}})


def test_flujo_de_estados_valido():
    e = estados.CREADA
    for accion in ("transcribir", "extraer", "guardar", "explicar", "aprobar"):
        e = estados.siguiente_estado(e, accion)
    assert e == estados.APROBADA


@pytest.mark.parametrize("estado, accion", [
    (estados.CREADA, "extraer"),            # no se extrae sin dictado
    (estados.TRANSCRITA, "guardar"),        # no se guarda sin borrador
    (estados.BORRADOR, "explicar"),         # no se explica sin revisión médica
    (estados.GUARDADA, "extraer"),          # la historia guardada es inmutable
    (estados.APROBADA, "aprobar"),
])
def test_transiciones_invalidas(estado, accion):
    with pytest.raises(TransicionInvalida):
        estados.siguiente_estado(estado, accion)
