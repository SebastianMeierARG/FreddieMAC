"""
00_eda.py – Análisis Exploratorio de Datos (EDA)
=================================================
Genera estadísticas descriptivas y visualizaciones del dataset Freddie Mac.
Portado desde EDA.R.

Entrada  : data/orig_all.parquet, data/svcg_all.parquet
Salida   : outputs/figuras/eda_*.png, outputs/tablas/eda_*.csv
           Retorna dict con todos los resultados para uso en crear_tesis.py
"""

import re
import warnings
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

from config import (
    ORIG_PARQUET, SVCG_PARQUET, FIGURAS_PATH, TABLAS_PATH,
)


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina sufijos _V# generados por data_reader.R y renombra year→vintage_year."""
    df.columns = [re.sub(r"_V\d+$", "", c) for c in df.columns]
    if "year" in df.columns and "vintage_year" not in df.columns:
        df = df.rename(columns={"year": "vintage_year"})
    return df

warnings.filterwarnings("ignore")
plt.rcParams.update({
    "font.family": "serif", "font.size": 11,
    "axes.titlesize": 12, "axes.labelsize": 11,
})

ZERO_BALANCE_DEFAULT = {"02", "03", "09"}


# ---------------------------------------------------------------------------
# Carga y limpieza básica
# ---------------------------------------------------------------------------

def cargar_datos_eda():
    orig = pd.read_parquet(ORIG_PARQUET)
    orig = normalizar_columnas(orig)
    svcg = pd.read_parquet(SVCG_PARQUET)
    svcg = normalizar_columnas(svcg)

    # Sentinel → NaN
    for col, val in [("credit_score", 9999), ("original_ltv", 999),
                     ("original_dti", 999), ("original_cltv", 999)]:
        if col in orig.columns:
            orig[col] = pd.to_numeric(orig[col], errors="coerce").replace(val, np.nan)

    # Fechas
    for col in ["first_payment_date", "maturity_date"]:
        if col in orig.columns:
            orig[col] = pd.to_datetime(
                orig[col].astype(str).str[:6], format="%Y%m", errors="coerce"
            )

    svcg["monthly_reporting_period"] = pd.to_datetime(
        svcg["monthly_reporting_period"].astype(str).str[:6],
        format="%Y%m", errors="coerce",
    )
    svcg["dpd_numerico"] = pd.to_numeric(
        svcg["current_loan_delinquency_status"].replace("RA", 99),
        errors="coerce",
    )
    svcg["current_actual_upb"] = pd.to_numeric(svcg["current_actual_upb"], errors="coerce")

    return orig, svcg


# ---------------------------------------------------------------------------
# Estadísticas descriptivas
# ---------------------------------------------------------------------------

def estadisticas_originacion(orig: pd.DataFrame) -> dict:
    n_prestamos = orig["loan_sequence_number"].nunique()
    fecha_min   = orig["first_payment_date"].min()
    fecha_max   = orig["first_payment_date"].max()

    stats_fico = orig["credit_score"].describe(percentiles=[.05,.25,.50,.75,.95])
    stats_ltv  = orig["original_ltv"].describe(percentiles=[.05,.25,.50,.75,.95])
    stats_dti  = orig["original_dti"].describe(percentiles=[.05,.25,.50,.75,.95])
    stats_upb  = pd.to_numeric(orig["original_upb"], errors="coerce").describe(
                     percentiles=[.05,.25,.50,.75,.95])

    resumen = pd.DataFrame({
        "FICO (Credit Score)": stats_fico,
        "LTV Original (%)":    stats_ltv,
        "DTI Original (%)":    stats_dti,
        "UPB Original ($)":    stats_upb,
    }).T

    ruta = TABLAS_PATH / "eda_stats_originacion.csv"
    resumen.to_csv(ruta)

    return {
        "n_prestamos":  n_prestamos,
        "fecha_min":    fecha_min,
        "fecha_max":    fecha_max,
        "stats_orig":   resumen,
    }


def estadisticas_performance(svcg: pd.DataFrame) -> dict:
    n_obs       = len(svcg)
    n_loans     = svcg["loan_sequence_number"].nunique()
    per_min     = svcg["monthly_reporting_period"].min()
    per_max     = svcg["monthly_reporting_period"].max()

    svcg["is_default"] = (
        (svcg["dpd_numerico"] >= 3) |
        svcg["zero_balance_code"].astype(str).isin(ZERO_BALANCE_DEFAULT)
    )
    tasa_default = svcg["is_default"].mean()
    tasa_90dpd   = (svcg["dpd_numerico"] >= 3).mean()

    stats_upb = svcg["current_actual_upb"].describe(percentiles=[.25,.50,.75,.95])

    return {
        "n_obs":         n_obs,
        "n_loans":       n_loans,
        "per_min":       per_min,
        "per_max":       per_max,
        "tasa_default":  tasa_default,
        "tasa_90dpd":    tasa_90dpd,
        "stats_upb":     stats_upb,
        "svcg_con_flag": svcg,
    }


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------

def fig_distribucion_fico(orig: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 4))
    vals = orig["credit_score"].dropna()
    ax.hist(vals, bins=50, color="steelblue", edgecolor="white", alpha=0.85)
    ax.axvline(vals.median(), color="firebrick", linestyle="--",
               label=f"Mediana: {vals.median():.0f}")
    ax.set_xlabel("Credit Score (FICO)")
    ax.set_ylabel("Frecuencia")
    ax.set_title("Distribución del Credit Score (FICO) – Dataset Freddie Mac")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    ruta = str(FIGURAS_PATH / "eda_fico_distribucion.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    return ruta


def fig_distribucion_upb(svcg: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 4))
    vals = svcg["current_actual_upb"].dropna()
    vals = vals[vals > 0]
    ax.hist(vals / 1_000, bins=60, color="teal", edgecolor="white", alpha=0.85)
    ax.set_xlabel("Saldo Actual (miles de USD)")
    ax.set_ylabel("Frecuencia")
    ax.set_title("Distribución del Saldo Actual (Current Actual UPB)")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:.0f}K"))
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    ruta = str(FIGURAS_PATH / "eda_upb_distribucion.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    return ruta


def fig_distribucion_dpd(svcg: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 4))
    conteo = (
        svcg["dpd_numerico"]
        .dropna()
        .clip(upper=12)
        .value_counts()
        .sort_index()
    )
    etiquetas = [f"{int(v)*30}+" if v == 12 else str(int(v*30)) for v in conteo.index]
    ax.bar(range(len(conteo)), conteo.values, color="coral", edgecolor="white")
    ax.set_xticks(range(len(conteo)))
    ax.set_xticklabels(etiquetas, rotation=45)
    ax.set_xlabel("Días en Mora (DPD)")
    ax.set_ylabel("Observaciones")
    ax.set_title("Distribución de Días en Mora (DPD) – Performance mensual")
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    ruta = str(FIGURAS_PATH / "eda_dpd_distribucion.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    return ruta


def fig_tasa_default_tiempo(svcg: pd.DataFrame) -> str:
    mensual = (
        svcg.groupby("monthly_reporting_period")
        .agg(
            n=("is_default", "count"),
            defaults=("is_default", "sum"),
        )
        .assign(tasa=lambda d: d["defaults"] / d["n"] * 100)
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(mensual["monthly_reporting_period"], mensual["tasa"],
            color="firebrick", linewidth=1.5)
    ax.fill_between(mensual["monthly_reporting_period"], mensual["tasa"],
                    alpha=0.15, color="firebrick")
    ax.set_xlabel("Período")
    ax.set_ylabel("Tasa de Default (%)")
    ax.set_title("Tasa de Default Mensual en el Dataset Freddie Mac")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    ruta = str(FIGURAS_PATH / "eda_default_tiempo.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    return ruta


def fig_default_por_vintage(svcg: pd.DataFrame) -> str:
    tasa_vintage = (
        svcg.groupby("vintage_year")["is_default"]
        .agg(["mean", "count"])
        .rename(columns={"mean": "tasa_default", "count": "obs"})
        .reset_index()
    )
    tasa_vintage = tasa_vintage[tasa_vintage["vintage_year"].notna()]

    fig, ax = plt.subplots(figsize=(8, 4))
    bars = ax.bar(
        tasa_vintage["vintage_year"].astype(int).astype(str),
        tasa_vintage["tasa_default"] * 100,
        color="steelblue", edgecolor="white",
    )
    ax.bar_label(bars, fmt="%.2f%%", padding=3, fontsize=9)
    ax.set_xlabel("Año de Originación (Vintage Year)")
    ax.set_ylabel("Tasa de Default (%)")
    ax.set_title("Tasa de Default por Vintage Year (Freddie Mac Sample)")
    ax.grid(True, alpha=0.3, axis="y")
    ax.annotate("* Vintage 2021 no disponible en el dataset",
                xy=(0.01, 0.02), xycoords="axes fraction", fontsize=9, color="gray")
    plt.tight_layout()
    ruta = str(FIGURAS_PATH / "eda_default_vintage.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    return ruta


def fig_ltv_vs_default(orig: pd.DataFrame, svcg: pd.DataFrame) -> str:
    """Tasa de default por bucket de LTV original."""
    svcg_flag = svcg.groupby("loan_sequence_number")["is_default"].max().reset_index()
    merged = orig[["loan_sequence_number", "original_ltv"]].merge(svcg_flag, on="loan_sequence_number")
    merged["ltv_bucket"] = pd.cut(
        merged["original_ltv"], bins=[0, 60, 70, 80, 90, 100, 200],
        labels=["≤60", "60-70", "70-80", "80-90", "90-100", ">100"],
    )
    tasa = merged.groupby("ltv_bucket", observed=True)["is_default"].mean() * 100
    fig, ax = plt.subplots(figsize=(8, 4))
    tasa.plot(kind="bar", ax=ax, color="darkorange", edgecolor="white")
    ax.set_xlabel("Bucket LTV Original (%)")
    ax.set_ylabel("Tasa de Default (%)")
    ax.set_title("Tasa de Default por Bucket de LTV Original")
    ax.grid(True, alpha=0.3, axis="y")
    plt.xticks(rotation=0)
    plt.tight_layout()
    ruta = str(FIGURAS_PATH / "eda_ltv_default.png")
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    return ruta


def tabla_composicion_cartera(orig: pd.DataFrame) -> pd.DataFrame:
    """Distribución de variables categóricas de la cartera."""
    variables = {
        "Propósito del Préstamo (loan_purpose)":    "loan_purpose",
        "Tipo de Propiedad (property_type)":        "property_type",
        "Estado de Ocupación (occupancy_status)":   "occupancy_status",
        "Canal de Originación (channel)":           "channel",
    }
    tablas = []
    for nombre, col in variables.items():
        if col in orig.columns:
            t = (
                orig[col].value_counts(normalize=True)
                .mul(100).round(2)
                .rename("Porcentaje (%)")
                .reset_index()
                .rename(columns={col: "Categoría"})
            )
            t.insert(0, "Variable", nombre)
            tablas.append(t)
    df = pd.concat(tablas, ignore_index=True)
    df.to_csv(TABLAS_PATH / "eda_composicion_cartera.csv", index=False)
    return df


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main() -> dict:
    print("=" * 60)
    print("PASO 0 – Análisis Exploratorio de Datos (EDA)")
    print("=" * 60)

    orig, svcg = cargar_datos_eda()
    print(f"  Originación: {len(orig):,} préstamos")
    print(f"  Performance: {len(svcg):,} observaciones mensuales")

    print("\n  Calculando estadísticas descriptivas...")
    stats_o = estadisticas_originacion(orig)
    stats_p = estadisticas_performance(svcg)
    svcg    = stats_p.pop("svcg_con_flag")

    print(f"  Préstamos únicos: {stats_o['n_prestamos']:,}")
    print(f"  Período: {stats_o['fecha_min']} a {stats_o['fecha_max']}")
    print(f"  Tasa de default global: {stats_p['tasa_default']:.4%}")

    print("\n  Generando gráficos...")
    figuras = {
        "fico":    fig_distribucion_fico(orig),
        "upb":     fig_distribucion_upb(svcg),
        "dpd":     fig_distribucion_dpd(svcg),
        "default_tiempo":  fig_tasa_default_tiempo(svcg),
        "default_vintage": fig_default_por_vintage(svcg),
        "ltv_default":     fig_ltv_vs_default(orig, svcg),
    }

    print("\n  Generando tabla de composición de cartera...")
    tabla_comp = tabla_composicion_cartera(orig)

    print("Paso 0 completado.\n")

    return {
        "stats_orig":     stats_o,
        "stats_perf":     stats_p,
        "figuras":        figuras,
        "tabla_comp":     tabla_comp,
        "n_prestamos":    stats_o["n_prestamos"],
        "n_obs_perf":     stats_p["n_obs"],
        "fecha_min":      stats_o["fecha_min"],
        "fecha_max":      stats_o["fecha_max"],
        "tasa_default":   stats_p["tasa_default"],
    }


if __name__ == "__main__":
    main()
