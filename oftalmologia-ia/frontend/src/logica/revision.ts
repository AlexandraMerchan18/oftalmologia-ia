// Reglas de la revisión obligatoria (paso 5), separadas de React para poder probarlas.
// El backend aplica las mismas reglas: esto solo evita que el médico pulse un botón que fallaría.
import type { Alerta, HistoriaClinica } from "../tipos";

export interface EstadoRevision {
  alertas: Alerta[];
  resueltas: Set<string>;
  medico: string;
  confirmo: boolean;
}

export function alertasPendientes(alertas: Alerta[], resueltas: Set<string>): Alerta[] {
  return alertas.filter((a) => a.bloqueante && !resueltas.has(a.id));
}

export function motivosBloqueo(e: EstadoRevision): string[] {
  const motivos: string[] = [];
  const pendientes = alertasPendientes(e.alertas, e.resueltas).length;
  if (pendientes > 0) {
    motivos.push(pendientes === 1 ? "Falta revisar 1 alerta" : `Faltan revisar ${pendientes} alertas`);
  }
  if (!e.medico.trim()) motivos.push("Escriba el nombre del médico que revisa");
  if (!e.confirmo) motivos.push("Marque la confirmación de revisión");
  return motivos;
}

export const puedeGuardar = (e: EstadoRevision) => motivosBloqueo(e).length === 0;

/** Alertas que afectan a un campo concreto ("pio.od" afecta a "pio.od" y a "pio.od.ambigua"). */
export function alertasDeCampo(alertas: Alerta[], ruta: string): Alerta[] {
  return alertas.filter((a) => a.campo === ruta || a.campo.startsWith(`${ruta}.`));
}

/** Copia inmutable de la historia con un valor cambiado en `ruta` ("pio.od.valor_mmhg"). */
export function conValor(historia: HistoriaClinica, ruta: string, valor: unknown): HistoriaClinica {
  const copia = structuredClone(historia) as unknown as Record<string, unknown>;
  const partes = ruta.split(".");
  let nodo = copia;
  for (const p of partes.slice(0, -1)) nodo = nodo[p] as Record<string, unknown>;
  nodo[partes[partes.length - 1]] = valor;
  return copia as unknown as HistoriaClinica;
}

/** Posición de la cita en la transcripción, ignorando mayúsculas (para resaltarla). */
export function ubicarCita(transcripcion: string, cita: string | null | undefined): [number, number] | null {
  if (!cita) return null;
  const i = transcripcion.toLowerCase().indexOf(cita.toLowerCase().trim());
  return i < 0 ? null : [i, i + cita.trim().length];
}

export const NOMBRE_ALERTA: Record<string, string> = {
  conflicto: "La IA y el extractor no coinciden",
  ambigua: "Dictado ambiguo",
  lateralidad: "Ojo sin confirmar",
  sin_evidencia: "Sin cita en el dictado",
  posible_alucinacion: "Dato que no aparece en el dictado",
  solo_llm: "Solo lo encontró la IA",
  fuera_de_rango: "Valor fuera de rango",
  completado_determinista: "Completado por el extractor",
  extraccion_parcial: "Extracción incompleta",
};
