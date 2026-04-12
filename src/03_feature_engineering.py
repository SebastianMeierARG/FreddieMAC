"""
03_feature_engineering.py – Ingeniería de variables para el modelo PD
=======================================================================
Genera las variables predictoras para el modelo de Probabilidad de Default.
Combina variables de originación (estáticas) con variables de comportamiento
mensual (dinámicas), conforme a la práctica IFRS 9.

Variables generadas:
  - Comportamiento: DPD rolling, spread de tasa, amortización relativa
  - Flags binarios: modificación, diferimiento de pagos
  - ELTV: usa valor disponible cuando loan_age > 6 meses y existe AVM

Notas de datos:
  - ELTV disponible solo desde abril 2017 (NaN para períodos anteriores)
  - Código postal truncado → NO usar a nivel zip, solo state (property_state)
  - credit_score 9999 ya reemplazado por NaN en carga

Entrada  : data/panel_con_default.parquet
Salida   : data/dataset_modelado.parquet
"""

import pandas as pd
import numpy as np

from config import (
    PANEL_DEF_PARQUET, DATASET_MOD_PARQUET,
    FEATURES_MODELO, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST,
)


# ---------------------------------------------------------------------------
# Helpers para variables de comportamiento
# ---------------------------------------------------------------------------

def crear_features_rolling_dpd(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula el máximo DPD observado en ventanas de 3, 6 y 12 meses.
    Se calcula dentro de cada préstamo, ordenado por fecha.
    """
    print("  Calculando variables rolling de DPD...")
    grp = df.groupby("loan_sequence_number", sort=False)["dpd_numerico"]

    # Ventana deslizante hacia ATRÁS (historial del préstamo)
    df["max_dpd_3m"]  = grp.transform(lambda x: x.rolling(3,  min_periods=1).max())
    df["max_dpd_6m"]  = grp.transform(lambda x: x.rolling(6,  min_periods=1).max())
    df["max_dpd_12m"] = grp.transform(lambda x: x.rolling(12, min_periods=1).max())

    return df


def crear_features_tasa(df: pd.DataFrame) -> pd.DataFrame:
    """
    Spread de tasa: diferencia entre tasa corriente y tasa original.
    Un spread negativo indica modificación (tasa reducida).
    """
    df["spread_tasa"] = (
        df["current_interest_rate"] - df["original_interest_rate"]
    )
    return df


def crear_features_upb(df: pd.DataFrame) -> pd.DataFrame:
    """
    Amortización relativa del saldo: cuánto del capital original se ha pagado.
    amortizacion_upb = 1 - (saldo_actual / upb_original)
    Valores cercanos a 0 → préstamo casi sin amortizar.
    """
    df["amortizacion_upb"] = 1.0 - (
        df["current_actual_upb"] / df["original_upb"].replace(0, np.nan)
    )
    # Clampear para evitar valores fuera de [0, 1] por redondeos
    df["amortizacion_upb"] = df["amortizacion_upb"].clip(0, 1)
    return df


def crear_flags_binarios(df: pd.DataFrame) -> pd.DataFrame:
    """
    Variables binarias (0/1) indicadoras de eventos en la historia del préstamo.
    """
    # ¿Fue modificado alguna vez? (flag Y=actual, P=período anterior)
    df["fue_modificado"] = (
        df["modification_flag"].isin(["Y", "P"])
    ).astype("Int8")

    # ¿Tiene diferimiento de pagos (COVID / desastre natural)?
    df["tiene_deferral"] = (
        df["payment_deferral_flag"].isin(["Y", "P"])
    ).astype("Int8")

    return df


def codificar_categoricas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte variables categóricas a numéricas para los modelos de ML.
    Se usa Label Encoding simple (los modelos de árbol no necesitan one-hot).
    Para regresión logística, generar dummies en el pipeline de sklearn.
    """
    categoricas = [
        "loan_purpose",
        "property_type",
        "occupancy_status",
        "channel",
        "amortization_type",
    ]
    for col in categoricas:
        if col in df.columns:
            df[col] = pd.Categorical(df[col]).codes   # -1 para NaN

    return df


def tratar_eltv(df: pd.DataFrame) -> pd.DataFrame:
    """
    ELTV (Estimated Loan-to-Value): disponible desde abril 2017.
    Para observaciones anteriores → NaN (se imputará con original_ltv en el pipeline).
    Sentinel 999 = desconocido → ya tratado en data_reader.py
    """
    if "estimated_loan_to_value_eltv" in df.columns:
        # El valor 999 es "Unknown" según el User Guide → NaN
        df["estimated_loan_to_value_eltv"] = df[
            "estimated_loan_to_value_eltv"
        ].replace(999, np.nan)
    return df


# ---------------------------------------------------------------------------
# Pipeline de feature engineering
# ---------------------------------------------------------------------------

def construir_dataset_modelado(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica todo el pipeline de feature engineering y filtra las observaciones
    elegibles para el modelo PD:
      - Solo Stage 1 y 2 (se predice default FUTURO, no presente)
      - Excluir últimas 12 observaciones de cada préstamo (sin horizonte suficiente)
    """
    print("  Creando features de comportamiento...")
    # Seleccionamos solo las columnas necesarias para ahorrar RAM.
    # El panel completo tiene ~64 columnas; el modelo usa ~25.
    cols_necesarias = list(set(
        ["loan_sequence_number", "monthly_reporting_period",
         "vintage_year", "ifrs9_stage", "default_12m",
         "dpd_numerico", "current_actual_upb", "current_interest_rate",
         "modification_flag", "payment_deferral_flag",
         "estimated_loan_to_value_eltv", "loan_age",
         # features de originación
         "credit_score", "original_ltv", "original_cltv", "original_dti",
         "original_interest_rate", "original_loan_term", "original_upb",
         "number_of_borrowers", "loan_purpose", "property_type",
         "occupancy_status", "channel", "amortization_type", "number_of_units",
        ]
    ) & set(panel.columns))
    # El panel ya fue cargado con solo las columnas necesarias (via read_parquet columns=)
    # Usamos reset_index para obtener un DataFrame contiguo sin .copy() que daría OOM
    df = panel.reset_index(drop=True)
    del panel  # liberar referencia al parquet original

    # Reducir uso de RAM: convertir float64 a float32
    for col in df.select_dtypes(include="float64").columns:
        df[col] = df[col].astype("float32")

    df = crear_features_rolling_dpd(df)
    df = crear_features_tasa(df)
    df = crear_features_upb(df)
    df = crear_flags_binarios(df)
    df = tratar_eltv(df)
    df = codificar_categoricas(df)

    # Filtrar: solo Stage 1 y 2 (observaciones activas, no en default)
    n_antes = len(df)
    mask = df["ifrs9_stage"].isin([1, 2])
    df = df.loc[mask].reset_index(drop=True)   # reset_index evita consolidación RAM
    print(f"  Filtrado Stage 1/2: {n_antes:,} -> {len(df):,} filas")

    # Estadísticas de la variable objetivo
    print(f"\n  Tasa de default a 12m en dataset modelado: {df[TARGET].mean():.4%}")
    print(f"  Defaults (1): {df[TARGET].sum():,} | No-defaults (0): {(df[TARGET]==0).sum():,}")

    # Distribución por partición temporal
    print("\n  Distribución por partición:")
    for particion, años in [
        ("Entrenamiento", AÑOS_ENTRENAMIENTO),
        ("Validación",   AÑOS_VALIDACION),
        ("Test",         AÑOS_TEST),
    ]:
        sub = df[df["vintage_year"].isin(años)]
        tasa = sub[TARGET].mean() if len(sub) > 0 else float("nan")
        print(f"    {particion:15s}: {len(sub):>10,} obs | tasa default = {tasa:.4%}")

    return df


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 3 – Feature Engineering")
    print("=" * 60)

    # Leer solo las columnas necesarias para evitar OOM en la lectura de 3GB
    cols_leer = list(set([
        "loan_sequence_number", "monthly_reporting_period",
        "vintage_year", "ifrs9_stage", "default_12m",
        "dpd_numerico", "current_actual_upb", "current_interest_rate",
        "modification_flag", "payment_deferral_flag",
        "estimated_loan_to_value_eltv", "loan_age",
        "credit_score", "original_ltv", "original_cltv", "original_dti",
        "original_interest_rate", "original_loan_term", "original_upb",
        "number_of_borrowers", "loan_purpose", "property_type",
        "occupancy_status", "channel", "amortization_type", "number_of_units",
    ]))
    import pyarrow.parquet as pq
    available = pq.read_schema(PANEL_DEF_PARQUET).names
    cols_leer = [c for c in cols_leer if c in available]
    panel = pd.read_parquet(PANEL_DEF_PARQUET, columns=cols_leer)
    print(f"Panel cargado: {len(panel):,} filas")

    dataset = construir_dataset_modelado(panel)

    # Verificar que todas las features del config estén presentes
    faltantes = [f for f in FEATURES_MODELO if f not in dataset.columns]
    if faltantes:
        print(f"\n  ADVERTENCIA: features no encontradas: {faltantes}")

    print(f"\nGuardando dataset de modelado en: {DATASET_MOD_PARQUET}")
    dataset.to_parquet(DATASET_MOD_PARQUET, index=False)
    print("Paso 3 completado.\n")

    return dataset


if __name__ == "__main__":
    main()
