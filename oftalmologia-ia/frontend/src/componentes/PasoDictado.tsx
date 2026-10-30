import { useEffect, useRef, useState } from "react";
import type { Consulta, Ejemplo } from "../tipos";

interface Props {
  consulta: Consulta | null;
  ejemplos: Ejemplo[];
  ocupado: boolean;
  onCrear: (paciente: string, medico: string) => void;
  onAudio: (audio: Blob, nombre: string) => void;
  onExtraer: (textoEditado: string | null) => void;
}

type Modo = "grabar" | "archivo" | "texto";

export function PasoDictado({ consulta, ejemplos, ocupado, onCrear, onAudio, onExtraer }: Props) {
  const [paciente, setPaciente] = useState("");
  const [medico, setMedico] = useState(() => localStorageSeguro("medico") ?? "");
  const [modo, setModo] = useState<Modo>("grabar");
  const [texto, setTexto] = useState(consulta?.transcripcion ?? "");

  useEffect(() => setTexto(consulta?.transcripcion ?? ""), [consulta?.transcripcion]);

  if (!consulta) {
    return (
      <section className="tarjeta inicio">
        <h1>Nueva consulta</h1>
        <p className="ayuda">
          Dicte la consulta como lo haría normalmente. La IA la convierte en un borrador de historia clínica
          que usted revisa antes de guardar. La IA documenta; no diagnostica.
        </p>
        <form
          className="formulario-inicio"
          onSubmit={(e) => {
            e.preventDefault();
            guardarLocal("medico", medico);
            onCrear(paciente, medico);
          }}
        >
          <label>
            Identificador del paciente
            <input value={paciente} onChange={(e) => setPaciente(e.target.value)} placeholder="Ej. HC-2026-0457"
              required maxLength={64} />
            <small>Use un código interno, no el nombre del paciente.</small>
          </label>
          <label>
            Médico tratante
            <input value={medico} onChange={(e) => setMedico(e.target.value)} placeholder="Ej. Dra. Marcela Ríos"
              required maxLength={120} />
          </label>
          <button className="primario" disabled={ocupado || !paciente.trim() || !medico.trim()}>
            Iniciar dictado
          </button>
        </form>
      </section>
    );
  }

  const transcrita = consulta.transcripcion !== null;
  const editado = transcrita && texto.trim() !== (consulta.transcripcion ?? "").trim();

  return (
    <section className="tarjeta">
      <header className="cabecera-paso">
        <h1>Dictado</h1>
        <p className="meta">Paciente {consulta.paciente_ref}, {consulta.medico}</p>
      </header>

      <div className="pestanas" role="tablist">
        {(["grabar", "archivo", "texto"] as Modo[]).map((m) => (
          <button key={m} role="tab" aria-selected={modo === m} className={modo === m ? "activa" : ""}
            onClick={() => setModo(m)}>
            {{ grabar: "Grabar con el micrófono", archivo: "Subir un audio", texto: "Escribir o pegar" }[m]}
          </button>
        ))}
      </div>

      {modo === "grabar" && <Grabadora deshabilitada={ocupado} onListo={(b) => onAudio(b, nombreArchivo(b))} />}

      {modo === "archivo" && (
        <div className="zona-audio">
          <label className="boton-archivo">
            Elegir archivo de audio
            <input type="file" accept="audio/*,.webm,.m4a,.mp3,.wav,.ogg" disabled={ocupado}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onAudio(f, f.name);
                e.target.value = "";
              }} />
          </label>
          <p className="ayuda">webm, wav, mp3, m4a u ogg. Hasta 25 MB. El audio se elimina apenas se transcribe.</p>
        </div>
      )}

      {modo === "texto" && !transcrita && ejemplos.length > 0 && (
        <div className="ejemplos">
          <span>Dictados de ejemplo (ficticios):</span>
          {ejemplos.map((ej) => (
            <button key={ej.id} className="enlace" onClick={() => setTexto(ej.texto)}>{ej.titulo}</button>
          ))}
        </div>
      )}

      {(transcrita || modo === "texto") && (
        <div className="transcripcion">
          <label htmlFor="texto-dictado">
            {transcrita ? "Transcripción (puede corregirla antes de extraer)" : "Dictado"}
          </label>
          <textarea id="texto-dictado" value={texto} rows={9} onChange={(e) => setTexto(e.target.value)}
            placeholder="Paciente consulta por… Agudeza visual sin corrección ojo derecho 20/40…" />
          <div className="acciones">
            {consulta.duracion_audio_s && consulta.fuente_transcripcion !== "texto" && (
              <span className="meta">Audio de {consulta.duracion_audio_s.toFixed(0)} s transcrito con Whisper</span>
            )}
            <button className="primario" disabled={ocupado || texto.trim().length < 10}
              onClick={() => onExtraer(!transcrita || editado ? texto : null)}>
              Generar borrador con IA
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function Grabadora({ deshabilitada, onListo }: { deshabilitada: boolean; onListo: (b: Blob) => void }) {
  const [grabando, setGrabando] = useState(false);
  const [segundos, setSegundos] = useState(0);
  const [aviso, setAviso] = useState<string | null>(null);
  const grabador = useRef<MediaRecorder | null>(null);
  const trozos = useRef<Blob[]>([]);

  useEffect(() => {
    if (!grabando) return;
    const t = setInterval(() => setSegundos((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [grabando]);

  async function iniciar() {
    setAviso(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setAviso("Este navegador no permite grabar. Use “Subir un audio” o “Escribir o pegar”.");
      return;
    }
    try {
      const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      const tipo = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
      const g = new MediaRecorder(flujo, tipo ? { mimeType: tipo } : undefined);
      trozos.current = [];
      g.ondataavailable = (e) => e.data.size > 0 && trozos.current.push(e.data);
      g.onstop = () => {
        flujo.getTracks().forEach((t) => t.stop());
        onListo(new Blob(trozos.current, { type: g.mimeType || "audio/webm" }));
      };
      g.start(1000);
      grabador.current = g;
      setSegundos(0);
      setGrabando(true);
    } catch {
      setAviso("No se pudo usar el micrófono. Revise el permiso del navegador para este sitio.");
    }
  }

  function detener() {
    grabador.current?.stop();
    setGrabando(false);
  }

  const mmss = `${Math.floor(segundos / 60)}:${String(segundos % 60).padStart(2, "0")}`;
  return (
    <div className="zona-audio">
      {grabando ? (
        <button className="grabar activo" onClick={detener}>
          <span className="punto" aria-hidden /> Detener y transcribir · {mmss}
        </button>
      ) : (
        <button className="grabar" onClick={iniciar} disabled={deshabilitada}>
          <span className="punto" aria-hidden /> Empezar a grabar
        </button>
      )}
      <p className="ayuda">
        Dicte ojo por ojo y nombre el ojo en cada dato: “presión intraocular, ojo derecho 15, ojo izquierdo 17”.
      </p>
      {aviso && <p className="aviso-linea">{aviso}</p>}
    </div>
  );
}

function nombreArchivo(b: Blob) {
  return b.type.includes("mp4") ? "dictado.m4a" : "dictado.webm";
}

function localStorageSeguro(clave: string): string | null {
  try {
    return localStorage.getItem(clave);
  } catch {
    return null;
  }
}

function guardarLocal(clave: string, valor: string) {
  try {
    localStorage.setItem(clave, valor);
  } catch {
    /* almacenamiento no disponible: no es crítico */
  }
}
