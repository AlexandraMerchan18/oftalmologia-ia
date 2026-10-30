"""Suite de evaluación con casos dorados: mide el sistema COMPLETO de extracción (agente LLM + verificador).

Uso (desde la raíz del repo):
    ./run.sh eval            # proveedor configurado en .env (ej. Groq)
    ./run.sh eval mock       # proveedor simulado: prueba de humo, sin red
    ./run.sh eval -- --repeticiones 3 --casos c01,c02

Mide, por caso y en agregado:
  1. Exactitud de campos críticos  (AV sc/cc y PIO por ojo: 6 casillas por caso)
  2. Errores de lateralidad        (valor del otro ojo puesto en este ojo)
  3. Alucinaciones                 (valor donde no se dictó nada, diagnóstico no dictado, término prohibido)
  4. Latencia de extracción        (mediana, ms)
  5. Costo y tokens por consulta   (mediana)
  6. Sensibilidad de alertas       (casos ambiguos que sí bloquearon el guardado)
Escribe eval/resultados/<fecha>_<proveedor>.json y un bloque Markdown listo para docs/decisiones.md.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
for ruta in (AQUI.parent / "backend", Path("/app")):
    if (ruta / "app").exists():
        sys.path.insert(0, str(ruta))
        break

from app.config import Config  # noqa: E402
from app.errores import ErrorAplicacion  # noqa: E402
from app.ia.agente import LimitesAgente, ejecutar_agente  # noqa: E402
from app.ia.prompts import PROMPT_VERSION  # noqa: E402
from app.ia.proveedores import construir_proveedor  # noqa: E402

CASILLAS = [("av", "od_sc"), ("av", "oi_sc"), ("av", "od_cc"), ("av", "oi_cc"), ("pio", "od"), ("pio", "oi")]


def norm(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip()


def valor_obtenido(historia, grupo: str, clave: str):
    if grupo == "pio":
        return getattr(historia.pio, clave).valor_mmhg
    ojo, corr = clave.split("_")
    campo = getattr(getattr(historia.agudeza_visual, ojo), "sin_correccion" if corr == "sc" else "con_correccion")
    return campo.valor


def iguales(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    return norm(a).replace(" ", "") == norm(b).replace(" ", "")


def otro_ojo(clave: str) -> str:
    return clave.replace("od", "§").replace("oi", "od").replace("§", "oi")


def textos_de(historia) -> list[str]:
    d = historia.model_dump()
    salida: list[str] = []

    def recorrer(n):
        if isinstance(n, dict):
            if isinstance(n.get("valor"), str):
                salida.append(n["valor"])
            for k, v in n.items():
                if k != "evidencia":
                    recorrer(v)
    recorrer(d)
    return salida


def evaluar_caso(caso: dict, proveedor, limites: LimitesAgente) -> dict:
    esperado = caso["esperado"]
    inicio = time.perf_counter()
    try:
        r = ejecutar_agente(caso["dictado"], proveedor, limites)
    except ErrorAplicacion as e:
        return {"id": caso["id"], "error": e.codigo, "mensaje": e.mensaje,
                "latencia_ms": (time.perf_counter() - inicio) * 1000}

    aciertos, lateralidad, inventados, detalle = 0, 0, 0, []
    for grupo, clave in CASILLAS:
        exp = esperado[grupo][clave]
        obt = valor_obtenido(r.historia, grupo, clave)
        ok = iguales(obt, exp)
        aciertos += ok
        if not ok and obt is not None:
            exp_otro = esperado[grupo][otro_ojo(clave)]
            if exp_otro is not None and iguales(obt, exp_otro):
                lateralidad += 1
            elif exp is None:
                inventados += 1
        if not ok:
            detalle.append(f"{grupo}.{clave}: esperado {exp}, obtenido {obt}")

    impresion = r.historia.impresion_diagnostica.valor or ""
    impresion_ok = (not impresion) if esperado.get("impresion_vacia") else \
        all(norm(t) in norm(impresion) for t in esperado.get("impresion_incluye", []))
    if not impresion_ok:
        detalle.append(f"impresion_diagnostica: obtenido '{impresion}'")
    prohibidos = [t for t in esperado.get("prohibido", []) if any(norm(t) in norm(x) for x in textos_de(r.historia))]
    if prohibidos:
        detalle.append(f"términos prohibidos presentes: {prohibidos}")
    diagnostico_inventado = bool(esperado.get("impresion_vacia") and impresion)

    bloqueantes = [a for a in r.alertas if a.bloqueante]
    return {
        "id": caso["id"], "categoria": caso.get("categoria"),
        "aciertos": aciertos, "casillas": len(CASILLAS),
        "errores_lateralidad": lateralidad,
        "alucinacion": bool(inventados or prohibidos or diagnostico_inventado),
        "impresion_ok": impresion_ok,
        "alerta_esperada": esperado.get("alerta_bloqueante", False),
        "alerta_bloqueante": bool(bloqueantes),
        "tipos_alerta": sorted({a.tipo for a in r.alertas}),
        "errores_llm_interceptados": sum(a.tipo == "conflicto" for a in r.alertas),
        "estado_agente": r.estado, "motivo_parada": r.motivo_parada, "iteraciones": r.iteraciones,
        "latencia_ms": r.latencia_ms, "tokens": r.tokens_entrada + r.tokens_salida, "costo_usd": r.costo_usd,
        "detalle": detalle,
    }


def mediana(valores):
    valores = [v for v in valores if v is not None]
    return statistics.median(valores) if valores else 0


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluación con casos dorados")
    p.add_argument("--proveedor", help="groq | gemini | openai | mock (por defecto, el del .env)")
    p.add_argument("--repeticiones", type=int, default=1)
    p.add_argument("--casos", help="ids separados por coma (prefijos válidos: c01,c02)")
    p.add_argument("--pausa", type=float, default=None, help="segundos entre casos (evita 429)")
    args = p.parse_args()

    config = Config(**({"llm_provider": args.proveedor} if args.proveedor else {}))
    proveedor = construir_proveedor(config)
    limites = LimitesAgente(config.agente_max_iteraciones, config.agente_timeout_s,
                            config.agente_max_tokens_totales, config.llm_max_tokens_respuesta, config.llm_timeout_s)
    pausa = args.pausa if args.pausa is not None else (0 if config.llm_provider == "mock" else 2)

    casos = json.loads((AQUI / "casos_dorados.json").read_text(encoding="utf-8"))["casos"]
    if args.casos:
        filtros = [c.strip() for c in args.casos.split(",")]
        casos = [c for c in casos if any(c["id"].startswith(f) for f in filtros)]

    print(f"\nEvaluando {len(casos)} casos × {args.repeticiones} con {config.llm_provider}/{proveedor.modelo} "
          f"({PROMPT_VERSION})\n")
    resultados = []
    for rep in range(args.repeticiones):
        for caso in casos:
            res = evaluar_caso(caso, proveedor, limites)
            res["repeticion"] = rep + 1
            resultados.append(res)
            if "error" in res:
                print(f"  ✘ {res['id']:<34} ERROR {res['error']}: {res['mensaje'][:60]}")
            else:
                marca = "✔" if res["aciertos"] == res["casillas"] and not res["alucinacion"] and res["impresion_ok"] else "•"
                print(f"  {marca} {res['id']:<34} {res['aciertos']}/{res['casillas']} críticos  "
                      f"lat.err={res['errores_lateralidad']}  aluc={'sí' if res['alucinacion'] else 'no'}  "
                      f"alerta={'sí' if res['alerta_bloqueante'] else 'no'}  {res['latencia_ms']:.0f} ms  "
                      f"{res['tokens']} tok")
                for d in res["detalle"]:
                    print(f"      - {d}")
            time.sleep(pausa)

    validos = [r for r in resultados if "error" not in r]
    casillas = sum(r["casillas"] for r in validos) or 1
    con_alerta_esperada = [r for r in validos if r["alerta_esperada"]]
    limpios = [r for r in validos if not r["alerta_esperada"]]
    resumen = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "proveedor": config.llm_provider, "modelo": proveedor.modelo, "prompt": PROMPT_VERSION,
        "casos": len(casos), "repeticiones": args.repeticiones, "ejecuciones_con_error": len(resultados) - len(validos),
        "exactitud_campos_criticos": round(sum(r["aciertos"] for r in validos) / casillas, 4),
        "errores_lateralidad": sum(r["errores_lateralidad"] for r in validos),
        "casos_con_alucinacion": sum(r["alucinacion"] for r in validos),
        "impresion_correcta": round(sum(r["impresion_ok"] for r in validos) / max(len(validos), 1), 4),
        "sensibilidad_alertas": f"{sum(r['alerta_bloqueante'] for r in con_alerta_esperada)}/{len(con_alerta_esperada)}",
        "casos_limpios_con_alerta_bloqueante": f"{sum(r['alerta_bloqueante'] for r in limpios)}/{len(limpios)}",
        "errores_llm_interceptados": sum(r["errores_llm_interceptados"] for r in validos),
        "mediana_latencia_ms": round(mediana([r["latencia_ms"] for r in validos])),
        "mediana_tokens": round(mediana([r["tokens"] for r in validos])),
        "mediana_costo_usd": round(mediana([r["costo_usd"] for r in validos]), 6),
        "mediana_iteraciones": mediana([r["iteraciones"] for r in validos]),
    }

    destino = AQUI / "resultados" / f"{datetime.now().strftime('%Y-%m-%d_%H%M')}_{config.llm_provider}.json"
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps({"resumen": resumen, "resultados": resultados}, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    n = len(validos)
    print("\n" + "=" * 78)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    print("=" * 78)
    print(f"\nResultados guardados en eval/resultados/{destino.name}")
    print("\nBloque para docs/decisiones.md (línea base):\n")
    print(f"| Métrica ({resumen['fecha']}, {resumen['proveedor']}/{resumen['modelo']}, n={n}) | Valor |")
    print("|---|---|")
    print(f"| 1. Latencia de extracción (mediana) | {resumen['mediana_latencia_ms'] / 1000:.2f} s |")
    print(f"| 2. Costo por consulta (mediana) | US$ {resumen['mediana_costo_usd']:.5f} ({resumen['mediana_tokens']} tokens) |")
    print(f"| 3. Exactitud de campos críticos AV/PIO | {resumen['exactitud_campos_criticos'] * 100:.1f} % |")
    print(f"| 4. Errores de lateralidad / casos con alucinación | {resumen['errores_lateralidad']} / "
          f"{resumen['casos_con_alucinacion']} de {n} |")
    print(f"| Sensibilidad de alertas en casos ambiguos | {resumen['sensibilidad_alertas']} |")


if __name__ == "__main__":
    main()
