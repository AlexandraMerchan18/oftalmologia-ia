import { describe, expect, it } from "vitest";
import type { Alerta, HistoriaClinica } from "../tipos";
import { alertasDeCampo, conValor, motivosBloqueo, puedeGuardar, ubicarCita } from "./revision";

const alerta = (id: string, bloqueante = true, campo = "pio.od"): Alerta => ({
  id, campo, tipo: "conflicto", bloqueante, mensaje: "x",
});

describe("revisión obligatoria", () => {
  it("bloquea el guardado mientras haya alertas bloqueantes sin revisar", () => {
    const e = { alertas: [alerta("a"), alerta("b", false)], resueltas: new Set<string>(), medico: "Dra. X", confirmo: true };
    expect(puedeGuardar(e)).toBe(false);
    expect(motivosBloqueo(e)).toEqual(["Falta revisar 1 alerta"]);
    expect(puedeGuardar({ ...e, resueltas: new Set(["a"]) })).toBe(true); // la no bloqueante no exige revisión
  });

  it("exige médico y confirmación explícita", () => {
    const e = { alertas: [], resueltas: new Set<string>(), medico: "  ", confirmo: false };
    expect(motivosBloqueo(e)).toHaveLength(2);
  });

  it("asocia alertas derivadas a su campo", () => {
    const alertas = [alerta("1", true, "pio.od"), alerta("2", true, "pio.od.ambigua"), alerta("3", true, "pio.oi")];
    expect(alertasDeCampo(alertas, "pio.od").map((a) => a.id)).toEqual(["1", "2"]);
  });

  it("edita un valor anidado sin mutar el original", () => {
    const h = { pio: { od: { valor_mmhg: 15, evidencia: null } } } as unknown as HistoriaClinica;
    const nueva = conValor(h, "pio.od.valor_mmhg", 17);
    expect(nueva.pio.od.valor_mmhg).toBe(17);
    expect(h.pio.od.valor_mmhg).toBe(15);
  });

  it("ubica la cita ignorando mayúsculas", () => {
    expect(ubicarCita("PIO de 15 en Ojo Derecho", "15 en ojo derecho")).toEqual([7, 24]);
    expect(ubicarCita("texto", "otra cosa")).toBeNull();
  });
});
