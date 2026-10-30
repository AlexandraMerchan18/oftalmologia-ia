"""Extractor determinista de AV y PIO: lo más crítico del sistema (números + lateralidad)."""
import pytest

from app.clinica.mediciones import extraer_mediciones


def valores(texto):
    r = extraer_mediciones(texto)
    return {(m.tipo, m.ojo, m.correccion): m.valor for m in r.mediciones}, r.ambiguedades


@pytest.mark.parametrize("texto, esperado", [
    # Caso canónico: ojo antes del valor, sc y cc
    ("Agudeza visual sin corrección ojo derecho 20/40, ojo izquierdo 20/30; con corrección ojo derecho 20/20 "
     "y ojo izquierdo 20/25.",
     {("AV", "OD", "sc"): "20/40", ("AV", "OI", "sc"): "20/30",
      ("AV", "OD", "cc"): "20/20", ("AV", "OI", "cc"): "20/25"}),
    # Valor antes del ojo
    ("Presión intraocular de 15 en ojo derecho y 17 en ojo izquierdo.",
     {("PIO", "OD", None): "15", ("PIO", "OI", None): "17"}),
    # Ojo dictado ANTES de la palabra clave (requiere mirar hacia atrás en la oración)
    ("En ojo izquierdo la presión intraocular es de 14 y en ojo derecho de 16 milímetros de mercurio.",
     {("PIO", "OI", None): "14", ("PIO", "OD", None): "16"}),
    # Abreviaturas y el error típico de Whisper "2040"
    ("PIO OD 14 OI 16 mmHg. AV OD 2040 OI 20 30.",
     {("PIO", "OD", None): "14", ("PIO", "OI", None): "16", ("AV", "OD", "sc"): "20/40", ("AV", "OI", "sc"): "20/30"}),
    # Ambos ojos y corrección dictada al final
    ("Agudeza visual de 20/20 en ambos ojos con corrección. PIO de 16 en ambos ojos.",
     {("AV", "OD", "cc"): "20/20", ("AV", "OI", "cc"): "20/20", ("PIO", "OD", None): "16", ("PIO", "OI", None): "16"}),
    # Números en palabras
    ("En ojo derecho la presión intraocular es de dieciocho y en ojo izquierdo de veintidós.",
     {("PIO", "OD", None): "18", ("PIO", "OI", None): "22"}),
    ("Agudeza visual ojo derecho cuenta dedos a un metro, ojo izquierdo veinte cuarenta.",
     {("AV", "OD", "sc"): "cuenta dedos a un metro", ("AV", "OI", "sc"): "20/40"}),
])
def test_extrae_valor_y_ojo_correctos(texto, esperado):
    obtenidos, ambiguedades = valores(texto)
    assert obtenidos == esperado
    assert ambiguedades == []


def test_no_confunde_presion_arterial_ni_tiempos_con_pio():
    obtenidos, ambiguedades = valores(
        "Paciente de 65 años con visión borrosa en ojo derecho hace 3 meses. Presión arterial 120/80.")
    assert obtenidos == {} and ambiguedades == []


def test_sin_ojo_dictado_genera_ambiguedad_y_no_asigna():
    obtenidos, ambiguedades = valores("La presión es 15 y 17.")
    assert obtenidos == {}
    assert len(ambiguedades) == 1 and "ojo" in ambiguedades[0].motivo


def test_dos_lecturas_posibles_se_marca_ambiguo_en_vez_de_adivinar():
    # "PIO 15, ojo izquierdo..." admite 15->OD (contexto previo) y 15->OI (ojo siguiente)
    obtenidos, ambiguedades = valores(
        "Ojo derecho agudeza visual 20/40, PIO 15, ojo izquierdo agudeza visual 20/30, PIO 17.")
    assert ("PIO", "OD", None) not in obtenidos
    assert obtenidos[("AV", "OD", "sc")] == "20/40" and obtenidos[("AV", "OI", "sc")] == "20/30"
    assert any(a.tipo == "PIO" for a in ambiguedades)


def test_valores_contradictorios_para_el_mismo_ojo_se_anulan():
    obtenidos, ambiguedades = valores("PIO ojo derecho 15. Más tarde, presión intraocular ojo derecho 19.")
    assert ("PIO", "OD", None) not in obtenidos
    assert "dos valores distintos" in ambiguedades[0].motivo


def test_la_evidencia_es_una_cita_literal_del_texto_original():
    texto = "Presión Intraocular de 15 en Ojo Derecho y 17 en Ojo Izquierdo."
    r = extraer_mediciones(texto)
    for m in r.mediciones:
        assert m.evidencia in texto  # conserva mayúsculas/tildes del original


def test_correccion_no_especificada_queda_anotada():
    r = extraer_mediciones("AV OD 20/40 OI 20/30.")
    assert all("no especificada" in " ".join(m.notas) for m in r.mediciones)
