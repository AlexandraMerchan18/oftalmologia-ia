import { useCallback, useEffect, useState } from "react";
import { ErrorApi, api } from "./api";
import { PanelTrazas } from "./componentes/PanelTrazas";
import { PasoDictado } from "./componentes/PasoDictado";
import { PasoExplicacion } from "./componentes/PasoExplicacion";
import { PasoRevision } from "./componentes/PasoRevision";
import { Progreso } from "./componentes/Progreso";
import type { Consulta, ConsultaResumen, Ejemplo, Salud } from "./tipos";

export function App() {
  const [consulta, setConsulta] = useState<Consulta | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [error, setError] = useState<ErrorApi | null>(null);
  const [salud, setSalud] = useState<Salud | null>(null);
  const [ejemplos, setEjemplos] = useState<Ejemplo[]>([]);
  const [recientes, setRecientes] = useState<ConsultaResumen[]>([]);

  useEffect(() => {
    api.salud().then(setSalud).catch((e) => setError(e));
    api.ejemplos().then(setEjemplos).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.listar().then(setRecientes).catch(() => undefined);
  }, [consulta?.estado]);

  /** Ejecuta una acción contra la API mostrando progreso y errores legibles. */
  const ejecutar = useCallback(async (mensaje: string, accion: () => Promise<Consulta>) => {
    setOcupado(mensaje);
    setError(null);
    try {
      setConsulta(await accion());
    } catch (e) {
      setError(e instanceof ErrorApi ? e : new ErrorApi("Ocurrió un error inesperado en la interfaz.", "interfaz"));
    } finally {
      setOcupado(null);
    }
  }, []);

  const id = consulta?.id ?? "";
  const estado = consulta?.estado ?? null;

  return (
    <div className="app">
      <header className="barra">
        <div className="marca">
          <svg viewBox="0 0 32 20" aria-hidden className="iris">
            <ellipse cx="16" cy="10" rx="15" ry="9" />
            <circle cx="16" cy="10" r="5.5" />
            <circle cx="16" cy="10" r="2.2" />
          </svg>
          <span>Oftalmología + IA</span>
        </div>
        <Progreso estado={estado} />
        {recientes.length > 0 && (
          <select className="recientes" aria-label="Abrir una consulta reciente" value=""
            onChange={(e) => e.target.value && ejecutar("Abriendo consulta…", () => api.obtener(e.target.value))}>
            <option value="">Consultas recientes</option>
            {recientes.map((c) => (
              <option key={c.id} value={c.id}>{c.paciente_ref} · {c.estado.toLowerCase().replace("_", " ")}</option>
            ))}
          </select>
        )}
      </header>

      <div className="contenido">
        <main>
          {error && (
            <div className="error" role="alert">
              <p>{error.message}</p>
              <p className="error-meta">
                {error.trazaId && <>Código {error.trazaId}. </>}
                {consulta && "Su trabajo está guardado; puede reintentar."}
              </p>
              <button className="enlace" onClick={() => setError(null)}>Cerrar</button>
            </div>
          )}
          {ocupado && (
            <div className="ocupado" role="status">
              <span className="pulso" aria-hidden />
              {ocupado}
            </div>
          )}

          {(!consulta || estado === "CREADA" || estado === "TRANSCRITA") && (
            <PasoDictado
              consulta={consulta}
              ejemplos={ejemplos}
              ocupado={!!ocupado}
              onCrear={(p, m) => ejecutar("Creando consulta…", () => api.crear(p, m))}
              onAudio={(b, n) => ejecutar("Transcribiendo con Whisper…", () => api.subirAudio(id, b, n))}
              onExtraer={(texto) =>
                ejecutar("La IA está extrayendo la historia clínica…", async () => {
                  if (texto !== null) await api.fijarTranscripcion(id, texto);
                  return api.extraer(id);
                })
              }
            />
          )}

          {consulta && estado === "BORRADOR" && (
            <PasoRevision
              key={consulta.id + (consulta.resumen_extraccion?.latencia_ms ?? "")}
              consulta={consulta}
              ocupado={!!ocupado}
              onGuardar={(h, r, m, c) => ejecutar("Guardando historia…", () => api.revisar(id, h, r, m, c))}
            />
          )}

          {consulta && (estado === "GUARDADA" || estado === "EXPLICACION_GENERADA" || estado === "APROBADA") && (
            <PasoExplicacion
              consulta={consulta}
              ocupado={!!ocupado}
              onGenerar={() => ejecutar("La IA está redactando la explicación…", () => api.explicar(id))}
              onAprobar={(t, m, c) => ejecutar("Aprobando…", () => api.aprobar(id, t, m, c))}
              onNueva={() => {
                setConsulta(null);
                setError(null);
              }}
            />
          )}
        </main>

        <PanelTrazas consultaId={consulta?.id ?? null} salud={salud} />
      </div>
    </div>
  );
}
