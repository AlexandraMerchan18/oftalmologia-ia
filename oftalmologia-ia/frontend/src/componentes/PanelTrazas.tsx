import { useEffect, useState } from "react";
import { api } from "../api";
import type { RespuestaTrazas, Salud, Traza } from "../tipos";

// Observabilidad en vivo: cada llamada al LLM, cada herramienta, cada límite y cada fallo.
// Se consulta cada 1,5 s mientras hay una consulta abierta (el backend confirma cada traza al instante).

const FALLAS = [
  { valor: "timeout", nombre: "Timeout del LLM" },
  { valor: "caida", nombre: "Caída del proveedor" },
  { valor: "limite_tasa", nombre: "Error 429 (límite de tasa)" },
  { valor: "json_roto", nombre: "JSON roto del modelo" },
];

export function PanelTrazas({ consultaId, salud }: { consultaId: string | null; salud: Salud | null }) {
  const [datos, setDatos] = useState<RespuestaTrazas | null>(null);
  const [abierta, setAbierta] = useState<number | null>(null);
  const [falla, setFalla] = useState("timeout");
  const [armada, setArmada] = useState<string | null>(null);

  useEffect(() => {
    setDatos(null);
    if (!consultaId) return;
    let vivo = true;
    const cargar = () => api.trazas(consultaId).then((d) => vivo && setDatos(d)).catch(() => undefined);
    cargar();
    const t = setInterval(cargar, 1500);
    return () => {
      vivo = false;
      clearInterval(t);
    };
  }, [consultaId]);

  const r = datos?.resumen;
  return (
    <aside className="panel-trazas" aria-label="Trazas de ejecución">
      <h2>Trazas</h2>
      {salud && (
        <p className="proveedor">
          {salud.llm.proveedor} · {salud.llm.modelo}
          <br />
          {salud.transcripcion}
          {!salud.llm.llave_configurada && <span className="falta-llave"> Falta la llave de API en .env</span>}
        </p>
      )}

      {r && (
        <dl className="cifras">
          <div><dt>Llamadas LLM</dt><dd>{r.llamadas_llm}</dd></div>
          <div><dt>Tokens</dt><dd>{(r.tokens_entrada + r.tokens_salida).toLocaleString("es-CO")}</dd></div>
          <div><dt>Costo</dt><dd>US$ {r.costo_usd.toFixed(4)}</dd></div>
          <div><dt>Latencia LLM</dt><dd>{(r.latencia_llm_ms / 1000).toFixed(1)} s</dd></div>
          <div className={r.errores ? "con-errores" : ""}><dt>Fallos</dt><dd>{r.errores}</dd></div>
        </dl>
      )}

      {!consultaId && <p className="ayuda">Las trazas aparecen al iniciar una consulta.</p>}

      <ol className="lista-trazas">
        {datos?.trazas.map((t) => (
          <FilaTraza key={t.id} t={t} abierta={abierta === t.id} onAlternar={() => setAbierta(abierta === t.id ? null : t.id)} />
        ))}
      </ol>

      {salud?.simular_fallas && (
        <div className="simular">
          <label>
            Simular en la próxima llamada a la IA
            <select value={falla} onChange={(e) => setFalla(e.target.value)}>
              {FALLAS.map((f) => <option key={f.valor} value={f.valor}>{f.nombre}</option>)}
            </select>
          </label>
          <button className="secundario" onClick={() => api.simularFalla(falla).then((x) => setArmada(x.proxima_falla)).catch(() => undefined)}>
            Armar fallo
          </button>
          {armada && <p className="ayuda">Armado: {FALLAS.find((f) => f.valor === armada)?.nombre}. Se dispara en la próxima llamada.</p>}
        </div>
      )}
    </aside>
  );
}

function FilaTraza({ t, abierta, onAlternar }: { t: Traza; abierta: boolean; onAlternar: () => void }) {
  const tokens = (t.tokens_entrada ?? 0) + (t.tokens_salida ?? 0);
  return (
    <li className={`traza tipo-${t.tipo} ${t.ok ? "" : "fallida"}`}>
      <button className="traza-fila" onClick={onAlternar} aria-expanded={abierta}>
        <span className="traza-paso" title={`Paso ${t.paso}`}>{t.paso}</span>
        <span className="traza-tipo">{t.tipo}</span>
        <span className="traza-nombre">{t.nombre}</span>
        <span className="traza-cifras">
          {t.latencia_ms !== null && `${Math.round(t.latencia_ms)} ms`}
          {tokens > 0 && ` · ${tokens} tok`}
        </span>
      </button>
      {abierta && <pre className="traza-detalle">{JSON.stringify(t.detalle, null, 2)}</pre>}
    </li>
  );
}
