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
    "original_interest_rate", # Tasa nominal original
    "original_loan_term",     # Plazo en meses
    "original_upb",           # Monto original (redondeado a $1.000)
    "number_of_borrowers",    # Cantidad de deudores
    "loan_purpose",           # Propósito (P=compra, C/N=refinanciación)
    "property_type",          # Tipo de propiedad (SF, CO, PU…)
    "occupancy_status",       # Ocupación (P=primaria, I=inversión, S=segunda)
    "channel",                # Canal de originación (R=retail, B=broker, C=correspondent)
    "number_of_units",        # 1–4 unidades
]

FEATURES_COMPORTAMIENTO = [
    "loan_age",                            # Edad del préstamo en meses
    "current_interest_rate",               # Tasa corriente (post-modificación)
    "current_actual_upb",                  # Saldo actual
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

FEATURES_MODELO = FEATURES_ORIGINACION + FEATURES_COMPORTAMIENTO

TARGET = "default_12m"   # Variable objetivo: default en los próximos 12 meses
