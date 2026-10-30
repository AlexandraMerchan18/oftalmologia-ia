import { useMemo, useState } from "react";
import type { Alerta, Campo, Consulta, HistoriaClinica, Ojo } from "../tipos";
import {
  NOMBRE_ALERTA,
  alertasDeCampo,
  conValor,
  motivosBloqueo,
  ubicarCita,
} from "../logica/revision";

interface Props {
  consulta: Consulta;
  ocupado: boolean;
  onGuardar: (historia: HistoriaClinica, resueltas: string[], medico: string, confirmo: boolean) => void;
}

const OJOS: { clave: Ojo; corto: string; largo: string }[] = [
  { clave: "od", corto: "OD", largo: "Ojo derecho" },
  { clave: "oi", corto: "OI", largo: "Ojo izquierdo" },
];

export function nombreCampo(ruta: string): string {
  const p = ruta.replace(/\.ambigua$/, "").split(".");
  const ojo = p[1] === "od" ? "OD" : p[1] === "oi" ? "OI" : "";
  const base: Record<string, string> = {
    motivo_consulta: "Motivo de consulta", antecedentes: "Antecedentes", agudeza_visual: "Agudeza visual",
    pio: "Presión intraocular", biomicroscopia: "Biomicroscopía", fondo_de_ojo: "Fondo de ojo",
    impresion_diagnostica: "Impresión diagnóstica", plan: "Plan", general: "Extracción",
  };
  const corr = p[2] === "sin_correccion" ? " sin corrección" : p[2] === "con_correccion" ? " con corrección" : "";
  return `${base[p[0]] ?? p[0]}${corr}${ojo ? ` ${ojo}` : ""}`;
}

export function PasoRevision({ consulta, ocupado, onGuardar }: Props) {
  const [historia, setHistoria] = useState<HistoriaClinica>(() => structuredClone(consulta.borrador!));
  const [resueltas, setResueltas] = useState<Set<string>>(new Set());
  const [medico, setMedico] = useState(consulta.medico);
  const [confirmo, setConfirmo] = useState(false);
  const [foco, setFoco] = useState<string | null>(null);

  const alertas = consulta.alertas ?? [];
  const transcripcion = consulta.transcripcion ?? "";
  const motivos = motivosBloqueo({ alertas, resueltas, medico, confirmo });
  const bloqueantes = alertas.filter((a) => a.bloqueante);

  const citaEnFoco = useMemo(() => {
    if (!foco) return null;
    const nodo = foco.split(".").reduce<unknown>((n, k) => (n as Record<string, unknown>)?.[k], historia) as
      | { evidencia?: string | null }
      | undefined;
    return nodo?.evidencia ?? null;
  }, [foco, historia]);

  const fijar = (ruta: string, valor: unknown) => setHistoria((h) => conValor(h, ruta, valor));
  const alternar = (id: string, marcar: boolean) =>
    setResueltas((s) => {
      const n = new Set(s);
      if (marcar) n.add(id);
      else n.delete(id);
      return n;
    });

  const propsCampo = (ruta: string) => ({
    alertas: alertasDeCampo(alertas, ruta),
    resueltas,
    onFoco: () => setFoco(ruta),
  });

  return (
    <section className="tarjeta revision">
      <header className="cabecera-paso">
        <h1>Revisión médica</h1>
        <p className="meta">
          Paciente {consulta.paciente_ref}. Nada se guarda hasta que usted revise y confirme.
        </p>
      </header>

      {alertas.length > 0 && (
        <ListaAlertas alertas={alertas} resueltas={resueltas} onAlternar={alternar}
          onUsarValor={(a, valor) => {
            const ruta = a.campo.startsWith("pio.") ? `${a.campo}.valor_mmhg` : `${a.campo}.valor`;
            fijar(ruta, a.campo.startsWith("pio.") ? (valor === null ? null : Number(valor)) : valor);
            alternar(a.id, true);
          }} />
      )}

      <div className="revision-cuerpo">
        <aside className="dictado-fuente" aria-label="Transcripción del dictado">
          <h2>Dictado</h2>
          <Resaltado texto={transcripcion} cita={citaEnFoco} />
          <p className="ayuda">Al enfocar un campo se resalta la frase del dictado que lo respalda.</p>
        </aside>

        <div className="formulario-historia">
          <CampoTexto etiqueta="Motivo de consulta" campo={historia.motivo_consulta}
            onCambio={(v) => fijar("motivo_consulta.valor", v)} {...propsCampo("motivo_consulta")} />
          <CampoTexto etiqueta="Antecedentes" campo={historia.antecedentes}
            onCambio={(v) => fijar("antecedentes.valor", v)} {...propsCampo("antecedentes")} />

          <table className="rejilla-ojos">
            <caption>Agudeza visual y presión intraocular</caption>
            <thead>
              <tr>
                <th scope="col"><span className="sr">Medición</span></th>
                {OJOS.map((o) => (
                  <th key={o.clave} scope="col" className={`ojo-${o.clave}`}>
                    <span className="sigla">{o.corto}</span> {o.largo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(["sin_correccion", "con_correccion"] as const).map((corr) => (
                <tr key={corr}>
                  <th scope="row">Agudeza visual {corr === "sin_correccion" ? "sin corrección" : "con corrección"}</th>
                  {OJOS.map((o) => {
                    const ruta = `agudeza_visual.${o.clave}.${corr}`;
                    return (
                      <td key={o.clave}>
                        <CeldaMedicion ojo={o.clave} valor={historia.agudeza_visual[o.clave][corr].valor ?? ""}
                          evidencia={historia.agudeza_visual[o.clave][corr].evidencia} placeholder="20/20"
                          etiqueta={`Agudeza visual ${corr === "sin_correccion" ? "sin" : "con"} corrección ${o.corto}`}
                          onCambio={(v) => fijar(`${ruta}.valor`, v.trim() || null)} {...propsCampo(ruta)} />
                      </td>
                    );
                  })}
                </tr>
              ))}
              <tr>
                <th scope="row">Presión intraocular <span className="unidad">mmHg</span></th>
                {OJOS.map((o) => {
                  const ruta = `pio.${o.clave}`;
                  const v = historia.pio[o.clave].valor_mmhg;
                  return (
                    <td key={o.clave}>
                      <CeldaMedicion ojo={o.clave} valor={v === null ? "" : String(v)} tipo="number" placeholder="15"
                        evidencia={historia.pio[o.clave].evidencia} etiqueta={`Presión intraocular ${o.corto}`}
                        onCambio={(t) => fijar(`${ruta}.valor_mmhg`, t === "" ? null : Number(t))} {...propsCampo(ruta)} />
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>

          {(["biomicroscopia", "fondo_de_ojo"] as const).map((seccion) => (
            <fieldset key={seccion} className="par-ojos">
              <legend>{seccion === "biomicroscopia" ? "Biomicroscopía" : "Fondo de ojo"}</legend>
              {OJOS.map((o) => (
                <CampoTexto key={o.clave} etiqueta={o.largo} claseOjo={`ojo-${o.clave}`}
                  campo={historia[seccion][o.clave]} onCambio={(v) => fijar(`${seccion}.${o.clave}.valor`, v)}
                  {...propsCampo(`${seccion}.${o.clave}`)} />
              ))}
            </fieldset>
          ))}

          <CampoTexto etiqueta="Impresión diagnóstica (tal como la dictó el médico)" campo={historia.impresion_diagnostica}
            onCambio={(v) => fijar("impresion_diagnostica.valor", v)} {...propsCampo("impresion_diagnostica")} />
          <CampoTexto etiqueta="Plan" campo={historia.plan} onCambio={(v) => fijar("plan.valor", v)}
            {...propsCampo("plan")} />
        </div>
      </div>

      <footer className="barra-confirmacion">
        <label className="medico">
          Revisado por
          <input value={medico} onChange={(e) => setMedico(e.target.value)} maxLength={120} />
        </label>
        <label className="confirmar">
          <input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} />
          Revisé la historia completa y confirmo que refleja lo que dicté
          {bloqueantes.length > 0 && ` (${bloqueantes.length - motivosPendientes(bloqueantes, resueltas)} de ${bloqueantes.length} alertas revisadas)`}
        </label>
        <div className="guardar">
          {motivos.length > 0 && <p className="motivos">{motivos.join(" · ")}</p>}
          <button className="primario" disabled={ocupado || motivos.length > 0}
            onClick={() => onGuardar(historia, [...resueltas], medico, confirmo)}>
            Guardar historia clínica
          </button>
        </div>
      </footer>
    </section>
  );
}

const motivosPendientes = (bloqueantes: Alerta[], resueltas: Set<string>) =>
  bloqueantes.filter((a) => !resueltas.has(a.id)).length;

function ListaAlertas({ alertas, resueltas, onAlternar, onUsarValor }: {
  alertas: Alerta[];
  resueltas: Set<string>;
  onAlternar: (id: string, marcar: boolean) => void;
  onUsarValor: (a: Alerta, valor: string | null) => void;
}) {
  const ordenadas = [...alertas].sort((a, b) => Number(b.bloqueante) - Number(a.bloqueante));
  return (
    <section className="alertas" aria-label="Alertas de la verificación">
      <h2>Para revisar antes de guardar</h2>
      <ul>
        {ordenadas.map((a) => (
          <li key={a.id} className={`alerta ${a.bloqueante ? "bloqueante" : "informativa"} ${resueltas.has(a.id) ? "resuelta" : ""}`}>
            <div className="alerta-texto">
              <strong>{nombreCampo(a.campo)}: {NOMBRE_ALERTA[a.tipo] ?? a.tipo}</strong>
              <p>{a.mensaje}</p>
              {a.evidencia && <q>{a.evidencia}</q>}
              {a.tipo === "conflicto" && (
                <div className="elegir-valor">
                  <button className="secundario" onClick={() => onUsarValor(a, a.valor_determinista ?? null)}>
                    Usar {a.valor_determinista} (extractor)
                  </button>
                  <button className="secundario" onClick={() => onUsarValor(a, a.valor_llm ?? null)}>
                    Usar {a.valor_llm} (IA)
                  </button>
                </div>
              )}
            </div>
            {a.bloqueante && (
              <label className="revisado">
                <input type="checkbox" checked={resueltas.has(a.id)} onChange={(e) => onAlternar(a.id, e.target.checked)} />
                Revisado
              </label>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

interface PropsCampoBase {
  alertas: Alerta[];
  resueltas: Set<string>;
  onFoco: () => void;
}

function estadoAlerta(alertas: Alerta[], resueltas: Set<string>) {
  if (alertas.some((a) => a.bloqueante && !resueltas.has(a.id))) return "con-alerta";
  if (alertas.length > 0) return "con-nota";
  return "";
}

function CampoTexto({ etiqueta, campo, onCambio, alertas, resueltas, onFoco, claseOjo = "" }: PropsCampoBase & {
  etiqueta: string;
  campo: Campo;
  onCambio: (v: string | null) => void;
  claseOjo?: string;
}) {
  return (
    <label className={`campo ${claseOjo} ${estadoAlerta(alertas, resueltas)}`}>
      <span className="campo-etiqueta">{etiqueta}</span>
      <textarea rows={2} value={campo.valor ?? ""} placeholder="No dictado" onFocus={onFoco}
        onChange={(e) => onCambio(e.target.value.trim() === "" ? null : e.target.value)} />
      <Cita evidencia={campo.evidencia} hayValor={!!campo.valor} />
    </label>
  );
}

function CeldaMedicion({ ojo, valor, evidencia, etiqueta, placeholder, tipo = "text", onCambio, alertas, resueltas, onFoco }:
  PropsCampoBase & {
    ojo: Ojo;
    valor: string;
    evidencia: string | null;
    etiqueta: string;
    placeholder: string;
    tipo?: "text" | "number";
    onCambio: (v: string) => void;
  }) {
  return (
    <div className={`celda ojo-${ojo} ${estadoAlerta(alertas, resueltas)}`}>
      <input aria-label={etiqueta} type={tipo} inputMode={tipo === "number" ? "decimal" : "text"} step="any"
        value={valor} placeholder={placeholder} onFocus={onFoco} onChange={(e) => onCambio(e.target.value)} />
      <Cita evidencia={evidencia} hayValor={valor !== ""} />
    </div>
  );
}

function Cita({ evidencia, hayValor }: { evidencia: string | null; hayValor: boolean }) {
  if (evidencia) return <q className="cita">{evidencia}</q>;
  return <span className="cita vacia">{hayValor ? "Escrito por el médico" : "No dictado"}</span>;
}

function Resaltado({ texto, cita }: { texto: string; cita: string | null }) {
  const pos = ubicarCita(texto, cita);
  if (!pos) return <p className="texto-dictado">{texto}</p>;
  return (
    <p className="texto-dictado">
      {texto.slice(0, pos[0])}
      <mark>{texto.slice(pos[0], pos[1])}</mark>
      {texto.slice(pos[1])}
    </p>
  );
}
