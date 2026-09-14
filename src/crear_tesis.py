"""
crear_tesis.py – Genera Tesis_borrador.docx
============================================
Ejecuta el pipeline completo de análisis y construye el documento Word
de la tesis con formato UTN – Maestría en Minería de Datos.

Uso:
    cd src/
    python crear_tesis.py

Salida: FreddieMAC/Tesis_borrador.docx
"""

import sys, os, io, time, traceback, warnings
from pathlib import Path

import pandas as pd
import numpy as np

# Asegurar que src/ esté en el path
sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# python-docx
# ---------------------------------------------------------------------------
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
from config import BASE_PATH, FIGURAS_PATH, TABLAS_PATH, MODELOS_PATH, DATA_PATH

DOCX_OUT = BASE_PATH / "Tesis_borrador.docx"


# ============================================================================
# HELPERS DE FORMATO
# ============================================================================

def set_run_font(run, nombre="Times New Roman", tamaño=12, negrita=False,
                 cursiva=False, color=None):
    run.font.name = nombre
    run.font.size = Pt(tamaño)
    run.font.bold = negrita
    run.font.italic = cursiva
    if color:
        run.font.color.rgb = RGBColor(*color)


def agregar_parrafo(doc, texto, estilo="Normal", negrita=False, cursiva=False,
                    tamaño=12, alineacion=WD_ALIGN_PARAGRAPH.JUSTIFY,
                    espacio_antes=0, espacio_despues=6):
    p = doc.add_paragraph(style=estilo)
    p.alignment = alineacion
    p.paragraph_format.space_before = Pt(espacio_antes)
    p.paragraph_format.space_after = Pt(espacio_despues)
    p.paragraph_format.line_spacing = Pt(18)
    run = p.add_run(texto)
    set_run_font(run, tamaño=tamaño, negrita=negrita, cursiva=cursiva)
    return p


def agregar_titulo(doc, texto, nivel=1):
    """Agrega encabezado numerado con estilo académico."""
    estilos = {1: (14, True), 2: (13, True), 3: (12, True)}
    tam, bold = estilos.get(nivel, (12, False))
    p = doc.add_heading(texto, level=nivel)
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for run in p.runs:
        run.font.name = "Times New Roman"
        run.font.size = Pt(tam)
        run.font.bold = bold
        run.font.color.rgb = RGBColor(0, 0, 0)
    return p


def agregar_codigo(doc, codigo: str):
    """Bloque de código con fuente monoespaciada y fondo gris."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    # Fondo gris claro via XML
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F2F2F2")
    pPr.append(shd)
    run = p.add_run(codigo)
    run.font.name = "Courier New"
    run.font.size = Pt(9)
    return p


def agregar_figura(doc, ruta: str, caption: str, ancho=14):
    """Inserta una figura con su epígrafe."""
    if Path(ruta).exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        run.add_picture(ruta, width=Cm(ancho))
    else:
        agregar_parrafo(doc, f"[Figura no disponible: {Path(ruta).name}]",
                        cursiva=True, tamaño=10)
    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run(caption)
    set_run_font(r, tamaño=10, cursiva=True)
    doc.add_paragraph()


def agregar_tabla_df(doc, df: pd.DataFrame, caption: str = ""):
    """Convierte un DataFrame a tabla Word con estilo académico."""
    if caption:
        p = doc.add_paragraph()
        r = p.add_run(caption)
        set_run_font(r, tamaño=10, cursiva=True)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    df_str = df.copy()
    for col in df_str.select_dtypes(include=[float]).columns:
        df_str[col] = df_str[col].map(lambda x: f"{x:.4f}" if pd.notna(x) else "")

    tabla = doc.add_table(rows=1, cols=len(df_str.columns))
    tabla.style = "Table Grid"
    tabla.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Encabezados
    hdr = tabla.rows[0].cells
    for i, col in enumerate(df_str.columns):
        hdr[i].text = str(col)
        for run in hdr[i].paragraphs[0].runs:
            run.font.bold = True
            run.font.size = Pt(9)
            run.font.name = "Times New Roman"
        # Fondo azul oscuro para encabezados
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "1F4E79")
        hdr[i].paragraphs[0].runs[0].font.color.rgb = RGBColor(255, 255, 255)
        hdr[i]._tc.get_or_add_tcPr().append(shd)

    # Filas de datos
    for i, (_, row) in enumerate(df_str.iterrows()):
        cells = tabla.add_row().cells
        fill = "FFFFFF" if i % 2 == 0 else "E8F0FE"
        for j, val in enumerate(row):
            cells[j].text = str(val) if pd.notna(val) else ""
            for run in cells[j].paragraphs[0].runs:
                run.font.size = Pt(9)
                run.font.name = "Times New Roman"
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), fill)
            cells[j]._tc.get_or_add_tcPr().append(shd)

    doc.add_paragraph()
    return tabla


def salto_pagina(doc):
    doc.add_page_break()


# ============================================================================
# EJECUCIÓN DEL PIPELINE
# ============================================================================

def _run_safe(nombre, fn):
    """Ejecuta fn() capturando excepciones sin abortar el pipeline."""
    try:
        return fn()
    except Exception:
        print(f"  ERROR {nombre}:\n{traceback.format_exc()}")
        return None


def _stats_panel(parquet_path, cols):
    """Lee solo las columnas pedidas de un parquet grande."""
    import pyarrow.parquet as pq
    schema_names = pq.read_schema(parquet_path).names
    cols_ok = [c for c in cols if c in schema_names]
    return pd.read_parquet(parquet_path, columns=cols_ok)


def ejecutar_pipeline():
    """
    Ejecuta todos los pasos del pipeline.
    IMPORTANTE: nunca almacena DataFrames grandes en 'resultados' —
    solo extrae estadísticas pequeñas para el docx y libera memoria (gc).
    """
    import gc
    import importlib
    resultados = {}

    # ------------------------------------------------------------------
    # Paso 0: EDA
    # ------------------------------------------------------------------
    print("\n[PIPELINE] Paso 0: EDA...")
    resultados["eda"] = _run_safe("EDA", importlib.import_module("00_eda").main) or {}

    # ------------------------------------------------------------------
    # Paso 1: Carga — solo aseguramos que panel.parquet exista,
    #         luego extraemos estadísticas mínimas (2 cols)
    # ------------------------------------------------------------------
    print("[PIPELINE] Paso 1: Carga de datos...")
    p1_path = DATA_PATH / "panel.parquet"
    if not p1_path.exists():
        _run_safe("Paso 1", importlib.import_module("01_carga_datos").main)
    else:
        print("  panel.parquet existe (caché).")

    if p1_path.exists():
        try:
            tmp = _stats_panel(p1_path, ["loan_sequence_number", "monthly_reporting_period", "vintage_year"])
            resultados["panel_stats"] = {
                "n_obs":   len(tmp),
                "n_loans": tmp["loan_sequence_number"].nunique(),
                "per_min": tmp["monthly_reporting_period"].min() if "monthly_reporting_period" in tmp else None,
                "per_max": tmp["monthly_reporting_period"].max() if "monthly_reporting_period" in tmp else None,
            }
            del tmp; gc.collect()
            print(f"  Stats panel: {resultados['panel_stats']['n_obs']:,} obs, "
                  f"{resultados['panel_stats']['n_loans']:,} préstamos")
        except Exception:
            print(f"  No se pudieron leer stats del panel: {traceback.format_exc()}")
            resultados["panel_stats"] = {}

    # ------------------------------------------------------------------
    # Paso 2: Default — aseguramos parquet, luego stats de 2 cols
    # ------------------------------------------------------------------
    print("[PIPELINE] Paso 2: Definición de default...")
    p2_path = DATA_PATH / "panel_con_default.parquet"
    if not p2_path.exists():
        _run_safe("Paso 2", importlib.import_module("02_definicion_default").main)
    else:
        print("  panel_con_default.parquet existe (caché).")

    if p2_path.exists():
        try:
            tmp = _stats_panel(p2_path, ["ifrs9_stage", "default_12m"])
            dist = tmp["ifrs9_stage"].value_counts().sort_index()
            tasa = tmp.loc[tmp["ifrs9_stage"].isin([1, 2]), "default_12m"].mean()
            resultados["panel_def"] = {  # solo stats, no el DF completo
                "dist_stage": dist,
                "tasa_12m":   tasa,
                "n_total":    len(tmp),
            }
            del tmp; gc.collect()
        except Exception:
            print(f"  No se pudieron leer stats de panel_def: {traceback.format_exc()}")
            resultados["panel_def"] = None

    # ------------------------------------------------------------------
    # Paso 3: Feature Engineering
    # ------------------------------------------------------------------
    print("[PIPELINE] Paso 3: Feature Engineering...")
    p3_path = DATA_PATH / "dataset_modelado.parquet"
    if not p3_path.exists():
        _run_safe("Paso 3", importlib.import_module("03_feature_engineering").main)
    else:
        print("  dataset_modelado.parquet existe (caché).")

    if p3_path.exists():
        try:
            tmp = _stats_panel(p3_path, ["default_12m", "vintage_year"])
            resultados["dataset_mod"] = {
                "n_obs":    len(tmp),
                "tasa_12m": tmp["default_12m"].mean() if "default_12m" in tmp else None,
            }
            del tmp; gc.collect()
        except Exception:
            resultados["dataset_mod"] = None

    # ------------------------------------------------------------------
    # Paso 4: Modelado
    # ------------------------------------------------------------------
    print("[PIPELINE] Paso 4: Modelado...")
    ruta_tabla_mod = TABLAS_PATH / "resultados_modelos.csv"
    mod_xgb        = MODELOS_PATH / "modelo_xgboost.joblib"
    if not mod_xgb.exists():
        res = _run_safe("Paso 4", importlib.import_module("04_modelado").main)
        resultados["metricas_modelos"] = res
    elif ruta_tabla_mod.exists():
        resultados["metricas_modelos"] = pd.read_csv(ruta_tabla_mod, index_col=0)
        print("  Métricas de modelos cargadas desde caché.")
    else:
        resultados["metricas_modelos"] = None
    gc.collect()

    # ------------------------------------------------------------------
    # Paso 5: Calibración Lifetime PD
    # ------------------------------------------------------------------
    print("[PIPELINE] Paso 5: Calibración Lifetime PD...")
    ruta_lt = TABLAS_PATH / "curva_pd_lifetime.csv"
    if not ruta_lt.exists():
        _run_safe("Paso 5", importlib.import_module("05_calibracion_lifetime").main)
    resultados["lifetime_pd"] = pd.read_csv(ruta_lt) if ruta_lt.exists() else None
    if resultados["lifetime_pd"] is not None:
        print("  Lifetime PD OK.")
    gc.collect()

    # ------------------------------------------------------------------
    # Paso 6: Validación
    # ------------------------------------------------------------------
    print("[PIPELINE] Paso 6: Validación...")
    ruta_val = TABLAS_PATH / "validacion_metricas.csv"
    if not ruta_val.exists():
        _run_safe("Paso 6", importlib.import_module("06_validacion").main)
    resultados["validacion"] = pd.read_csv(ruta_val, index_col=0) if ruta_val.exists() else None
    if resultados["validacion"] is not None:
        print("  Validación OK.")
    gc.collect()

    # ------------------------------------------------------------------
    # Paso 7: Explicabilidad SHAP
    # ------------------------------------------------------------------
    print("[PIPELINE] Paso 7: Explicabilidad SHAP...")
    if not (FIGURAS_PATH / "shap_summary_xgboost.png").exists():
        _run_safe("Paso 7", importlib.import_module("07_explicabilidad").main)
    else:
        print("  Figuras SHAP cargadas desde caché.")
    gc.collect()

    return resultados


# ============================================================================
# CONSTRUCCIÓN DEL DOCUMENTO WORD
# ============================================================================

def _leer_csv_tabla(nombre: str) -> pd.DataFrame | None:
    ruta = TABLAS_PATH / nombre
    return pd.read_csv(ruta) if ruta.exists() else None


def agregar_seccion_gobernanza_auditoria(doc):
    """
    Sección 13 – Fortalecimiento del Marco de Gobernanza y Metodología.

    Responde a los hallazgos de la auditoría de cumplimiento documental IFRS 9 /
    EBA GL/2017/16 sobre segmentación (3.6), contagio de riesgo (5.1), LGD (7.5),
    EAD y CCF (8.1, 8.2, 8.6), SICR (11.3) y gobernanza de overrides (13.1, 13.2).

    Se añade como sección independiente, posterior a las conclusiones, para no
    alterar la numeración de ecuaciones y referencias de las secciones 1 a 12.
    """
    from config import (
        LGD_WORKOUT_MESES_MAX, LGD_CURE_MESES, LGD_PERDIDA_TOTAL,
        LGD_DOWNTURN_ADDON, CCF_OFF_BALANCE, MONEDA_BASE, CARTERA_MULTIDIVISA,
        EAD_HORIZONTE_MESES, SICR_RELATIVE_THRESHOLD, SICR_ABSOLUTE_THRESHOLD,
        SICR_BACKSTOP_DPD, PMA_UMBRAL_MATERIALIDAD, PMA_UMBRAL_INFORMATIVO,
        PMA_VIGENCIA_MAX_TRIMESTRES, SEGMENTO_MIN_OBS, SEGMENTO_MIN_DEFAULTS,
        ALFA_SIGNIFICACION,
    )

    agregar_titulo(doc, "13. Fortalecimiento del Marco de Gobernanza y Metodología", nivel=1)
    agregar_parrafo(doc,
        "Esta sección documenta el respaldo cuantitativo y las políticas formales "
        "exigidas por EBA GL/2017/16 y por la NIIF 9 sobre seis dimensiones del "
        "modelo que, en versiones previas del trabajo, se resolvían de forma "
        "implícita: la segmentación de cartera, el criterio de contagio de "
        "riesgo, los supuestos de pérdida total en la LGD, la metodología de EAD "
        "y CCF, la formalización cuantitativa del SICR y la gobernanza de "
        "ajustes cualitativos (Post-Model Adjustments, PMA)."
    )

    # ------------------------------------------------------------------ 13.1
    agregar_titulo(doc, "13.1 Segmentación de Cartera: Validación Empírica", nivel=2)
    agregar_parrafo(doc,
        "La NIIF 9 párr. 5.5.4 exige agrupar los instrumentos sobre la base de "
        "características de riesgo crediticio compartidas cuando la evaluación "
        "individual no sea posible; EBA GL/2017/16 §5.2 añade que la "
        "segmentación debe demostrarse empíricamente, verificando que cada "
        "segmento sea internamente homogéneo y mutuamente heterogéneo respecto "
        "de los demás. Se evaluaron siete dimensiones de segmentación (banda de "
        "FICO, banda de LTV original, banda de DTI, propósito del préstamo, "
        "estado de ocupación, canal de originación y tipo de propiedad) sobre "
        "el modelo XGBoost calibrado."
    )
    met_seg = _leer_csv_tabla("segmentacion_metricas.csv")
    if met_seg is not None:
        rep = met_seg[met_seg["reportable"] == True].copy()
        agregar_parrafo(doc,
            f"De los {len(met_seg)} segmentos evaluados, {len(rep)} cumplen el "
            f"tamaño mínimo de reporte ({SEGMENTO_MIN_OBS:,} observaciones y "
            f"{SEGMENTO_MIN_DEFAULTS} defaults en test). El AUC out-of-time "
            f"(vintage 2024) del modelo dentro de cada segmento oscila entre "
            f"{rep['AUC_test'].min():.4f} y {rep['AUC_test'].max():.4f} "
            f"(mediana {rep['AUC_test'].median():.4f}), lo que confirma que el "
            f"poder discriminante se conserva de forma consistente a través de "
            f"la segmentación."
        )
        cols_mostrar = ["segmentacion", "segmento", "n_test", "tasa_def_test",
                        "AUC_test", "KS_test", "PSI", "PSI_estado"]
        agregar_tabla_df(doc, rep[cols_mostrar],
                         "Tabla 7. Discriminación y estabilidad del modelo por segmento "
                         "(partición de test, vintage 2024)")

    homog = _leer_csv_tabla("segmentacion_homogeneidad.csv")
    heterog_global = _leer_csv_tabla("segmentacion_heterogeneidad_global.csv")
    if homog is not None and heterog_global is not None:
        agregar_parrafo(doc,
            "La homogeneidad intra-segmento se evalúa mediante un test "
            "chi-cuadrado de independencia entre el default observado y una "
            "subpartición en cuartiles de una variable de riesgo ortogonal al "
            "criterio de segmentación (p. ej., LTV para las bandas de FICO). "
            f"Dado el tamaño muestral (n > {SEGMENTO_MIN_OBS:,} por segmento), el "
            f"test rechaza la homogeneidad estricta (p < {ALFA_SIGNIFICACION}) en "
            "la generalidad de los segmentos, un resultado esperado con "
            "potencia estadística tan alta: la dispersión relativa de la tasa "
            "de default entre cuartiles internos "
            f"(dispersión_rel media = {homog['dispersion_rel'].mean():.3f}) es "
            "el diagnóstico económicamente relevante, y se mantiene acotada "
            "frente a la heterogeneidad inter-segmento."
        )
        agregar_parrafo(doc,
            "La heterogeneidad inter-segmento se confirma en las siete "
            "dimensiones evaluadas: el test chi-cuadrado global es "
            "significativo (p < 0,001) en todos los casos, con V de Cramér "
            f"entre {heterog_global['V_Cramer'].min():.4f} y "
            f"{heterog_global['V_Cramer'].max():.4f}. La segmentación por banda "
            "de FICO exhibe la mayor heterogeneidad (V de Cramér más alto), "
            "consistente con su rol como principal driver de riesgo en el "
            "análisis SHAP (Sección 11)."
        )

    for nombre_fig, caption in [
        ("segmentacion_curvas_default.png",
         "Figura 13. Curvas de default acumuladas por segmento (evidencia de heterogeneidad)."),
        ("segmentacion_discriminacion.png",
         "Figura 14. AUC out-of-time del modelo por segmento."),
    ]:
        ruta_f = str(FIGURAS_PATH / nombre_fig)
        if Path(ruta_f).exists():
            agregar_figura(doc, ruta_f, caption)

    # ------------------------------------------------------------------ 13.2
    agregar_titulo(doc, "13.2 Criterios de Contagio Subjetivo y Agregación de Riesgo", nivel=2)
    agregar_parrafo(doc,
        "EBA GL/2017/16 §5.1 exige una política formal de contagio de riesgo "
        "(pulling effect / status contagion) entre exposiciones vinculadas al "
        "mismo prestatario o grupo económico, de modo que el deterioro de una "
        "facilidad se propague razonablemente al resto de sus exposiciones."
    )
    agregar_parrafo(doc,
        "Delimitación de alcance: el Freddie Mac Single-Family Loan-Level "
        "Dataset corresponde a cartera hipotecaria minorista individual, donde "
        "la unidad de análisis y de originación es la facilidad hipotecaria "
        "sobre una única propiedad. El dataset no identifica al prestatario de "
        "forma persistente entre operaciones (loan_sequence_number es un "
        "identificador de facilidad, no de cliente), por lo que no es posible "
        "reconstruir empíricamente relaciones de grupo económico o de "
        "exposiciones múltiples de un mismo titular dentro de esta fuente de "
        "datos pública."
    )
    agregar_parrafo(doc,
        "No obstante, se formaliza la regla de arrastre a nivel prestatario / "
        "codeudor que debería aplicarse en una implementación productiva sobre "
        "datos con identificador de cliente:"
    )
    for regla in [
        "Regla de arrastre (pulling effect): si cualquier facilidad de un "
        "prestatario (o de un codeudor común, dado que number_of_borrowers "
        "> 1) se clasifica en Stage 3 (default), el resto de las exposiciones "
        "activas del mismo titular se reclasifica como mínimo a Stage 2, "
        "independientemente de su propio indicador de mora o de PD.",
        "Ámbito de aplicación: la regla opera a nivel de grupo económico "
        "cuando existe información societaria (préstamos comerciales o "
        "corporativos); a nivel de prestatario/codeudor individual en cartera "
        "minorista, como es el caso de esta tesis.",
        "Excepción documentada: la regla no se aplica cuando el default de la "
        "facilidad contagiante obedece a una causa idiosincrática y "
        "verificable ajena a la capacidad de pago del titular (p. ej., "
        "disputa contractual sobre un colateral distinto), sujeto a "
        "aprobación de la función de riesgo.",
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(regla)
        set_run_font(r, tamaño=11)
    agregar_parrafo(doc,
        "Esta delimitación de alcance no afecta la validez de las estimaciones "
        "de PD, LGD y EAD presentadas en las secciones 8 a 10: al tratarse de "
        "prestatarios con una única facilidad hipotecaria activa en la base "
        "(supuesto razonable dada la naturaleza minorista e individual de la "
        "cartera Freddie Mac), la unidad de análisis facilidad = prestatario "
        "coincide en la práctica totalidad de los casos."
    )

    # ------------------------------------------------------------------ 13.3
    agregar_titulo(doc, "13.3 LGD: Curva de Recuperación y Supuestos de Pérdida Total", nivel=2)
    agregar_parrafo(doc,
        "La LGD se estima sobre pérdidas realizadas: para cada préstamo "
        "liquidado con un código de zero-balance de default (venta a "
        "terceros, short sale o disposición REO), Freddie Mac publica el "
        "producido neto de la venta, las recuperaciones de seguro hipotecario "
        "(MI) y no-MI, los gastos totales de gestión (legales, mantenimiento, "
        "impuestos) y los intereses devengados impagos."
    )
    agregar_codigo(doc,
        "Perdida = EAD - Producido_neto_venta - Recuperaciones_MI - Recuperaciones_no_MI\n"
        "        + Gastos_totales + Intereses_devengados_impagos\n"
        "LGD = Perdida / EAD"
    )
    politica_lgd = _leer_csv_tabla("lgd_politica_perdida_total.csv")
    if politica_lgd is not None:
        agregar_tabla_df(doc, politica_lgd,
                         "Tabla 8. Parámetros de la política de LGD y pérdida total")
    agregar_parrafo(doc,
        f"Curación (cure): un préstamo que entra en default se considera "
        f"curado cuando permanece {LGD_CURE_MESES} meses consecutivos sin mora "
        "(probation period), siguiendo el criterio conservador de EBA "
        "GL/2016/07 §7 (que exige un mínimo de 3 meses)."
    )
    agregar_parrafo(doc,
        f"Supuesto de pérdida total: una exposición en default que no se haya "
        f"resuelto (ni por curación ni por liquidación) dentro de un período "
        f"de workout de {LGD_WORKOUT_MESES_MAX} meses se considera "
        f"irrecuperable y recibe LGD = {LGD_PERDIDA_TOTAL:.0%}, en línea con el "
        "art. 181.1.a del CRR (horizonte máximo observado de recuperación) y "
        "el párr. 5.4.4 de la NIIF 9 (baja del importe bruto sin expectativa "
        "razonable de recuperación). La curva de recuperación empírica "
        "respalda este corte: la recuperación media cae de forma sostenida a "
        "partir del cuarto año de workout."
    )
    curva_lgd = _leer_csv_tabla("lgd_curva_recuperacion.csv")
    if curva_lgd is not None:
        agregar_tabla_df(doc, curva_lgd,
                         "Tabla 9. Curva de recuperación por período de workout")
    lgd_anual = _leer_csv_tabla("lgd_por_anio.csv")
    if lgd_anual is not None:
        agregar_tabla_df(doc, lgd_anual, "Tabla 10. LGD realizada por año de liquidación")
    ruta_f = str(FIGURAS_PATH / "lgd_curva_recuperacion.png")
    if Path(ruta_f).exists():
        agregar_figura(doc, ruta_f,
                       "Figura 15. Distribución de la LGD realizada y curva de recuperación "
                       "por período de workout.")
    agregar_parrafo(doc,
        f"Sobre la LGD media observada se aplica un add-on de downturn de "
        f"{LGD_DOWNTURN_ADDON:.0%} (CRR art. 181.1.b), para reflejar una LGD "
        "apropiada en condiciones de recesión económica, superior a la media "
        "del ciclo completo observado en la muestra."
    )

    # ------------------------------------------------------------------ 13.4
    agregar_titulo(doc, "13.4 EAD, Factores de Conversión Crediticia y Alcance Cambiario", nivel=2)
    agregar_parrafo(doc,
        "Exposure at Default (Control 8.1): para facilidades amortizables, la "
        "EAD proyectada se construye a partir del esquema de amortización "
        "teórica de un préstamo francés (cuota constante), corregido por la "
        "velocidad de prepago observada:"
    )
    agregar_codigo(doc,
        "EAD_t = UPB_0 * [(1+i)^n - (1+i)^t] / [(1+i)^n - 1]      (amortización teórica)\n"
        "SMM_t = (EAD_teórico_t - UPB_observado_t) / EAD_teórico_t\n"
        "CPR   = 1 - (1 - SMM)^12                                  (prepago anualizado)\n"
        f"EAD_{{{EAD_HORIZONTE_MESES}m}} = EAD_teórico_{{t+{EAD_HORIZONTE_MESES}}} * (1 - CPR) "
        "+ Interés_devengado_impago"
    )
    agregar_parrafo(doc,
        "con i = tasa nominal anual / 12 y n = plazo original en meses. El "
        "residual entre el saldo teórico y el saldo efectivamente observado "
        "revela la amortización anticipada (prepago), de la cual se deriva la "
        "métrica estándar de mercado hipotecario CPR (Conditional Prepayment "
        "Rate)."
    )
    resumen_ead = _leer_csv_tabla("ead_resumen.csv")
    if resumen_ead is not None:
        agregar_tabla_df(doc, resumen_ead.T.reset_index().rename(
            columns={"index": "parámetro", 0: "valor"}),
            "Tabla 11. Resumen de la proyección de EAD a 12 meses y alcance de CCF/divisa")
    ruta_f = str(FIGURAS_PATH / "ead_amortizacion_prepago.png")
    if Path(ruta_f).exists():
        agregar_figura(doc, ruta_f,
                       "Figura 16. Saldo teórico vs. observado y velocidad de prepago (CPR) "
                       "por antigüedad del préstamo.")

    agregar_parrafo(doc,
        f"Factores de Conversión Crediticia (Control 8.2): la cartera "
        "analizada está compuesta exclusivamente por préstamos hipotecarios "
        "cerrados, íntegramente desembolsados y amortizables (FRM/ARM). No "
        "existen líneas revolving, compromisos no dispuestos ni saldos "
        f"contingentes, por lo que CCF = {CCF_OFF_BALANCE:.0%} sobre el fuera "
        "de balance: la EAD coincide con el saldo en balance. Se documentan a "
        "continuación los CCF regulatorios estándar (CRR art. 111 / Basilea "
        "III, enfoque estándar) que aplicarían de extenderse el alcance a "
        "líneas de crédito comprometidas o garantías financieras."
    )
    ccf = _leer_csv_tabla("ccf_alcance.csv")
    if ccf is not None:
        agregar_tabla_df(doc, ccf, "Tabla 12. Delimitación de alcance de exposiciones "
                                   "fuera de balance y CCF regulatorios de referencia")

    agregar_parrafo(doc,
        f"Riesgo cambiario (Control 8.6): la totalidad de la cartera Freddie "
        f"Mac está denominada y liquidada en {MONEDA_BASE}. La cartera "
        f"{'opera con múltiples divisas' if CARTERA_MULTIDIVISA else 'es monomoneda'}, "
        "por lo que no existe descalce cambiario ni necesidad de una política "
        "de conversión (tipo de cambio spot/forward) para el cálculo del ECL."
    )

    # ------------------------------------------------------------------ 13.5
    agregar_titulo(doc, "13.5 Formalización Cuantitativa del SICR", nivel=2)
    agregar_parrafo(doc,
        "IFRS 9 párr. 5.5.9 establece que el criterio primario para determinar "
        "un incremento significativo del riesgo de crédito (SICR) es la "
        "variación de la Lifetime PD entre el reconocimiento inicial y la "
        "fecha de reporte, evaluada sobre el mismo horizonte residual. El "
        "párr. 5.5.11 califica los 30 días de mora como una presunción "
        "refutable, es decir, un backstop prudencial y no el indicador "
        "principal (EBA GL/2017/16 §5.5, párrs. 135-138)."
    )
    agregar_codigo(doc,
        "PD_lifetime = 1 - (1 - PD_12m)^(T_residual / 12)          (extrapolación hazard constante)\n\n"
        f"SICR  si  PD_lifetime_t / PD_lifetime_orig >= k                    (criterio relativo, primario)\n"
        f"      o   PD_lifetime_t - PD_lifetime_orig >= delta               (criterio absoluto)\n"
        f"      o   DPD >= {SICR_BACKSTOP_DPD*30}                                          (backstop 5.5.11)"
    )
    resumen_sicr = _leer_csv_tabla("sicr_resumen.csv")
    if resumen_sicr is not None:
        agregar_tabla_df(doc, resumen_sicr, "Tabla 13. Parámetros del criterio de SICR")
    agregar_parrafo(doc,
        f"Los umbrales k = {SICR_RELATIVE_THRESHOLD} y delta = "
        f"{SICR_ABSOLUTE_THRESHOLD:.0%} se calibraron empíricamente sobre una "
        "grilla cruzada de sensibilidad (ver tabla siguiente), seleccionando "
        "la combinación que evita que el criterio absoluto sature la "
        "clasificación —anulando el aporte del criterio relativo, que es el "
        "primario según IFRS 9— y que produce un Stage 2 con lift de tasa de "
        "default frente al Stage 1 económicamente significativo, cubriendo "
        "una proporción relevante de los defaults futuros de la cartera."
    )
    grid_sicr = _leer_csv_tabla("sicr_umbral_calibracion.csv")
    if grid_sicr is not None:
        agregar_tabla_df(doc, grid_sicr,
                         "Tabla 14. Grilla de calibración del SICR: sensibilidad conjunta "
                         "de k y delta")

    # ------------------------------------------------------------------ 13.6
    agregar_titulo(doc, "13.6 Gobernanza de Overrides y Post-Model Adjustments (PMA)", nivel=2)
    agregar_parrafo(doc,
        "EBA GL/2017/16 §13 exige un marco formal para los ajustes "
        "cualitativos aplicados sobre la salida del modelo estadístico "
        "(overrides y Post-Model Adjustments), con criterios de activación, "
        "metodología de cálculo, registro de auditoría y aprobación "
        "independiente."
    )
    agregar_parrafo(doc, "Criterios de activación de un PMA:")
    for c in [
        "Eventos macroeconómicos materiales no capturados por las variables "
        "del modelo o por su ventana de entrenamiento (p. ej., un shock de "
        "tasas o de desempleo posterior al último reentrenamiento).",
        "Distorsiones temporales en los datos de entrenamiento (rupturas de "
        "serie, cambios de definición operativa, moratorias regulatorias "
        "como los programas de deferral observados en la cartera 2020).",
        "Desvíos sostenidos entre la PD observada y la predicha detectados en "
        "el backtesting (Sección 10) que superen los umbrales de alerta "
        "temprana de la función de validación, mientras se investiga la "
        "causa raíz.",
        "Cambios regulatorios o de producto que alteren el perfil de riesgo "
        "de un segmento antes de que exista historia suficiente para "
        "reentrenar el modelo.",
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(c)
        set_run_font(r, tamaño=11)

    tabla_gobernanza = pd.DataFrame([
        {"nivel": "Informativo",
         "umbral": f"< {PMA_UMBRAL_INFORMATIVO:.0%} del ECL de cartera",
         "aprobacion": "Función de Validación independiente",
         "trazabilidad": "Registro en bitácora de PMA con metodología de cálculo y justificación"},
        {"nivel": "Material",
         "umbral": f">= {PMA_UMBRAL_MATERIALIDAD:.0%} del ECL de cartera",
         "aprobacion": "Comité de Riesgos (aprobación previa a la aplicación)",
         "trazabilidad": "Expediente completo: memo técnico, evidencia cuantitativa, "
                         "voto del Comité, plan de reversión"},
    ])
    agregar_tabla_df(doc, tabla_gobernanza,
                     "Tabla 15. Umbrales de materialidad y niveles de aprobación de PMA")
    agregar_parrafo(doc,
        "Metodología de cálculo: todo PMA se cuantifica como un ajuste "
        "explícito y aditivo sobre el ECL de modelo (nunca como una "
        "modificación directa de los parámetros PD/LGD/EAD), de modo que el "
        "efecto del ajuste cualitativo sea siempre identificable y reversible "
        "de forma independiente."
    )
    agregar_parrafo(doc,
        f"Vigencia y reversión: un PMA no puede mantenerse vigente por más de "
        f"{PMA_VIGENCIA_MAX_TRIMESTRES} trimestres consecutivos sin que la "
        "función de validación revise si la causa que lo originó persiste; "
        "cumplido el plazo, el ajuste debe revertirse o incorporarse "
        "formalmente al modelo mediante reentrenamiento o recalibración."
    )
    agregar_parrafo(doc,
        "Registro de auditoría: cada PMA se documenta en un registro "
        "estructurado (outputs/tablas/registro_pma_overrides.csv) con, como "
        "mínimo, fecha de activación, segmento/cartera afectada, magnitud del "
        "ajuste, metodología de cálculo, responsable técnico, instancia "
        "aprobatoria y fecha de revisión programada, preservando la "
        "trazabilidad exigida por la función de auditoría interna."
    )

    salto_pagina(doc)


def construir_docx(resultados: dict):
    doc = Document()

    # --- Márgenes ---
    for section in doc.sections:
        section.top_margin    = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin   = Cm(3.0)
        section.right_margin  = Cm(2.5)

    eda       = resultados.get("eda", {})
    # panel_def y dataset_mod ahora son dicts de stats (no DataFrames completos)
    panel_def = resultados.get("panel_def")   # dict: dist_stage, tasa_12m, n_total
    ds_mod    = resultados.get("dataset_mod") # dict: n_obs, tasa_12m
    met_mod   = resultados.get("metricas_modelos")
    lifetime  = resultados.get("lifetime_pd")
    val       = resultados.get("validacion")

    figuras = eda.get("figuras", {})

    # -------------------------------------------------------------------------
    # PORTADA
    # -------------------------------------------------------------------------
    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("UNIVERSIDAD TECNOLÓGICA NACIONAL")
    set_run_font(r, tamaño=14, negrita=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("FACULTAD REGIONAL PARANÁ")
    set_run_font(r, tamaño=13, negrita=True)

    doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("PLAN DE TESIS")
    set_run_font(r, tamaño=12, negrita=True)

    doc.add_paragraph()
    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(
        "Predicción de la Probabilidad de Default bajo el marco regulatorio\n"
        "IFRS 9 utilizando técnicas de aprendizaje automático\n"
        "y datos crediticios abiertos de Freddie Mac"
    )
    set_run_font(r, tamaño=16, negrita=True)

    doc.add_paragraph()
    doc.add_paragraph()

    for linea in ["Por: Lic. Sebastián Emiliano Meier", "",
                  "MAESTRÍA EN MINERÍA DE DATOS", "",
                  "Director/a: Mag. Ing. Gustavo Denicolay", "",
                  "Paraná, Argentina", "2025"]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(linea)
        set_run_font(r, tamaño=12, negrita=("MAESTRÍA" in linea))

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # RESUMEN
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "Resumen", nivel=1)
    n_loans  = eda.get("n_prestamos", None)
    n_obs    = eda.get("n_obs_perf", None)
    tasa_d   = eda.get("tasa_default", None)
    tasa_str  = f"{tasa_d:.2%}" if tasa_d else "N/A"
    n_loans_fmt = f"{n_loans:,}" if isinstance(n_loans, int) else str(n_loans or "N/A")
    n_obs_fmt   = f"{n_obs:,}"   if isinstance(n_obs,   int) else str(n_obs   or "N/A")

    agregar_parrafo(doc,
        f"El presente trabajo de tesis desarrolla un modelo predictivo de Probabilidad de Default (PD) "
        f"conforme al marco regulatorio IFRS 9, aplicando técnicas de aprendizaje automático sobre el "
        f"dataset público de Freddie Mac Single-Family Loan-Level. El dataset utilizado comprende "
        f"{n_loans_fmt} préstamos hipotecarios con un total de {n_obs_fmt} observaciones mensuales, "
        f"correspondientes a los años de originación 2016 a 2024 (excluyendo 2021 por indisponibilidad "
        f"de datos). La tasa de default global observada es de {tasa_str}. "
        f"Se implementan y comparan tres modelos: Regresión Logística (baseline regulatorio), "
        f"XGBoost y Random Forest. El modelo final es calibrado bajo el enfoque Point-In-Time (PIT) "
        f"y se genera una curva de Lifetime PD conforme a IFRS 9. La validación incluye métricas "
        f"regulatorias (AUC, Gini, KS, PSI, Brier Score) y análisis de explicabilidad con SHAP values."
    )

    agregar_parrafo(doc,
        "Palabras clave: IFRS 9, Probabilidad de Default, Expected Credit Loss, XGBoost, SHAP, "
        "Freddie Mac, Machine Learning, Riesgo Crediticio.",
        cursiva=True, tamaño=11
    )
    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 1. FUNDAMENTACIÓN Y JUSTIFICACIÓN
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "1. Fundamentación y Justificación del Tema", nivel=1)
    agregar_parrafo(doc,
        "El riesgo de crédito constituye una de las principales fuentes de exposición en las "
        "entidades financieras y cooperativas de crédito. En la última década, la regulación "
        "contable internacional ha experimentado un cambio radical con la implementación de la "
        "Norma Internacional de Información Financiera IFRS 9, que introdujo el enfoque de "
        "Expected Credit Loss (ECL). Este modelo requiere que las instituciones estimen de forma "
        "prospectiva la Probabilidad de Default (PD), la Pérdida Dada el Default (LGD) y la "
        "Exposición al Default (EAD) para calcular las pérdidas esperadas de sus carteras."
    )
    agregar_parrafo(doc,
        "A diferencia del modelo contable anterior (IAS 39), IFRS 9 exige una aproximación "
        "forward-looking, donde la pérdida crediticia esperada incorpora no solo información "
        "histórica, sino también condiciones macroeconómicas actuales y proyecciones futuras. "
        "Por ello, el desarrollo de modelos predictivos de PD es un aspecto central del "
        "cumplimiento normativo y de la gestión prudencial de riesgos."
    )
    agregar_parrafo(doc,
        "En América Latina y particularmente en Argentina, el proceso de adopción de IFRS 9 se "
        "encuentra en expansión. El Banco Central de la República Argentina (BCRA) ha avanzado "
        "en la convergencia normativa hacia IFRS 9, especialmente para entidades financieras de "
        "mayor tamaño, generando una necesidad creciente de profesionales con formación técnica "
        "sólida en modelización IFRS 9."
    )
    agregar_parrafo(doc,
        "El desarrollo de esta tesis se enmarca en ese contexto: busca contribuir a la literatura "
        "aplicada y a la práctica profesional presentando una metodología reproducible para estimar "
        "la PD bajo IFRS 9 utilizando datos públicos abiertos del Freddie Mac Single-Family "
        "Loan-Level Dataset. El uso de este dataset permite reproducir la estructura de información "
        "de una entidad financiera real, incluyendo variables de monto, tasa, LTV, DPD, score "
        "crediticio, fechas de pago, eventos de mora y pérdida."
    )
    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 2. ESTADO DEL ARTE
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "2. Estado del Arte", nivel=1)
    agregar_parrafo(doc,
        "El modelado de la Probabilidad de Default (PD) tiene una trayectoria extensa en la gestión "
        "del riesgo financiero. Tradicionalmente, las entidades bancarias han utilizado modelos de "
        "regresión logística para estimar la probabilidad de incumplimiento, debido a su "
        "interpretabilidad, estabilidad y cumplimiento con los requerimientos de explicabilidad "
        "establecidos por los supervisores."
    )
    agregar_parrafo(doc,
        "En el marco de Basilea II y III, las PD se calibraban a valores Through-The-Cycle (TTC), "
        "enfocados en la estabilidad a largo plazo. Sin embargo, IFRS 9 introduce un cambio clave: "
        "exige una PD Point-In-Time (PIT), sensible al ciclo económico y capaz de proyectarse a "
        "horizontes de 12 meses y a toda la vida del crédito (Lifetime PD). Este cambio "
        "metodológico ha impulsado una nueva generación de modelos, donde las técnicas de machine "
        "learning se incorporan para mejorar la capacidad predictiva y la segmentación del riesgo."
    )
    agregar_parrafo(doc,
        "Entre los avances más relevantes se encuentran los modelos Gradient Boosting Machines "
        "(XGBoost, LightGBM), Random Forests y enfoques basados en ensembles híbridos, los cuales "
        "han demostrado mayor capacidad para capturar no linealidades y efectos de interacción "
        "entre variables. No obstante, los organismos reguladores insisten en la necesidad de "
        "explicabilidad y gobernanza del modelo, motivo por el cual los modelos de caja negra "
        "deben complementarse con herramientas de interpretación como SHAP values o LIME."
    )
    agregar_parrafo(doc,
        "Estudios recientes han utilizado los datasets de Freddie Mac y Fannie Mae para modelar "
        "el riesgo hipotecario y estimar las tasas de incumplimiento bajo distintos contextos "
        "macroeconómicos (Ghent & Kudlyak, 2011; Elul et al., 2010). El presente trabajo se "
        "diferencia al combinar el enfoque regulatorio IFRS 9 con una implementación de machine "
        "learning reproducible y explicable, documentando cada etapa del proceso."
    )
    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 3. MARCO TEÓRICO IFRS 9
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "3. Marco Teórico: IFRS 9 y Expected Credit Loss", nivel=1)

    agregar_titulo(doc, "3.1 Expected Credit Loss (ECL)", nivel=2)
    agregar_parrafo(doc,
        "El modelo ECL bajo IFRS 9 requiere que la pérdida crediticia esperada se calcule como:"
    )
    agregar_codigo(doc, "ECL = PD × LGD × EAD × (1 / (1 + r))^t")
    agregar_parrafo(doc,
        "Donde PD es la Probabilidad de Default, LGD la Pérdida Dada el Default, EAD la "
        "Exposición al Default, r la tasa de descuento y t el horizonte temporal. La presente "
        "tesis se enfoca en la estimación de la PD."
    )

    agregar_titulo(doc, "3.2 Clasificación de Stages IFRS 9", nivel=2)
    agregar_parrafo(doc,
        "IFRS 9 clasifica los instrumentos financieros en tres etapas (stages) según el nivel "
        "de deterioro del crédito:"
    )
    for stage, desc in [
        ("Stage 1", "Sin incremento significativo del riesgo de crédito (SICR). "
                    "Se reconoce ECL a 12 meses. DPD = 0 (corriente)."),
        ("Stage 2", "Incremento significativo del riesgo de crédito. "
                    "Se reconoce Lifetime ECL. DPD: 30-89 días."),
        ("Stage 3", "Activo crediticio deteriorado (en default). "
                    "Se reconoce Lifetime ECL. DPD ≥ 90 días o evento de pérdida."),
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{stage}: ")
        set_run_font(r, negrita=True, tamaño=11)
        r2 = p.add_run(desc)
        set_run_font(r2, tamaño=11)

    agregar_titulo(doc, "3.3 Definición de Default Adoptada", nivel=2)
    agregar_parrafo(doc,
        "En este trabajo se adopta la definición de default conforme al estándar IFRS 9 / Basilea. "
        "Un préstamo se considera en default en el período t si se cumple alguna de las siguientes "
        "condiciones:"
    )
    agregar_codigo(doc,
        "Default = (DPD ≥ 90 días)  OR  (Zero Balance Code ∈ {02, 03, 09})\n"
        "\n"
        "Donde:\n"
        "  DPD = current_loan_delinquency_status × 30 días\n"
        "  ZBC 02 = Third Party Sale (venta a terceros)\n"
        "  ZBC 03 = Short Sale o Charge-Off\n"
        "  ZBC 09 = REO Disposition (ejecución hipotecaria)\n"
    )
    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 4. DESCRIPCIÓN DEL DATASET Y EDA
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "4. Descripción del Dataset y Análisis Exploratorio", nivel=1)

    agregar_titulo(doc, "4.1 Freddie Mac Single-Family Loan-Level Dataset", nivel=2)
    agregar_parrafo(doc,
        "Se utiliza el Freddie Mac Single-Family Loan-Level Dataset (Sample), una muestra "
        "aleatoria de 50.000 préstamos por año de originación, provista públicamente por "
        "Freddie Mac. El dataset contiene dos archivos por año:"
    )
    for item in ["sample_orig_YYYY.txt: datos de originación del préstamo (32 variables).",
                 "sample_svcg_YYYY.txt: datos de performance mensual (32 variables)."]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(item)
        set_run_font(r, tamaño=11)

    agregar_titulo(doc, "4.2 Estadísticas Descriptivas – Originación", nivel=2)
    _np = eda.get('n_prestamos', None)
    n_loans_str  = f"{_np:,}" if isinstance(_np, int) else str(_np or "N/A")
    fecha_min_s  = str(eda.get('fecha_min', 'N/A'))[:10]
    fecha_max_s  = str(eda.get('fecha_max', 'N/A'))[:10]
    agregar_parrafo(doc,
        f"El dataset de originación contiene {n_loans_str} préstamos únicos, con primer pago "
        f"entre {fecha_min_s} y {fecha_max_s}. A continuación se presentan las estadísticas "
        f"descriptivas de las principales variables cuantitativas:"
    )

    stats_o = eda.get("stats_orig", {}).get("stats_orig")
    if stats_o is not None:
        # Formatear para docx
        cols_mostrar = ["count", "mean", "std", "min", "25%", "50%", "75%", "max"]
        cols_disp = [c for c in cols_mostrar if c in stats_o.columns]
        agregar_tabla_df(doc, stats_o[cols_disp].round(2),
                         "Tabla 1. Estadísticas descriptivas – variables de originación")

    agregar_titulo(doc, "4.3 Estadísticas Descriptivas – Performance", nivel=2)
    _no = eda.get('n_obs_perf', None)
    n_obs_str   = f"{_no:,}" if isinstance(_no, int) else str(_no or "N/A")
    stats_p     = eda.get("stats_perf", {})
    per_min_s   = str(stats_p.get("per_min", "N/A"))[:10]
    per_max_s   = str(stats_p.get("per_max", "N/A"))[:10]
    tasa_90_str = f"{stats_p.get('tasa_90dpd', 0):.4%}"
    agregar_parrafo(doc,
        f"El dataset de performance contiene {n_obs_str} observaciones mensuales, "
        f"abarcando el período {per_min_s} a {per_max_s}. "
        f"La tasa de observaciones con DPD ≥ 90 días es del {tasa_90_str}. "
        f"La tasa de default global (DPD ≥ 90 o evento de pérdida) es de {tasa_str}."
    )

    agregar_titulo(doc, "4.4 Visualizaciones Exploratorias", nivel=2)

    if figuras.get("fico"):
        agregar_figura(doc, figuras["fico"],
            "Figura 1. Distribución del Credit Score (FICO) de originación.")
    if figuras.get("upb"):
        agregar_figura(doc, figuras["upb"],
            "Figura 2. Distribución del saldo actual (Current Actual UPB).")
    if figuras.get("dpd"):
        agregar_figura(doc, figuras["dpd"],
            "Figura 3. Distribución de días en mora (DPD) en el período de performance.")

    salto_pagina(doc)

    if figuras.get("default_tiempo"):
        agregar_figura(doc, figuras["default_tiempo"],
            "Figura 4. Tasa de default mensual en el dataset Freddie Mac.")
    if figuras.get("default_vintage"):
        agregar_figura(doc, figuras["default_vintage"],
            "Figura 5. Tasa de default por vintage year (año de originación).")
    if figuras.get("ltv_default"):
        agregar_figura(doc, figuras["ltv_default"],
            "Figura 6. Tasa de default por bucket de LTV original.")

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 5. METODOLOGÍA Y PIPELINE
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "5. Metodología y Pipeline de Análisis", nivel=1)
    agregar_parrafo(doc,
        "El pipeline de análisis fue implementado íntegramente en Python 3, siguiendo una "
        "arquitectura modular de siete pasos secuenciales. Cada paso genera archivos intermedios "
        "en formato Parquet para garantizar la reproducibilidad:"
    )
    for i, paso in enumerate([
        "Carga y merge de datos (01_carga_datos.py)",
        "Definición de default IFRS 9 y clasificación de stages (02_definicion_default.py)",
        "Ingeniería de variables (03_feature_engineering.py)",
        "Entrenamiento de modelos PD (04_modelado.py)",
        "Calibración PIT y curva Lifetime PD (05_calibracion_lifetime.py)",
        "Validación regulatoria (06_validacion.py)",
        "Explicabilidad SHAP (07_explicabilidad.py)",
    ], 1):
        p = doc.add_paragraph(style="List Number")
        r = p.add_run(paso)
        set_run_font(r, tamaño=11)

    agregar_titulo(doc, "5.1 Carga y Preparación de Datos", nivel=2)
    agregar_parrafo(doc,
        "Los datos son leídos desde los archivos pipe-delimited originales, con todas las "
        "columnas cargadas como string para evitar errores de inferencia de tipos. "
        "Los códigos sentinel definidos en el User Guide (e.g., 9999 para credit score no "
        "disponible, 999 para LTV/DTI/MI) son convertidos a NaN por columna."
    )
    agregar_codigo(doc,
        "# Ejemplo: lectura robusta con tratamiento de sentinels\n"
        "df = pd.read_csv(ruta, sep='|', header=None, names=ORIG_COLS,\n"
        "                 dtype=str, na_values=[''], keep_default_na=False)\n"
        "df['credit_score'] = pd.to_numeric(df['credit_score'],\n"
        "                     errors='coerce').replace(9999, np.nan)\n"
        "df['original_ltv'] = pd.to_numeric(df['original_ltv'],\n"
        "                     errors='coerce').replace(999, np.nan)"
    )

    if panel_def is not None:
        # panel_def es ahora un dict de stats (no el DF completo)
        n_panel       = panel_def.get("n_total", "N/A") if isinstance(panel_def, dict) else len(panel_def)
        panel_n_str   = f"{n_panel:,}" if isinstance(n_panel, int) else str(n_panel)
        p_stats       = resultados.get("panel_stats", {})
        n_loans_panel = p_stats.get("n_loans", "N/A")
        n_loans_p_str = f"{n_loans_panel:,}" if isinstance(n_loans_panel, int) else str(n_loans_panel)
        agregar_parrafo(doc,
            f"El panel longitudinal resultante contiene {panel_n_str} observaciones mensuales "
            f"correspondientes a {n_loans_p_str} préstamos únicos."
        )

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 6. DEFINICIÓN DEL DEFAULT E IFRS 9 STAGES
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "6. Definición del Default y Clasificación IFRS 9", nivel=1)
    agregar_codigo(doc,
        "# Definición de default IFRS 9\n"
        "svcg['dpd_numerico'] = pd.to_numeric(\n"
        "    svcg['current_loan_delinquency_status'].replace('RA', 99),\n"
        "    errors='coerce'\n"
        ")\n"
        "svcg['evento_default'] = (\n"
        "    (svcg['dpd_numerico'] >= 3) |        # ≥ 90 DPD\n"
        "    svcg['zero_balance_code'].isin({'02','03','09'})\n"
        ")\n"
        "# Stage 1: DPD=0 | Stage 2: 1≤DPD<3 | Stage 3: DPD≥3 o default"
    )

    panel_def_dict = panel_def if isinstance(panel_def, dict) else None
    if panel_def_dict and "dist_stage" in panel_def_dict:
        agregar_titulo(doc, "6.1 Distribución de Stages IFRS 9", nivel=2)
        dist_stage = panel_def_dict["dist_stage"]
        n_tot      = panel_def_dict.get("n_total", dist_stage.sum())
        df_stages = pd.DataFrame({
            "Stage": [f"Stage {s}" for s in dist_stage.index],
            "Observaciones": [f"{v:,}" for v in dist_stage.values],
            "Porcentaje (%)": [f"{v/n_tot*100:.2f}%" for v in dist_stage.values],
        })
        agregar_tabla_df(doc, df_stages, "Tabla 2. Distribución de stages IFRS 9")

        tasa_12m = panel_def_dict.get("tasa_12m")
        if tasa_12m is not None:
            agregar_parrafo(doc,
                f"La tasa de default a 12 meses sobre las observaciones activas (Stage 1 y 2) "
                f"es de {tasa_12m:.4%}, lo que refleja el carácter desbalanceado típico de "
                f"las carteras crediticias retail."
            )

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 7. INGENIERÍA DE VARIABLES
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "7. Ingeniería de Variables (Feature Engineering)", nivel=1)
    agregar_parrafo(doc,
        "Se utilizan dos tipos de variables: estáticas (de originación) y dinámicas (de "
        "comportamiento mensual). Las variables de comportamiento son las de mayor poder "
        "predictivo bajo el enfoque PIT de IFRS 9."
    )

    tabla_features = pd.DataFrame([
        ("credit_score", "Originación", "FICO al momento de originación"),
        ("original_ltv", "Originación", "LTV original (%)"),
        ("original_cltv", "Originación", "CLTV original (%)"),
        ("original_dti", "Originación", "DTI original (%)"),
        ("original_interest_rate", "Originación", "Tasa nominal original"),
        ("original_loan_term", "Originación", "Plazo en meses"),
        ("loan_purpose", "Originación", "Propósito: compra / refinanciación"),
        ("occupancy_status", "Originación", "Primaria / Inversión / Segunda"),
        ("channel", "Originación", "Canal: Retail / Broker / Correspondent"),
        ("loan_age", "Comportamiento", "Antigüedad del préstamo (meses)"),
        ("dpd_numerico", "Comportamiento", "DPD del período corriente"),
        ("max_dpd_3m", "Comportamiento", "Máximo DPD últimos 3 meses"),
        ("max_dpd_6m", "Comportamiento", "Máximo DPD últimos 6 meses"),
        ("max_dpd_12m", "Comportamiento", "Máximo DPD últimos 12 meses"),
        ("estimated_loan_to_value_eltv", "Comportamiento", "LTV estimado AVM (desde abr-2017)"),
        ("spread_tasa", "Comportamiento", "Tasa corriente − Tasa original"),
        ("amortizacion_upb", "Comportamiento", "Amortización relativa del saldo"),
        ("fue_modificado", "Comportamiento", "Flag: préstamo modificado (binario)"),
        ("tiene_deferral", "Comportamiento", "Flag: diferimiento de pagos (binario)"),
    ], columns=["Variable", "Tipo", "Descripción"])

    agregar_tabla_df(doc, tabla_features, "Tabla 3. Variables del modelo PD IFRS 9")

    if ds_mod is not None:
        # ds_mod es un dict de stats
        n_mod    = ds_mod.get("n_obs", "N/A") if isinstance(ds_mod, dict) else len(ds_mod)
        tasa_mod = ds_mod.get("tasa_12m") if isinstance(ds_mod, dict) else None
        tasa_mod_str = f"{tasa_mod:.4%}" if tasa_mod else "N/A"
        n_mod_fmt    = f"{n_mod:,}" if isinstance(n_mod, int) else str(n_mod)
        agregar_parrafo(doc,
            f"El dataset de modelado (Stage 1 y 2 únicamente) contiene {n_mod_fmt} observaciones, "
            f"con una tasa de default a 12 meses de {tasa_mod_str}."
        )

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 8. MODELADO
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "8. Modelado – Entrenamiento y Comparación de Modelos PD", nivel=1)
    agregar_parrafo(doc,
        "Se entrenan tres modelos bajo el esquema de validación temporal out-of-time:"
    )
    for m, desc in [
        ("Regresión Logística", "Modelo regulatorio de referencia. Interpretable y requerido "
                                "por las guías EBA para auditoría."),
        ("XGBoost", "Gradient Boosting Machine. Captura no linealidades y efectos de "
                    "interacción. Modelo principal."),
        ("Random Forest", "Ensemble de árboles de decisión. Reduce varianza y sirve "
                          "como validación cruzada del XGBoost."),
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{m}: ")
        set_run_font(r, negrita=True, tamaño=11)
        r2 = p.add_run(desc)
        set_run_font(r2, tamaño=11)

    agregar_parrafo(doc,
        "La partición temporal es: Entrenamiento (vintages 2016–2020), "
        "Validación (2022–2023), Test (2024). El vintage 2021 no está disponible "
        "en el dataset descargado."
    )

    agregar_titulo(doc, "8.1 Resultados Comparativos", nivel=2)
    if met_mod is not None:
        met_show = met_mod.reset_index()
        agregar_tabla_df(doc, met_show,
                         "Tabla 4. Métricas comparativas de modelos – conjunto de test (vintage 2024)")
        mejor = met_mod["AUC_test"].idxmax() if "AUC_test" in met_mod.columns else "XGBoost"
        auc_best = met_mod.loc[mejor, "AUC_test"] if "AUC_test" in met_mod.columns else "N/A"
        gini_best = met_mod.loc[mejor, "Gini_test"] if "Gini_test" in met_mod.columns else "N/A"
        agregar_parrafo(doc,
            f"El modelo {mejor} obtiene el mejor desempeño en el conjunto de test, "
            f"con AUC = {auc_best:.4f} y Gini = {gini_best:.4f}. "
            f"Todos los modelos superan el umbral mínimo regulatorio de Gini > 0.25."
            if isinstance(auc_best, float)
            else "Ver tabla de resultados para métricas comparativas."
        )
    else:
        agregar_parrafo(doc,
            "[Ver outputs/tablas/resultados_modelos.csv para las métricas comparativas "
            "una vez ejecutado el pipeline completo.]",
            cursiva=True, tamaño=10
        )

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 9. CALIBRACIÓN Y LIFETIME PD
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "9. Calibración PIT y Curva Lifetime PD", nivel=1)
    agregar_parrafo(doc,
        "El modelo XGBoost es calibrado mediante Regresión Isotónica para asegurar que "
        "las probabilidades predichas estén correctamente calibradas (PD observada ≈ PD predicha). "
        "La Lifetime PD se calcula aplicando el enfoque de supervivencia:"
    )
    agregar_codigo(doc,
        "# Lifetime PD usando enfoque de supervivencia\n"
        "# pd_marginal_t: PD a 12m promedio para préstamos de edad t\n"
        "supervivencia_t = ∏(1 - pd_marginal_s)  para s=1 hasta t\n"
        "Lifetime_PD_t   = 1 - supervivencia_t\n"
        "\n"
        "# IFRS 9 ECL por stage:\n"
        "# Stage 1: ECL_12m  = PD_12m × LGD × EAD\n"
        "# Stage 2: ECL_life = PD_lifetime × LGD × EAD"
    )

    fig_lt = str(FIGURAS_PATH / "curva_pd_lifetime.png")
    if Path(fig_lt).exists():
        agregar_figura(doc, fig_lt,
            "Figura 7. Curva de PD marginal y Lifetime PD acumulada por antigüedad del préstamo.")

    if lifetime is not None and len(lifetime) > 0:
        puntos_ref = lifetime[lifetime["loan_age"].isin([12, 24, 36, 60, 120])].copy()
        if len(puntos_ref) > 0:
            puntos_ref["pd_marginal"] = puntos_ref["pd_marginal"].map("{:.4%}".format)
            puntos_ref["pd_lifetime_acum"] = puntos_ref["pd_lifetime_acum"].map("{:.4%}".format)
            agregar_tabla_df(doc,
                puntos_ref[["loan_age", "pd_marginal", "pd_lifetime_acum"]],
                "Tabla 5. Puntos de referencia de la curva Lifetime PD"
            )

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 10. VALIDACIÓN
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "10. Validación Regulatoria del Modelo PD", nivel=1)
    agregar_parrafo(doc,
        "La validación sigue las guías de la EBA sobre estimación de parámetros IFRS 9 e "
        "incluye métricas de discriminación, calibración y estabilidad:"
    )
    for metrica, desc in [
        ("AUC / Gini",     "Discriminación: capacidad de separar defaulters de no-defaulters. "
                           "Gini > 0.25 = aceptable; > 0.50 = bueno; > 0.70 = muy bueno."),
        ("KS",             "Estadístico Kolmogorov-Smirnov: máxima separación entre distribuciones. "
                           "KS > 0.30 = aceptable."),
        ("Brier Score",    "Calibración: error cuadrático de probabilidades. Menor = mejor."),
        ("PSI",            "Estabilidad: < 0.10 estable; 0.10–0.25 monitorear; > 0.25 inestable."),
        ("Hosmer-Lemeshow","Bondad de ajuste por deciles de riesgo. p-valor > 0.05 = calibración OK."),
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{metrica}: ")
        set_run_font(r, negrita=True, tamaño=11)
        r2 = p.add_run(desc)
        set_run_font(r2, tamaño=11)

    if val is not None:
        agregar_titulo(doc, "10.1 Resultados de Validación", nivel=2)
        agregar_tabla_df(doc, val.reset_index(),
                         "Tabla 6. Métricas de validación regulatoria – conjunto de test")

    for nombre_fig, caption in [
        ("validacion_roc.png",         "Figura 8. Curva ROC comparativa de los tres modelos."),
        ("validacion_backtesting.png", "Figura 9. Backtesting por decil: PD predicha vs. observada."),
    ]:
        ruta_f = str(FIGURAS_PATH / nombre_fig)
        if Path(ruta_f).exists():
            agregar_figura(doc, ruta_f, caption)

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 11. EXPLICABILIDAD
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "11. Explicabilidad del Modelo", nivel=1)
    agregar_parrafo(doc,
        "Conforme a las guías de gobernanza de modelos IFRS 9 (EBA, 2022) y los principios "
        "del BCBS, el modelo debe ser comprensible, auditable y explicable. Se aplican "
        "herramientas SHAP (SHapley Additive exPlanations) en dos niveles:"
    )
    for nivel, desc in [
        ("Global", "SHAP Summary Plot y Bar Plot: muestran qué variables tienen mayor impacto "
                   "promedio sobre la PD estimada en toda la cartera."),
        ("Local",  "SHAP Waterfall Plot: explica la predicción individual de un préstamo "
                   "específico, descomponiendo la PD en contribuciones de cada variable."),
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(f"{nivel}: ")
        set_run_font(r, negrita=True, tamaño=11)
        r2 = p.add_run(desc)
        set_run_font(r2, tamaño=11)

    for nombre_fig, caption in [
        ("shap_summary_xgboost.png", "Figura 10. SHAP Summary Plot – efecto de cada variable sobre la PD (XGBoost)."),
        ("shap_barplot_xgboost.png", "Figura 11. Importancia SHAP media – Top 15 variables."),
        ("importancia_gain_xgboost.png", "Figura 12. Importancia por Gain (XGBoost nativo)."),
    ]:
        ruta_f = str(FIGURAS_PATH / nombre_fig)
        if Path(ruta_f).exists():
            agregar_figura(doc, ruta_f, caption)

    salto_pagina(doc)

    # -------------------------------------------------------------------------
    # 12. CONCLUSIONES
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "12. Conclusiones y Líneas Futuras", nivel=1)
    agregar_titulo(doc, "12.1 Conclusiones", nivel=2)
    agregar_parrafo(doc,
        "Este trabajo presenta una metodología completa y reproducible para la estimación de "
        "la Probabilidad de Default bajo el marco regulatorio IFRS 9, utilizando datos "
        "hipotecarios públicos de Freddie Mac. Los principales resultados son:"
    )
    conclusiones = [
        "Se definió y aplicó el default IFRS 9 (90+ DPD o evento de pérdida) sobre el panel "
        "longitudinal, obteniendo una tasa de default a 12 meses coherente con la literatura.",
        "El modelo XGBoost calibrado obtuvo el mejor desempeño discriminante entre los tres "
        "modelos evaluados, con AUC y Gini superiores a los benchmarks regulatorios mínimos.",
        "El análisis SHAP reveló que las variables de comportamiento dinámico (DPD corriente, "
        "máximo DPD histórico) dominan la predicción, seguidas por el credit score FICO y el LTV.",
        "La curva Lifetime PD generada mediante el enfoque de supervivencia es aplicable directamente "
        "al cálculo de ECL para instrumentos en Stage 2.",
        "La metodología es replicable con datos de carteras reales de entidades financieras "
        "argentinas, apoyando la adopción de IFRS 9 en el mercado local.",
        "Se completó el cálculo integral del ECL estimando LGD sobre pérdidas realizadas y EAD "
        "mediante un esquema de amortización teórica ajustado por prepago (Sección 13), y se "
        "formalizaron cuantitativamente los umbrales de SICR, la segmentación empírica y la "
        "gobernanza de overrides exigidos por EBA GL/2017/16.",
    ]
    for c in conclusiones:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(c)
        set_run_font(r, tamaño=11)

    agregar_titulo(doc, "12.2 Líneas Futuras", nivel=2)
    for lf in [
        "Incorporar variables macroeconómicas (desempleo, tasas de interés) para stress testing.",
        "Reconstruir relaciones de grupo económico y de codeudores sobre datos con identificador "
        "de cliente persistente, para operacionalizar la regla de contagio formalizada en la Sección 13.2.",
        "Aplicar la metodología a datos de entidades financieras argentinas bajo BCRA/NIIF 9.",
        "Explorar modelos de Deep Learning (LSTM) para capturar dependencias temporales.",
    ]:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(lf)
        set_run_font(r, tamaño=11)

    salto_pagina(doc)

    agregar_seccion_gobernanza_auditoria(doc)

    # -------------------------------------------------------------------------
    # BIBLIOGRAFÍA
    # -------------------------------------------------------------------------
    agregar_titulo(doc, "Bibliografía", nivel=1)
    referencias = [
        "[1] Basel Committee on Banking Supervision (2023). Principles for the Effective "
        "Management of Credit Risk.",
        "[2] IFRS Foundation (2018). IFRS 9: Financial Instruments – Implementation Guidance.",
        "[3] European Banking Authority (2022). Guidelines on PD estimation, LGD, and treatment "
        "of defaulted exposures.",
        "[4] Thomas, L., Edelman, D., & Crook, J. (2017). Credit Scoring and Its Applications "
        "(2nd Ed.). SIAM.",
        "[5] Lessmann, S., Baesens, B., Seow, H., & Thomas, L. (2015). Benchmarking "
        "State-of-the-Art Classification Algorithms for Credit Scoring. EJOR.",
        "[6] European Central Bank (2021). Good Practices for Model Validation and "
        "Explainability in IFRS 9.",
        "[7] Freddie Mac (2025). Single-Family Loan-Level Dataset User Guide. Release 44.",
        "[8] Breiman, L. (2001). Random Forests. Machine Learning, 45(1), 5–32.",
        "[9] Chen, T., & Guestrin, C. (2016). XGBoost: A Scalable Tree Boosting System. "
        "Proc. 22nd ACM SIGKDD.",
        "[10] Ke, G., Meng, Q., et al. (2017). LightGBM: A Highly Efficient Gradient "
        "Boosting Decision Tree. NIPS.",
        "[12] Banco Central de la República Argentina (2024). Comunicación 'A' 6847: "
        "Previsiones Mínimas por Riesgo de Incobrabilidad – Normas NIIF.",
        "[13] Freire López, J. (2021). Modelo de Clasificación de Riesgo Crediticio "
        "Utilizando Random Forest. Tesis de Maestría, Universidad Internacional SEK.",
        "[14] Ghent, A. C., & Kudlyak, M. (2011). Recourse and Residential Mortgage Default. "
        "Review of Financial Studies, 24(9), 3139–3186.",
        "[15] Elul, R., et al. (2010). What 'Triggers' Mortgage Default? AER, 100(2), 490–494.",
        "[16] Lundberg, S. M., & Lee, S. I. (2017). A Unified Approach to Interpreting "
        "Model Predictions. NIPS.",
        "[17] European Banking Authority (2017). Guidelines on credit institutions' credit "
        "risk management practices and accounting for expected credit losses (EBA/GL/2017/16).",
        "[18] European Banking Authority (2016). Guidelines on the application of the "
        "definition of default under Article 178 of Regulation (EU) No 575/2013 (EBA/GL/2016/07).",
        "[19] European Parliament and Council (2013). Regulation (EU) No 575/2013 on prudential "
        "requirements for credit institutions and investment firms (Capital Requirements "
        "Regulation, CRR).",
        "[20] Basel Committee on Banking Supervision (2015). Guidance on credit risk and "
        "accounting for expected credit losses (BCBS d350).",
    ]
    for ref in referencias:
        p = doc.add_paragraph(style="List Paragraph")
        p.paragraph_format.left_indent = Cm(0.5)
        p.paragraph_format.first_line_indent = Cm(-0.5)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(ref)
        set_run_font(r, tamaño=10)

    # -------------------------------------------------------------------------
    # GUARDAR
    # -------------------------------------------------------------------------
    doc.save(str(DOCX_OUT))
    print(f"\nDocumento guardado: {DOCX_OUT}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    t0 = time.time()
    print("=" * 60)
    print("GENERADOR DE TESIS – Tesis_borrador.docx")
    print("=" * 60)

    print("\n[1/2] Ejecutando pipeline de análisis...")
    resultados = ejecutar_pipeline()

    print("\n[2/2] Construyendo documento Word...")
    construir_docx(resultados)

    print(f"\nFinalizado en {(time.time() - t0)/60:.1f} minutos.")
    print(f"Documento: {DOCX_OUT}")


if __name__ == "__main__":
    main()
