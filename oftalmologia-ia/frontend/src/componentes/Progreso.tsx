import type { Estado } from "../tipos";

// Los 8 pasos del producto. Indica quién actúa en cada uno: la frontera de la IA, visible.
const PASOS: { nombre: string; actor: "médico" | "IA" | "sistema" }[] = [
  { nombre: "Dictado", actor: "médico" },
  { nombre: "Transcripción", actor: "IA" },
  { nombre: "Extracción", actor: "IA" },
  { nombre: "Borrador", actor: "sistema" },
  { nombre: "Revisión médica", actor: "médico" },
  { nombre: "Guardado", actor: "sistema" },
  { nombre: "Explicación", actor: "IA" },
  { nombre: "Aprobación final", actor: "médico" },
];

/** Último paso COMPLETADO para cada estado de la consulta. */
const COMPLETADO: Record<Estado, number> = {
  CREADA: 0,
  TRANSCRITA: 2,
  BORRADOR: 4,
  GUARDADA: 6,
  EXPLICACION_GENERADA: 7,
  APROBADA: 8,
};

export function Progreso({ estado }: { estado: Estado | null }) {
  const hechos = estado ? COMPLETADO[estado] : 0;
  return (
    <ol className="progreso" aria-label="Pasos de la consulta">
      {PASOS.map((p, i) => {
        const n = i + 1;
        const clase = n <= hechos ? "hecho" : n === hechos + 1 ? "actual" : "";
        return (
          <li key={p.nombre} className={clase} aria-current={clase === "actual" ? "step" : undefined}>
            <span className="progreso-numero">{n}</span>
            <span className="progreso-nombre">{p.nombre}</span>
            <span className={`progreso-actor actor-${p.actor === "IA" ? "ia" : p.actor === "médico" ? "medico" : "sistema"}`}>
              {p.actor}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
