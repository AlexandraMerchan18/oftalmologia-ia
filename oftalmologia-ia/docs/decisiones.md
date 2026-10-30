# Registro de decisiones — Oftalmología + IA (MVP, Momento 2)

Documento único de arquitectura, datos y línea base. Cada decisión dice **qué** se eligió, **por qué** y
**qué se descartó**. Está escrito para defenderse en la sustentación: cualquier integrante debe poder explicar
cada fila.

---

## 1. Qué hace el sistema y dónde interviene la IA

El oftalmólogo dicta la consulta; el sistema produce una historia clínica estructurada y una explicación para
el paciente. **La IA documenta y explica; nunca diagnostica.** La impresión diagnóstica solo puede contener lo
que el médico dictó, y eso se verifica en código.

| Paso | Qué ocurre | Quién actúa | Dónde está en el código |
|---|---|---|---|
| 1. Dictado | Grabación en el navegador (MediaRecorder), archivo o texto | Médico | `frontend/src/componentes/PasoDictado.tsx` |
| 2. Transcripción | Whisper (faster-whisper local o Groq) | **IA** | `backend/app/ia/transcripcion.py` |
| 3. Extracción | Agente LLM con herramientas → JSON | **IA** + código | `backend/app/ia/agente.py`, `herramientas.py` |
| 4. Borrador | Verificador determinista genera alertas | Código | `backend/app/clinica/verificador.py` |
| 5. Revisión médica | Pantalla obligatoria; alertas bloqueantes | Médico | `PasoRevision.tsx`, `servicios.py::guardar_revision` |
| 6. Guardado | PostgreSQL; la historia queda inmutable | Código | `servicios.py`, `estados.py` |
| 7. Explicación | LLM redacta + guarda de seguridad | **IA** + código | `backend/app/ia/explicacion.py`, `clinica/guardas.py` |
| 8. Aprobación final | El médico edita y aprueba | Médico | `PasoExplicacion.tsx`, `servicios.py::aprobar` |

**Frontera exacta del modelo:** el LLM solo (a) ubica en campos lo dictado y (b) redacta en lenguaje sencillo.
Todo lo demás es determinista: orden de pasos (máquina de estados), extracción de AV/PIO, verificación de citas,
números y lateralidad, guarda anti-diagnóstico, validación de esquema, bloqueo de guardado sin revisión,
persistencia y trazas.

---

## 2. Arquitectura y patrón de integración

```
 Navegador (React)                 nginx (frontend:80)            FastAPI (backend:8000)               PostgreSQL 16
 ┌──────────────────┐  /api/*     ┌───────────────┐  proxy       ┌─────────────────────────────┐      ┌─────────────┐
 │ Dictado (mic)    │────────────▶│ estáticos +   │─────────────▶│ rutas → ServicioConsultas   │─────▶│ consultas   │
 │ Revisión         │◀────────────│ proxy /api    │◀─────────────│  ├ Whisper (faster-whisper) │◀─────│ trazas      │
 │ Panel de trazas  │  polling    └───────────────┘              │  ├ Agente (bucle + 4 límites)│      └─────────────┘
 └──────────────────┘  1,5 s                                      │  │   └ ProveedorLLM ────────┼────▶ Groq / Gemini / OpenAI
                                                                  │  ├ Extractor AV/PIO (reglas) │
                                                                  │  └ Verificador + guardas     │
                                                                  └─────────────────────────────┘
```

**Patrón: in-request síncrono + trazas persistidas consultadas por polling.**

- Cada paso con IA es una petición HTTP que responde cuando termina (Whisper ~5–20 s en CPU, agente ~2–8 s).
- Mientras el agente trabaja, cada evento (llamada LLM, herramienta, límite, error) se **confirma en la BD al
  instante**; el panel de trazas lo lee cada 1,5 s. Así se ve el agente "pensar" en vivo sin SSE.
- **Descartado SSE (streaming):** lo que el médico necesita es el borrador completo y validado, no tokens
  parciales; un JSON a medio generar no se puede validar ni mostrar. SSE añadía complejidad de reconexión sin valor.
- **Descartado colas (Celery/Redis):** el flujo es humano-en-el-bucle y de baja concurrencia (un médico, una
  consulta); las operaciones duran segundos y los límites del agente acotan la duración máxima (60 s).
  Una cola agregaría dos servicios más y un estado "pendiente" que complicaría la revisión obligatoria.
  Si el volumen creciera (transcripción de audios largos), la transcripción sería lo primero en ir a una cola.

---

## 3. Stack elegido y alternativas descartadas

| Capa | Elegido | Por qué | Descartado y razón técnica |
|---|---|---|---|
| Backend | **Python 3.11 + FastAPI** | Whisper y los SDK de LLM son nativos de Python; Pydantic valida el JSON del LLM con el mismo modelo que valida la API; OpenAPI/Swagger gratis (`/docs`) para el evaluador | **Node/Express**: Whisper local requiere binarios o un servicio Python aparte. **Django**: ORM/admin/plantillas que no se usan, más peso. **Flask**: sin validación ni documentación automática; habría que reimplementar lo que da Pydantic |
| Frontend | **React 18 + Vite + TypeScript** | La revisión obligatoria es un formulario con mucho estado (alertas resueltas, campo en foco, resaltado de citas): React lo maneja bien; TS replica los contratos del backend | **Streamlit/Gradio**: no permiten controlar el flujo de revisión ni el bloqueo del botón; rehacen la página en cada interacción. **Next.js**: SSR y servidor Node innecesarios para una SPA detrás de nginx. **Angular**: curva y boilerplate mayores para 4 pantallas |
| Transcripción | **faster-whisper `small` int8 (CPU)** + opción Groq | Implementación CTranslate2 de Whisper: ~4× más rápida y con menos RAM que la original en CPU; el audio no sale del equipo (dato de salud). `initial_prompt` con vocabulario oftalmológico sesga a "20/40", "OD", "mmHg". `vad_filter` recorta silencios | **openai-whisper**: arrastra PyTorch (~2 GB de imagen) y es más lento en CPU. **whisper.cpp**: bindings de Python menos maduros. **Solo API en la nube**: rápida, pero el audio del paciente sale a un tercero; queda como opción (`TRANSCRIPCION_PROVIDER=groq`) |
| LLM | **Groq · `openai/gpt-oss-120b`** (por defecto) | Latencia muy baja (LPU), US$0,15/0,60 por M tokens, 131k de contexto, *tool calling* compatible con OpenAI y `reasoning_effort=low` | **Llama 3.3 70B en Groq**: era la opción inicial, pero en 2026 pasó a nivel Enterprise (sin autoservicio); cambiarlo fue una línea de configuración gracias a la capa de proveedor. **Gemini 2.5 Flash**: soportado (`LLM_PROVIDER=gemini`), pero su dialecto de JSON Schema difiere (sin `additionalProperties`, `nullable`) y el *thinking* sube la latencia. **GPT-4o-mini**: soportado; similar en costo, mayor latencia |
| Orquestación del agente | **Bucle propio (~150 líneas)** | Los 4 límites, el registro de trazas y la recuperación de errores quedan explícitos y explicables línea por línea | **LangChain / LlamaIndex**: abstracciones que ocultan el bucle, los reintentos y los límites; trazas menos legibles; dependencia pesada para 3 herramientas |
| Salida estructurada | **Tool calling + Pydantic `extra="forbid"`** | El esquema viaja como parámetros de `enviar_borrador`; si el modelo se equivoca, recibe los errores exactos de Pydantic y corrige | **JSON mode / texto libre + regex**: no da retroalimentación por campo; errores silenciosos |
| Base de datos | **PostgreSQL 16 (JSONB)** | Concurrencia real, JSONB para historia/alertas/trazas, la rúbrica pide BD declarada en Compose | **SQLite**: se usa solo en tests (en memoria). **MongoDB**: la auditoría (consulta → trazas) es relacional |
| ORM / esquema | **SQLAlchemy 2.0 + `create_all` al arrancar** | Cero pasos manuales para el evaluador | **Alembic**: correcto en producción; para un MVP con un solo esquema añadía un paso más sin beneficio. Es el primer cambio si el esquema evoluciona |
| Servidor web | **nginx** | Sirve el build y hace proxy de `/api` (mismo origen: sin CORS) con `proxy_read_timeout` de 180 s | Servir estáticos desde FastAPI: mezcla responsabilidades y no da tiempos de espera por ruta |

---

## 4. El agente

### 4.1 Herramientas propias (descripciones escritas como prompts)

| Herramienta | Qué hace | Por qué existe |
|---|---|---|
| `obtener_mediciones_oculares` | Devuelve AV y PIO del extractor determinista, con ojo, corrección, cita y ambigüedades | Los números y la lateralidad son lo más peligroso de delegar al LLM |
| `verificar_cita` | Dice si un fragmento está literalmente en el dictado y sugiere la oración más parecida | Permite al modelo autocorregir sus `evidencia` antes de entregar |
| `enviar_borrador` | Valida contra el esquema y el verificador; rechaza con errores precisos o acepta | Convierte la salida en un contrato verificable con retroalimentación |

**Iteración de las descripciones** (registrar aquí cada cambio con su efecto en `./run.sh eval`):

| Versión | Cambio | Motivo |
|---|---|---|
| v1 | `enviar_borrador` sin instrucciones de corrección | El modelo podía repetir el mismo error al ser rechazado |
| v2 | Se agregó "corrige exactamente los errores indicados y vuelve a llamarla"; respuesta con `errores` por campo | Reducir iteraciones desperdiciadas |
| v3 (actual) | `obtener_mediciones_oculares` dice "ÚSALA SIEMPRE… NO adivines el ojo"; `verificar_cita` dice "no la uses para cada campo" | Evitar lateralidad inventada y llamadas innecesarias (tokens) |
| _pendiente_ | _Registrar resultado de la corrida real con Groq_ | |

### 4.2 Los cuatro límites activos (`backend/app/ia/agente.py`)

| Límite | Valor por defecto | Qué pasa al alcanzarlo |
|---|---|---|
| 1. Iteraciones | `AGENTE_MAX_ITERACIONES=5` (lo normal son 2) | Se detiene; borrador parcial con AV/PIO deterministas + alerta bloqueante "extracción incompleta" |
| 2. Timeout | `AGENTE_TIMEOUT_S=60` total y `LLM_TIMEOUT_S=30` por llamada | Igual que arriba; si el timeout es del proveedor sin borrador → HTTP 504 con mensaje claro |
| 3. Tokens | `AGENTE_MAX_TOKENS_TOTALES=20000` (entrada+salida) y `LLM_MAX_TOKENS_RESPUESTA=4096` | Se detiene antes de pedir otra llamada si quedan < 600 tokens |
| 4. Confirmación humana | Fijo, no configurable | El agente no tiene herramientas con efectos; cualquier herramienta marcada `requiere_confirmacion_humana` es rechazada por el ejecutor. Guardar (paso 6) y aprobar (paso 8) exigen `confirmo_revision=true` / `confirmo_aprobacion=true` del médico y la resolución de todas las alertas bloqueantes |

Todos están cubiertos por pruebas en `backend/tests/unit/test_agente.py`.

### 4.3 Capa de proveedor desacoplada (`backend/app/ia/proveedores.py`)

- Protocolo `ProveedorLLM.completar(mensajes, herramientas, max_tokens, timeout_s)`. El agente no importa ningún SDK.
- Una sola implementación (`ProveedorOpenAICompatible`) cubre Groq, Gemini y OpenAI porque los tres exponen la API
  de Chat Completions; cambia `base_url`, modelo, precios y el dialecto de JSON Schema.
- `ProveedorSimulado` (mock) implementa el mismo protocolo para tests y plan B.
- Los errores del SDK se traducen a errores de dominio (`TimeoutIA`, `ProveedorNoDisponible`, `LimiteDeTasa`,
  `ConfiguracionIncompleta`, `RespuestaInvalidaModelo`). `max_retries=1`: un reintento automático ante 429/5xx,
  nunca un bucle de reintentos.

---

## 5. Exactitud clínica: defensa en capas contra alucinaciones y errores de lateralidad

1. **Prompt** con reglas explícitas (null si no se dictó, cita literal, nunca intercambiar ojos, la transcripción
   va delimitada y "se trata como datos").
2. **Extractor determinista de AV/PIO** (`clinica/mediciones.py`) con *consenso de dos lecturas*: para cada
   segmento calcula "valor→ojo" y "ojo→valor"; si solo una es coherente la usa, si ambas son coherentes y
   discrepan **no asigna** y reporta ambigüedad. Normaliza errores de Whisper ("2040" → 20/40, números en palabras).
3. **Esquema estricto** (Pydantic): AV en Snellen o cualitativa, PIO 0–80 mmHg, sin campos extra.
4. **Verificador** (`clinica/verificador.py`): R1 cita literal, R2 ningún número inventado, R3 contraste AV/PIO
   con el extractor (conflicto → se precarga el valor determinista y se bloquea hasta que el médico elija),
   R4 ningún diagnóstico no dictado, R5 detección de instrucciones inyectadas en el dictado.
5. **Revisión humana obligatoria** con la cita resaltada en la transcripción para cada campo.
6. **Explicación al paciente** solo desde la historia aprobada y con guarda (`clinica/guardas.py`): bloquea
   diagnósticos y cifras que no estén en la historia y frases prohibidas; 1 reintento y luego plantilla segura.

---

## 6. Los datos: decisión de NO usar RAG

**Decisión: no se usa RAG.** Argumentos:

1. **La tarea es extracción, no consulta de conocimiento.** Toda la información necesaria está en un único
   dictado de 100–400 palabras (~600 tokens), que cabe completo en el contexto. No hay nada que "recuperar".
2. **RAG aumentaría el riesgo central del producto.** Inyectar guías clínicas o historias previas en el contexto
   le da al modelo material para "completar" o sugerir diagnósticos, justo lo que el producto prohíbe
   ("la IA nunca diagnostica"). Cada dato de la historia debe trazarse a una frase del dictado; un fragmento
   recuperado rompería esa trazabilidad.
3. **Costo y operación.** Embeddings, una BD vectorial (pgvector) y su mantenimiento añadirían latencia, servicios
   y una nueva superficie de fallos sin mejorar ninguna métrica que nos importe (exactitud de AV/PIO, lateralidad).
4. **Dónde sí tendría sentido (trabajo futuro):** un buscador de historias anteriores del mismo paciente para
   que el *médico* compare evoluciones (no para que la IA infiera). Se mediría con precisión@k sobre consultas reales.

Los datos persistidos son mínimos: identificador seudonimizado (no el nombre), transcripción, borrador, historia
final, explicación y trazas. **El audio se borra apenas se transcribe** (traza `audio_conservado: false`).

---

## 7. Manejo elegante de fallos (sin stack traces visibles)

Todo error llega al frontend como `{"error": {"codigo", "mensaje", "detalle", "traza_id"}}`; el stack trace solo
queda en los logs del servidor, enlazado por `traza_id`.

| Fallo | Detección | Lo que ve el médico | Estado del trabajo | Demostración en vivo |
|---|---|---|---|---|
| **Timeout** del LLM | `openai.APITimeoutError` → `TimeoutIA` (504) | "El servicio de IA tardó demasiado… su dictado está guardado" | La consulta sigue en `TRANSCRITA`; reintentar funciona | Panel de trazas → "Timeout del LLM" → Armar fallo |
| **Caída de la API** | Conexión / 5xx → `ProveedorNoDisponible` (503) | "El proveedor de IA no está disponible…" | Igual | "Caída del proveedor" |
| **Validación** | Pydantic (422), alertas pendientes, falta confirmación, transición inválida (409) | Mensaje por campo ("agudeza visual: formato Snellen…") | Nada se guarda | Intentar guardar sin marcar alertas |
| 429 | `RateLimitError` → `LimiteDeTasa` (429) | "Demasiadas solicitudes, espere unos segundos" | Igual | "Error 429" |
| JSON roto del modelo | `json.loads` falla / 400 `tool_use_failed` | Nada: el agente lo corrige en la siguiente iteración | Continúa | "JSON roto del modelo" |
| Falta llave | `ConfiguracionIncompleta` (503) | "Falta GROQ_API_KEY en .env…" | La app arranca igual | Dejar la llave vacía |
| Sin conexión con el backend | `fetch` falla en el navegador | "No hay conexión con el servidor. Verifique ./run.sh" | — | Detener el backend |

---

## 8. Medición y trazas

**Suite de casos dorados:** `eval/casos_dorados.json` — 14 dictados ficticios en 6 categorías (lateralidad,
errores de Whisper, formato, alucinación, ambigüedad, seguridad/inyección). Se ejecuta con `./run.sh eval`.

**Métricas** (`eval/run_eval.py`): exactitud de las 6 casillas críticas por caso (AV sc/cc y PIO por ojo),
errores de lateralidad, casos con alucinación, sensibilidad de alertas en casos ambiguos, y medianas de
latencia, tokens y costo. Se usa **mediana** (no promedio) porque la latencia de APIs tiene colas largas.

### Línea base

**A. Proveedor simulado por reglas** — ejecutado el **2026-10-27 05:54** (`eval/resultados/2026-10-27_0554_mock.json`).
Sirve como piso de referencia y prueba de que la suite funciona; NO mide al LLM.

| Métrica (n = 14) | Valor |
|---|---|
| 1. Latencia de extracción (mediana) | 0,004 s (sin red) |
| 2. Costo por consulta (mediana) | US$ 0 (1.246 tokens simulados) |
| 3. Exactitud de campos críticos AV/PIO | 100 % (84/84) |
| 4. Errores de lateralidad / casos con alucinación | 0 / 0 |
| Sensibilidad de alertas en casos ambiguos | 4/4 (0 de 10 casos limpios con alerta bloqueante) |

> Advertencia metodológica: el extractor determinista se desarrolló junto con estos casos, así que el 100 %
> del simulador está sesgado a favor. Antes de la sustentación, un compañero que no escribió el extractor debe
> agregar 5 dictados nuevos (`c15`–`c19`) y volver a medir.

**B. Proveedor real — Groq `openai/gpt-oss-120b`** — _PENDIENTE: ejecutar `./run.sh eval -- --repeticiones 3`
con la llave del equipo y pegar aquí el bloque que imprime el script (incluye fecha)._

| Métrica (fecha, proveedor/modelo, n) | Valor |
|---|---|
| 1. Latencia de extracción (mediana) | _completar_ |
| 2. Costo por consulta (mediana) | _completar_ |
| 3. Exactitud de campos críticos AV/PIO | _completar_ |
| 4. Errores de lateralidad / casos con alucinación | _completar_ |

**Trazas visibles en vivo:** panel derecho de la app (cada llamada LLM con tokens, latencia y costo; cada
herramienta con argumentos y resultado; límites alcanzados; fallos en rojo) y `./run.sh logs` (JSON por evento).

---

## 9. Seguridad y privacidad

- Llaves solo en `.env` (excluido del ZIP y de git); `.env.example` sin valores reales.
- Identificador del paciente seudonimizado; el audio no se conserva.
- Con proveedor en la nube, **la transcripción sale a un tercero**: en la demo se usan solo dictados ficticios.
  Para uso real se requeriría un acuerdo de tratamiento de datos acorde a la Ley 1581 de 2012 (habeas data) y a
  la normativa de historia clínica, o un LLM desplegado localmente.
- El backend corre con un usuario sin privilegios dentro del contenedor.

---

## 10. Limitaciones conocidas

- Agudeza visual en notación decimal (0,5) o logMAR no se reconoce (solo Snellen y cualitativa).
- Agujero estenopeico, refracción y queratometría no tienen campo en este MVP.
- Whisper `small` en CPU tarda ~0,3–0,6× la duración del audio; dictados > 3 min conviene subirlos como archivo.
- La guarda de la explicación usa una lista cerrada de diagnósticos; un diagnóstico fuera de la lista no se detecta
  (mitigado por la aprobación final del médico).
- Sin autenticación de usuarios (fuera del alcance del MVP).

## 11. Retos reales y lecciones (para la sustentación)

1. **Modelo retirado del autoservicio:** Llama 3.3 70B pasó a Enterprise en Groq. La capa de proveedor hizo que
   el cambio a `gpt-oss-120b` fuera una línea en `config.py`.
2. **Whisper escribe "2040" en vez de "20/40"** y a veces números en palabras: se normaliza en el extractor y se
   anota en la evidencia ("normalizado desde '2040'").
3. **Lateralidad ambigua:** "Ojo derecho AV 20/40, PIO 15, ojo izquierdo…" admite dos lecturas para el 15.
   En vez de adivinar, el sistema lo marca y el médico decide (caso dorado `c10`).
4. **Contratos JSON rotos:** el agente recibe el error de parseo como resultado de herramienta y reintenta.
5. **Inyección de instrucciones:** la suite de evaluación mostró que un dictado con "ignora las instrucciones…"
   podía filtrarse a la impresión diagnóstica en el baseline por reglas; se agregó la regla R5 al verificador.
