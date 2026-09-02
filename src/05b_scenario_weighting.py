"""
05b_scenario_weighting.py – Ponderación de escenarios macroeconómicos (IFRS 9 5.5.17c)
========================================================================================
Implementa la ponderación de escenarios múltiples requerida por IFRS 9 para la
estimación de ECL con información prospectiva (Forward-Looking Information).

Marco regulatorio:
  IFRS 9 5.5.17(c): incorporar información prospectiva razonable y sustentable.
  BIS d350 Principio 6 (paras 62-68): múltiples escenarios ponderados por probabilidad.

Escenarios (shocks sobre HPI, desempleo y Fed Funds respecto al valor base):
  Base       (50%): sin ajuste – condiciones macro actuales del período de test
  Pesimista  (30%): inspirado en CCAR Severely Adverse – HPI -25%, desempleo +4pp
  Optimista  (20%): recuperación leve – HPI +2%, desempleo -1pp

ECL_ponderado = Σ peso_i × ECL_escenario_i

Entrada  : data/dataset_modelado.parquet, data/macro/macro_monthly.parquet,
           outputs/modelos/modelo_xgboost.joblib, outputs/modelos/features_lista.joblib
Salida   : outputs/tablas/ecl_by_scenario.csv
           outputs/figuras/lifetime_pd_scenarios.png
"""

import joblib
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    DATASET_MOD_PARQUET, MACRO_PARQUET,
    MODELOS_PATH, TABLAS_PATH, FIGURAS_PATH,
    MACRO_FEATURES, SCENARIO_WEIGHTS,
    AÑOS_TEST,
)

import sys as _sys, os as _os
_sys.path.insert(0, str(_os.path.dirname(__file__)))
from importlib import import_module as _im
_p04 = _im("04_modelado")
ModeloCalibraado = _p04.ModeloCalibraado  # noqa: F401

warnings.filterwarnings("ignore")
plt.rcParams.update({"font.family": "serif", "font.size": 11})

# Shocks aplicados a cada escenario (sobre el valor observado en el período)
_ESCENARIO_PARAMS = {
    "base":        {"hpi_mult": 1.00, "unemp_delta":  0.0, "fedfunds_delta":  0.0},
    "pessimistic": {"hpi_mult": 0.75, "unemp_delta":  4.0, "fedfunds_delta": -2.5},
    "optimistic":  {"hpi_mult": 1.02, "unemp_delta": -1.0, "fedfunds_delta":  0.0},
}


def ajustar_macro(df: pd.DataFrame, escenario: str) -> pd.DataFrame:
    """Aplica los shocks del escenario sobre las variables macro del DataFrame."""
    df = df.copy()
    p = _ESCENARIO_PARAMS[escenario]

    if "hpi" in df.columns:
        df["hpi"] = (df["hpi"] * p["hpi_mult"]).astype("float32")
    if "hpi_yoy_change" in df.columns:
        df["hpi_yoy_change"] = (
            df["hpi_yoy_change"] + (p["hpi_mult"] - 1) * 100
        ).astype("float32")
    if "unemployment_rate" in df.columns:
        df["unemployment_rate"] = (
            (df["unemployment_rate"] + p["unemp_delta"]).clip(lower=0)
        ).astype("float32")
    if "unemployment_yoy_change" in df.columns:
        df["unemployment_yoy_change"] = (
            df["unemployment_yoy_change"] + p["unemp_delta"]
        ).astype("float32")
    if "fed_funds_rate" in df.columns:
        df["fed_funds_rate"] = (
            (df["fed_funds_rate"] + p["fedfunds_delta"]).clip(lower=0)
        ).astype("float32")
    return df


def calcular_lifetime_pd(df: pd.DataFrame, pd_col: str) -> pd.DataFrame:
    """Lifetime PD acumulada por loan_age usando la fórmula de supervivencia."""
    por_edad = (
        df.groupby("loan_age")[pd_col]
        .agg(pd_marginal="mean", n_obs="count")
        .reset_index()
    )
    por_edad = por_edad[por_edad["n_obs"] >= 50].sort_values("loan_age")
    por_edad["pd_lifetime"] = 1 - (1 - por_edad["pd_marginal"]).cumprod()
    return por_edad[["loan_age", "pd_marginal", "pd_lifetime", "n_obs"]]


def main():
    print("=" * 60)
    print("PASO 5b – Ponderación de escenarios macroeconómicos")
    print("=" * 60)

    if not MACRO_PARQUET.exists():
        print("  ADVERTENCIA: datos macro no disponibles. Ejecutar 00_macro_data.py primero.")
        print("  Paso 5b omitido.\n")
        return None

    dataset = pd.read_parquet(DATASET_MOD_PARQUET)
    modelo = joblib.load(MODELOS_PATH / "modelo_xgboost.joblib")
    features_lista = joblib.load(MODELOS_PATH / "features_lista.joblib")

    test = dataset[dataset["vintage_year"].isin(AÑOS_TEST)].copy()
    print(f"  Observaciones test (vintage {AÑOS_TEST}): {len(test):,}")

    macro_presentes = [f for f in MACRO_FEATURES if f in test.columns]
    if not macro_presentes:
        print("  ADVERTENCIA: features macro no encontradas en dataset_modelado.")
        print("  Re-ejecutar paso 03 después de paso 00 para integrar variables macro.")
        print("  Paso 5b omitido.\n")
        return None
    print(f"  Features macro disponibles: {macro_presentes}")

    resultados = {}
    curvas = {}
    features_disp = [f for f in features_lista if f in test.columns]

    for nombre_esc, peso in SCENARIO_WEIGHTS.items():
        print(f"\n  Escenario '{nombre_esc}' (peso={peso:.0%})...")
        df_esc = ajustar_macro(test, nombre_esc)
        df_esc["pd_esc"] = modelo.predict_proba(df_esc[features_disp])[:, 1].astype("float32")

        pd_media = float(df_esc["pd_esc"].mean())
        lifetime = calcular_lifetime_pd(df_esc, "pd_esc")
        curvas[nombre_esc] = lifetime
        print(f"    PD media 12m: {pd_media:.4%}")

        resultados[nombre_esc] = {
            "peso": peso,
            "pd_media_12m": round(pd_media, 6),
            "pd_lifetime_max": round(float(lifetime["pd_lifetime"].max()), 6) if len(lifetime) > 0 else float("nan"),
        }

    ecl_pond = sum(SCENARIO_WEIGHTS[e] * resultados[e]["pd_media_12m"] for e in SCENARIO_WEIGHTS)
    print(f"\n  ECL ponderado (PD 12m): {ecl_pond:.4%}")
    print(f"  Desglose: " + " | ".join(
        f"{e}={resultados[e]['pd_media_12m']:.4%}" for e in SCENARIO_WEIGHTS
    ))

    # Tabla de resultados
    df_res = (
        pd.DataFrame(resultados)
        .T.reset_index()
        .rename(columns={"index": "escenario"})
    )
    df_res["ecl_ponderado"] = ecl_pond
    df_res.to_csv(TABLAS_PATH / "ecl_by_scenario.csv", index=False)
    print(f"\n  Tabla guardada: {TABLAS_PATH / 'ecl_by_scenario.csv'}")

    # Gráfico: Lifetime PD por escenario
    colores = {"base": "steelblue", "pessimistic": "firebrick", "optimistic": "forestgreen"}
    fig, ax = plt.subplots(figsize=(10, 6))
    for nombre_esc, df_l in curvas.items():
        peso_str = f"{SCENARIO_WEIGHTS[nombre_esc]:.0%}"
        ax.plot(
            df_l["loan_age"], df_l["pd_lifetime"] * 100,
            color=colores[nombre_esc], linewidth=2,
            label=f"{nombre_esc.capitalize()} (w={peso_str})",
        )
    ax.set_xlabel("Loan Age (meses)")
    ax.set_ylabel("Lifetime PD Acumulada (%)")
    ax.set_title("Lifetime PD por Escenario Macroeconómico – IFRS 9 FLI\n"
                 f"ECL ponderado: {ecl_pond:.4%}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    ruta_fig = FIGURAS_PATH / "lifetime_pd_scenarios.png"
    plt.savefig(ruta_fig, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Gráfico guardado: {ruta_fig}")

    print("Paso 5b completado.\n")
    return df_res


if __name__ == "__main__":
    main()
