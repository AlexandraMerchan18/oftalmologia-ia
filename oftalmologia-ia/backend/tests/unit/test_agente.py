"""Bucle del agente: los CUATRO límites activos y la recuperación ante contratos JSON rotos."""
import time

import pytest

from app.errores import ProveedorNoDisponible
from app.ia import herramientas as mod_herramientas
from app.ia.agente import LimitesAgente, ejecutar_agente
from app.ia.herramientas import ContextoAgente, Herramienta, ejecutar_herramienta
from app.ia.proveedores import InyectorFallas, LlamadaHerramienta, ProveedorConFallas, RespuestaLLM
from app.ia.simulado import ProveedorSimulado

DICTADO = ("Consulta por visión borrosa. Agudeza visual sin corrección ojo derecho 20/40, ojo izquierdo 20/30. "
           "Presión intraocular de 15 en ojo derecho y 17 en ojo izquierdo. Plan: control en un mes.")


class ProveedorTerco:
    """Nunca llama herramientas: obliga al agente a cortar por iteraciones."""
    nombre, modelo, estilo_esquema = "terco", "terco", "openai"

    def __init__(self, tokens=100, espera_s=0.0):
        self.llamadas, self.tokens, self.espera_s = 0, tokens, espera_s

    def completar(self, mensajes, herramientas, max_tokens, timeout_s):
        self.llamadas += 1
        time.sleep(self.espera_s)
        return RespuestaLLM("No sé usar herramientas.", [], self.tokens, self.tokens, 1.0, "stop")

    def costo_usd(self, a, b):
        return 0.0


def test_proveedor_simulado_completa_en_dos_iteraciones():
    eventos = []
    r = ejecutar_agente(DICTADO, ProveedorSimulado(), LimitesAgente(), eventos.append)
    assert r.estado == "completo" and r.iteraciones == 2
    assert r.herramientas_usadas == ["obtener_mediciones_oculares", "enviar_borrador"]
    assert r.historia.pio.od.valor_mmhg == 15 and r.historia.agudeza_visual.oi.sin_correccion.valor == "20/30"
    assert any(e.tipo == "llm" for e in eventos) and any(e.tipo == "herramienta" for e in eventos)


def test_limite_1_iteraciones_maximas():
    proveedor = ProveedorTerco()
    r = ejecutar_agente(DICTADO, proveedor, LimitesAgente(max_iteraciones=3))
    assert proveedor.llamadas == 3
    assert r.estado == "parcial" and r.motivo_parada == "max_iteraciones"
    # degradación elegante: borrador parcial con AV/PIO deterministas + alerta bloqueante
    assert r.alertas[0].tipo == "extraccion_parcial" and r.alertas[0].bloqueante
    assert r.historia.pio.oi.valor_mmhg == 17


def test_limite_2_timeout_total_del_bucle():
    proveedor = ProveedorTerco(espera_s=0.6)
    r = ejecutar_agente(DICTADO, proveedor, LimitesAgente(max_iteraciones=50, timeout_s=1.5))
    assert r.motivo_parada == "timeout_agente"
    assert proveedor.llamadas <= 2


def test_limite_3_presupuesto_de_tokens():
    proveedor = ProveedorTerco(tokens=3000)
    r = ejecutar_agente(DICTADO, proveedor, LimitesAgente(max_iteraciones=50, max_tokens_totales=10000))
    assert r.motivo_parada == "presupuesto_tokens"
    assert r.tokens_entrada + r.tokens_salida <= 12000


def test_limite_4_herramienta_que_requiere_confirmacion_humana_no_se_ejecuta():
    ejecutada = []
    peligrosa = Herramienta("guardar_historia", "Guarda en la BD", {"type": "object", "properties": {}},
                            ejecutar=lambda ctx, args: ejecutada.append(True) or {"ok": True},
                            requiere_confirmacion_humana=True)
    ctx = ContextoAgente(DICTADO, mediciones=None)  # type: ignore[arg-type]
    resultado = ejecutar_herramienta({"guardar_historia": peligrosa}, "guardar_historia", "{}", ctx)
    assert ejecutada == [] and "confirmación humana" in resultado["error"]


def test_el_agente_no_expone_herramientas_con_efectos():
    herramientas = mod_herramientas.construir_herramientas()
    assert not any(h.requiere_confirmacion_humana for h in herramientas.values())
    assert set(herramientas) == {"obtener_mediciones_oculares", "verificar_cita", "enviar_borrador"}


def test_se_recupera_de_json_roto():
    inyector = InyectorFallas(habilitado=True)
    inyector.armar("json_roto")
    eventos = []
    r = ejecutar_agente(DICTADO, ProveedorConFallas(ProveedorSimulado(), inyector), LimitesAgente(), eventos.append)
    assert r.estado == "completo"
    assert any(e.tipo == "herramienta" and not e.ok and "JSON" in str(e.detalle) for e in eventos)


def test_caida_del_proveedor_sin_borrador_se_propaga_como_error_de_dominio():
    inyector = InyectorFallas(habilitado=True)
    inyector.armar("caida")
    with pytest.raises(ProveedorNoDisponible):
        ejecutar_agente(DICTADO, ProveedorConFallas(ProveedorSimulado(), inyector), LimitesAgente())


def test_herramienta_inexistente_devuelve_error_al_modelo():
    ctx = ContextoAgente(DICTADO, mediciones=None)  # type: ignore[arg-type]
    r = ejecutar_herramienta(mod_herramientas.construir_herramientas(), "borrar_todo", "{}", ctx)
    assert "no existe" in r["error"]


def test_esquema_para_gemini_no_usa_tipos_lista_ni_additional_properties():
    import json
    texto = json.dumps(mod_herramientas.esquema_para_proveedor("gemini"))
    assert "$ref" not in texto and "additionalProperties" not in texto and '"nullable": true' in texto
    texto_openai = json.dumps(mod_herramientas.esquema_para_proveedor("openai"))
    assert '["string", "null"]' in texto_openai


def test_enviar_borrador_rechaza_esquema_invalido_con_mensaje_util():
    from app.clinica.mediciones import extraer_mediciones
    ctx = ContextoAgente(DICTADO, extraer_mediciones(DICTADO))
    r = ejecutar_herramienta(mod_herramientas.construir_herramientas(), "enviar_borrador",
                             '{"agudeza_visual": {"od": {"sin_correccion": {"valor": "muy buena"}}}}', ctx)
    assert r["aceptado"] is False and any("Snellen" in e for e in r["errores_de_esquema"])


def test_llamada_sin_herramienta_recibe_recordatorio():
    class UnaVezTexto(ProveedorSimulado):
        def __init__(self):
            self.primera = True

        def completar(self, mensajes, herramientas, max_tokens, timeout_s):
            if self.primera:
                self.primera = False
                return RespuestaLLM("Aquí está la historia...", [], 10, 10, 1.0, "stop")
            return super().completar(mensajes, herramientas, max_tokens, timeout_s)

    r = ejecutar_agente(DICTADO, UnaVezTexto(), LimitesAgente())
    assert r.estado == "completo" and r.iteraciones == 3


def test_respuesta_llm_reinyecta_tool_calls_en_formato_openai():
    m = RespuestaLLM(None, [LlamadaHerramienta("x1", "verificar_cita", '{"cita": "a"}')]).como_mensaje()
    assert m["tool_calls"][0]["function"]["name"] == "verificar_cita"
