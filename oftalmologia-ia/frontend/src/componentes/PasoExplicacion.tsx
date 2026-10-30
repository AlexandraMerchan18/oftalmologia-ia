import { useEffect, useState } from "react";
import type { Campo, Consulta, HistoriaClinica } from "../tipos";

interface Props {
  consulta: Consulta;
  ocupado: boolean;
  onGenerar: () => void;
  onAprobar: (texto: string, medico: string, confirmo: boolean) => void;
  onNueva: () => void;
}

const METODO: Record<string, string> = {
  llm: "Redactada por la IA y verificada: no agrega diagnósticos ni cifras.",
  llm_corregida: "La IA la corrigió en un segundo intento tras fallar la verificación de seguridad.",
  plantilla: "La verificación bloqueó el texto de la IA (o la IA no respondió); se usó una plantilla segura.",
};

export function PasoExplicacion({ consulta, ocupado, onGenerar, onAprobar, onNueva }: Props) {
  const [texto, setTexto] = useState(consulta.explicacion_borrador ?? "");
  const [medico, setMedico] = useState(consulta.revisado_por ?? consulta.medico);
  const [confirmo, setConfirmo] = useState(false);
  useEffect(() => setTexto(consulta.explicacion_borrador ?? ""), [consulta.explicacion_borrador]);

  const historia = consulta.historia_final!;

  if (consulta.estado === "APROBADA") {
    return (
      <section className="tarjeta final">
        <header className="cabecera-paso">
          <h1>Consulta finalizada</h1>
          <p className="meta">
            Historia revisada por {consulta.revisado_por}. Explicación aprobada por {consulta.aprobado_por}
            {consulta.aprobado_en && ` el ${new Date(consulta.aprobado_en).toLocaleString("es-CO")}`}.
          </p>
        </header>
        <ResumenHistoria historia={historia} />
        <h2>Explicación para el paciente</h2>
        <div className="explicacion-final">{consulta.explicacion_final}</div>
        <div className="acciones">
          <button className="secundario" onClick={() => window.print()}>Imprimir</button>
          <button className="primario" onClick={onNueva}>Nueva consulta</button>
        </div>
      </section>
    );
  }

  return (
    <section className="tarjeta">
      <header className="cabecera-paso">
        <h1>Explicación para el paciente</h1>
        <p className="meta">
          Historia guardada por {consulta.revisado_por}
          {consulta.campos_corregidos?.length ? `, con ${consulta.campos_corregidos.length} correcciones del médico` : ""}.
        </p>
      </header>

      <details className="historia-guardada">
        <summary>Ver la historia clínica guardada</summary>
        <ResumenHistoria historia={historia} />
      </details>

      {consulta.estado === "GUARDADA" ? (
        <div className="vacio">
          <p>La IA redactará una explicación en lenguaje sencillo usando solo la historia que usted aprobó.</p>
          <button className="primario" disabled={ocupado} onClick={onGenerar}>Redactar explicación</button>
        </div>
      ) : (
        <>
          {consulta.explicacion_metodo && (
            <p className={`metodo metodo-${consulta.explicacion_metodo}`}>{METODO[consulta.explicacion_metodo]}</p>
          )}
          <label className="campo">
            <span className="campo-etiqueta">Texto para el paciente (puede editarlo)</span>
            <textarea rows={12} value={texto} onChange={(e) => setTexto(e.target.value)} />
          </label>
          <p className="ayuda">
            Al aprobar se agrega automáticamente un aviso: el texto fue preparado con apoyo de IA, revisado por su
            médico, y no reemplaza la consulta.
          </p>
          <footer className="barra-confirmacion">
            <label className="medico">
              Aprobado por
              <input value={medico} onChange={(e) => setMedico(e.target.value)} />
            </label>
            <label className="confirmar">
              <input type="checkbox" checked={confirmo} onChange={(e) => setConfirmo(e.target.checked)} />
              Leí la explicación y autorizo entregarla al paciente
            </label>
            <div className="guardar">
              <button className="secundario" disabled={ocupado} onClick={onGenerar}>Redactar de nuevo</button>
              <button className="primario" disabled={ocupado || !confirmo || !medico.trim() || texto.trim().length < 20}
                onClick={() => onAprobar(texto, medico, confirmo)}>
                Aprobar explicación
              </button>
            </div>
          </footer>
        </>
      )}
    </section>
  );
}

function ResumenHistoria({ historia }: { historia: HistoriaClinica }) {
  const v = (c: Campo) => c.valor ?? "—";
  const av = (ojo: "od" | "oi") =>
    `sc ${historia.agudeza_visual[ojo].sin_correccion.valor ?? "—"} · cc ${historia.agudeza_visual[ojo].con_correccion.valor ?? "—"}`;
  const pio = (ojo: "od" | "oi") => (historia.pio[ojo].valor_mmhg ?? "—") + " mmHg";
  return (
    <dl className="resumen-historia">
      <dt>Motivo de consulta</dt><dd>{v(historia.motivo_consulta)}</dd>
      <dt>Antecedentes</dt><dd>{v(historia.antecedentes)}</dd>
      <dt>Agudeza visual</dt>
      <dd><span className="ojo-od-texto">OD {av("od")}</span><span className="ojo-oi-texto">OI {av("oi")}</span></dd>
      <dt>Presión intraocular</dt>
      <dd><span className="ojo-od-texto">OD {pio("od")}</span><span className="ojo-oi-texto">OI {pio("oi")}</span></dd>
      <dt>Biomicroscopía</dt>
      <dd><span className="ojo-od-texto">OD {v(historia.biomicroscopia.od)}</span><span className="ojo-oi-texto">OI {v(historia.biomicroscopia.oi)}</span></dd>
      <dt>Fondo de ojo</dt>
      <dd><span className="ojo-od-texto">OD {v(historia.fondo_de_ojo.od)}</span><span className="ojo-oi-texto">OI {v(historia.fondo_de_ojo.oi)}</span></dd>
      <dt>Impresión diagnóstica</dt><dd>{v(historia.impresion_diagnostica)}</dd>
      <dt>Plan</dt><dd>{v(historia.plan)}</dd>
    </dl>
  );
}
