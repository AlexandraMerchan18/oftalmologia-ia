# Evaluación con casos dorados

| Archivo | Contenido |
|---|---|
| `casos_dorados.json` | 14 dictados ficticios con el valor correcto de cada campo crítico |
| `run_eval.py` | Ejecuta el agente real (o el simulado) sobre cada caso y calcula las métricas |
| `resultados/` | Un JSON por corrida: resumen + detalle por caso (evidencia para la sustentación) |

## Ejecutar

```bash
./run.sh eval                                  # proveedor del .env
./run.sh eval mock                             # sin red ni llaves
./run.sh eval -- --repeticiones 3 --casos c09,c10
```

## Cómo se califica cada caso

- **6 casillas críticas**: AV sin y con corrección por ojo, y PIO por ojo. `null` esperado significa "no se
  dictó o es ambiguo": llenarla cuenta como error.
- **Error de lateralidad**: el valor obtenido para un ojo es el valor esperado del otro ojo.
- **Alucinación**: un valor donde no se dictó nada, una impresión diagnóstica cuando el médico no dictó ninguna,
  o un término de la lista `prohibido`.
- **Sensibilidad de alertas**: en los casos marcados `alerta_bloqueante: true`, el borrador debe impedir el
  guardado hasta que el médico revise.

Se evalúa el **sistema completo** (agente + verificador), que es lo que ve el médico. La métrica
`errores_llm_interceptados` cuenta los conflictos en que el verificador corrigió al LLM.

## Agregar un caso

Copie un objeto de `casos_dorados.json`, asigne un `id` nuevo (`c15-…`), escriba el dictado y los valores
esperados. Idealmente lo escribe alguien que **no** programó el extractor, para no sesgar la medición.
