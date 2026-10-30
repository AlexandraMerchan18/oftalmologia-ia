"""Paso 7: la explicación al paciente nunca agrega diagnósticos ni cifras."""
from app.clinica.guardas import AVISO_PACIENTE, violaciones_explicacion
from app.esquemas import HistoriaClinica
from app.ia.explicacion import generar_explicacion, texto_de_historia
from app.ia.proveedores import RespuestaLLM
from app.ia.simulado import ProveedorSimulado

HISTORIA = HistoriaClinica.model_validate({
    "pio": {"od": {"valor_mmhg": 18, "evidencia": "18 en ojo derecho"},
            "oi": {"valor_mmhg": 24, "evidencia": "24 en ojo izquierdo"}},
    "impresion_diagnostica": {"valor": "sospecha de glaucoma en ojo izquierdo", "evidencia": "sospecha de glaucoma"},
    "plan": {"valor": "campimetría y control en un mes", "evidencia": "campimetría y control en un mes"},
})
BASE = texto_de_historia(HISTORIA)


class ProveedorFijo:
    nombre, modelo, estilo_esquema = "fijo", "fijo", "openai"

    def __init__(self, *textos):
        self.textos = list(textos)

    def completar(self, mensajes, herramientas, max_tokens, timeout_s):
        return RespuestaLLM(self.textos.pop(0), [], 50, 50, 1.0, "stop")

    def costo_usd(self, a, b):
        return 0.0


def test_explicacion_fiel_no_tiene_violaciones():
    texto = ("Hoy revisamos la presión dentro de sus ojos: 18 mmHg en el derecho y 24 mmHg en el izquierdo. "
             "Su médico anotó una sospecha de glaucoma en el ojo izquierdo. Le harán una campimetría.")
    assert violaciones_explicacion(texto, BASE) == []


def test_detecta_diagnostico_que_el_medico_no_dicto():
    v = violaciones_explicacion("Usted tiene glaucoma y además catarata.", BASE)
    assert any("catarata" in x for x in v)


def test_detecta_cifras_inventadas_y_frases_prohibidas():
    v = violaciones_explicacion("Su presión de 30 mmHg no es nada grave.", BASE)
    assert any("30" in x for x in v) and any("no permitida" in x for x in v)


def test_si_el_llm_viola_dos_veces_se_usa_la_plantilla_segura():
    r = generar_explicacion(HISTORIA, ProveedorFijo("Usted tiene catarata.", "Tiene retinopatía."))
    assert r.metodo == "plantilla"
    assert violaciones_explicacion(r.texto, BASE) == []
    assert r.aviso == AVISO_PACIENTE


def test_si_el_llm_corrige_en_el_segundo_intento_se_acepta():
    r = generar_explicacion(HISTORIA, ProveedorFijo("Usted tiene catarata.", "Su médico revisó sus ojos."))
    assert r.metodo == "llm_corregida" and r.texto == "Su médico revisó sus ojos."


def test_proveedor_simulado_produce_explicacion_segura():
    r = generar_explicacion(HISTORIA, ProveedorSimulado())
    assert r.metodo == "llm" and "glaucoma" in r.texto
