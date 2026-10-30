"""Dictados FICTICIOS para la demo (botón "Cargar ejemplo"). Ningún dato corresponde a un paciente real."""

EJEMPLOS = [
    {
        "id": "control-glaucoma",
        "titulo": "Sospecha de glaucoma (dictado completo)",
        "texto": (
            "Paciente de 58 años que consulta por visión borrosa de lejos desde hace 6 meses. "
            "Antecedente de diabetes mellitus tipo 2 en tratamiento con metformina. "
            "Agudeza visual sin corrección ojo derecho 20/50, ojo izquierdo 20/40; con corrección ojo derecho 20/25 "
            "y ojo izquierdo 20/20. Presión intraocular de 18 en ojo derecho y 24 en ojo izquierdo. "
            "Biomicroscopía: córnea clara, cristalino con opacidad nuclear leve en ambos ojos. "
            "Fondo de ojo: ojo derecho excavación 0.4, ojo izquierdo excavación 0.7 con adelgazamiento del borde inferior. "
            "Impresión diagnóstica: sospecha de glaucoma en ojo izquierdo y catarata nuclear incipiente bilateral. "
            "Plan: campimetría computarizada y OCT de nervio óptico, control en un mes con resultados."
        ),
    },
    {
        "id": "lateralidad-dificil",
        "titulo": "Lateralidad difícil (ojo dictado antes del valor)",
        "texto": (
            "Consulta por ardor y sensación de cuerpo extraño. En ojo izquierdo la presión intraocular es de 14 y "
            "en ojo derecho de 16 milímetros de mercurio. AV OD 2040 OI 20 25. "
            "Biomicroscopía con hiperemia conjuntival leve bilateral, fondo de ojo normal en ambos ojos. "
            "Impresión diagnóstica: ojo seco. Plan: lágrimas artificiales cada 4 horas y control en 3 meses."
        ),
    },
    {
        "id": "dictado-ambiguo",
        "titulo": "Dictado ambiguo (debe generar alertas)",
        "texto": (
            "Paciente que viene a control. Ojo derecho agudeza visual 20/30, PIO 15, ojo izquierdo agudeza visual "
            "20/60, PIO 19. La presión es 17. Fondo de ojo sin hallazgos. Plan: control anual."
        ),
    },
]
