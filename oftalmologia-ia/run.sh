#!/usr/bin/env bash
# =====================================================================================
#  Oftalmología + IA — arranque en UN comando.
#
#   ./run.sh            construye y levanta todo (BD + API + web) y espera a que esté sano
#   ./run.sh test       pruebas unitarias e integración (backend) + pruebas del frontend
#   ./run.sh eval       suite de casos dorados con el proveedor del .env  (./run.sh eval mock = sin llaves)
#   ./run.sh logs       trazas del backend en vivo
#   ./run.sh stop       detiene los contenedores (conserva los datos)
#   ./run.sh reset      detiene y BORRA la base de datos
# =====================================================================================
set -euo pipefail
cd "$(dirname "$0")"

AZUL='\033[1;34m'; VERDE='\033[1;32m'; AMARILLO='\033[1;33m'; ROJO='\033[1;31m'; FIN='\033[0m'
info()  { echo -e "${AZUL}▸${FIN} $*"; }
ok()    { echo -e "${VERDE}✔${FIN} $*"; }
aviso() { echo -e "${AMARILLO}!${FIN} $*"; }
falla() { echo -e "${ROJO}✘ $*${FIN}" >&2; exit 1; }

verificar_docker() {
  command -v docker >/dev/null 2>&1 || falla "Docker no está instalado. Instale Docker Desktop (Windows/Mac) o Docker Engine (Linux)."
  docker compose version >/dev/null 2>&1 || falla "Se requiere Docker Compose v2 (comando 'docker compose')."
  docker info >/dev/null 2>&1 || falla "Docker está instalado pero no está corriendo. Abra Docker Desktop y reintente."
}

valor_env() { grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '\r' | sed 's/^"//; s/"$//'; }

preparar_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    aviso "Se creó .env a partir de .env.example."
  fi
  local proveedor llave_var
  proveedor="$(valor_env LLM_PROVIDER)"; proveedor="${proveedor:-groq}"
  case "$proveedor" in
    mock) aviso "LLM_PROVIDER=mock: la IA es SIMULADA por reglas (útil sin llaves; no es el modelo real)." ;;
    groq|gemini|openai)
      llave_var="$(echo "$proveedor" | tr '[:lower:]' '[:upper:]')_API_KEY"
      if [ -z "$(valor_env "$llave_var")" ]; then
        aviso "Falta $llave_var en .env. La app arrancará, pero la IA responderá 'falta la llave'."
        aviso "Edite .env y vuelva a ejecutar ./run.sh  (o ponga LLM_PROVIDER=mock para probar sin llaves)."
      else
        ok "Proveedor LLM: $proveedor ($llave_var configurada)."
      fi ;;
    *) falla "LLM_PROVIDER='$proveedor' no es válido en .env (use groq, gemini, openai o mock)." ;;
  esac
  if [ "$(valor_env TRANSCRIPCION_PROVIDER)" = "groq" ] && [ -z "$(valor_env GROQ_API_KEY)" ]; then
    aviso "TRANSCRIPCION_PROVIDER=groq requiere GROQ_API_KEY."
  fi
}

esperar_salud() {
  info "Esperando a que la API responda..."
  for _ in $(seq 1 90); do
    if docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/salud', timeout=3)" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  docker compose logs --tail=40 backend
  falla "La API no respondió en 3 minutos. Revise los mensajes de arriba."
}

case "${1:-up}" in
  up)
    verificar_docker
    preparar_env
    info "Construyendo imágenes y levantando servicios (la primera vez tarda varios minutos: descarga dependencias y el modelo de Whisper)..."
    docker compose up --build -d
    esperar_salud
    puerto="$(valor_env PUERTO_WEB)"; puerto="${puerto:-8080}"
    api="$(valor_env PUERTO_API)"; api="${api:-8000}"
    echo
    ok "Aplicación lista:"
    echo "    Web:              http://localhost:${puerto}"
    echo "    API (Swagger):    http://localhost:${api}/docs"
    echo "    Trazas en vivo:   ./run.sh logs"
    echo "    Detener:          ./run.sh stop"
    ;;
  test)
    verificar_docker
    [ -f .env ] || cp .env.example .env
    info "Backend: pruebas unitarias + integración (SQLite en memoria, IA y Whisper simulados, sin red)..."
    docker compose build backend
    docker compose run --rm --no-deps backend pytest -v
    info "Frontend: pruebas de la lógica de revisión (se ejecutan dentro del build)..."
    docker compose build frontend
    ok "Todas las pruebas pasaron."
    ;;
  eval)
    verificar_docker
    preparar_env
    shift || true
    extra=()
    if [ "${1:-}" = "mock" ]; then extra=(--proveedor mock); shift; fi
    docker compose build backend
    # -u: escribe los resultados en eval/resultados con su usuario (evita problemas de permisos en Linux)
    docker compose run --rm --no-deps -u "$(id -u):$(id -g)" -v "$(pwd)/eval:/eval" backend \
      python /eval/run_eval.py ${extra[@]+"${extra[@]}"} "$@"
    ;;
  logs)  docker compose logs -f backend ;;
  stop)  docker compose down && ok "Servicios detenidos (los datos se conservan)." ;;
  reset) docker compose down -v && ok "Servicios detenidos y base de datos borrada." ;;
  *)     falla "Acción desconocida '$1'. Use: up | test | eval [mock] | logs | stop | reset" ;;
esac
