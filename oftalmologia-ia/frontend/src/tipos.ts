// Espejo de los contratos del backend (app/esquemas.py y app/api/rutas.py).

export interface Campo {
  valor: string | null;
  evidencia: string | null;
}
export interface CampoPIO {
  valor_mmhg: number | null;
  evidencia: string | null;
}
export interface AgudezaOjo {
  sin_correccion: Campo;
  con_correccion: Campo;
}
export type Ojo = "od" | "oi";

export interface HistoriaClinica {
  motivo_consulta: Campo;
  antecedentes: Campo;
  agudeza_visual: Record<Ojo, AgudezaOjo>;
  pio: Record<Ojo, CampoPIO>;
  biomicroscopia: Record<Ojo, Campo>;
  fondo_de_ojo: Record<Ojo, Campo>;
  impresion_diagnostica: Campo;
  plan: Campo;
}

export type TipoAlerta =
  | "conflicto"
  | "ambigua"
  | "lateralidad"
  | "sin_evidencia"
  | "posible_alucinacion"
  | "solo_llm"
  | "fuera_de_rango"
  | "completado_determinista"
  | "extraccion_parcial";

export interface Alerta {
  id: string;
  campo: string;
  tipo: TipoAlerta;
  bloqueante: boolean;
  mensaje: string;
  valor_llm?: string | null;
  valor_determinista?: string | null;
  evidencia?: string | null;
}

export type Estado =
  | "CREADA"
  | "TRANSCRITA"
  | "BORRADOR"
  | "GUARDADA"
  | "EXPLICACION_GENERADA"
  | "APROBADA";

export interface ResumenExtraccion {
  estado: "completo" | "parcial";
  motivo_parada: string;
  iteraciones: number;
  tokens_entrada: number;
  tokens_salida: number;
  costo_usd: number;
  latencia_ms: number;
  herramientas: string[];
  proveedor: string;
  modelo: string;
}

export interface Consulta {
  id: string;
  paciente_ref: string;
  medico: string;
  estado: Estado;
  transcripcion: string | null;
  fuente_transcripcion: string | null;
  duracion_audio_s: number | null;
  borrador: HistoriaClinica | null;
  alertas: Alerta[] | null;
  resumen_extraccion: ResumenExtraccion | null;
  historia_final: HistoriaClinica | null;
  campos_corregidos: string[] | null;
  revisado_por: string | null;
  revisado_en: string | null;
  explicacion_borrador: string | null;
  explicacion_metodo: "llm" | "llm_corregida" | "plantilla" | null;
  explicacion_final: string | null;
  aprobado_por: string | null;
  aprobado_en: string | null;
  creado_en: string;
}

export interface ConsultaResumen {
  id: string;
  paciente_ref: string;
  medico: string;
  estado: Estado;
  creado_en: string;
}

export interface Traza {
  id: number;
  paso: number;
  tipo: string;
  nombre: string;
  ok: boolean;
  detalle: Record<string, unknown> | null;
  latencia_ms: number | null;
  tokens_entrada: number | null;
  tokens_salida: number | null;
  costo_usd: number | null;
  creado_en: string;
}

export interface RespuestaTrazas {
  resumen: {
    llamadas_llm: number;
    tokens_entrada: number;
    tokens_salida: number;
    costo_usd: number;
    latencia_llm_ms: number;
    errores: number;
  };
  trazas: Traza[];
}

export interface Salud {
  estado: string;
  base_datos: string;
  llm: { proveedor: string; modelo: string; llave_configurada: boolean };
  transcripcion: string;
  prompt_version: string;
  limites_agente: Record<string, string | number>;
  simular_fallas: boolean;
}

export interface Ejemplo {
  id: string;
  titulo: string;
  texto: string;
}
