"""
02_definicion_default.py – Definición de default IFRS 9 y clasificación de stages
====================================================================================
Define la variable objetivo (default a 12 meses) y clasifica cada observación
en Stage 1, 2 o 3 según el marco regulatorio IFRS 9.

Criterio de default adoptado (consistente con IFRS 9 / Basilea):
  - DPD ≥ 90 días (bucket ≥ 3), O
  - Zero Balance Code en {02, 03, 09} (venta a terceros, short sale, REO).

Clasificación de stages:
  - Stage 1: corriente o DPD < 30 días (sin deterioro significativo de crédito)
  - Stage 2: SICR – 30 ≤ DPD < 90 días (incremento significativo del riesgo)
  - Stage 3: deteriorado – DPD ≥ 90 días o evento de default

Entrada  : data/panel.parquet
Salida   : data/panel_con_default.parquet
"""

import pandas as pd
import numpy as np

from config import (
    PANEL_PARQUET, PANEL_DEF_PARQUET,
    UMBRAL_DPD_DEFAULT, HORIZONTE_PD_MESES, ZERO_BALANCE_DEFAULT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extraer_dpd_numerico(serie: pd.Series) -> pd.Series:
    """
    Convierte current_loan_delinquency_status a entero.
    - "0"..."XX" → int
    - "RA" (REO Acquisition) → 99 (tratado como default severo)
    - NaN → NaN
    """
    return pd.to_numeric(
        serie.replace("RA", 99),
        errors="coerce",
    )


def es_evento_default(dpd: pd.Series, zero_bal: pd.Series) -> pd.Series:
    """
    Retorna True si la observación constituye un evento de default IFRS 9.
    dpd      : DPD numérico (0, 1, 2, 3... 99 para RA)
    zero_bal : zero_balance_code como string
    """
    default_por_dpd     = dpd >= UMBRAL_DPD_DEFAULT
    default_por_zbc     = zero_bal.isin(ZERO_BALANCE_DEFAULT)
    return (default_por_dpd | default_por_zbc).fillna(False)


def asignar_stage(dpd: pd.Series, en_default: pd.Series) -> pd.Series:
    """
    Asigna Stage IFRS 9 a cada observación mensual:
      Stage 3 → en default
      Stage 2 → SICR: 30 ≤ DPD < 90 (bucket 1 o 2)
      Stage 1 → sin deterioro significativo (DPD = 0)
    """
    stage = pd.Series(1, index=dpd.index, dtype="Int8")
    stage = stage.where(~(dpd.between(1, 2)), other=2)
    stage = stage.where(~en_default, other=3)
    return stage


def calcular_default_12m(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada observación (loan × mes), crea la variable objetivo:
    default_12m = 1 si el préstamo tiene un evento de default
    dentro de los próximos HORIZONTE_PD_MESES meses.

    Implementación vectorizada (sin bucles Python):
      1. Convertimos evento_default a int.
      2. Invertimos la serie dentro de cada préstamo.
      3. Aplicamos rolling max de N períodos (= mirar N períodos hacia ADELANTE).
      4. Shift(1) para excluir el período corriente.
      5. Invertimos de vuelta.

    Esta operación es O(N) en pandas y escala a millones de filas.
    """
    print("  Calculando variable objetivo (default a 12 meses) – método vectorizado...")
    n = HORIZONTE_PD_MESES

    panel["_ev_int"] = panel["evento_default"].astype(int)

    def _lookahead_max(x):
        """Max de los próximos n períodos (excluye el actual)."""
        rev   = x.iloc[::-1]
        roll  = rev.rolling(window=n, min_periods=1).max()
        shift = roll.shift(1)        # excluir el período corriente
        return shift.iloc[::-1]

    panel["default_12m"] = (
        panel.groupby("loan_sequence_number", sort=False)["_ev_int"]
        .transform(_lookahead_max)
        .fillna(0)
        .clip(0, 1)
        .astype(int)
    )
    panel.drop(columns=["_ev_int"], inplace=True)
    return panel


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 2 – Definición de default IFRS 9 y stages")
    print("=" * 60)

    panel = pd.read_parquet(PANEL_PARQUET)
    print(f"Panel cargado: {len(panel):,} filas")

    # 1. DPD numérico
    panel["dpd_numerico"] = extraer_dpd_numerico(
        panel["current_loan_delinquency_status"]
    )

    # 2. Evento de default en el período corriente
    panel["evento_default"] = es_evento_default(
        panel["dpd_numerico"],
        panel["zero_balance_code"].astype(str),
    )

    # 3. Stage IFRS 9
    panel["ifrs9_stage"] = asignar_stage(
        panel["dpd_numerico"],
        panel["evento_default"],
    )

    # 4. Variable objetivo: default en los próximos 12 meses
    panel = calcular_default_12m(panel)

    # ---------------------------------------------------------------------------
    # Estadísticas descriptivas
    # ---------------------------------------------------------------------------
    print("\n  Distribución de stages:")
    dist_stage = panel["ifrs9_stage"].value_counts().sort_index()
    for stage, cnt in dist_stage.items():
        pct = cnt / len(panel) * 100
        print(f"    Stage {stage}: {cnt:>10,} obs ({pct:.1f}%)")

    print("\n  Tasa de default a 12 meses (sobre obs. no en default):")
    df_activos = panel[panel["ifrs9_stage"].isin([1, 2])]
    tasa_global = df_activos["default_12m"].mean()
    print(f"    Tasa global: {tasa_global:.4%}")

    print("\n  Tasa de default a 12 meses por vintage year:")
    tasa_vintage = (
        df_activos.groupby("vintage_year")["default_12m"]
        .agg(["mean", "count"])
        .rename(columns={"mean": "tasa_default", "count": "observaciones"})
    )
    tasa_vintage["tasa_default"] = tasa_vintage["tasa_default"].map("{:.4%}".format)
    print(tasa_vintage.to_string())

    print("\n  Aviso: vintage 2021 no disponible en el dataset (gap de datos).")

    # ---------------------------------------------------------------------------
    # Guardar
    # ---------------------------------------------------------------------------
    print(f"\nGuardando en: {PANEL_DEF_PARQUET}")
    panel.to_parquet(PANEL_DEF_PARQUET, index=False)
    print("Paso 2 completado.\n")

    return panel


if __name__ == "__main__":
    main()
