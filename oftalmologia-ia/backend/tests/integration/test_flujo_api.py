"""Integración: los 8 pasos por HTTP y el manejo elegante de los 3 fallos (timeout, validación, caída)."""
import pytest

pytestmark = pytest.mark.integracion

DICTADO = ("Paciente consulta por visión borrosa de lejos. Agudeza visual sin corrección ojo derecho 20/40, "
           "ojo izquierdo 20/30. Presión intraocular de 15 en ojo derecho y 17 en ojo izquierdo. "
           "Fondo de ojo normal en ambos ojos. Impresión diagnóstica: miopía. Plan: control en un año.")


def nueva_consulta(cliente, texto=DICTADO):
    r = cliente.post("/api/consultas", json={"paciente_ref": "PAC-001", "medico": "Dra. Prueba"})
    assert r.status_code == 201
    cid = r.json()["id"]
    if texto:
        assert cliente.put(f"/api/consultas/{cid}/transcripcion", json={"texto": texto}).status_code == 200
    return cid


def assert_error_amigable(r, status, codigo):
    assert r.status_code == status, r.text
    cuerpo = r.json()["error"]
    assert cuerpo["codigo"] == codigo and cuerpo["mensaje"] and cuerpo["traza_id"]
    assert "Traceback" not in r.text and 'File "' not in r.text


def test_flujo_completo_de_los_8_pasos(cliente):
    cid = nueva_consulta(cliente)                                          # pasos 1-2 (modo texto)

    r = cliente.post(f"/api/consultas/{cid}/extraccion")                  # pasos 3-4
    assert r.status_code == 200
    consulta = r.json()
    assert consulta["estado"] == "BORRADOR"
    assert consulta["borrador"]["pio"]["od"]["valor_mmhg"] == 15
    assert consulta["borrador"]["agudeza_visual"]["oi"]["sin_correccion"]["valor"] == "20/30"
    assert consulta["resumen_extraccion"]["estado"] == "completo"

    historia = consulta["borrador"]
    historia["plan"]["valor"] = "control en un año con refracción"         # paso 5: el médico corrige
    bloqueantes = [a["id"] for a in consulta["alertas"] if a["bloqueante"]]
    r = cliente.post(f"/api/consultas/{cid}/revision", json={
        "historia": historia, "alertas_resueltas": bloqueantes, "medico": "Dra. Prueba", "confirmo_revision": True})
    assert r.status_code == 200, r.text                                   # paso 6
    assert r.json()["estado"] == "GUARDADA" and "plan.valor" in r.json()["campos_corregidos"]

    r = cliente.post(f"/api/consultas/{cid}/explicacion")                 # paso 7
    assert r.status_code == 200 and r.json()["explicacion_borrador"]

    r = cliente.post(f"/api/consultas/{cid}/aprobacion", json={            # paso 8
        "explicacion_final": r.json()["explicacion_borrador"], "medico": "Dra. Prueba", "confirmo_aprobacion": True})
    assert r.status_code == 200 and r.json()["estado"] == "APROBADA"
    assert "inteligencia artificial" in r.json()["explicacion_final"]

    trazas = cliente.get(f"/api/consultas/{cid}/trazas").json()
    pasos = {t["paso"] for t in trazas["trazas"]}
    assert {1, 2, 3, 4, 5, 6, 7, 8} <= pasos
    assert trazas["resumen"]["llamadas_llm"] >= 3


def test_audio_se_transcribe_y_no_se_conserva(cliente):
    cid = nueva_consulta(cliente, texto=None)
    r = cliente.post(f"/api/consultas/{cid}/audio",
                     files={"audio": ("dictado.webm", b"\x1aE\xdf\xa3" + b"0" * 2000, "audio/webm")})
    assert r.status_code == 200 and r.json()["estado"] == "TRANSCRITA"
    traza = [t for t in cliente.get(f"/api/consultas/{cid}/trazas").json()["trazas"] if t["tipo"] == "whisper"][0]
    assert traza["detalle"]["audio_conservado"] is False


def test_audio_con_formato_no_soportado(cliente):
    cid = nueva_consulta(cliente, texto=None)
    r = cliente.post(f"/api/consultas/{cid}/audio", files={"audio": ("notas.pdf", b"%PDF", "application/pdf")})
    assert_error_amigable(r, 400, "audio_invalido")


# ------------------------------------------------------------------ Fallo 1: TIMEOUT
def test_timeout_del_llm_responde_504_amigable_y_conserva_el_dictado(cliente):
    cid = nueva_consulta(cliente)
    cliente.post("/api/demo/falla", json={"tipo": "timeout"})
    r = cliente.post(f"/api/consultas/{cid}/extraccion")
    assert_error_amigable(r, 504, "ia_timeout")
    consulta = cliente.get(f"/api/consultas/{cid}").json()
    assert consulta["estado"] == "TRANSCRITA" and consulta["transcripcion"] == DICTADO
    trazas = cliente.get(f"/api/consultas/{cid}/trazas").json()["trazas"]
    assert any(t["tipo"] == "error" and not t["ok"] for t in trazas)
    # reintento exitoso
    assert cliente.post(f"/api/consultas/{cid}/extraccion").status_code == 200


# ------------------------------------------------------------------ Fallo 2: CAÍDA DE LA API
def test_caida_del_proveedor_responde_503_amigable(cliente):
    cid = nueva_consulta(cliente)
    cliente.post("/api/demo/falla", json={"tipo": "caida"})
    assert_error_amigable(cliente.post(f"/api/consultas/{cid}/extraccion"), 503, "ia_no_disponible")


def test_429_del_proveedor_responde_amigable(cliente):
    cid = nueva_consulta(cliente)
    cliente.post("/api/demo/falla", json={"tipo": "limite_tasa"})
    assert_error_amigable(cliente.post(f"/api/consultas/{cid}/extraccion"), 429, "ia_limite_tasa")


def test_json_roto_se_recupera_sin_error_visible(cliente):
    cid = nueva_consulta(cliente)
    cliente.post("/api/demo/falla", json={"tipo": "json_roto"})
    r = cliente.post(f"/api/consultas/{cid}/extraccion")
    assert r.status_code == 200 and r.json()["resumen_extraccion"]["estado"] == "completo"


# ------------------------------------------------------------------ Fallo 3: VALIDACIÓN
def test_guardar_sin_confirmar_revision_es_rechazado(cliente):
    cid = nueva_consulta(cliente)
    borrador = cliente.post(f"/api/consultas/{cid}/extraccion").json()["borrador"]
    r = cliente.post(f"/api/consultas/{cid}/revision", json={
        "historia": borrador, "alertas_resueltas": [], "medico": "Dra. Prueba", "confirmo_revision": False})
    assert_error_amigable(r, 422, "validacion")


def test_guardar_con_alertas_bloqueantes_sin_revisar_es_rechazado(cliente):
    dictado_ambiguo = "Paciente a control. La presión intraocular es 15 y 17. Plan: control anual."
    cid = nueva_consulta(cliente, dictado_ambiguo)
    consulta = cliente.post(f"/api/consultas/{cid}/extraccion").json()
    assert any(a["tipo"] == "ambigua" and a["bloqueante"] for a in consulta["alertas"])
    r = cliente.post(f"/api/consultas/{cid}/revision", json={
        "historia": consulta["borrador"], "alertas_resueltas": [], "medico": "Dra. Prueba", "confirmo_revision": True})
    assert_error_amigable(r, 422, "validacion")
    assert r.json()["error"]["detalle"]["pendientes"]


def test_historia_con_agudeza_invalida_es_rechazada_con_mensaje_claro(cliente):
    cid = nueva_consulta(cliente)
    borrador = cliente.post(f"/api/consultas/{cid}/extraccion").json()["borrador"]
    borrador["agudeza_visual"]["od"]["sin_correccion"]["valor"] = "bastante buena"
    r = cliente.post(f"/api/consultas/{cid}/revision", json={
        "historia": borrador, "alertas_resueltas": [], "medico": "Dra. Prueba", "confirmo_revision": True})
    assert_error_amigable(r, 422, "validacion")
    assert "Snellen" in r.json()["error"]["mensaje"]


def test_datos_de_entrada_invalidos(cliente):
    r = cliente.post("/api/consultas", json={"paciente_ref": "", "medico": "Dra. Prueba"})
    assert_error_amigable(r, 422, "validacion")


def test_no_se_puede_explicar_antes_de_la_revision_medica(cliente):
    cid = nueva_consulta(cliente)
    cliente.post(f"/api/consultas/{cid}/extraccion")
    assert_error_amigable(cliente.post(f"/api/consultas/{cid}/explicacion"), 409, "transicion_invalida")


def test_consulta_inexistente(cliente):
    assert_error_amigable(cliente.get("/api/consultas/no-existe"), 404, "no_encontrado")


def test_salud_declara_proveedor_y_limites(cliente):
    salud = cliente.get("/api/salud").json()
    assert salud["base_datos"] == "ok" and salud["llm"]["proveedor"] == "mock"
    assert salud["limites_agente"]["max_iteraciones"] >= 1
