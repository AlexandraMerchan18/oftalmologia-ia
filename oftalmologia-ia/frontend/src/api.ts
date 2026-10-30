// Cliente HTTP. Convierte cualquier fallo (HTTP, red, tiempo de espera) en un ErrorApi con
// mensaje legible: la interfaz nunca muestra un stack trace ni un "Failed to fetch".
import type {
  Consulta,
  ConsultaResumen,
  Ejemplo,
  HistoriaClinica,
  RespuestaTrazas,
  Salud,
} from "./tipos";

export class ErrorApi extends Error {
  constructor(
    mensaje: string,
    public codigo: string,
    public trazaId?: string,
    public detalle?: Record<string, unknown>,
  ) {
    super(mensaje);
  }
}

const TIEMPO_NORMAL = 30_000;
const TIEMPO_IA = 200_000; // Whisper en CPU y el agente pueden tardar

async function pedir<T>(ruta: string, opciones: RequestInit = {}, tiempoMs = TIEMPO_NORMAL): Promise<T> {
  const control = new AbortController();
  const reloj = setTimeout(() => control.abort(), tiempoMs);
  try {
    const r = await fetch(`/api${ruta}`, { ...opciones, signal: control.signal });
    const cuerpo = await r.json().catch(() => null);
    if (!r.ok) {
      const e = cuerpo?.error;
      throw new ErrorApi(
        e?.mensaje ?? `El servidor respondió con un error (${r.status}).`,
        e?.codigo ?? `http_${r.status}`,
        e?.traza_id,
        e?.detalle,
      );
    }
    return cuerpo as T;
  } catch (e) {
    if (e instanceof ErrorApi) throw e;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ErrorApi("La operación superó el tiempo de espera del navegador. Reintente.", "timeout_cliente");
    }
    throw new ErrorApi(
      "No hay conexión con el servidor. Verifique que la aplicación esté en ejecución (./run.sh).",
      "sin_conexion",
    );
  } finally {
    clearTimeout(reloj);
  }
}

const json = (cuerpo: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(cuerpo),
});

export const api = {
  salud: () => pedir<Salud>("/salud"),
  ejemplos: () => pedir<Ejemplo[]>("/ejemplos"),
  listar: () => pedir<ConsultaResumen[]>("/consultas"),
  obtener: (id: string) => pedir<Consulta>(`/consultas/${id}`),
  crear: (paciente_ref: string, medico: string) => pedir<Consulta>("/consultas", json({ paciente_ref, medico })),
  subirAudio: (id: string, audio: Blob, nombre: string) => {
    const datos = new FormData();
    datos.append("audio", audio, nombre);
    return pedir<Consulta>(`/consultas/${id}/audio`, { method: "POST", body: datos }, TIEMPO_IA);
  },
  fijarTranscripcion: (id: string, texto: string) =>
    pedir<Consulta>(`/consultas/${id}/transcripcion`, { ...json({ texto }), method: "PUT" }),
  extraer: (id: string) => pedir<Consulta>(`/consultas/${id}/extraccion`, { method: "POST" }, TIEMPO_IA),
  revisar: (id: string, historia: HistoriaClinica, alertas_resueltas: string[], medico: string, confirmo_revision: boolean) =>
    pedir<Consulta>(`/consultas/${id}/revision`, json({ historia, alertas_resueltas, medico, confirmo_revision })),
  explicar: (id: string) => pedir<Consulta>(`/consultas/${id}/explicacion`, { method: "POST" }, TIEMPO_IA),
  aprobar: (id: string, explicacion_final: string, medico: string, confirmo_aprobacion: boolean) =>
    pedir<Consulta>(`/consultas/${id}/aprobacion`, json({ explicacion_final, medico, confirmo_aprobacion })),
  trazas: (id: string) => pedir<RespuestaTrazas>(`/consultas/${id}/trazas`),
  simularFalla: (tipo: string | null) => pedir<{ proxima_falla: string | null }>("/demo/falla", json({ tipo })),
};
