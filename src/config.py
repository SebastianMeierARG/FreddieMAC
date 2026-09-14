"""
config.py – Configuración global del proyecto de tesis
========================================================
Rutas, constantes y parámetros compartidos por todos los módulos.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------------------------
BASE_PATH        = Path(__file__).parent.parent          # raíz FreddieMAC/
DATA_PATH        = BASE_PATH / "data"                    # parquets finales
DATA_SAMPLE_PATH = BASE_PATH / "data_sample_year"        # txt crudos por año
OUTPUTS_PATH     = BASE_PATH / "outputs"                 # tablas, figuras, modelos

# Sub-carpetas de salida (se crean automáticamente si no existen)
FIGURAS_PATH = OUTPUTS_PATH / "figuras"
MODELOS_PATH = OUTPUTS_PATH / "modelos"
TABLAS_PATH  = OUTPUTS_PATH / "tablas"

for p in [OUTPUTS_PATH, FIGURAS_PATH, MODELOS_PATH, TABLAS_PATH]:
    p.mkdir(parents=True, exist_ok=True)

MACRO_PATH = DATA_PATH / "macro"
MACRO_PATH.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Archivos de datos intermedios (se van generando por paso)
# ---------------------------------------------------------------------------
ORIG_PARQUET        = DATA_PATH / "orig_all.parquet"
SVCG_PARQUET        = DATA_PATH / "svcg_all.parquet"
PANEL_PARQUET       = DATA_PATH / "panel.parquet"
PANEL_DEF_PARQUET   = DATA_PATH / "panel_con_default.parquet"
DATASET_MOD_PARQUET = DATA_PATH / "dataset_modelado.parquet"

# ---------------------------------------------------------------------------
# Parámetros IFRS 9
# ---------------------------------------------------------------------------
# Umbral de días en mora para default (90+ DPD = bucket ≥ 3)
UMBRAL_DPD_DEFAULT = 3

# Horizonte de predicción en meses (PD a 12 meses)
HORIZONTE_PD_MESES = 12

# Códigos de Zero Balance que constituyen evento de default/pérdida
# 02 = Third Party Sale, 03 = Short Sale/Charge Off, 09 = REO Disposition
ZERO_BALANCE_DEFAULT = {"02", "03", "09"}

# Código sentinel de credit score "No disponible" en el dataset crudo
SENTINEL_CREDIT_SCORE = 9999

# ---------------------------------------------------------------------------
# Partición temporal (out-of-time)
# ---------------------------------------------------------------------------
AÑOS_ENTRENAMIENTO  = [2016, 2017, 2018, 2019, 2020]
AÑOS_VALIDACION     = [2022, 2023]          # 2021 no existe en el dataset
AÑOS_TEST           = [2024]

# ---------------------------------------------------------------------------
# Features utilizados en el modelo
# (definidos aquí para mantener consistencia entre entrenamiento y scoring)
# ---------------------------------------------------------------------------
FEATURES_ORIGINACION = [
    "credit_score",           # FICO al momento de originación
    "original_ltv",           # LTV original
    "original_cltv",          # CLTV original
    "original_dti",           # DTI original
    "original_loan_term",     # Plazo en meses
    "number_of_borrowers",    # Cantidad de deudores
    "loan_purpose",           # Propósito (P=compra, C/N=refinanciación)
    "property_type",          # Tipo de propiedad (SF, CO, PU…)
    "occupancy_status",       # Ocupación (P=primaria, I=inversión, S=segunda)
    "channel",                # Canal de originación (R=retail, B=broker, C=correspondent)
    "number_of_units",        # 1–4 unidades
]

FEATURES_COMPORTAMIENTO = [
    "loan_age",                            # Edad del préstamo en meses
    "estimated_loan_to_value_eltv",        # LTV estimado (AVM, desde abr-2017)
    "dpd_numerico",                        # DPD numérico del período
    "max_dpd_3m",                          # Máximo DPD en los últimos 3 meses
    "max_dpd_6m",                          # Máximo DPD en los últimos 6 meses
    "max_dpd_12m",                         # Máximo DPD en los últimos 12 meses
    "fue_modificado",                      # Flag: el préstamo fue modificado alguna vez
    "tiene_deferral",                      # Flag: tiene diferimiento de pagos
    "spread_tasa",                         # Diferencia tasa_corriente - tasa_original
    "amortizacion_upb",                    # Amortización relativa del saldo
]

# ---------------------------------------------------------------------------
# Variables relativas a la cohorte de originación
# ---------------------------------------------------------------------------
# Las variables de NIVEL ABSOLUTO (tasas en %, saldos en USD) presentan un
# desplazamiento de covariables severo entre particiones: la tasa media de
# originación pasa de 3,96 % (train 2016-2020) a 6,74 % (test 2024) y el UPB
# medio de USD 231 mil a USD 337 mil. Los modelos basados en árboles no
# extrapolan fuera del rango observado en entrenamiento, por lo que estas
# variables destruyen su poder discriminante out-of-time. Se sustituyen por
# desviaciones respecto de la media de la cohorte de originación (mes de
# concesión), que son estacionarias y capturan el mismo riesgo relativo.
FEATURES_NIVEL_EXCLUIDAS = [
    "original_interest_rate",
    "current_interest_rate",
    "original_upb",
    "current_actual_upb",
]

FEATURES_RELATIVAS = [
    "rate_vs_cohorte",   # Tasa original − media de la cohorte de originación
    "upb_vs_cohorte",    # UPB original − media de la cohorte de originación
    "fico_vs_cohorte",   # FICO − media de la cohorte de originación
    "ltv_vs_cohorte",    # LTV original − media de la cohorte de originación
    "age_ratio",         # loan_age / original_loan_term (madurez relativa)
]

MACRO_FEATURES = [
    "hpi",
    "unemployment_rate",
    "fed_funds_rate",
    "gdp_real",
    "mortgage_rate_30y",
    "hpi_yoy_change",
    "unemployment_yoy_change",
]

# Conjunto disponible en el momento de la concesión: alimenta el modelo de PD
# de originación usado como referencia para el SICR (IFRS 9 5.5.9).
FEATURES_ORIGINACION_EXT = FEATURES_ORIGINACION + [
    "rate_vs_cohorte", "upb_vs_cohorte", "fico_vs_cohorte", "ltv_vs_cohorte",
]

FEATURES_MODELO = (FEATURES_ORIGINACION + FEATURES_COMPORTAMIENTO
                   + FEATURES_RELATIVAS + MACRO_FEATURES)

TARGET = "default_12m"   # Variable objetivo: default en los próximos 12 meses

# ---------------------------------------------------------------------------
# Datos macroeconómicos (FRED) – Forward-Looking Information (IFRS 9 5.5.17c)
# ---------------------------------------------------------------------------
MACRO_PARQUET = MACRO_PATH / "macro_monthly.parquet"

FRED_SERIES = {
    "USSTHPI":      "hpi",               # House Price Index (trimestral)
    "UNRATE":       "unemployment_rate", # Tasa de desempleo (mensual)
    "FEDFUNDS":     "fed_funds_rate",    # Fed Funds Rate (mensual)
    "GDPC1":        "gdp_real",          # GDP real (trimestral)
    "MORTGAGE30US": "mortgage_rate_30y", # Mortgage rate 30y (semanal)
}

# ---------------------------------------------------------------------------
# IFRS 9 – Ponderación de escenarios macroeconómicos (IFRS 9 5.5.17c / BIS d350 P6)
# ---------------------------------------------------------------------------
SCENARIO_WEIGHTS = {"base": 0.50, "pessimistic": 0.30, "optimistic": 0.20}

# ---------------------------------------------------------------------------
# SICR basado en Lifetime PD (IFRS 9 5.5.9 / EBA GL 135-138)
# ---------------------------------------------------------------------------
# Ambos umbrales se aplican sobre la LIFETIME PD (no la PD a 12 meses), evaluada
# sobre el horizonte residual del préstamo (ver 03b_sicr_assessment.py). El
# umbral absoluto se calibró empíricamente sobre esa escala: la Lifetime PD
# media de la cartera es ~14 %, de modo que un delta de 50 puntos básicos
# (adecuado para una PD a 12 meses) resulta demasiado laxo y termina dominando
# por completo la clasificación, anulando el aporte del criterio relativo. Con
# delta = 5 p.p. el criterio absoluto deja de ser el único disparador
# (contribuye ~13 % de los casos marginalmente, no ~100 %) y el Stage 2
# resultante (8,5 % de la cartera) exhibe un lift de tasa de default de ~8,7x
# frente al Stage 1, cubriendo el 44,5 % de los defaults futuros de la cartera.
# Ver outputs/tablas/sicr_umbral_calibracion.csv para la grilla completa.
SICR_RELATIVE_THRESHOLD = 2.5    # Lifetime PD actual > 2.5x Lifetime PD en originación
SICR_ABSOLUTE_THRESHOLD = 0.05   # o incremento absoluto > 5 p.p. de Lifetime PD

# Backstop prudencial (IFRS 9 5.5.11): 30 DPD = bucket 1 en la escala Freddie Mac.
# Es un REFUERZO cualitativo, no el criterio primario de SICR.
SICR_BACKSTOP_DPD = 1

# Grillas de sensibilidad para la calibración del SICR (umbral relativo k y
# umbral absoluto delta, evaluados conjuntamente en 03b_sicr_assessment.py)
SICR_GRID_K     = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
SICR_GRID_DELTA = [0.01, 0.02, 0.03, 0.05, 0.08]

# ---------------------------------------------------------------------------
# Hiperparámetros de los modelos PD
# ---------------------------------------------------------------------------
# Dirección económica esperada de cada driver de riesgo (EBA GL/2017/16 §5.3.1:
# plausibilidad económica de los factores). +1 = a mayor valor, mayor PD.
MONOTONE_CONSTRAINTS = {
    "credit_score":                 -1,
    "fico_vs_cohorte":              -1,
    "original_ltv":                  1,
    "original_cltv":                 1,
    "ltv_vs_cohorte":                1,
    "estimated_loan_to_value_eltv":  1,
    "original_dti":                  1,
    "dpd_numerico":                  1,
    "max_dpd_3m":                    1,
    "max_dpd_6m":                    1,
    "max_dpd_12m":                   1,
    "rate_vs_cohorte":               1,
    "amortizacion_upb":             -1,
}

# Seleccionados por AUC sobre el conjunto de VALIDACIÓN (2022-2023).
# El número de árboles se fija por early stopping sobre un holdout temporal
# interno al set de entrenamiento (vintage 2020), nunca sobre validación/test.
XGB_PARAMS = {
    "max_depth":         4,
    "min_child_weight":  200,
    "learning_rate":     0.03,
    "reg_lambda":        5.0,
    "subsample":         0.8,
    "colsample_bytree":  0.6,
}
XGB_MAX_ESTIMATORS      = 3000
XGB_EARLY_STOPPING      = 80
AÑO_EARLY_STOPPING      = 2020   # último vintage de train, reservado para early stopping

RF_PARAMS = {
    "n_estimators":     300,
    "max_depth":        10,
    "min_samples_leaf": 50,
}

# Submuestreo del set de entrenamiento (control de RAM)
MAX_TRAIN_OBS = 1_000_000

# ---------------------------------------------------------------------------
# Segmentación de cartera (IFRS 9 5.5.4 / EBA GL/2017/16 §5.2 – Control 3.6)
# ---------------------------------------------------------------------------
# Cada segmentación se valida empíricamente: discriminación (AUC/Gini/KS),
# estabilidad (PSI) y homogeneidad intra / heterogeneidad inter segmento.
SEGMENTOS_CORTES = {
    "banda_fico":   {"var": "credit_score",
                     "cortes": [0, 660, 700, 740, 780, 900],
                     "etiquetas": ["<660", "660-699", "700-739", "740-779", "780+"]},
    "banda_ltv":    {"var": "original_ltv",
                     "cortes": [0, 60, 75, 80, 90, 1000],
                     "etiquetas": ["<=60", "60-75", "75-80", "80-90", ">90"]},
    "banda_dti":    {"var": "original_dti",
                     "cortes": [0, 30, 36, 43, 100],
                     "etiquetas": ["<=30", "30-36", "36-43", ">43"]},
    "proposito":    {"var": "loan_purpose",   "categorica": True},
    "ocupacion":    {"var": "occupancy_status", "categorica": True},
    "canal":        {"var": "channel",        "categorica": True},
    "tipo_prop":    {"var": "property_type",  "categorica": True},
}

# Tamaño mínimo de un segmento para que sus métricas sean reportables
SEGMENTO_MIN_OBS      = 5_000
SEGMENTO_MIN_DEFAULTS = 50
# Nivel de significación de los tests de heterogeneidad inter-segmento
ALFA_SIGNIFICACION    = 0.05

# ---------------------------------------------------------------------------
# LGD – Loss Given Default (IFRS 9 5.5.17 / EBA GL/2017/16 §6 – Control 7.5)
# ---------------------------------------------------------------------------
# Horizonte máximo de recuperación (workout period). Superado este plazo sin
# resolución, la exposición se considera irrecuperable y se asigna LGD = 100 %.
LGD_WORKOUT_MESES_MAX = 60

# Ventana de observación para declarar curación (cure): meses consecutivos sin
# mora tras haber entrado en default (EBA GL/2016/07 §7: mínimo 3 meses de
# probation period; se adopta el criterio conservador de 12 meses).
LGD_CURE_MESES = 12

# Piso y techo regulatorios de LGD
LGD_MIN = 0.0
LGD_MAX = 1.0

# LGD asignada a exposiciones que superan el workout máximo sin resolución
LGD_PERDIDA_TOTAL = 1.0

# Add-on de downturn sobre la LGD media observada (CRR art. 181.1.b)
LGD_DOWNTURN_ADDON = 0.05

# Tasa de descuento efectiva anual para llevar recuperaciones a valor presente
# (IFRS 9 B5.5.44: tasa de interés efectiva original del instrumento).
# Se usa la tasa media de originación de la cartera como proxy.
TASA_DESCUENTO_ANUAL = 0.045

# ---------------------------------------------------------------------------
# EAD – Exposure at Default (Controles 8.1, 8.2, 8.6)
# ---------------------------------------------------------------------------
# La cartera Freddie Mac Single-Family está compuesta exclusivamente por
# préstamos cerrados, totalmente desembolsados y amortizables (amortization_type
# FRM/ARM). No existen saldos contingentes ni líneas revolving, por lo que el
# factor de conversión crediticia no aplica: CCF = 0 sobre off-balance.
CCF_OFF_BALANCE = 0.0

# CCF regulatorios estándar (CRR art. 111 / Basilea III SA) que aplicarían si
# la cartera incorporase exposiciones fuera de balance. Se documentan para
# completitud metodológica y para el caso de extensión del alcance.
CCF_REGULATORIOS = {
    "compromiso_incondicionalmente_cancelable": 0.10,
    "compromiso_vencimiento_hasta_1a":          0.20,
    "compromiso_vencimiento_mayor_1a":          0.50,
    "linea_revolving_no_comprometida":          0.40,
    "garantia_financiera":                      1.00,
}

# Moneda base única: la totalidad de la cartera está denominada y liquidada en
# USD, por lo que no existe descalce de divisas ni necesidad de conversión.
MONEDA_BASE = "USD"
CARTERA_MULTIDIVISA = False

# Horizonte de proyección de la EAD (meses) y tasa de prepago
EAD_HORIZONTE_MESES = 12

# ---------------------------------------------------------------------------
# Gobernanza de Overrides y Post-Model Adjustments (Controles 13.1, 13.2)
# ---------------------------------------------------------------------------
# Umbral de materialidad: un PMA que modifique el ECL total por encima de este
# porcentaje requiere aprobación del Comité de Riesgos (no basta la función
# de validación independiente).
PMA_UMBRAL_MATERIALIDAD = 0.05     # 5 % del ECL de cartera
PMA_UMBRAL_INFORMATIVO  = 0.01     # 1 % → registro y reporte, aprueba Validación

# Vigencia máxima de un PMA antes de exigir su reversión o incorporación al modelo
PMA_VIGENCIA_MAX_TRIMESTRES = 4

# Registro de auditoría de PMAs y overrides
PMA_REGISTRO = TABLAS_PATH / "registro_pma_overrides.csv"
