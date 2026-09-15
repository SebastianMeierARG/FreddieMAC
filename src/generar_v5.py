"""
generar_v5.py - Genera Tesis_Meier_IFRS9_APA_v5.docx a partir de la v4
=========================================================================
Sigue el contrato de THESIS_WRITING_GUIDELINES.md: preserva los Capitulos
1-4 y Referencias de v4 exactamente como estan, y reconstruye los Capitulos
5-18 con los mismos helpers de formato (ahora corregidos a APA 7 estricto -
ver Sec. 4 de las guidelines) mas el contenido nuevo especificado en
IFRS9_COMPLIANCE_SPEC.md que no existia en v4:

  - Cap. 7 : nueva Sec. 7.3, brecha UTP/NPV-concession (Control 4.1/4.2).
  - Cap. 10: nueva Sec. 10.1, alcance individual vs. colectivo (Control 3.1);
             las secciones 10.1-10.3 originales pasan a 10.2-10.4.
  - Cap. 12: nueva Sec. 12.3, gobernanza cambiaria hipotetica (Control 8.6).
  - Cap. 13: nueva Sec. 13.3, test Z binomial + IC95 Wilson por decil
             (Control 6.5), con la tabla generada por 06_validacion.py en
             outputs/tablas/validacion_calibracion_intervalos.csv.

Como se insertan 2 tablas nuevas (Cap. 7 y Cap. 13), el resto de las tablas
se renumera secuencialmente (ver TABLA_RENUM). Las figuras no cambian de
numero: no se agrega ninguna figura nueva en esta version.

Entrada : ../Tesis_Meier_IFRS9_APA_v4.docx  (nunca se sobreescribe)
Salida  : ../Tesis_Meier_IFRS9_APA_v5.docx
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from config import (
    BASE_PATH, FIGURAS_PATH, TABLAS_PATH,
    LGD_WORKOUT_MESES_MAX, LGD_CURE_MESES, LGD_PERDIDA_TOTAL,
    LGD_DOWNTURN_ADDON, CCF_OFF_BALANCE, MONEDA_BASE, EAD_HORIZONTE_MESES,
    PMA_UMBRAL_MATERIALIDAD, PMA_UMBRAL_INFORMATIVO, PMA_VIGENCIA_MAX_TRIMESTRES,
)

V4_PATH = BASE_PATH / "Tesis_Meier_IFRS9_APA_v4.docx"
V5_PATH = BASE_PATH / "Tesis_Meier_IFRS9_APA_v5.docx"

FONT = "Times New Roman"
BODY_PT = 12

# Renumeracion de tablas: 2 tablas nuevas se insertan despues de la vieja
# Tabla 4 (Cap. 7) y despues de la vieja Tabla 16 (Cap. 13). Toda tabla con
# numero original >= 5 sube +1; toda tabla con numero original >= 17 sube
# +1 adicional (+2 en total). Las figuras no se renumeran (ninguna nueva).
def _tn(n: int) -> int:
    # La tabla UTP nueva se inserta despues de la vieja Tabla 5 (no la 4: la
    # Sec. 7.3 va despues de la Sec. 7.2, que contiene la grilla SICR) y la
    # tabla de calibracion Wilson/Z despues de la vieja Tabla 16.
    return n + (1 if n >= 6 else 0) + (1 if n >= 17 else 0)


# ============================================================================
# HELPERS DE FORMATO APA 7 ESTRICTO
# (corrigen las desviaciones documentadas en THESIS_WRITING_GUIDELINES.md
# Sec. 4: bordes/sombreado de tabla, sangria de primera linea, notacion
# estadistica en cursiva puntual dentro de una misma oracion)
# ============================================================================

def set_run_font(run, tamaño=BODY_PT, negrita=False, cursiva=False, color=None):
    run.font.name = FONT
    run.font.size = Pt(tamaño)
    run.font.bold = negrita
    run.font.italic = cursiva
    if color:
        run.font.color.rgb = RGBColor(*color)


def parrafo(doc, texto, negrita=False, cursiva=False, tamaño=BODY_PT,
           indent=True, alineacion=WD_ALIGN_PARAGRAPH.LEFT):
    p = doc.add_paragraph()
    p.alignment = alineacion
    p.paragraph_format.line_spacing = 2.0
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    if indent:
        p.paragraph_format.first_line_indent = Cm(1.27)   # 0.5 in exacto (APA 2.1)
    run = p.add_run(texto)
    set_run_font(run, tamaño=tamaño, negrita=negrita, cursiva=cursiva)
    return p


def parrafo_mixto(doc, partes, tamaño=BODY_PT, indent=True,
                  alineacion=WD_ALIGN_PARAGRAPH.LEFT):
    """Como parrafo(), pero acepta una lista de (texto, cursiva) para permitir
    itálicas puntuales dentro de la misma oración -- notación estadística APA
    (N, n, p, z, chi cuadrado, R^2) sin cursivar la oración completa. Ver
    THESIS_WRITING_GUIDELINES.md Sec. 2.6 y Sec. 4."""
    p = doc.add_paragraph()
    p.alignment = alineacion
    p.paragraph_format.line_spacing = 2.0
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    if indent:
        p.paragraph_format.first_line_indent = Cm(1.27)
    for texto, cursiva in partes:
        run = p.add_run(texto)
        set_run_font(run, tamaño=tamaño, cursiva=cursiva)
    return p


def titulo(doc, texto, nivel=1):
    p = doc.add_heading(texto, level=nivel)
    for run in p.runs:
        run.font.name = FONT
        run.font.color.rgb = RGBColor(0, 0, 0)
    return p


def codigo(doc, texto: str):
    """Bloque de formula/pseudocodigo: fuente monoespaciada, fondo gris claro."""
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.15
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F2F2F2")
    pPr.append(shd)
    run = p.add_run(texto)
    run.font.name = "Courier New"
    run.font.size = Pt(9.5)
    return p


def lista(doc, items, tamaño=BODY_PT):
    for it in items:
        p = doc.add_paragraph()
        p.paragraph_format.line_spacing = 2.0
        p.paragraph_format.left_indent = Cm(1.0)
        p.paragraph_format.first_line_indent = Cm(-0.5)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run("• ")
        set_run_font(r, tamaño=tamaño)
        r2 = p.add_run(it)
        set_run_font(r2, tamaño=tamaño)


def salto_pagina(doc):
    doc.add_page_break()


def callout_tabla(doc, numero: int, frase: str):
    parrafo(doc, frase)


def caption_tabla(doc, numero: int, titulo_tabla: str):
    p1 = doc.add_paragraph()
    p1.paragraph_format.line_spacing = 2.0
    p1.paragraph_format.space_after = Pt(0)
    r1 = p1.add_run(f"Tabla {numero}")
    set_run_font(r1, negrita=True)

    p2 = doc.add_paragraph()
    p2.paragraph_format.line_spacing = 2.0
    p2.paragraph_format.space_after = Pt(6)
    r2 = p2.add_run(titulo_tabla)
    set_run_font(r2, cursiva=True)


def nota_tabla(doc, texto: str):
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 2.0
    p.paragraph_format.space_before = Pt(4)
    r1 = p.add_run("Nota. ")
    set_run_font(r1, cursiva=True)
    r2 = p.add_run(texto)
    set_run_font(r2)


def tabla_df(doc, df: pd.DataFrame, numero: int, titulo_tabla: str,
            callout: str = None, nota: str = None, max_filas: int = 40):
    if callout:
        callout_tabla(doc, numero, callout)
    caption_tabla(doc, numero, titulo_tabla)

    df_str = df.head(max_filas).copy()
    for col in df_str.select_dtypes(include=["float", "float64", "float32"]).columns:
        df_str[col] = df_str[col].map(lambda x: f"{x:.4f}" if pd.notna(x) else "")

    t = doc.add_table(rows=1, cols=len(df_str.columns))
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    hdr = t.rows[0].cells
    for i, col in enumerate(df_str.columns):
        hdr[i].text = str(col)
        for run in hdr[i].paragraphs[0].runs:
            run.font.bold = True
            run.font.size = Pt(9)
            run.font.name = FONT
        hdr[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    for i, (_, row) in enumerate(df_str.iterrows()):
        cells = t.add_row().cells
        for j, val in enumerate(row):
            cells[j].text = str(val) if pd.notna(val) else ""
            for run in cells[j].paragraphs[0].runs:
                run.font.size = Pt(9)
                run.font.name = FONT

    # APA (THESIS_WRITING_GUIDELINES.md Sec. 2.3 / 4): solo tres reglas
    # horizontales -- arriba de la tabla, bajo el encabezado, y abajo de la
    # tabla -- sin bordes verticales y sin sombreado de celda.
    tblPr = t._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("left", "right", "insideV", "insideH"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)
    for edge in ("top", "bottom"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single"); el.set(qn("w:sz"), "8")
        el.set(qn("w:space"), "0"); el.set(qn("w:color"), "000000")
        borders.append(el)
    tblPr.append(borders)

    # Regla bajo la fila de encabezado unicamente (no entre cada fila de cuerpo)
    for cell in t.rows[0].cells:
        tcPr = cell._tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single"); bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "0"); bottom.set(qn("w:color"), "000000")
        tcBorders.append(bottom)
        tcPr.append(tcBorders)

    if nota:
        nota_tabla(doc, nota)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return t


def figura(doc, ruta: Path, numero: int, titulo_fig: str, callout: str = None,
          nota: str = None, ancho=15.5):
    if callout:
        callout_tabla(doc, numero, callout)
    p1 = doc.add_paragraph()
    p1.paragraph_format.line_spacing = 2.0
    p1.paragraph_format.space_after = Pt(0)
    r1 = p1.add_run(f"Figura {numero}")
    set_run_font(r1, negrita=True)
    p2 = doc.add_paragraph()
    p2.paragraph_format.line_spacing = 2.0
    p2.paragraph_format.space_after = Pt(6)
    r2 = p2.add_run(titulo_fig)
    set_run_font(r2, cursiva=True)

    if ruta.exists():
        p = doc.add_paragraph()
        run = p.add_run()
        run.add_picture(str(ruta), width=Cm(ancho))
    else:
        parrafo(doc, f"[Figura no disponible: {ruta.name}]", cursiva=True, indent=False)

    if nota:
        nota_tabla(doc, nota)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


# ============================================================================
# 1. Cargar v4, localizar los puntos de corte
# ============================================================================

def localizar_anclas(doc):
    ch5_idx = refs_idx = None
    for i, p in enumerate(doc.paragraphs):
        if p.style.name == "Heading 1":
            t = p.text.strip()
            if t.startswith("5. Descripci"):
                ch5_idx = i
            elif t == "Referencias":
                refs_idx = i
    assert ch5_idx is not None and refs_idx is not None, "anclas no encontradas"
    return ch5_idx, refs_idx


def eliminar_rango(doc, idx_inicio_par, idx_fin_par_exclusive):
    inicio_el = doc.paragraphs[idx_inicio_par]._p
    fin_el = doc.paragraphs[idx_fin_par_exclusive]._p
    body = doc.element.body
    children = list(body.iterchildren())
    i_start = children.index(inicio_el)
    i_end = children.index(fin_el)
    for el in children[i_start:i_end]:
        body.remove(el)


def ultimo_elemento_de_contenido(doc):
    children = list(doc.element.body.iterchildren())
    sectPr = children[-1]
    assert sectPr.tag == qn("w:sectPr"), "se esperaba sectPr al final del body"
    return children[-2]


def reubicar_nuevo_contenido(doc, refs_heading_par, ultimo_original):
    body = doc.element.body
    children = list(body.iterchildren())
    sectPr = children[-1]
    i_ultimo = children.index(ultimo_original)
    nuevos = children[i_ultimo + 1: len(children) - 1]
    assert sectPr not in nuevos
    anchor = refs_heading_par._p
    for el in nuevos:
        anchor.addprevious(el)


def insertar_referencia_antes(doc, texto_partes, ancla_texto_prefijo):
    ancla = None
    for p in doc.paragraphs:
        if p.text.startswith(ancla_texto_prefijo):
            ancla = p
            break
    assert ancla is not None, f"ancla de referencia no encontrada: {ancla_texto_prefijo!r}"

    ultimo_antes = ultimo_elemento_de_contenido(doc)
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(1)
    p.paragraph_format.first_line_indent = Cm(-1)
    p.paragraph_format.line_spacing = 2.0
    p.paragraph_format.space_after = Pt(0)
    for texto, cursiva in texto_partes:
        r = p.add_run(texto)
        set_run_font(r, cursiva=cursiva)

    body = doc.element.body
    children = list(body.iterchildren())
    i_ultimo = children.index(ultimo_antes)
    nuevo_el = children[i_ultimo + 1]
    assert nuevo_el.tag == qn("w:p") and nuevo_el is not children[-1]
    ancla._p.addprevious(nuevo_el)


# ============================================================================
# 2. Contenido de los capitulos 5-18 (identico a v4 salvo lo señalado)
# ============================================================================

def _tabla(doc, df, numero, titulo_tabla, callout=None, nota=None, max_filas=40):
    return tabla_df(doc, df, numero, titulo_tabla, callout=callout, nota=nota,
                    max_filas=max_filas)


def cap5_dataset_completo(doc):
    titulo(doc, "5. Descripción del Dataset y Análisis Exploratorio", nivel=1)
    parrafo(doc,
        "Este capítulo describe la fuente de datos, el proceso de extracción de la "
        "muestra y las estadísticas descriptivas de la cartera hipotecaria utilizada "
        "para la estimación de PD. La formulación matemática de cada modelo y de "
        "cada métrica se desarrolló en el Capítulo 4; aquí se presentan los "
        "resultados aplicados sobre los datos reales de Freddie Mac.")

    titulo(doc, "5.1 Freddie Mac Single-Family Loan-Level Dataset", nivel=2)
    parrafo(doc,
        "Se utiliza el Freddie Mac Single-Family Loan-Level Dataset (Sample), una "
        "muestra aleatoria de 50.000 préstamos por año de originación, publicada "
        "públicamente por Freddie Mac (Freddie Mac, 2025). El dataset contiene dos "
        "archivos por vintage: el archivo de originación (características estáticas "
        "del préstamo al momento de la concesión) y el archivo de performance "
        "(evolución mensual del saldo, la mora y el estado del préstamo hasta su "
        "liquidación o el cierre de la ventana de observación). Se descargaron los "
        "vintages 2016 a 2024, excluyendo 2021 por indisponibilidad de datos en la "
        "fuente pública al momento de la extracción.")
    parrafo(doc,
        "La muestra de originación comprende 400.000 préstamos únicos, con primer "
        "pago entre el 1 de febrero de 2016 y el 1 de abril de 2025. El archivo de "
        "performance, tras el join loan-mes, produce 14.603.212 observaciones "
        "mensuales. Tras aplicar la definición de default IFRS 9 y filtrar a Stage 1 "
        "y 2 (Capítulo 7), el dataset de modelado final contiene 14.481.471 "
        "observaciones, con una tasa de default a 12 meses de 1,2193 %.")

    titulo(doc, "5.2 Estadísticas Descriptivas – Originación", nivel=2)
    eda_orig = pd.read_csv(TABLAS_PATH / "eda_stats_originacion.csv")
    eda_orig = eda_orig.rename(columns={eda_orig.columns[0]: "Variable"})
    _tabla(doc, eda_orig, _tn(1), "Estadísticas descriptivas – variables de originación",
          callout=f"La Tabla {_tn(1)} presenta las estadísticas descriptivas de las "
                  "principales variables cuantitativas de originación.")
    parrafo(doc,
        "El FICO score promedio de la cartera es 749 (mediana 758), con un LTV "
        "original promedio de 74,4 % y un DTI promedio de 35,8 %. La cola derecha "
        "del UPB original (máximo USD 2.100.000, percentil 95 USD 570.000) refleja "
        "la inclusión de préstamos jumbo-conforming en años de límites de "
        "conformidad más altos.")

    titulo(doc, "5.3 Estadísticas Descriptivas – Performance", nivel=2)
    parrafo(doc,
        "El dataset de performance contiene 14.603.212 observaciones mensuales, "
        f"abarcando el período febrero de 2016 a abril de 2025. La Tabla {_tn(2)} resume "
        "la composición de la cartera por las principales variables categóricas de "
        "originación.")
    comp = pd.read_csv(TABLAS_PATH / "eda_composicion_cartera.csv")
    _tabla(doc, comp, _tn(2), "Composición de la cartera por variable categórica",
          max_filas=20)
    parrafo(doc,
        "El 60,5 % de los préstamos corresponde a compras (loan_purpose = P), el "
        "62,2 % son propiedades unifamiliares (property_type = SF) y el 89,3 % son "
        "residencias primarias (occupancy_status = P). El canal retail (R) origina "
        "el 54,5 % de la cartera.")

    titulo(doc, "5.4 Visualizaciones Exploratorias", nivel=2)
    figura(doc, FIGURAS_PATH / "eda_fico_distribucion.png", 1,
          "Distribución del FICO score al momento de la originación.")
    figura(doc, FIGURAS_PATH / "eda_ltv_default.png", 2,
          "Tasa de default a 12 meses por decil de LTV original.")
    figura(doc, FIGURAS_PATH / "eda_dpd_distribucion.png", 3,
          "Distribución del DPD numérico.")
    figura(doc, FIGURAS_PATH / "eda_default_vintage.png", 4,
          "Tasa de default a 12 meses por vintage de originación.")
    figura(doc, FIGURAS_PATH / "eda_default_tiempo.png", 5,
          "Evolución temporal de la tasa de default observada (ODR mensual).")
    salto_pagina(doc)


def cap6_pipeline(doc):
    titulo(doc, "6. Metodología e Implementación del Pipeline", nivel=1)
    parrafo(doc,
        "El pipeline se implementa en Python como una secuencia de módulos "
        "independientes y reproducibles, cada uno con una entrada y una salida en "
        "formato parquet, orquestados por pipeline_completo.py. Los parámetros "
        "regulatorios, las rutas de datos y las listas de features se centralizan "
        "en config.py, de modo que ningún valor crítico (umbral de DPD, ventana de "
        "SICR, partición temporal, hiperparámetros de los modelos) queda "
        "hardcodeado en la lógica de negocio. IFRS9_COMPLIANCE_SPEC.md documenta la "
        "trazabilidad completa entre cada uno de los 32 controles de auditoría "
        "IFRS 9 / EBA GL evaluados, el módulo que lo implementa, el artefacto "
        "generado y la sección de esta tesis que lo desarrolla.")

    titulo(doc, "6.1 Carga y Preparación de Datos", nivel=2)
    parrafo(doc,
        "El Paso 1 (01_carga_datos.py) normaliza los nombres de columna del "
        "formato crudo de Freddie Mac (sufijos _V##) a nombres semánticos, castea "
        "tipos y realiza el join originación-performance por loan_sequence_number, "
        "produciendo panel.parquet. El Paso 2 (02_definicion_default.py) aplica la "
        "definición de default IFRS 9 (Capítulo 7) y construye la variable objetivo "
        "default_12m mediante una ventana móvil hacia adelante vectorizada.")

    titulo(doc, "6.2 Secuencia Completa del Pipeline", nivel=2)
    parrafo(doc,
        "La auditoría de cumplimiento incorporada en esta versión amplía el "
        f"pipeline original de 8 a 11 pasos. La Tabla {_tn(3)} documenta la secuencia "
        "completa, sus dependencias y el control regulatorio que atiende cada uno.")
    pasos = pd.DataFrame([
        {"Paso": "1",  "Módulo": "01_carga_datos.py", "Salida": "panel.parquet",
         "Control atendido": "2.1, 7.7"},
        {"Paso": "2",  "Módulo": "02_definicion_default.py", "Salida": "panel_con_default.parquet",
         "Control atendido": "4.1, 4.2"},
        {"Paso": "3",  "Módulo": "03_feature_engineering.py", "Salida": "dataset_modelado.parquet",
         "Control atendido": "Variables relativas a cohorte (estacionariedad)"},
        {"Paso": "4",  "Módulo": "04_modelado.py", "Salida": "modelo_{logistica,xgboost,random_forest}.joblib",
         "Control atendido": "6.1, 6.2"},
        {"Paso": "3b", "Módulo": "03b_sicr_assessment.py", "Salida": "dataset_modelado.parquet (actualizado)",
         "Control atendido": "11.2, 11.3"},
        {"Paso": "5",  "Módulo": "05_calibracion_lifetime.py", "Salida": "curva_pd_lifetime.csv",
         "Control atendido": "6.3"},
        {"Paso": "6",  "Módulo": "06_validacion.py", "Salida": "validacion_*.csv",
         "Control atendido": "6.5, 12.1"},
        {"Paso": "6b", "Módulo": "06b_segmentacion.py", "Salida": "segmentacion_*.csv",
         "Control atendido": "3.1, 3.2, 3.6"},
        {"Paso": "7",  "Módulo": "07_explicabilidad.py", "Salida": "shap_*.png/csv",
         "Control atendido": "—"},
        {"Paso": "8",  "Módulo": "08_lgd_ead.py", "Salida": "lgd_*.csv, ead_*.csv",
         "Control atendido": "7.1, 7.3, 7.5, 7.7, 8.1, 8.2, 8.6"},
        {"Paso": "9",  "Módulo": "09_woe_vs_ml.py", "Salida": "comparacion_woe_vs_raw_*.csv",
         "Control atendido": "11.1, 11.5"},
    ])
    _tabla(doc, pasos, _tn(3), "Secuencia del pipeline y controles regulatorios atendidos "
                              "(IFRS9_COMPLIANCE_SPEC.md, Sec. 2)")
    salto_pagina(doc)


def cap7_default_sicr(doc):
    titulo(doc, "7. Definición del Default, Clasificación IFRS 9 y Evaluación de SICR",
          nivel=1)
    parrafo(doc,
        "El evento de default se define conforme a la Ecuación 4.2 (Capítulo 4): "
        "dpd_numérico ≥ 3 (90 días de mora) o zero_balance_code ∈ {02, 03, 09} "
        "(venta a terceros, short sale o disposición REO). El código \"RA\" en "
        "current_loan_delinquency_status se trata como 99 DPD (REO), no como "
        "valor faltante; el código \"0\" indica corriente, no ausencia de dato.")

    titulo(doc, "7.1 Distribución de Stages IFRS 9", nivel=2)
    stages = pd.DataFrame([
        {"Stage": "1 (DPD = 0)", "Observaciones": "14.328.713", "Porcentaje (%)": 98.90},
        {"Stage": "2 (DPD ∈ {1,2})", "Observaciones": "152.758", "Porcentaje (%)": 1.10},
        {"Stage": "3 (default)", "Observaciones": "121.741", "Porcentaje (%)": 0.83},
    ])
    _tabla(doc, stages, _tn(4), "Distribución de stages IFRS 9 (criterio DPD)",
          callout=f"La Tabla {_tn(4)} presenta la distribución de stages IFRS 9 bajo el "
                  "criterio de backstop DPD.")
    parrafo(doc,
        "La tasa de default a 12 meses sobre las observaciones activas (Stage 1 y "
        "2) es de 1,2193 %, consistente con una cartera hipotecaria prime de bajo "
        "riesgo relativo (Low Default Portfolio, Sección 2.4).")

    titulo(doc, "7.2 Formalización Cuantitativa del Criterio de SICR", nivel=2)
    parrafo(doc,
        "Conforme a lo desarrollado en la Sección 3.4.2, el criterio primario de "
        "SICR bajo IFRS 9 párr. 5.5.9 es la variación de la Lifetime PD entre el "
        "reconocimiento inicial y la fecha de reporte, evaluada sobre el mismo "
        "horizonte residual. El párr. 5.5.11 califica el backstop de 30 días de "
        "mora como una presunción refutable —un refuerzo prudencial, no el "
        "indicador principal— en línea con EBA GL/2017/16 (European Banking "
        "Authority, 2017, párrs. 135-138).")
    codigo(doc,
        "PD_lifetime = 1 - (1 - PD_12m)^(T_residual / 12)      (extrapolación de hazard constante)\n\n"
        "SICR  si   PD_lifetime_t / PD_lifetime_orig  >=  k          (criterio relativo, primario)\n"
        "      o    PD_lifetime_t  -  PD_lifetime_orig  >=  delta    (criterio absoluto)\n"
        "      o    DPD >= 30                                        (backstop, IFRS 9 5.5.11)")
    parrafo(doc,
        "La PD de originación se estima con una Regresión Logística entrenada "
        "exclusivamente sobre variables disponibles al momento de la concesión "
        "(FEATURES_ORIGINACION_EXT), calibrada isotónicamente en validación. La PD "
        "corriente se obtiene del modelo XGBoost del Capítulo 9. Ambas se convierten "
        "a Lifetime PD sobre el horizonte residual del préstamo antes de comparar, "
        "de modo que la condición relativa sea invariante a la duración residual "
        "del contrato.")
    parrafo(doc,
        "Los umbrales k = 2,5 y delta = 5 puntos porcentuales se calibraron "
        "empíricamente sobre una grilla cruzada de sensibilidad. Un umbral "
        "absoluto de 0,5 p.p. —adecuado para una PD a 12 meses— resulta demasiado "
        "laxo aplicado sobre la escala de la Lifetime PD (media de la cartera "
        "≈ 14 %): con ese valor, el criterio absoluto por sí solo explicaba el "
        "99,98 % de la clasificación en Stage 2, anulando el aporte del criterio "
        "relativo pese a ser este el criterio primario según IFRS 9 5.5.9. Con "
        "delta = 5 p.p. el criterio absoluto deja de dominar por completo (aporta "
        "de forma marginal en 13,1 % de los casos), y el Stage 2 resultante "
        "conserva significancia económica.")
    grid = pd.read_csv(TABLAS_PATH / "sicr_umbral_calibracion.csv")
    grid_show = grid[(grid["delta_absoluto"].isin([0.01, 0.03, 0.05, 0.08]))
                     & (grid["k_relativo"].isin([1.5, 2.0, 2.5, 3.0]))]
    _tabla(doc, grid_show, _tn(5),
          "Grilla de calibración del umbral de SICR (sensibilidad conjunta de k y delta)",
          callout=f"La Tabla {_tn(5)} presenta la grilla de calibración del umbral de SICR.",
          nota="rel_share es la proporción del Stage 2 explicada exclusivamente por el "
               "criterio relativo (no por el absoluto); pct_solo_por_backstop es la "
               "proporción explicada exclusivamente por el backstop de 30 DPD.")
    parrafo(doc,
        "Con la combinación seleccionada (k = 2,5; delta = 0,05), el 8,46 % de la "
        "cartera se clasifica en Stage 2, con una tasa de default observada a 12 "
        "meses de 6,42 % dentro de ese Stage 2 frente a 0,74 % en Stage 1 (lift de "
        "8,7×), cubriendo el 44,55 % de los defaults futuros de la cartera. El "
        "backstop de 30 DPD explica apenas el 0,10 % de las clasificaciones en "
        "Stage 2 de forma exclusiva —el 99,90 % restante ya estaba correctamente "
        "identificado por el criterio basado en PD—, confirmando que el backstop "
        "opera como refuerzo cualitativo y no como indicador principal, conforme "
        "exige EBA GL/2017/16 §5.5 (Control 11.3, IFRS9_COMPLIANCE_SPEC.md).")

    # --- NUEVO EN v5: Sec. 7.3, brecha UTP / criterio de concesión NPV -------
    titulo(doc, "7.3 Criterios Subjetivos de Improbabilidad de Pago (UTP) y "
                "Brecha Documentada", nivel=2)
    parrafo(doc,
        "Además del backstop objetivo de 90 DPD (Sección 7.1), EBA GL/2016/07 "
        "exige incorporar criterios subjetivos de unlikeliness-to-pay (UTP) que "
        "capturen el deterioro crediticio antes de que se materialice la mora. "
        "Los códigos de zero-balance de Freddie Mac ya utilizados en la "
        "definición de default (Sección 7.1) se mapean directamente a las "
        "categorías de UTP de esa guía:")
    utp_map = pd.DataFrame([
        {"Código Freddie Mac": "02", "Evento": "Third-Party Sale",
         "Categoría EBA GL/2016/07": "Venta de deuda en dificultades / pérdida económica material"},
        {"Código Freddie Mac": "03", "Evento": "Short Sale / Charge-off",
         "Categoría EBA GL/2016/07": "Venta de deuda en dificultades / pérdida económica material"},
        {"Código Freddie Mac": "09", "Evento": "Deed-in-Lieu / REO Disposition",
         "Categoría EBA GL/2016/07": "Ejecución legal y recuperación del activo en garantía"},
    ])
    _tabla(doc, utp_map, 6,
          "Mapeo de códigos de zero-balance de Freddie Mac a categorías UTP de EBA GL/2016/07",
          callout="La Tabla 6 presenta el mapeo entre los eventos de liquidación "
                  "de Freddie Mac y las categorías de UTP de la guía EBA.")
    parrafo(doc,
        "Estos tres códigos ya están incorporados como disparadores objetivos del "
        "evento de default (Sección 7.1) y, por lo tanto, cubren la mayor parte "
        "de las categorías de UTP relevantes para una cartera hipotecaria "
        "minorista. Persiste, sin embargo, una brecha documentada: las banderas "
        "de comportamiento fue_modificado y tiene_deferral (FEATURES_COMPORTAMIENTO, "
        "config.py) se utilizan únicamente como covariables del modelo de PD, no "
        "como un disparador de default independiente. Un criterio formal de "
        "concesión basado en el valor presente neto (NPV) —donde una "
        "modificación se trata como evento UTP cuando el NPV de los flujos "
        "reestructurados cae materialmente por debajo del NPV contractual "
        "original— se especifica como el diseño objetivo en "
        "IFRS9_COMPLIANCE_SPEC.md (Control 4.1) pero no está implementado en "
        "02_definicion_default.py.")
    codigo(doc,
        "NPV_original      = Σ_t  CF_contractual_t / (1 + i)^t\n"
        "NPV_reestructurado = Σ_t  CF_modificado_t   / (1 + i)^t\n\n"
        "UTP_concesion  si  (NPV_original - NPV_reestructurado) / NPV_original  >=  umbral_materialidad")
    parrafo(doc,
        "con i la tasa de descuento efectiva anual (TASA_DESCUENTO_ANUAL, "
        "config.py, ya utilizada para descontar recuperaciones de LGD en el "
        "Capítulo 12). Cerrar esta brecha requiere: (i) reconstruir el flujo de "
        "pagos pre y post-modificación por préstamo, (ii) fijar un umbral de "
        "materialidad explícito en config.py, y (iii) incorporar la bandera "
        "resultante a es_evento_default() junto con los disparadores de DPD y "
        "zero-balance ya existentes. Esta brecha se documenta explícitamente, en "
        "lugar de omitirse, siguiendo el principio de trazabilidad íntegra de "
        "IFRS9_COMPLIANCE_SPEC.md.")
    salto_pagina(doc)


def cap8_feature_engineering(doc):
    titulo(doc, "8. Ingeniería de Variables (Feature Engineering)", nivel=1)
    parrafo(doc,
        "Además de las variables de comportamiento dinámico (DPD rolling a 3/6/12 "
        "meses, spread de tasa, amortización relativa) descriptas en la Sección "
        "4.1, esta versión incorpora un conjunto de variables relativas a la "
        "cohorte de originación que resultó indispensable para la validez "
        "out-of-time del modelo XGBoost (Capítulo 9).")

    titulo(doc, "8.1 El Problema del Desplazamiento de Covariables", nivel=2)
    parrafo(doc,
        "Las variables de nivel absoluto —tasa nominal original y corriente, UPB "
        "original y saldo corriente en USD— presentan un desplazamiento de "
        "covariables severo entre particiones temporales: la tasa media de "
        "originación pasa de 3,96 % en el conjunto de entrenamiento (vintages "
        "2016-2020) a 6,74 % en el conjunto de test (vintage 2024), reflejando el "
        "ciclo de tasas de interés observado en Estados Unidos en ese período. Los "
        "modelos basados en árboles de decisión particionan el espacio de "
        "features dentro del rango observado en entrenamiento y no extrapolan "
        "fuera de él: toda la cartera de test cae, para esta variable, fuera del "
        "rango de valores visto durante el ajuste del modelo. La Regresión "
        "Logística, al ser un modelo lineal global, no sufre esta limitación en "
        "la misma medida.")
    parrafo(doc,
        "Esta asimetría explica un hallazgo inicial contraintuitivo: en una "
        "primera especificación del modelo, XGBoost obtenía un AUC de test "
        "(0,7804) sensiblemente inferior al de la Regresión Logística (0,8527), "
        "pese a ser sistemáticamente el modelo con mayor capacidad de ajuste en "
        "entrenamiento y validación. La causa no era una limitación del "
        "algoritmo, sino la especificación defectuosa del conjunto de features.")

    titulo(doc, "8.2 Variables Relativas a la Cohorte de Originación", nivel=2)
    parrafo(doc,
        "La corrección consiste en sustituir las variables de nivel absoluto por "
        "su desviación respecto de la media de la cohorte de originación (mes de "
        "concesión del préstamo), que sí es estacionaria entre vintages y captura "
        "el mismo riesgo relativo (préstamo caro o barato, grande o chico frente a "
        "sus pares de la misma cohorte).")
    codigo(doc,
        "rate_vs_cohorte  = original_interest_rate  -  media_cohorte(original_interest_rate)\n"
        "upb_vs_cohorte   = original_upb             -  media_cohorte(original_upb)\n"
        "fico_vs_cohorte  = credit_score              -  media_cohorte(credit_score)\n"
        "ltv_vs_cohorte   = original_ltv               -  media_cohorte(original_ltv)\n"
        "age_ratio        = loan_age / original_loan_term")
    parrafo(doc,
        "Toda la información utilizada está disponible en el momento de la "
        "originación del préstamo, por lo que no se introduce look-ahead bias. "
        "Las variables de nivel absoluto (original_interest_rate, "
        "current_interest_rate, original_upb, current_actual_upb) se excluyen del "
        "conjunto de entrenamiento de los modelos de árboles; la Regresión "
        "Logística conserva ambos conjuntos vía su propio pipeline de "
        "estandarización.")
    parrafo(doc,
        "El efecto de esta corrección, junto con la incorporación de restricciones "
        "de monotonía y un esquema de early stopping disciplinado, se cuantifica "
        "en la Sección 9.2.")
    salto_pagina(doc)


def cap9_modelado(doc):
    titulo(doc, "9. Modelado – Entrenamiento y Comparación de Modelos PD", nivel=1)
    parrafo(doc,
        "Se entrenan y comparan tres modelos bajo partición temporal out-of-time: "
        "entrenamiento (vintages 2016-2020, submuestreado a 1.000.000 de "
        "observaciones), validación (2022-2023) y test (2024). El vintage 2021 no "
        "existe en el dataset descargado.")

    titulo(doc, "9.1 Ajustes Metodológicos sobre la Especificación Inicial", nivel=2)
    parrafo(doc,
        "Además de la corrección de covariables de la Sección 8.1, se introdujeron "
        "tres ajustes adicionales:")
    lista(doc, [
        "Restricciones de monotonía en XGBoost sobre los drivers de riesgo "
        "(credit_score y fico_vs_cohorte: −1; LTV, DTI, ELTV, DPD rolling y "
        "rate_vs_cohorte: +1), conforme a la exigencia de plausibilidad económica "
        "de EBA GL/2017/16 §5.3.1.",
        "Número de árboles de XGBoost fijado por early stopping sobre un holdout "
        "temporal interno al propio conjunto de entrenamiento (vintage 2020), de "
        "modo que validación y test nunca intervienen en la selección del modelo.",
        "Eliminación de scale_pos_weight en XGBoost: el re-pesado de clases "
        "distorsiona el nivel de las probabilidades crudas, que bajo IFRS 9 deben "
        "ser interpretables como PD; el desbalance se corrige exclusivamente por "
        "calibración isotónica posterior sobre el conjunto de validación.",
    ])

    titulo(doc, "9.2 Resultados Comparativos", nivel=2)
    res = pd.read_csv(TABLAS_PATH / "resultados_modelos.csv")
    _tabla(doc, res, _tn(6), "Métricas comparativas de modelos – validación y test (vintage 2024)",
          callout=f"La Tabla {_tn(6)} presenta las métricas comparativas de los tres modelos.")
    parrafo(doc,
        "Con la especificación corregida, XGBoost es el modelo con mejor "
        "discriminación en el conjunto de validación (AUC = 0,8639, Gini = "
        "0,7278), seguido de Random Forest (AUC = 0,8585) y la Regresión "
        "Logística (AUC = 0,8581). En test, los tres modelos quedan dentro de un "
        "margen de un punto porcentual de AUC entre sí (0,8540-0,8647): la brecha "
        "artificial de más de siete puntos observada en la especificación inicial "
        "desaparece por completo, confirmando que el desplazamiento de "
        "covariables —y no una limitación inherente del algoritmo— era la causa "
        "del deterioro de XGBoost fuera de muestra.")
    parrafo(doc,
        "Dado que la selección de modelo campeón se realiza sobre el conjunto de "
        "validación —la partición metodológicamente correcta para ese propósito, "
        "ya que el test (2024) se reserva exclusivamente para la evaluación "
        "final out-of-time—, XGBoost calibrado isotónicamente se adopta como el "
        "modelo principal de PD utilizado en los Capítulos 10 a 13 y 16. Su "
        "desempeño se contrasta en el Capítulo 17 contra un scorecard "
        "regulatorio tradicional basado en Weight of Evidence.")
    salto_pagina(doc)


def cap10_segmentacion(doc):
    titulo(doc, "10. Segmentación de Cartera: Validación Empírica", nivel=1)
    parrafo(doc,
        "La NIIF 9 párr. 5.5.4 exige agrupar los instrumentos financieros sobre la "
        "base de características de riesgo crediticio compartidas cuando la "
        "evaluación individual del deterioro no es posible; EBA GL/2017/16 §5.2 "
        "añade que la segmentación debe demostrarse empíricamente, verificando que "
        "cada segmento sea internamente homogéneo y mutuamente heterogéneo "
        "respecto de los demás (European Banking Authority, 2017). Este capítulo "
        "aporta el respaldo cuantitativo correspondiente y delimita formalmente el "
        "alcance de la evaluación colectiva frente a la individual.")

    # --- NUEVO EN v5: Sec. 10.1, alcance colectivo vs. individual -----------
    titulo(doc, "10.1 Alcance: Tratamiento Colectivo vs. Individual (Control 3.1)",
          nivel=2)
    parrafo(doc,
        "IFRS 9 §B5.5.1–B5.5.6 permite la evaluación colectiva cuando las "
        "exposiciones son homogéneas y carecen de significatividad individual. "
        "Esta cartera no contiene ninguna exposición que exija evaluación "
        "individual: está compuesta exclusivamente por préstamos hipotecarios "
        "cerrados, unifamiliares, prime / near-prime, sin contrapartes "
        "corporativas ni mayoristas. A efectos de completitud institucional, se "
        "documentan a continuación los criterios que activarían la evaluación "
        "individual en una cartera de producción, explicitando su carácter fuera "
        "de alcance para esta tesis:")
    lista(doc, [
        "Exposiciones corporativas o mayoristas con un importe en libros bruto "
        "superior a EUR 1.000.000 (o su equivalente en moneda local), conforme a "
        "la práctica habitual de EBA GL/2017/16 §5.1 para exposiciones "
        "individualmente significativas.",
        "Reestructuraciones o acuerdos de forbearance a medida, con cronogramas "
        "de flujo de fondos específicos del prestatario que no pueden "
        "representarse mediante una curva de PD/LGD/EAD compartida a nivel de "
        "segmento.",
        "Exposiciones ya clasificadas en Stage 3 con una estrategia de "
        "recuperación específica del caso (p. ej., un workout negociado sobre una "
        "garantía única), donde la curva de LGD colectiva (Sección 12.1) deja de "
        "ser representativa.",
    ])
    parrafo(doc,
        "Ningún registro de dataset_modelado.parquet cumple estos criterios: la "
        "segmentación colectiva desarrollada en las Secciones 10.2 a 10.4 "
        "constituye, por lo tanto, el tratamiento completo y suficiente para "
        "esta cartera.")

    titulo(doc, "10.2 Metodología", nivel=2)
    parrafo(doc,
        "Se evaluaron siete dimensiones de segmentación sobre el modelo XGBoost "
        "calibrado: banda de FICO score, banda de LTV original, banda de DTI, "
        "propósito del préstamo, estado de ocupación, canal de originación y tipo "
        "de propiedad. Para cada segmento se calculan, sobre la partición de test "
        "out-of-time (vintage 2024): AUC, Gini y KS (discriminación); Population "
        "Stability Index entre entrenamiento y test (estabilidad); un test "
        "chi-cuadrado entre el default observado y una subpartición en cuartiles "
        "de una variable de riesgo ortogonal al criterio de segmentación "
        "(homogeneidad intra-segmento); y un test chi-cuadrado global con V de "
        "Cramér, más tests z de dos proporciones entre segmentos contiguos "
        "(heterogeneidad inter-segmento). Se exige un mínimo de 5.000 "
        "observaciones y 50 defaults en test para que un segmento sea reportable.")

    titulo(doc, "10.3 Resultados: Discriminación y Estabilidad por Segmento", nivel=2)
    seg = pd.read_csv(TABLAS_PATH / "segmentacion_metricas.csv")
    rep = seg[seg["reportable"]].copy()
    cols = ["segmentacion", "segmento", "n_test", "tasa_def_test", "AUC_test",
            "KS_test", "PSI", "PSI_estado"]
    _tabla(doc, rep[cols], _tn(7),
          "Discriminación y estabilidad del modelo por segmento (test, vintage 2024)",
          callout=f"La Tabla {_tn(7)} presenta la discriminación y estabilidad del modelo "
                  "dentro de cada segmento.",
          max_filas=30)
    parrafo(doc,
        f"De los {len(seg)} segmentos evaluados, {len(rep)} cumplen el tamaño "
        f"mínimo de reporte. El AUC out-of-time dentro de cada segmento oscila "
        f"entre {rep['AUC_test'].min():.4f} (banda de FICO <660) y "
        f"{rep['AUC_test'].max():.4f} (LTV ≤ 60), con una mediana de "
        f"{rep['AUC_test'].median():.4f}: el poder discriminante del modelo se "
        "conserva de forma consistente a través de todos los cortes evaluados, "
        "sin colapsar en ningún segmento particular. El PSI resulta elevado en la "
        "mayoría de los segmentos —una consecuencia esperable del fuerte cambio "
        "en la composición etaria de la cartera entre entrenamiento (loan_age "
        "medio 31 meses) y test (loan_age medio 4 meses), documentado en la "
        "Sección 8.1, y no de una inestabilidad del modelo en sí.")

    titulo(doc, "10.4 Homogeneidad Intra-Segmento y Heterogeneidad Inter-Segmento",
          nivel=2)
    heterog = pd.read_csv(TABLAS_PATH / "segmentacion_heterogeneidad_global.csv")
    _tabla(doc, heterog, _tn(8), "Heterogeneidad inter-segmento por dimensión de segmentación",
          callout=f"La Tabla {_tn(8)} presenta los resultados del test de heterogeneidad "
                  "inter-segmento.")
    parrafo(doc,
        "Las siete dimensiones evaluadas exhiben heterogeneidad inter-segmento "
        "estadísticamente significativa (p < 0,001 en todos los casos), "
        "confirmando que los segmentos definidos capturan perfiles de riesgo "
        "efectivamente distintos entre sí. La segmentación por banda de FICO "
        "exhibe la mayor V de Cramér, consistente con su rol como principal "
        "driver de riesgo identificado en el análisis SHAP (Capítulo 16).")
    parrafo(doc,
        "El test de homogeneidad intra-segmento (chi-cuadrado entre el default y "
        "una subpartición en cuartiles de una variable de riesgo ortogonal) "
        "rechaza la hipótesis de homogeneidad estricta en la generalidad de los "
        "segmentos. Dado el tamaño muestral de cada segmento (superior a 40.000 "
        "observaciones en la mayoría de los casos), esto es un resultado esperado "
        "de la alta potencia estadística del test —cualquier diferencia "
        "económicamente pequeña se vuelve estadísticamente significativa— y no "
        "necesariamente indica una segmentación defectuosa. La dispersión "
        "relativa de la tasa de default entre los cuartiles internos, "
        "sensiblemente menor que la dispersión observada entre segmentos, es el "
        "diagnóstico económicamente relevante y respalda la adecuación de la "
        "segmentación adoptada.")
    figura(doc, FIGURAS_PATH / "segmentacion_curvas_default.png", 6,
          "Curvas de default acumuladas por segmento (evidencia de heterogeneidad).")
    figura(doc, FIGURAS_PATH / "segmentacion_discriminacion.png", 7,
          "AUC out-of-time del modelo por segmento.")
    salto_pagina(doc)


def cap11_calibracion_lifetime(doc):
    titulo(doc, "11. Calibración PIT y Curva Lifetime PD", nivel=1)
    parrafo(doc,
        "Conforme a la formalización de la Sección 4.6, se generan dos productos "
        "regulatorios: la PD Point-in-Time a 12 meses (output directo del modelo "
        "XGBoost calibrado) y la Lifetime PD, obtenida encadenando las PD "
        "marginales por antigüedad del préstamo (loan_age) mediante el enfoque de "
        "supervivencia en tiempo discreto.")
    curva = pd.read_csv(TABLAS_PATH / "curva_pd_lifetime.csv")
    puntos = curva[curva["loan_age"].isin([12, 24, 36, 60, 120])]
    _tabla(doc, puntos, _tn(9), "Puntos de referencia de la curva Lifetime PD",
          callout=f"La Tabla {_tn(9)} presenta puntos de referencia de la curva Lifetime PD.")
    parrafo(doc,
        "La Lifetime PD acumulada alcanza 8,88 % a los 12 meses, 25,63 % a los 36 "
        "meses y 44,41 % en el límite superior de la ventana observada (109 "
        "meses), estabilizándose a partir de ese punto por escasez de "
        "observaciones de préstamos de mayor antigüedad en la muestra.")
    figura(doc, FIGURAS_PATH / "curva_pd_lifetime.png", 8,
          "PD marginal y Lifetime PD acumulada por antigüedad del préstamo.")
    salto_pagina(doc)


def cap12_ecl_lgd_ead(doc):
    titulo(doc, "12. Cálculo del ECL: LGD, EAD, CCF y Alcance Cambiario", nivel=1)
    parrafo(doc,
        "El cálculo integral del ECL requiere, además de la PD desarrollada en "
        "los capítulos precedentes, una estimación de la Pérdida Dada el Default "
        "(LGD) y de la Exposición al Default (EAD): ECL = PD × LGD × EAD "
        "(Ecuación 3.1). Este capítulo documenta ambos parámetros sobre pérdidas "
        "realizadas del panel Freddie Mac, atendiendo los controles 7.1, 7.3, "
        "7.5, 7.7, 8.1, 8.2 y 8.6 de IFRS9_COMPLIANCE_SPEC.md.")

    titulo(doc, "12.1 LGD: Metodología sobre Pérdidas Realizadas", nivel=2)
    parrafo(doc,
        "Para cada préstamo liquidado con un código de zero-balance de default "
        "(venta a terceros, short sale o disposición REO), Freddie Mac publica el "
        "producido neto de la venta, las recuperaciones de seguro hipotecario "
        "(MI) y no-MI, los gastos totales de gestión y los intereses devengados "
        "impagos, lo que permite estimar la LGD sobre pérdidas efectivamente "
        "materializadas en lugar de sobre supuestos:")
    codigo(doc,
        "Pérdida = EAD - Producido_neto_venta - Recuperaciones_MI - Recuperaciones_no_MI\n"
        "        + Gastos_totales + Intereses_devengados_impagos\n\n"
        "LGD = Pérdida / EAD")
    parrafo(doc,
        f"Curación (cure): un préstamo en default se considera curado cuando "
        f"permanece {LGD_CURE_MESES} meses consecutivos sin mora (probation "
        "period), un criterio conservador frente al mínimo de 3 meses exigido "
        "por EBA GL/2016/07 §7 (European Banking Authority, 2016). Sobre los "
        "13.708 préstamos que registran al menos un evento de default en el "
        "panel, la tasa de curación observada es de 47,67 %.")
    desenlace = pd.read_csv(TABLAS_PATH / "lgd_desenlace_episodios.csv")
    _tabla(doc, desenlace, _tn(10), "Desenlace de los episodios de default y duración del workout",
          callout=f"La Tabla {_tn(10)} presenta el desenlace de los episodios de default.")
    parrafo(doc,
        f"Supuesto de pérdida total: una exposición en default que no se resuelve "
        f"(ni por curación ni por liquidación) dentro de un período de workout de "
        f"{LGD_WORKOUT_MESES_MAX} meses se considera irrecuperable y recibe LGD = "
        f"{LGD_PERDIDA_TOTAL:.0%}, en línea con el art. 181.1.a del Reglamento "
        "(UE) 575/2013 (horizonte máximo observado de recuperación) y el párr. "
        "5.4.4 de la NIIF 9 (baja del importe bruto sin expectativa razonable de "
        "recuperación). En la muestra, 58 exposiciones superan este umbral sin "
        "resolución y reciben el tratamiento de pérdida total. La recuperación "
        "marginal por tramo de workout (Tabla siguiente) decrece y se vuelve "
        "negativa a partir del cuarto año, respaldando empíricamente —no solo "
        "regulatoriamente— el corte de 60 meses (Control 7.5, "
        "IFRS9_COMPLIANCE_SPEC.md).")
    curva_lgd = pd.read_csv(TABLAS_PATH / "lgd_curva_recuperacion.csv")
    _tabla(doc, curva_lgd, _tn(11), "Curva de recuperación por período de workout",
          callout=f"La Tabla {_tn(11)} presenta la curva de recuperación por período de workout.",
          nota="La recuperación marginal decrece y se vuelve negativa a partir del "
               "cuarto año de workout, respaldando empíricamente el corte de 60 meses.")
    figura(doc, FIGURAS_PATH / "lgd_curva_recuperacion.png", 9,
          "Distribución de la LGD realizada y curva de recuperación por período de workout.")
    ltv_lgd = pd.read_csv(TABLAS_PATH / "lgd_por_banda_ltv.csv")
    _tabla(doc, ltv_lgd, _tn(12), "LGD realizada por banda de LTV original",
          callout=f"La Tabla {_tn(12)} presenta la LGD realizada por banda de LTV original.")
    parrafo(doc,
        "La LGD media simple sobre liquidaciones con evento de default es "
        "24,82 %; ponderada por exposición (pérdida total / EAD total de las "
        "liquidaciones), 19,83 %. Sobre esta última se aplica un add-on de "
        f"downturn de {LGD_DOWNTURN_ADDON:.0%} (art. 181.1.b del Reglamento (UE) "
        "575/2013), resultando en una LGD de downturn de 24,83 % utilizada en las "
        "estimaciones de provisión del Capítulo 17.")

    titulo(doc, "12.2 EAD: Amortización Teórica, Prepago y Alcance de CCF", nivel=2)
    parrafo(doc,
        "Para facilidades amortizables, la EAD proyectada se construye a partir "
        "del esquema de amortización teórica de un préstamo francés (cuota "
        "constante), corregido por la velocidad de prepago observada:")
    codigo(doc,
        "EAD_t = UPB_0 · [(1+i)^n − (1+i)^t] / [(1+i)^n − 1]        (amortización teórica)\n"
        "SMM_t = (EAD_teórico_t − UPB_observado_t) / EAD_teórico_t\n"
        "CPR   = 1 − (1 − SMM)^12                                    (prepago anualizado)\n"
        f"EAD_{{{EAD_HORIZONTE_MESES}m}} = EAD_teórico_{{t+{EAD_HORIZONTE_MESES}}} · (1 − CPR) "
        "+ Interés_devengado_impago")
    parrafo(doc,
        "con i = tasa nominal anual / 12 y n = plazo original en meses. El "
        "residual entre el saldo teórico y el saldo efectivamente observado "
        "revela la amortización anticipada, de la cual se deriva la métrica "
        "estándar de mercado hipotecario CPR (Conditional Prepayment Rate).")
    ead_res = pd.read_csv(TABLAS_PATH / "ead_resumen.csv")
    _tabla(doc, ead_res.T.reset_index().rename(columns={"index": "Parámetro", 0: "Valor"}),
          _tn(13), "Resumen de la proyección de EAD a 12 meses y alcance de CCF/divisa",
          callout=f"La Tabla {_tn(13)} resume la proyección de EAD a 12 meses.")
    figura(doc, FIGURAS_PATH / "ead_amortizacion_prepago.png", 10,
          "Saldo teórico vs. observado y velocidad de prepago (CPR) por antigüedad del préstamo.")
    parrafo(doc,
        f"La CPR anual media implícita es de 0,86 %, y la EAD proyectada a "
        f"{EAD_HORIZONTE_MESES} meses representa el 99,6 % del saldo actual medio "
        "de la cartera viva —una cartera de amortización lenta relativa a su "
        "saldo, consistente con tasas de interés de originación bajas en gran "
        "parte del período muestral, que reducen el incentivo económico al "
        "prepago (refinanciamiento).")
    parrafo(doc,
        f"Factores de Conversión Crediticia: la cartera analizada está compuesta "
        f"exclusivamente por préstamos hipotecarios cerrados, íntegramente "
        f"desembolsados y amortizables. No existen líneas revolving, compromisos "
        f"no dispuestos ni saldos contingentes, por lo que CCF = "
        f"{CCF_OFF_BALANCE:.0%} sobre el fuera de balance: la EAD coincide "
        "íntegramente con el saldo en balance. Los CCF regulatorios estándar "
        "(art. 111 del Reglamento (UE) 575/2013 / Basilea III, enfoque estándar) "
        f"que aplicarían de extenderse el alcance a líneas de crédito "
        f"comprometidas o garantías financieras se documentan en la Tabla {_tn(14)} a "
        "efectos de completitud metodológica.")
    ccf = pd.read_csv(TABLAS_PATH / "ccf_alcance.csv")
    _tabla(doc, ccf, _tn(14), "Delimitación de alcance de exposiciones fuera de balance y "
                        "CCF regulatorios de referencia")
    parrafo(doc,
        f"Alcance cambiario: la totalidad de la cartera Freddie Mac está "
        f"denominada y liquidada en {MONEDA_BASE}, por lo que no existe descalce "
        "cambiario ni necesidad de una política de conversión (tipo de cambio "
        "spot o forward) para el cálculo del ECL de esta cartera (Control 8.6, "
        "IFRS9_COMPLIANCE_SPEC.md).")

    # --- NUEVO EN v5: Sec. 12.3, gobernanza cambiaria hipotetica ------------
    titulo(doc, "12.3 Gobernanza de Riesgo Cambiario para Facilidades "
                "Multi-Divisa (Extensión Hipotética)", nivel=2)
    parrafo(doc,
        "La declaración de perímetro anterior —cartera 100 % denominada y "
        "liquidada en USD, CARTERA_MULTIDIVISA = False (config.py)— cierra el "
        "Control 8.6 para el alcance efectivo de esta tesis. A efectos de "
        "completitud institucional, se formalizan a continuación los controles "
        "que regirían el cálculo de EAD si el alcance de modelado se extendiera "
        "en el futuro a facilidades no denominadas en USD:")
    lista(doc, [
        "Conversión a tipo de cambio de fixing diario: la EAD y los saldos "
        "vigentes en moneda extranjera se convierten a la moneda de reporte "
        "utilizando el tipo de cambio de fixing oficial diario (publicación H.10 "
        "de la Reserva Federal para cruces con USD, o los tipos de referencia del "
        "BCE para reporte en EUR), aplicado de forma consistente en cada fecha de "
        "reporte —nunca el tipo histórico de la fecha de la transacción para "
        "fines de ECL.",
        "Descuento a tipo forward para el CCF de líneas revolving: para todo "
        "compromiso revolving fuera de balance en moneda extranjera, la "
        "disposición proyectada (vía el factor CCF_REGULATORIOS aplicable, "
        "config.py) se descuenta utilizando el tipo de cambio forward "
        "correspondiente a la fecha esperada de disposición, no el tipo spot, "
        "para evitar subestimar la EAD ante escenarios de apreciación de la "
        "divisa.",
        "Haircuts de divisa sobre la garantía: cuando la garantía (p. ej., una "
        "propiedad en el extranjero) está denominada en una moneda distinta de "
        "la de la facilidad, el valor de la garantía utilizado en el cálculo de "
        "LGD se somete a un haircut adicional que refleja la volatilidad "
        "cambiaria histórica entre ambas monedas, por encima del add-on de "
        "downturn estándar (LGD_DOWNTURN_ADDON, Sección 12.1).",
    ])
    parrafo(doc,
        "Esta política se especifica en detalle en IFRS9_COMPLIANCE_SPEC.md "
        "(Sección 3.6) y se referencia aquí para que el capítulo empírico y el "
        "documento de cumplimiento permanezcan sincronizados.")
    salto_pagina(doc)


def cap13_validacion(doc):
    titulo(doc, "13. Validación Regulatoria del Modelo PD", nivel=1)
    parrafo(doc,
        "Conforme a la formalización de la Sección 4.8, se reportan métricas de "
        "discriminación (AUC, Gini, KS), calibración (Brier Score, contraste de "
        "Hosmer-Lemeshow) y estabilidad (PSI) sobre el conjunto de test "
        "out-of-time (vintage 2024), completando así el Control 12.1 de "
        "IFRS9_COMPLIANCE_SPEC.md.")

    titulo(doc, "13.1 Resultados de Validación", nivel=2)
    val = pd.read_csv(TABLAS_PATH / "validacion_metricas.csv")
    _tabla(doc, val, _tn(15), "Métricas de validación regulatoria – test set (vintage 2024)",
          callout=f"La Tabla {_tn(15)} presenta las métricas de validación regulatoria.")
    parrafo_mixto(doc, [
        ("Los tres modelos superan ampliamente el umbral mínimo de KS > 0,30 "
         "considerado aceptable para modelos de crédito (KS entre 0,545 y "
         "0,557). El contraste de Hosmer-Lemeshow rechaza la hipótesis de "
         "calibración perfecta por decil (", False),
        ("p", True),
        (" ≈ 0) en los tres casos, un resultado habitual dado el tamaño "
         "muestral del test (", False),
        ("N", True),
        (" = 412.065 observaciones), que otorga potencia estadística "
         "suficiente para detectar desvíos de calibración económicamente "
         "pequeños; el Brier Score (0,0028 en los tres modelos) es el "
         "diagnóstico de calibración más informativo a esta escala.", False),
    ])
    figura(doc, FIGURAS_PATH / "validacion_roc.png", 11,
          "Curva ROC comparativa de los tres modelos (test, vintage 2024).")
    figura(doc, FIGURAS_PATH / "validacion_backtesting.png", 12,
          "Backtesting por decil: PD predicha vs. observada.")

    titulo(doc, "13.2 Backtesting de Transiciones de Stages y Lifetime PD", nivel=2)
    parrafo(doc,
        "La matriz de transición trimestral observada (Stage t → Stage t+3 "
        "meses) confirma la coherencia direccional del modelo de stages: "
        "99,14 % de las observaciones en Stage 1 permanecen en Stage 1 al "
        "trimestre siguiente, y solo un 0,10 % migra directamente a Stage 3 sin "
        "pasar por Stage 2, lo que indica que el criterio de SICR captura el "
        "deterioro con antelación en la inmensa mayoría de los casos. La tasa de "
        "curación trimestral (Stage 2 → 1) es de 48,96 %.")
    trans = pd.DataFrame({
        "Stage t \\ Stage t+3m": ["1", "2", "3"],
        "→ 1": [0.9914, 0.4896, 0.2569],
        "→ 2": [0.0077, 0.2993, 0.0433],
        "→ 3": [0.0010, 0.2111, 0.6998],
    })
    _tabla(doc, trans, _tn(16), "Matriz de transición trimestral observada de stages IFRS 9")
    parrafo(doc,
        "El backtesting de la curva Lifetime PD contra la tasa de default "
        "acumulada observada por cohorte de originación arroja un ratio "
        "predicho/observado promedio de 10,7×: la curva es marcadamente "
        "conservadora en los horizontes largos, sobre todo por la extrapolación "
        "de hazard constante sobre observaciones limitadas más allá de los 60 "
        "meses de antigüedad. Se documenta como limitación metodológica y línea "
        "futura (Capítulo 18) refinar la extrapolación de la cola de la curva.")

    # --- NUEVO EN v5: Sec. 13.3, test Z binomial + IC95 Wilson --------------
    titulo(doc, "13.3 Intervalos de Confianza Binomiales y Test Z por Decil "
                "(Control 6.5)", nivel=2)
    parrafo_mixto(doc, [
        ("El contraste de Hosmer-Lemeshow (Sección 13.1) pierde potencia "
         "discriminante a ", False),
        ("N", True),
        (" > 400.000: rechaza la calibración perfecta incluso ante desvíos "
         "económicamente irrelevantes. Como complemento, se calcula por decil "
         "un test binomial ", False),
        ("Z", True),
        (" (bajo H0: PD observada = PD predicha) y el intervalo de Wilson al "
         "95 % sobre la tasa observada —más robusto que el intervalo normal a "
         "la tasa de evento de esta cartera (≈1,3 %)—:", False),
    ])
    codigo(doc,
        "Z = (pd_observada - pd_predicha) / sqrt(pd_predicha·(1-pd_predicha)/n)\n\n"
        "IC95_Wilson = [ p̂ + z²/2n ± z·sqrt(p̂(1-p̂)/n + z²/4n²) ] / (1 + z²/n),   z = 1,96")
    ic = pd.read_csv(TABLAS_PATH / "validacion_calibracion_intervalos.csv")
    _tabla(doc, ic, 18,
          "Test Z binomial e intervalo de Wilson al 95 % por decil y modelo (test, vintage 2024)",
          callout="La Tabla 18 presenta el test Z binomial y el intervalo de Wilson "
                  "al 95 % por decil, para los tres modelos.",
          nota="pd_predicha_dentro_ic95 indica si la PD media predicha del decil cae dentro "
               "del intervalo de Wilson de la tasa observada.",
          max_filas=30)
    n_rechaza = int((ic["p_valor_z"] < 0.05).sum())
    n_total = len(ic)
    parrafo_mixto(doc, [
        (f"De las {n_total} combinaciones modelo-decil evaluadas, {n_rechaza} "
         "rechazan H0 (", False),
        ("p", True),
        (" < 0,05) y muestran la PD predicha fuera del intervalo de Wilson de "
         "la tasa observada —el mismo efecto de sobre-potencia estadística por "
         "tamaño muestral ya documentado para Hosmer-Lemeshow, no evidencia de "
         "un problema de calibración distinto—. El hallazgo económicamente "
         "relevante es la dirección sistemática del sesgo: en la práctica "
         "totalidad de los deciles, la PD predicha excede a la observada (", False),
        ("z", True),
        (" negativo en todos los casos), es decir, los tres modelos son "
         "consistentemente conservadores, más pronunciadamente en el decil de "
         "mayor riesgo. Este sesgo conservador es cualitativamente consistente "
         "con el ratio predicho/observado de 10,7× ya documentado para la curva "
         "Lifetime PD (más arriba en esta sección) y con el add-on de downturn "
         "aplicado sobre la LGD (Sección 12.1): el pipeline erra sistemáticamente "
         "hacia una mayor prudencia regulatoria, nunca hacia la subestimación "
         "del riesgo.", False),
    ])
    salto_pagina(doc)


def cap14_contagio(doc):
    titulo(doc, "14. Criterios de Contagio Subjetivo y Agregación de Riesgo", nivel=1)
    parrafo(doc,
        "EBA GL/2017/16 §5.1 exige una política formal de contagio de riesgo "
        "(pulling effect) entre exposiciones vinculadas al mismo prestatario o "
        "grupo económico, de modo que el deterioro de una facilidad se propague "
        "razonablemente al resto de sus exposiciones (European Banking "
        "Authority, 2017).")
    parrafo(doc,
        "Delimitación de alcance: el Freddie Mac Single-Family Loan-Level "
        "Dataset corresponde a cartera hipotecaria minorista individual, donde la "
        "unidad de análisis y de originación es la facilidad hipotecaria sobre "
        "una única propiedad. El dataset no identifica al prestatario de forma "
        "persistente entre operaciones —loan_sequence_number es un identificador "
        "de facilidad, no de cliente—, por lo que no es posible reconstruir "
        "empíricamente relaciones de grupo económico o de exposiciones múltiples "
        "de un mismo titular dentro de esta fuente de datos pública (Controles "
        "5.1 y 5.3, IFRS9_COMPLIANCE_SPEC.md).")
    parrafo(doc,
        "Se formaliza, no obstante, la regla de arrastre a nivel prestatario / "
        "codeudor que debería aplicarse en una implementación productiva sobre "
        "datos con identificador de cliente:")
    lista(doc, [
        "Regla de arrastre (pulling effect): si cualquier facilidad de un "
        "prestatario —o de un codeudor común, dado que number_of_borrowers > 1— "
        "se clasifica en Stage 3, el resto de las exposiciones activas del mismo "
        "titular se reclasifica como mínimo a Stage 2, independientemente de su "
        "propio indicador de mora o de PD individual.",
        "Ámbito de aplicación: la regla opera a nivel de grupo económico cuando "
        "existe información societaria (carteras comerciales o corporativas); a "
        "nivel de prestatario o codeudor individual en cartera minorista, como "
        "es el caso de esta tesis.",
        "Excepción documentada: la regla no se aplica cuando el default de la "
        "facilidad contagiante obedece a una causa idiosincrática y verificable "
        "ajena a la capacidad de pago del titular, sujeto a aprobación de la "
        "función de riesgo.",
    ])
    parrafo(doc,
        "Esta delimitación de alcance no afecta la validez de las estimaciones "
        "de PD, LGD y EAD presentadas en los Capítulos 9 a 12: al tratarse de "
        "prestatarios con una única facilidad hipotecaria activa en la base "
        "—supuesto razonable dada la naturaleza minorista e individual de la "
        "cartera Freddie Mac—, la unidad de análisis facilidad = prestatario "
        "coincide en la práctica totalidad de los casos.")
    salto_pagina(doc)


def cap15_pma(doc):
    titulo(doc, "15. Gobernanza de Overrides y Post-Model Adjustments (PMA)", nivel=1)
    parrafo(doc,
        "EBA GL/2017/16 §13 exige un marco formal para los ajustes cualitativos "
        "aplicados sobre la salida del modelo estadístico (overrides y PMA), con "
        "criterios de activación, metodología de cálculo, registro de auditoría "
        "y aprobación independiente (European Banking Authority, 2017).")
    parrafo(doc, "Criterios de activación de un PMA:")
    lista(doc, [
        "Eventos macroeconómicos materiales no capturados por las variables del "
        "modelo o por su ventana de entrenamiento (por ejemplo, un shock de "
        "tasas o de desempleo posterior al último reentrenamiento).",
        "Distorsiones temporales en los datos de entrenamiento (rupturas de "
        "serie, cambios de definición operativa, moratorias regulatorias como "
        "los programas de deferral observados en la cartera 2020).",
        "Desvíos sostenidos entre la PD observada y la predicha detectados en el "
        "backtesting del Capítulo 13 que superen los umbrales de alerta "
        "temprana de la función de validación, mientras se investiga la causa "
        "raíz.",
        "Cambios regulatorios o de producto que alteren el perfil de riesgo de "
        "un segmento antes de que exista historia suficiente para reentrenar "
        "el modelo.",
    ])
    gob = pd.DataFrame([
        {"Nivel": "Informativo", "Umbral": f"< {PMA_UMBRAL_INFORMATIVO:.0%} del ECL de cartera",
         "Aprobación": "Función de Validación independiente"},
        {"Nivel": "Material", "Umbral": f">= {PMA_UMBRAL_MATERIALIDAD:.0%} del ECL de cartera",
         "Aprobación": "Comité de Riesgos (previa a la aplicación)"},
    ])
    _tabla(doc, gob, _tn(17), "Umbrales de materialidad y niveles de aprobación de PMA")
    parrafo(doc,
        "Metodología de cálculo: todo PMA se cuantifica como un ajuste explícito "
        "y aditivo sobre el ECL de modelo —nunca como una modificación directa de "
        "los parámetros PD, LGD o EAD—, de modo que su efecto sea siempre "
        "identificable y reversible de forma independiente.")
    parrafo(doc,
        f"Vigencia y reversión: un PMA no puede mantenerse vigente por más de "
        f"{PMA_VIGENCIA_MAX_TRIMESTRES} trimestres consecutivos sin que la "
        "función de validación revise si la causa que lo originó persiste; "
        "cumplido el plazo, el ajuste debe revertirse o incorporarse "
        "formalmente al modelo mediante reentrenamiento o recalibración. Cada "
        "PMA se documenta en un registro estructurado "
        "(outputs/tablas/registro_pma_overrides.csv) con fecha de activación, "
        "segmento afectado, magnitud, metodología de cálculo, responsable "
        "técnico, instancia aprobatoria y fecha de revisión programada. Este "
        "registro está especificado y su ruta configurada (config.PMA_REGISTRO), "
        "pero no contiene eventos: al tratarse de un backtest histórico sin un "
        "proceso de override en producción, no existe ningún PMA que documentar "
        "(Control 13.2, IFRS9_COMPLIANCE_SPEC.md).")
    salto_pagina(doc)


def cap16_explicabilidad(doc):
    titulo(doc, "16. Explicabilidad del Modelo", nivel=1)
    parrafo(doc,
        "Conforme a los principios de gobernanza de modelos IFRS 9 (European "
        "Central Bank, 2021) y a la formalización de Shapley values de la "
        "Sección 4.7, se aplican herramientas SHAP en dos niveles sobre el "
        "modelo XGBoost calibrado.")
    lista(doc, [
        "Global: SHAP Summary Plot y Bar Plot, que muestran qué variables tienen "
        "mayor impacto promedio sobre la PD estimada en toda la cartera.",
        "Local: SHAP Waterfall Plot, que descompone la predicción individual de "
        "un préstamo específico en la contribución marginal de cada variable.",
    ])
    shap_imp = pd.read_csv(TABLAS_PATH / "importancia_shap_xgboost.csv")
    _tabla(doc, shap_imp, _tn(18), "Importancia SHAP media por variable (modelo XGBoost)",
          callout=f"La Tabla {_tn(18)} presenta la importancia SHAP media por variable.",
          max_filas=15)
    parrafo(doc,
        "El credit_score domina la atribución SHAP, seguido del ELTV, la "
        "antigüedad del préstamo (loan_age) y el máximo DPD en los últimos 12 "
        "meses: las variables de comportamiento dinámico y el score de "
        "originación dominan la predicción, consistente con la literatura de "
        "scoring de crédito hipotecario (Fitzpatrick & Mues, 2016; Elul et al., "
        "2010).")
    figura(doc, FIGURAS_PATH / "shap_summary_xgboost.png", 13,
          "SHAP Summary Plot – efecto de cada variable sobre la PD.")
    figura(doc, FIGURAS_PATH / "shap_barplot_xgboost.png", 14,
          "Importancia SHAP media – top 15 variables.")
    salto_pagina(doc)


def cap17_costo_regulacion(doc):
    titulo(doc,
        "17. El Costo de la Regulación: Scorecard WoE vs. Machine Learning sin Restricciones",
        nivel=1)
    parrafo(doc,
        "Este capítulo compara dos arquitecturas de modelado de PD bajo el mismo "
        "marco IFRS 9 y la misma partición temporal out-of-time: un scorecard "
        "regulatorio tradicional basado en Weight of Evidence (WoE) —el enfoque "
        "canónico de la industria de riesgo de crédito (Siddiqi, 2006; Thomas et "
        "al., 2017)— y los modelos de Machine Learning sin restricciones de "
        "discretización desarrollados en los Capítulos 8 y 9. El objetivo es "
        "cuantificar cuánta capacidad predictiva se sacrifica —o se gana en "
        "gobernabilidad— al imponer la estructura WoE, y cómo esa diferencia se "
        "traduce en provisiones de ECL y en la tasa de falsos positivos de la "
        "migración a Stage 2.")

    titulo(doc, "17.1 Metodología: Binning WoE e Information Value", nivel=2)
    parrafo(doc,
        "El Weight of Evidence de un bin se define como el logaritmo del "
        "cociente entre la proporción de no-defaulters y de defaulters que caen "
        "en ese bin, y el Information Value (IV) de una variable como la suma, "
        "sobre todos sus bins, del producto entre esa diferencia de proporciones "
        "y su WoE:")
    codigo(doc,
        "WoE_bin = ln( %no-default en el bin / %default en el bin )\n"
        "IV      = Σ_bin (%no-default - %default) · WoE_bin")
    parrafo(doc,
        "Las variables continuas se discretizan en 10 bins por cuantiles "
        "ajustados exclusivamente sobre el conjunto de entrenamiento; las "
        "variables categóricas reciben un bin por categoría. Se aplica "
        "suavizado de Laplace para evitar log(0) en bins con cero defaults, dada "
        "la baja tasa de eventos de la cartera (≈1,3 %). Sobre la matriz "
        "transformada se entrenan Regresión Logística, XGBoost y Random Forest "
        "(familia WoE); ambos algoritmos de árboles se restringen a "
        "profundidades moderadas dado que la estructura WoE ya impone "
        "monotonía por diseño. La familia de ML sin restricciones reutiliza los "
        "modelos XGBoost y Random Forest del Capítulo 9, entrenados "
        "directamente sobre variables continuas y relativas a cohorte, "
        "calibrados isotónicamente.")
    iv = pd.read_csv(TABLAS_PATH / "woe_bins_iv.csv")
    _tabla(doc, iv, _tn(19), "Information Value por variable (scorecard WoE)",
          callout=f"La Tabla {_tn(19)} presenta el Information Value de cada variable "
                  "bajo la transformación WoE.",
          max_filas=15)
    parrafo(doc,
        "El credit_score y su versión relativa a cohorte concentran el mayor "
        "poder predictivo individual (IV = 0,532 y 0,467 respectivamente), "
        "seguidos de la amortización relativa del saldo y el ELTV. El IV del "
        "credit_score se clasifica convencionalmente como \"sospechoso\" "
        "(IV > 0,50): en la práctica de la industria, un valor tan alto suele "
        "señalar sobreajuste del binning a la muestra de entrenamiento y amerita "
        "una revisión de la granularidad de los bins antes de un despliegue "
        "productivo del scorecard.")

    titulo(doc, "17.2 Discriminación y Calibración Comparadas", nivel=2)
    cmp = pd.read_csv(TABLAS_PATH / "comparacion_woe_vs_raw_metricas.csv")
    _tabla(doc, cmp, _tn(20),
          "Discriminación y calibración: scorecard WoE vs. ML sin restricciones (test 2024)",
          callout=f"La Tabla {_tn(20)} compara la discriminación y calibración de ambas familias de modelos.")
    parrafo(doc,
        "La familia de ML sin restricciones domina en discriminación pura: el "
        "AUC de XGBoost y Random Forest (Raw, calibrados) se ubica entre 0,854 y "
        "0,856, frente a 0,782-0,792 de los tres modelos WoE —una brecha de Gini "
        "de aproximadamente 13 a 15 puntos—, consistente con la pérdida de "
        "información inherente a la discretización en bins. El Brier Score es "
        "levemente inferior (mejor) en la familia Raw (0,0028 vs. 0,0030-0,0031).")
    figura(doc, FIGURAS_PATH / "woe_vs_raw_roc.png", 15,
          "Curva ROC – scorecard WoE vs. ML sin restricciones (test 2024).")

    titulo(doc, "17.3 Migración a Stage 2 y Provisión de ECL", nivel=2)
    parrafo(doc,
        "Para aislar el efecto de la arquitectura de modelado sobre el "
        "staging, se recalcula el criterio de SICR del Capítulo 7 (k = 2,5; "
        "delta = 5 p.p.; backstop de 30 DPD) usando la propia PD de originación "
        "y PD corriente de cada modelo, y se estima el ECL de cartera bajo esa "
        "clasificación propia (LGD de downturn = 24,83 %, Capítulo 12; EAD = "
        "saldo actual por préstamo).")
    sicr_cmp = pd.read_csv(TABLAS_PATH / "comparacion_woe_vs_raw_sicr.csv")
    _tabla(doc, sicr_cmp, _tn(21),
          "Migración a Stage 2 (SICR) y falsos positivos por arquitectura de modelo",
          callout=f"La Tabla {_tn(21)} presenta la migración a Stage 2 y la tasa de falsos "
                  "positivos de SICR por modelo.",
          nota="sicr_falsos_positivos es la proporción de préstamos flagueados en "
               "Stage 2 que NO defaultearon en los 12 meses siguientes.")
    ecl_cmp = pd.read_csv(TABLAS_PATH / "comparacion_woe_vs_raw_ecl.csv")
    _tabla(doc, ecl_cmp, _tn(22), "Provisión de ECL de cartera bajo la propia clasificación de cada modelo",
          callout=f"La Tabla {_tn(22)} presenta la provisión de ECL resultante bajo la "
                  "clasificación de stage propia de cada modelo.")
    parrafo(doc,
        "Los scorecards WoE —en particular XGBoost y Random Forest entrenados "
        "sobre variables WoE— migran una proporción sensiblemente mayor de la "
        "cartera a Stage 2 (15,75 % y 19,63 %, respectivamente) que los modelos "
        "de ML sin restricciones (12,21 % y 9,46 %), pero con una tasa de "
        "default observada *menor* dentro de ese Stage 2 (0,90 % y 0,83 % "
        "frente a 1,11 % y 1,40 %): es decir, generan una proporción "
        "sensiblemente mayor de falsos positivos de SICR. Esto se traduce "
        "directamente en una provisión de ECL agregada más alta: el scorecard "
        "Random Forest-WoE provisiona 163,5 puntos básicos sobre EAD, 2,02 veces "
        "más que el scorecard Logístico-WoE (80,8 pb) para un riesgo real "
        "subyacente esencialmente idéntico —la tasa de default global observada "
        "en test es la misma para todos los modelos por construcción "
        "(0,3007 %).")
    figura(doc, FIGURAS_PATH / "woe_vs_raw_ecl_provisiones.png", 16,
          "Provisión de ECL de cartera y tasa de migración a Stage 2 por modelo.")

    titulo(doc, "17.4 Discusión: El Costo de la Regulación", nivel=2)
    parrafo(doc,
        "Los resultados cuantifican el trade-off entre gobernabilidad y "
        "eficiencia de capital que subyace a la elección entre un scorecard "
        "regulatorio tradicional y un modelo de ML sin restricciones. El "
        "scorecard WoE ofrece ventajas de gobernanza difíciles de replicar con "
        "modelos de árboles sin discretizar —monotonía garantizada por "
        "construcción, coeficientes de la Regresión Logística directamente "
        "interpretables como contribución marginal al log-odds, e Information "
        "Value como métrica estándar de la industria para justificar la "
        "inclusión de cada variable ante el supervisor—, pero a un costo "
        "concreto y medible: una pérdida de discriminación de 13 a 15 puntos de "
        "Gini y una sobre-provisión de hasta 2,02× frente al modelo de ML mejor "
        "calibrado, para el mismo riesgo real subyacente. Dado que el modelo "
        "XGBoost sobre variables raw se calibra isotónicamente y conserva "
        "restricciones de monotonía sobre sus drivers de riesgo (Sección 9.1), "
        "gran parte de la ventaja de gobernanza del scorecard WoE se preserva "
        "sin incurrir en el costo de discretización, sugiriendo que la brecha "
        "cuantificada en este capítulo es, en gran medida, evitable.")
    salto_pagina(doc)


def cap18_conclusiones(doc):
    titulo(doc, "18. Conclusiones y Líneas Futuras", nivel=1)
    titulo(doc, "18.1 Conclusiones", nivel=2)
    parrafo(doc,
        "Este trabajo presenta una metodología completa y reproducible para la "
        "estimación de la Probabilidad de Default, la Pérdida Dada el Default y "
        "la Exposición al Default bajo el marco regulatorio IFRS 9, utilizando "
        "datos hipotecarios públicos de Freddie Mac, y remedia de forma "
        "cuantitativa los hallazgos de la auditoría de cumplimiento documental "
        "IFRS 9 / EBA GL/2017/16 sistematizados en IFRS9_COMPLIANCE_SPEC.md "
        "sobre una versión previa del modelo. Los principales resultados son:")
    lista(doc, [
        "Se diagnosticó y corrigió un desplazamiento de covariables severo que "
        "hacía que XGBoost, pese a ser el modelo con mayor capacidad de ajuste, "
        "obtuviera el peor desempeño out-of-time de los tres modelos evaluados; "
        "la sustitución de variables de nivel absoluto por variables relativas a "
        "la cohorte de originación, junto con restricciones de monotonía y un "
        "esquema disciplinado de early stopping, cerró por completo esa brecha.",
        "Se formalizó cuantitativamente el criterio de SICR sobre Lifetime PD "
        "(umbral relativo k = 2,5, umbral absoluto de 5 p.p., backstop de 30 DPD "
        "como refuerzo estrictamente prudencial), calibrado empíricamente sobre "
        "una grilla de sensibilidad y validado contra el backtesting de "
        "transiciones de stages, y se documentó formalmente el mapeo de "
        "criterios subjetivos de UTP y la brecha pendiente de un disparador "
        "explícito por concesión NPV (Capítulo 7).",
        "Se completó el cálculo integral del ECL, estimando LGD sobre pérdidas "
        "realizadas (24,83 % de downturn) y EAD mediante un esquema de "
        "amortización teórica ajustado por prepago, con delimitación explícita "
        "del alcance de CCF (nulo, cartera cerrada), de la exposición cambiaria "
        "(monomoneda USD) y de la gobernanza que regiría una extensión "
        "hipotética a facilidades multi-divisa (Capítulo 12).",
        "Se aportó el respaldo cuantitativo empírico de la segmentación de "
        "cartera exigido por EBA GL/2017/16 §5.2 sobre siete dimensiones, "
        "confirmando discriminación estable y heterogeneidad inter-segmento "
        "estadísticamente significativa en todos los casos, y se delimitó "
        "formalmente el alcance de la evaluación colectiva frente a la "
        "individual (Capítulo 10).",
        "Se complementó el backtesting de calibración con un test binomial Z e "
        "intervalos de Wilson por decil, que confirman un sesgo conservador "
        "sistemático (la PD predicha excede a la observada en la práctica "
        "totalidad de los deciles) cualitativamente consistente con el sesgo ya "
        "documentado en la curva Lifetime PD (Capítulo 13).",
        "Se formalizaron las políticas de contagio de riesgo entre exposiciones "
        "de un mismo prestatario y de gobernanza de overrides y Post-Model "
        "Adjustments, ausentes en la versión previa del modelo.",
        "Se cuantificó el costo de la regulación: un scorecard WoE tradicional "
        "sacrifica entre 13 y 15 puntos de Gini frente a un modelo de ML "
        "calibrado y monotónico, y puede sobre-provisionar el ECL de cartera "
        "hasta 2,02× para el mismo riesgo real subyacente, por una tasa "
        "sensiblemente mayor de falsos positivos en la migración a Stage 2.",
    ])

    titulo(doc, "18.2 Líneas Futuras", nivel=2)
    lista(doc, [
        "Incorporar variables macroeconómicas (desempleo, tasas de interés) de "
        "forma sistemática para stress testing y ponderación de escenarios "
        "(Sección 3.5), actualmente condicionadas a la disponibilidad de una "
        "clave de acceso a la API de FRED (Controles 9.3 y 10.1, "
        "IFRS9_COMPLIANCE_SPEC.md).",
        "Refinar la extrapolación de la cola de la curva Lifetime PD más allá de "
        "los 60 meses de antigüedad, dado el sesgo conservador (ratio "
        "predicho/observado de 10,7×) detectado en el backtesting del Capítulo "
        "13.",
        "Implementar el disparador de default por concesión NPV para "
        "modificaciones y forbearance (Capítulo 7, Control 4.1), actualmente "
        "capturado solo como covariable de comportamiento.",
        "Reconstruir relaciones de grupo económico y de codeudores sobre datos "
        "con identificador de cliente persistente, para operacionalizar la "
        "regla de contagio formalizada en el Capítulo 14.",
        "Reducir la granularidad del binning WoE del credit_score (IV "
        "actualmente en rango \"sospechoso\") antes de cualquier despliegue "
        "productivo del scorecard regulatorio del Capítulo 17.",
        "Aplicar la metodología completa —PD, LGD, EAD y gobernanza— a datos de "
        "entidades financieras argentinas bajo BCRA/NIIF 9 (Banco Central de la "
        "República Argentina, 2024).",
    ])


def agregar_referencias_nuevas(doc):
    """Inserta la referencia nueva de v5 (Wilson, 1927) en su posicion
    alfabetica correcta (entre Vasicek, 2002 y Zadrozny & Elkan, 2002),
    sin tocar las referencias ya existentes de v3/v4."""
    insertar_referencia_antes(
        doc,
        [("Wilson, E. B. (1927). ", False),
         ("Probable inference, the law of succession, and statistical inference.",
          True),
         (" Journal of the American Statistical Association, 22(158), 209–212.", False)],
        "Zadrozny, B., & Elkan",
    )


# ============================================================================
# 3. Orquestacion principal
# ============================================================================

def main():
    print("=" * 60)
    print("GENERADOR DE TESIS v5 - a partir de v4")
    print("=" * 60)
    assert V4_PATH.exists(), f"No se encontro el documento base: {V4_PATH}"

    doc = Document(str(V4_PATH))
    ch5_idx, refs_idx = localizar_anclas(doc)
    print(f"Capitulo 5 (v4) en parrafo {ch5_idx} | 'Referencias' en parrafo {refs_idx}")

    refs_heading_par = doc.paragraphs[refs_idx]
    eliminar_rango(doc, ch5_idx, refs_idx)
    print("Capitulos 5-18 (v4) y tablas asociadas eliminados. "
          "Capitulos 1-4 y Referencias preservados intactos.")

    ultimo_original = ultimo_elemento_de_contenido(doc)

    print("Escribiendo capitulos 5-18 (con contenido nuevo de "
          "IFRS9_COMPLIANCE_SPEC.md y tablas renumeradas) ...")
    cap5_dataset_completo(doc)
    cap6_pipeline(doc)
    cap7_default_sicr(doc)
    cap8_feature_engineering(doc)
    cap9_modelado(doc)
    cap10_segmentacion(doc)
    cap11_calibracion_lifetime(doc)
    cap12_ecl_lgd_ead(doc)
    cap13_validacion(doc)
    cap14_contagio(doc)
    cap15_pma(doc)
    cap16_explicabilidad(doc)
    cap17_costo_regulacion(doc)
    cap18_conclusiones(doc)

    reubicar_nuevo_contenido(doc, refs_heading_par, ultimo_original)
    print("Capitulos nuevos reubicados antes de 'Referencias'.")

    agregar_referencias_nuevas(doc)
    print("Referencia nueva insertada (Wilson, 1927).")

    doc.save(str(V5_PATH))
    print(f"\nDocumento guardado: {V5_PATH}")
    print(f"v4 preservado sin modificaciones en: {V4_PATH}")


if __name__ == "__main__":
    main()
