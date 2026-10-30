# Oftalmología + IA — Historia clínica asistida por voz

MVP que convierte el **dictado de un oftalmólogo** en una **historia clínica estructurada** y en una
**explicación en lenguaje sencillo para el paciente**. La IA transcribe, organiza y redacta; **nunca diagnostica**.
Nada se guarda sin la revisión del médico.

```
 1 Dictado ─▶ 2 Transcripción ─▶ 3 Extracción ─▶ 4 Borrador ─▶ 5 Revisión ─▶ 6 Guardado ─▶ 7 Explicación ─▶ 8 Aprobación
   médico       IA (Whisper)       IA (LLM)        código        MÉDICO        código        IA (LLM)          MÉDICO
```

Este README es el **contrato de ingeniería**: siguiéndolo al pie de la letra, la aplicación debe quedar
funcionando en una máquina limpia. Las decisiones técnicas están en [`docs/decisiones.md`](docs/decisiones.md).

---

## 1. Qué necesita instalado

| Requisito | Versión | Cómo verificarlo |
|---|---|---|
| Docker Desktop (Windows / Mac) o Docker Engine (Linux) | 24 o superior | `docker --version` |
| Docker Compose **v2** (viene con Docker Desktop) | 2.20 o superior | `docker compose version` |
| Conexión a internet | Solo la primera vez (descarga imágenes, librerías y el modelo de Whisper) | — |
| Memoria / disco | 8 GB de RAM recomendados, 6 GB libres en disco | — |
| Puertos libres | `8080` (web) y `8000` (API) | — |

**No necesita** instalar Python, Node ni PostgreSQL: todo corre dentro de contenedores con versiones fijas
(Python 3.11, Node 20, PostgreSQL 16, nginx 1.27).

> En Windows, abra **Docker Desktop** y espere a que diga *"Engine running"* antes de continuar.

---

## 2. Levantar la aplicación (5 pasos)

**Paso 1. Descomprima el ZIP y entre a la carpeta**

```bash
cd oftalmologia-ia
```

**Paso 2. Cree su archivo de configuración**

```bash
cp .env.example .env          # Windows PowerShell:  copy .env.example .env
```

**Paso 3. Pegue la llave de API en `.env`**

Abra `.env` con cualquier editor y complete **una** línea, según el proveedor (por defecto Groq):

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_su_llave_aqui
```

Cómo obtener una llave de Groq (gratis, 2 minutos): entre a <https://console.groq.com/keys>, inicie sesión,
pulse **Create API Key**, copie el valor que empieza por `gsk_` y péguelo después del `=` sin comillas ni espacios.

> **¿No tiene llave?** Ponga `LLM_PROVIDER=mock`. La aplicación funciona completa con una IA *simulada por
> reglas* (sin internet). Sirve para revisar el flujo, no para evaluar al modelo.

**Paso 4. Ejecute el script de arranque**

```bash
./run.sh                      # Linux, Mac, o Windows con Git Bash / WSL
```

```powershell
.\run.ps1                     # Windows PowerShell
# si Windows bloquea el script:  powershell -ExecutionPolicy Bypass -File .\run.ps1
```

El script verifica Docker, revisa el `.env`, construye las imágenes, levanta los 3 servicios y espera a que la API
responda. **La primera vez tarda entre 5 y 10 minutos** (descarga ~2 GB: librerías y el modelo Whisper `small`).
Las siguientes veces arranca en segundos.

Al final verá:

```
✔ Aplicación lista:
    Web:              http://localhost:8080
    API (Swagger):    http://localhost:8000/docs
```

**Paso 5. Abra <http://localhost:8080>**

Equivalente manual al paso 4, si prefiere no usar el script: `docker compose up --build`.

---

## 3. Variables de entorno (`.env`)

| Variable | Obligatoria | Valor por defecto | Para qué sirve |
|---|---|---|---|
| `LLM_PROVIDER` | Sí | `groq` | Proveedor del LLM: `groq`, `gemini`, `openai` o `mock` (simulado, sin red) |
| `GROQ_API_KEY` | Si `LLM_PROVIDER=groq` o `TRANSCRIPCION_PROVIDER=groq` | — | Llave de <https://console.groq.com/keys> |
| `GEMINI_API_KEY` | Si `LLM_PROVIDER=gemini` | — | Llave de <https://aistudio.google.com/apikey> |
| `OPENAI_API_KEY` | Si `LLM_PROVIDER=openai` | — | Llave de OpenAI |
| `LLM_MODEL` | No | vacío = por defecto del proveedor | `openai/gpt-oss-120b` (groq), `gemini-2.5-flash` (gemini), `gpt-4o-mini` (openai) |
| `TRANSCRIPCION_PROVIDER` | No | `local` | `local` = faster-whisper en el contenedor (el audio no sale del equipo); `groq` = Whisper large-v3-turbo en la nube |
| `WHISPER_MODEL` | No | `small` | Tamaño del modelo local: `tiny`, `base`, `small`, `medium` |
| `PRECARGAR_WHISPER` | No | `true` | Descarga el modelo al construir la imagen (la demo no espera descargas) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | No | `oftalmologia` / `oftalmologia` / `oftalmologia_local` | Credenciales de la BD del contenedor |
| `DATABASE_URL` | No (informativa) | `postgresql+psycopg://…@db:5432/oftalmologia` | `docker-compose.yml` la construye a partir de las tres anteriores |
| `AGENTE_MAX_ITERACIONES` | No | `5` | Límite 1 del agente: llamadas máximas al LLM por extracción |
| `AGENTE_TIMEOUT_S` | No | `60` | Límite 2: tiempo máximo total del agente |
| `AGENTE_MAX_TOKENS_TOTALES` | No | `20000` | Límite 3: presupuesto de tokens por extracción |
| `LLM_TIMEOUT_S` | No | `30` | Tiempo máximo por llamada individual al LLM |
| `LLM_MAX_TOKENS_RESPUESTA` | No | `4096` | Tokens máximos de cada respuesta del LLM |
| `LLM_TEMPERATURE` | No | `0` | Temperatura (0 = lo más determinista posible) |
| `PERMITIR_SIMULAR_FALLAS` | No | `true` | Habilita "Armar fallo" en el panel de trazas para demostrar el manejo de errores |
| `PUERTO_WEB` / `PUERTO_API` | No | `8080` / `8000` | Cámbielos si esos puertos están ocupados |

Si falta la llave del proveedor elegido, la aplicación **arranca igual** y muestra un mensaje claro al usar la IA.

---

## 4. Proveedor y modelo declarados

| Uso | Proveedor / modelo | Justificación |
|---|---|---|
| Extracción (pasos 3–4) y explicación (paso 7) | **Groq · `openai/gpt-oss-120b`**, `temperature=0`, `reasoning_effort=low` | Latencia muy baja en hardware LPU, US$ 0,15 / 0,60 por millón de tokens, contexto de 131k, *tool calling* compatible con OpenAI |
| Transcripción (paso 2) | **faster-whisper `small`** (int8, CPU, local) | El audio de un paciente no sale del equipo; ~4× más rápido que Whisper original en CPU |
| Alternativas listas sin cambiar código | Gemini 2.5 Flash, GPT-4o-mini, Groq Whisper large-v3-turbo | Cambiando `LLM_PROVIDER` / `TRANSCRIPCION_PROVIDER` en `.env` |

El detalle y lo descartado está en [`docs/decisiones.md`](docs/decisiones.md), sección 3.

---

## 5. Recorrido guiado (sirve como guion de la demo de 6 minutos)

1. **Nueva consulta**: escriba un identificador (ej. `HC-0457`, nunca el nombre) y el médico.
2. **Dictado**: pestaña *Grabar con el micrófono* (el navegador pedirá permiso) o *Escribir o pegar* → elija
   *"Sospecha de glaucoma (dictado completo)"*. Pulse **Generar borrador con IA**.
3. Mire el **panel de Trazas** a la derecha: aparecen el extractor determinista, cada llamada al LLM (tokens,
   latencia, costo) y cada herramienta que el agente usó.
4. **Revisión médica**: la rejilla OD (rojo) / OI (azul) muestra AV y PIO. Al hacer clic en un campo se resalta en
   el dictado la frase que lo respalda. Corrija lo que quiera.
5. Pruebe el caso *"Dictado ambiguo"*: aparecen alertas bloqueantes; el botón **Guardar** no se habilita hasta
   marcarlas como revisadas y confirmar.
6. **Guardar** → **Redactar explicación** → edite → **Aprobar explicación**. Puede imprimir el resultado.
7. **Manejo de fallos en vivo**: en el panel de trazas elija *Timeout del LLM* o *Caída del proveedor*, pulse
   **Armar fallo** y genere un borrador: verá un mensaje claro (sin stack trace), la traza del error en rojo, y
   podrá reintentar sin perder el dictado.

---

## 6. Pruebas

```bash
./run.sh test           # Windows: .\run.ps1 test
```

Corre dentro de Docker (no instala nada en su equipo), sin internet ni llaves (BD SQLite en memoria, LLM y Whisper simulados):

| Suite | Archivo | Qué verifica |
|---|---|---|
| Unitarias — extractor AV/PIO | `backend/tests/unit/test_mediciones.py` | Lateralidad en 7 formas de dictado, "2040"→20/40, números en palabras, "ambos ojos", ambigüedades que NO se adivinan, distractores (presión arterial, "3 meses") |
| Unitarias — verificador | `backend/tests/unit/test_verificador.py` | Ojos intercambiados por el LLM, números inventados, citas falsas, diagnósticos no dictados, inyección de instrucciones |
| Unitarias — agente | `backend/tests/unit/test_agente.py` | Los 4 límites (iteraciones, timeout, tokens, confirmación humana), recuperación de JSON roto, caída del proveedor |
| Unitarias — explicación | `backend/tests/unit/test_guardas_y_explicacion.py` | La guarda bloquea diagnósticos y cifras nuevas; reintento y plantilla segura |
| Unitarias — contratos | `backend/tests/unit/test_esquemas_y_estados.py` | Formatos de AV/PIO y máquina de estados de los 8 pasos |
| Integración — API | `backend/tests/integration/test_flujo_api.py` | Los 8 pasos por HTTP; los 3 fallos (timeout 504, caída 503, validación 422) con mensaje amigable y sin stack trace; 409 por orden incorrecto |
| Frontend | `frontend/src/logica/revision.test.ts` | Reglas de bloqueo de la revisión obligatoria (se ejecutan en el build) |

## 7. Evaluación (casos dorados y línea base)

```bash
./run.sh eval                              # con el proveedor del .env (gasta tokens: ~40 llamadas)
./run.sh eval mock                         # proveedor simulado, sin red
./run.sh eval -- --repeticiones 3          # 3 corridas para medianas más estables
```

Imprime el resultado por caso, guarda `eval/resultados/<fecha>_<proveedor>.json` y un bloque Markdown con las
**4 cifras de línea base** (latencia mediana, costo mediano, exactitud de campos críticos, errores de lateralidad /
alucinaciones) para pegar en `docs/decisiones.md`. Ver [`eval/README.md`](eval/README.md).

## 8. Otros comandos

| Comando | Qué hace |
|---|---|
| `./run.sh logs` | Muestra las trazas del backend en vivo (un JSON por evento) |
| `./run.sh stop` | Detiene los contenedores (los datos se conservan) |
| `./run.sh reset` | Detiene y **borra** la base de datos |
| `make up` / `make test` / `make eval` | Atajos equivalentes |

## 9. API

Documentación interactiva en <http://localhost:8000/docs>.

| Método y ruta | Paso | Descripción |
|---|---|---|
| `POST /api/consultas` | 1 | Crea la consulta (`paciente_ref`, `medico`) |
| `POST /api/consultas/{id}/audio` | 2 | Sube el audio y lo transcribe con Whisper (multipart, campo `audio`) |
| `PUT /api/consultas/{id}/transcripcion` | 2 | Dictado escrito o corrección de la transcripción |
| `POST /api/consultas/{id}/extraccion` | 3–4 | Agente LLM + verificación → borrador con alertas |
| `POST /api/consultas/{id}/revision` | 5–6 | Revisión del médico y guardado |
| `POST /api/consultas/{id}/explicacion` | 7 | Explicación para el paciente |
| `POST /api/consultas/{id}/aprobacion` | 8 | Aprobación final |
| `GET /api/consultas/{id}/trazas` | — | Trazas y resumen (tokens, costo, latencia, fallos) |
| `GET /api/salud` | — | Estado, proveedor, modelo y límites activos |
| `POST /api/demo/falla` | — | Arma un fallo simulado para la próxima llamada a la IA |

## 10. Estructura del repositorio

```
oftalmologia-ia/
├── README.md                  ← este contrato
├── docker-compose.yml         ← BD + API + web
├── run.sh / run.ps1 / Makefile← arranque en un comando
├── .env.example               ← plantilla de variables (sin llaves reales)
├── docs/decisiones.md         ← arquitectura, datos (no-RAG), fallos, línea base
├── eval/                      ← casos dorados, script de medición y resultados
├── backend/
│   ├── Dockerfile, requirements*.txt
│   ├── app/
│   │   ├── main.py            ← FastAPI, manejo global de errores
│   │   ├── api/rutas.py       ← endpoints (sin lógica de negocio)
│   │   ├── servicios.py       ← orquestación de los 8 pasos
│   │   ├── estados.py         ← máquina de estados
│   │   ├── esquemas.py        ← contrato de la historia clínica (Pydantic)
│   │   ├── db.py              ← modelos SQLAlchemy (consultas, trazas)
│   │   ├── clinica/           ← DETERMINISTA: mediciones AV/PIO, verificador, guardas
│   │   └── ia/                ← PROBABILÍSTICO: agente, herramientas, proveedores, prompts, Whisper
│   └── tests/                 ← unitarias e integración
└── frontend/
    ├── Dockerfile, nginx.conf
    └── src/                   ← App, pantallas de dictado/revisión/explicación, panel de trazas
```

## 11. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `Docker está instalado pero no está corriendo` | Docker Desktop cerrado | Ábralo, espere "Engine running", repita `./run.sh` |
| `port is already allocated` | Otro programa usa 8080 u 8000 | Cambie `PUERTO_WEB` / `PUERTO_API` en `.env` |
| `permission denied: ./run.sh` | Se perdió el permiso de ejecución al descomprimir | `chmod +x run.sh` o `bash run.sh` |
| La IA dice "Falta GROQ_API_KEY" | Llave vacía o mal pegada | Revise `.env` (sin comillas ni espacios) y ejecute `./run.sh` de nuevo |
| "El proveedor rechazó la llave" | Llave vencida o revocada | Genere otra en la consola del proveedor |
| Error 429 frecuente | Cuota gratuita agotada | Espere un minuto o cambie de proveedor en `.env` |
| El micrófono no funciona | Permiso denegado o sitio no seguro | Use `http://localhost:8080` (no la IP) y permita el micrófono; o use *Subir un audio* / *Escribir o pegar* |
| La primera transcripción tarda | El modelo de Whisper se está cargando en memoria | Espere ~10 s; las siguientes son más rápidas. Con poca RAM use `WHISPER_MODEL=base` |
| La construcción tarda mucho | Primera descarga | Para una demo más liviana: `PRECARGAR_WHISPER=false` y `TRANSCRIPCION_PROVIDER=groq` |
| Quiero empezar de cero | — | `./run.sh reset` y luego `./run.sh` |

## 12. Prueba del compañero

Antes de entregar, otra persona descarga el ZIP en una máquina distinta y sigue este README **sin ayuda**.

| Fecha | Quién | Sistema operativo | Tiempo hasta ver la app | Problemas encontrados | Corrección aplicada |
|---|---|---|---|---|---|
| 29/10/2026 | Jose Pantoja | Linux | 5 minutos | Faltaba la llave de API en el archivo `.env` | Configurar la API Key en el archivo `.env` |

## 13. Seguridad

- **Nunca** incluya `.env` en el ZIP. Para empaquetar sin archivos pesados ni secretos:
  ```bash
  zip -r ../oftalmologia-ia.zip . -x ".env" "*/node_modules/*" "*/dist/*" "*/__pycache__/*" "*/.venv/*" ".git/*" "*.db"
  ```
- Use solo dictados **ficticios** en la demo: con un proveedor en la nube, la transcripción sale del equipo.
- El audio se elimina inmediatamente después de transcribirlo.
