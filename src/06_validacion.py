"""
06_validacion.py – Validación regulatoria del modelo PD
=========================================================
Calcula las métricas de validación exigidas por IFRS 9, la EBA y el BCBS:

  Discriminación:
    - AUC / Gini          : capacidad de separar defaulters de no-defaulters
    - KS (Kolmogorov-Smirnov): máxima separación entre distribuciones

  Calibración:
    - Brier Score         : error cuadrático medio de probabilidades
    - Hosmer-Lemeshow     : bondad de ajuste por deciles de riesgo

  Estabilidad:
    - PSI (Population Stability Index): deriva de la distribución del score
      PSI < 0.1  → estable | 0.1–0.25 → monitorear | > 0.25 → inestable

  Backtesting:
    - Comparación PD predicha vs. tasa de default observada por decil

Entrada  : data/dataset_modelado.parquet, outputs/modelos/
Salida   : outputs/tablas/validacion_*.csv, outputs/figuras/validacion_*.png
"""

import joblib
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import (
    roc_auc_score, roc_curve, brier_score_loss,
    precision_recall_curve,
)

from config import (
    DATASET_MOD_PARQUET, PANEL_DEF_PARQUET,
    MODELOS_PATH, TABLAS_PATH, FIGURAS_PATH,
    FEATURES_MODELO, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST,
)
import sys as _sys, os as _os
_sys.path.insert(0, str(_os.path.dirname(__file__)))
from importlib import import_module as _im
_p04 = _im("04_modelado")
ModeloCalibraado = _p04.ModeloCalibraado  # noqa: F401
_sys.modules["m04"] = _p04  # compat: algunos .joblib fueron pickled desde el notebook bajo ese alias

warnings.filterwarnings("ignore")
plt.rcParams.update({"font.family": "serif", "font.size": 11})


# ---------------------------------------------------------------------------
# Métricas individuales
# ---------------------------------------------------------------------------

def calcular_ks(y_true, y_prob) -> float:
    """
    Estadístico KS: máxima distancia entre la CDF de defaulters y no-defaulters.
    KS > 0.3 → poder discriminante aceptable para modelos de crédito.
    """
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    return float(np.max(tpr - fpr))


def calcular_psi(ref_scores: np.ndarray, new_scores: np.ndarray,
                 n_bins: int = 10) -> float:
    """
    Population Stability Index (PSI).
    Mide si la distribución del score cambió entre dos períodos.
      ref_scores : scores del período de referencia (entrenamiento)
      new_scores : scores del período de monitoreo (test)
    """
    bins = np.percentile(ref_scores, np.linspace(0, 100, n_bins + 1))
    bins[0] = -np.inf
    bins[-1] = np.inf

    def frecuencias(x):
        counts, _ = np.histogram(x, bins=bins)
        pct = counts / len(x)
        return np.clip(pct, 1e-6, None)   # evitar log(0)

    ref_pct = frecuencias(ref_scores)
    new_pct = frecuencias(new_scores)

    psi = np.sum((new_pct - ref_pct) * np.log(new_pct / ref_pct))
    return float(psi)


def backtesting_deciles(y_true, y_prob, nombre: str) -> pd.DataFrame:
    """
    Tabla de backtesting: compara PD predicha vs. tasa observada por decil de score.
    Permite detectar si el modelo sobre/sub-estima el riesgo en algún segmento.
    """
    df = pd.DataFrame({"y_true": y_true, "y_prob": y_prob})
    df["decil"] = pd.qcut(df["y_prob"], q=10, labels=False, duplicates="drop") + 1
    tabla = (
        df.groupby("decil")
        .agg(
            n=("y_true", "count"),
            defaults=("y_true", "sum"),
            pd_predicha=("y_prob", "mean"),
            pd_observada=("y_true", "mean"),
        )
        .reset_index()
    )
    tabla["diferencia"] = tabla["pd_predicha"] - tabla["pd_observada"]
    tabla["modelo"] = nombre
    return tabla


def intervalos_calibracion(df_backtesting: pd.DataFrame, z: float = 1.96) -> pd.DataFrame:
    """
    Complemento al backtesting por decil (Control 6.5): dado que Hosmer-Lemeshow
    pierde potencia discriminante a N > 400.000 (rechaza calibración perfecta por
    pura potencia estadística, no por desvío económicamente relevante), se agrega
    por decil un test binomial Z (H0: pd_observada == pd_predicha) y el intervalo
    de Wilson al 95% sobre la tasa observada, más robusto que el intervalo normal
    a tasas de evento bajas (~1.3% de la cartera).
    """
    from scipy.stats import norm

    df = df_backtesting.copy()
    p_pred = df["pd_predicha"]
    n = df["n"]

    se = np.sqrt(p_pred * (1 - p_pred) / n)
    df["z_stat"] = (df["pd_observada"] - p_pred) / se
    df["p_valor_z"] = 2 * (1 - norm.cdf(df["z_stat"].abs()))

    p_hat = df["pd_observada"]
    denom = 1 + z**2 / n
    centro = (p_hat + z**2 / (2 * n)) / denom
    margen = (z * np.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2))) / denom
    df["wilson_ic95_inferior"] = centro - margen
    df["wilson_ic95_superior"] = centro + margen
    df["pd_predicha_dentro_ic95"] = (p_pred >= df["wilson_ic95_inferior"]) & (
        p_pred <= df["wilson_ic95_superior"]
    )

    return df[[
        "modelo", "decil", "n", "defaults", "pd_predicha", "pd_observada",
        "z_stat", "p_valor_z", "wilson_ic95_inferior", "wilson_ic95_superior",
        "pd_predicha_dentro_ic95",
    ]]


def hosmer_lemeshow(y_true, y_prob, n_grupos: int = 10) -> tuple:
    """
    Test de Hosmer-Lemeshow: bondad de ajuste por grupos de probabilidad.
    H0: no hay diferencia significativa entre PD predicha y observada.
    Un p-valor > 0.05 indica calibración aceptable.

    Retorna (estadístico_HL, p_valor).
    """
    from scipy.stats import chi2

    df = pd.DataFrame({"y": y_true, "p": y_prob})
    df["grupo"] = pd.qcut(df["p"], q=n_grupos, duplicates="drop", labels=False)

    grupos = df.groupby("grupo").agg(n=("y", "count"),
                                     obs=("y", "sum"),
                                     pred=("p", "sum"))
    hl_stat = (
        ((grupos["obs"] - grupos["pred"]) ** 2) /
        (grupos["pred"] * (1 - grupos["pred"] / grupos["n"]))
    ).sum()
    p_valor = 1 - chi2.cdf(hl_stat, df=n_grupos - 2)
    return float(hl_stat), float(p_valor)


# ---------------------------------------------------------------------------
# Visualizaciones
# ---------------------------------------------------------------------------

def graficar_curva_roc(resultados_roc: dict) -> None:
    """Curva ROC comparativa de todos los modelos."""
    fig, ax = plt.subplots(figsize=(7, 6))
    colores = ["steelblue", "firebrick", "forestgreen"]

    for (nombre, (fpr, tpr, auc_val)), color in zip(resultados_roc.items(), colores):
        ax.plot(fpr, tpr, label=f"{nombre} (AUC={auc_val:.4f})",
                color=color, linewidth=2)

    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Aleatorio")
    ax.set_xlabel("Tasa de Falsos Positivos (FPR)")
    ax.set_ylabel("Tasa de Verdaderos Positivos (TPR)")
    ax.set_title("Curva ROC – Validación out-of-time (vintage 2024)")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "validacion_roc.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Gráfico ROC guardado.")


def graficar_backtesting(df_bt: pd.DataFrame) -> None:
    """Gráfico de backtesting: PD predicha vs. observada por decil."""
    modelos = df_bt["modelo"].unique()
    fig, axes = plt.subplots(1, len(modelos), figsize=(5 * len(modelos), 5),
                              sharey=False)
    if len(modelos) == 1:
        axes = [axes]

    for ax, modelo in zip(axes, modelos):
        sub = df_bt[df_bt["modelo"] == modelo]
        x = sub["decil"]
        ax.plot(x, sub["pd_observada"] * 100, "o-", color="firebrick",
                label="Observada", linewidth=2)
        ax.plot(x, sub["pd_predicha"] * 100, "s--", color="steelblue",
                label="Predicha", linewidth=2)
        ax.set_title(f"Backtesting – {modelo}")
        ax.set_xlabel("Decil de score (1=menor riesgo)")
        ax.set_ylabel("Tasa de default (%)")
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.suptitle("Backtesting por decil: PD predicha vs. observada", fontsize=12)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "validacion_backtesting.png", dpi=150,
                bbox_inches="tight")
    plt.close()
    print("  Gráfico backtesting guardado.")


# ---------------------------------------------------------------------------
# Prioridad 3: Backtesting de transiciones entre stages (EBA GL 38/66, BIS d350 P3)
# ---------------------------------------------------------------------------

def backtesting_transiciones() -> tuple:
    """
    Construye la matriz de transición trimestral observada entre stages IFRS 9
    y calcula tasas de curación por trimestre/año.

    Lee panel_con_default.parquet para incluir observaciones Stage 3
    (excluidas del dataset de modelado).

    Outputs:
      outputs/tablas/transition_matrix_observed.csv
      outputs/tablas/cure_rates_quarterly.csv
    """
    print("\n  [Backtesting de transiciones de stages]")
    cols = ["loan_sequence_number", "monthly_reporting_period",
            "vintage_year", "ifrs9_stage"]
    panel = pd.read_parquet(PANEL_DEF_PARQUET, columns=cols)
    panel = panel.sort_values(["loan_sequence_number", "monthly_reporting_period"])

    # Stage en t+3 meses (3 períodos hacia adelante dentro de cada préstamo)
    panel["stage_q3"] = (
        panel.groupby("loan_sequence_number")["ifrs9_stage"]
        .shift(-3)
    )
    panel = panel.dropna(subset=["stage_q3"]).copy()
    panel["stage_q3"] = panel["stage_q3"].astype("Int8")

    # Matriz de transición: proporción de transiciones Stage_i → Stage_j
    trans = (
        panel.groupby(["ifrs9_stage", "stage_q3"])
        .size()
        .reset_index(name="count")
    )
    totales = trans.groupby("ifrs9_stage")["count"].transform("sum")
    trans["prob"] = (trans["count"] / totales).round(4)
    matriz = trans.pivot(
        index="ifrs9_stage", columns="stage_q3", values="prob"
    ).fillna(0)

    # Métricas clave
    s1_to_s3 = float(matriz.loc[1, 3]) if (1 in matriz.index and 3 in matriz.columns) else np.nan
    cure_rate = float(matriz.loc[2, 1]) if (2 in matriz.index and 1 in matriz.columns) else np.nan

    print("  Matriz de transición trimestral (Stage t -> Stage t+3m):")
    print(matriz.round(4).to_string())
    if not np.isnan(s1_to_s3):
        print(f"\n  Stage 1->3 directo (sin pasar por Stage 2): {s1_to_s3:.4%}")
        if s1_to_s3 > 0.01:
            print("    AVISO: tasa alta – el SICR puede no estar capturando deterioro temprano")
    if not np.isnan(cure_rate):
        print(f"  Cure rate trimestral (Stage 2->1): {cure_rate:.4%}")

    # Cure rate anual (por año del período de reporte)
    panel_s2 = panel[panel["ifrs9_stage"] == 2].copy()
    panel_s2["year"] = pd.to_datetime(
        panel_s2["monthly_reporting_period"]
    ).dt.year
    cure_anual = (
        panel_s2.groupby("year")
        .apply(lambda x: (x["stage_q3"] == 1).mean())
        .reset_index()
        .rename(columns={0: "cure_rate"})
    )

    # PSI de distribución de stages entre train y test
    dist_train = panel[panel["vintage_year"].isin(AÑOS_ENTRENAMIENTO)]["ifrs9_stage"].value_counts(normalize=True)
    dist_test  = panel[panel["vintage_year"].isin(AÑOS_TEST)]["ifrs9_stage"].value_counts(normalize=True)
    stages_comunes = dist_train.index.intersection(dist_test.index)
    if len(stages_comunes) > 0:
        p_ref = dist_train.loc[stages_comunes].clip(1e-6)
        p_new = dist_test.loc[stages_comunes].clip(1e-6)
        psi_stages = float(np.sum((p_new - p_ref) * np.log(p_new / p_ref)))
        print(f"  PSI distribución de stages (train vs test): {psi_stages:.4f}")

    # Guardar outputs
    matriz.to_csv(TABLAS_PATH / "transition_matrix_observed.csv")
    cure_anual.to_csv(TABLAS_PATH / "cure_rates_quarterly.csv", index=False)
    print(f"  Guardado: transition_matrix_observed.csv, cure_rates_quarterly.csv")

    return matriz, cure_anual


# ---------------------------------------------------------------------------
# Prioridad 4: Validación de curva Lifetime PD (EBA GL 66, BIS d350 Principio 5)
# ---------------------------------------------------------------------------

def backtesting_lifetime_pd() -> pd.DataFrame:
    """
    Compara la curva de Lifetime PD predicha (paso 05) contra la tasa de default
    acumulada observada por cohorte de originación (vintage_year).

    Para cada vintage y horizonte h (12, 24, 36, 48, 60 meses):
      - Observada: P(prestamo defaultó dentro de sus primeros h meses de vida)
      - Predicha:  Lifetime PD acumulada al loan_age h (de curva_pd_lifetime.csv)

    Outputs:
      outputs/figuras/lifetime_pd_backtest.png
      outputs/tablas/lifetime_pd_backtest_by_vintage.csv
    """
    ruta_curva = TABLAS_PATH / "curva_pd_lifetime.csv"
    if not ruta_curva.exists():
        print("\n  [Backtesting Lifetime PD] curva_pd_lifetime.csv no encontrada – omitido")
        return pd.DataFrame()

    print("\n  [Backtesting Lifetime PD vs. defaults observados]")
    horizons = [12, 24, 36, 48, 60]

    # --- Datos observados ---
    cols = ["loan_sequence_number", "loan_age", "vintage_year", "evento_default"]
    panel = pd.read_parquet(PANEL_DEF_PARQUET, columns=cols)

    # Por cada préstamo: primera edad de default y edad máxima observada
    first_default = (
        panel[panel["evento_default"]]
        .groupby("loan_sequence_number")["loan_age"]
        .min()
        .rename("first_default_age")
    )
    loan_info = panel.groupby("loan_sequence_number").agg(
        vintage_year=("vintage_year", "first"),
        max_age=("loan_age", "max"),
    )
    loan_info = loan_info.join(first_default)

    # --- Curva predicha ---
    lifetime_pred = pd.read_csv(ruta_curva)

    def pd_pred_at(h: int) -> float:
        sub = lifetime_pred[lifetime_pred["loan_age"] <= h]
        return float(sub["pd_lifetime_acum"].iloc[-1]) if len(sub) > 0 else np.nan

    pred_at = {h: pd_pred_at(h) for h in horizons}

    # --- Comparar por vintage y horizonte ---
    rows = []
    for vintage in sorted(loan_info["vintage_year"].unique()):
        loans_v = loan_info[loan_info["vintage_year"] == vintage]
        for h in horizons:
            eligible = loans_v[loans_v["max_age"] >= h]
            if len(eligible) < 100:
                continue
            obs = float((eligible["first_default_age"] <= h).mean())
            pred = pred_at[h]
            rows.append({
                "vintage_year":    vintage,
                "horizon_months":  h,
                "obs_default_rate": round(obs,  6),
                "pred_lifetime_pd": round(pred, 6) if not np.isnan(pred) else np.nan,
                "ratio_pred_obs":   round(pred / obs, 3) if obs > 0 and not np.isnan(pred) else np.nan,
                "abs_error":        round(abs(pred - obs), 6) if not np.isnan(pred) else np.nan,
                "n_loans":          len(eligible),
            })

    df_bt = pd.DataFrame(rows)
    if df_bt.empty:
        print("  No hay suficientes datos para backtesting Lifetime PD.")
        return df_bt

    mae = df_bt["abs_error"].mean()
    ratio_medio = df_bt["ratio_pred_obs"].mean()
    print(f"  MAE predicho vs. observado: {mae:.4%}")
    print(f"  Ratio medio predicho/observado: {ratio_medio:.3f} (>1=conservador, <1=subestimación)")

    df_bt.to_csv(TABLAS_PATH / "lifetime_pd_backtest_by_vintage.csv", index=False)

    # Gráfico: curvas por vintage y horizonte
    vintages = sorted(df_bt["vintage_year"].unique())
    colores_base = plt.cm.tab10(np.linspace(0, 1, len(vintages)))
    fig, ax = plt.subplots(figsize=(11, 7))

    for i, vintage in enumerate(vintages):
        sub = df_bt[df_bt["vintage_year"] == vintage].sort_values("horizon_months")
        color = colores_base[i]
        ax.plot(sub["horizon_months"], sub["obs_default_rate"] * 100,
                color=color, linewidth=2, marker="o", label=f"{vintage} obs.")
        ax.plot(sub["horizon_months"], sub["pred_lifetime_pd"] * 100,
                color=color, linewidth=1.5, linestyle="--")

    # Línea dummy para la leyenda del estilo
    ax.plot([], [], "k-",  linewidth=2, label="Observada (sólida)")
    ax.plot([], [], "k--", linewidth=1.5, label="Predicha (punteada)")
    ax.set_xlabel("Horizonte (meses desde originación)")
    ax.set_ylabel("Tasa de default acumulada (%)")
    ax.set_title("Backtesting Lifetime PD: predicha vs. observada por vintage\n"
                 f"MAE={mae:.4%} | Ratio medio={ratio_medio:.3f}")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    ruta_fig = FIGURAS_PATH / "lifetime_pd_backtest.png"
    plt.savefig(ruta_fig, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Gráfico guardado: {ruta_fig}")
    print(f"  Tabla guardada:   lifetime_pd_backtest_by_vintage.csv")

    return df_bt


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 6 – Validación regulatoria del modelo PD")
    print("=" * 60)

    dataset  = pd.read_parquet(DATASET_MOD_PARQUET)
    features = joblib.load(MODELOS_PATH / "features_lista.joblib")
    features_disp = [f for f in features if f in dataset.columns]

    # Partición test (out-of-time)
    test  = dataset[dataset["vintage_year"].isin(AÑOS_TEST)]
    train = dataset[dataset["vintage_year"].isin(AÑOS_ENTRENAMIENTO)]
    X_test, y_test   = test[features_disp],  test[TARGET].astype(int)
    X_train, y_train = train[features_disp], train[TARGET].astype(int)

    # Cargar modelos
    nombres_modelos = ["logistica", "xgboost", "random_forest"]
    resultados_roc = {}
    filas_metricas = []
    df_backtesting = []

    for nombre in nombres_modelos:
        ruta = MODELOS_PATH / f"modelo_{nombre}.joblib"
        if not ruta.exists():
            print(f"  Modelo no encontrado: {ruta.name} (saltando)")
            continue

        modelo = joblib.load(ruta)
        prob_test  = modelo.predict_proba(X_test)[:, 1]
        prob_train = modelo.predict_proba(X_train)[:, 1]

        # Métricas discriminación
        auc  = roc_auc_score(y_test, prob_test)
        gini = 2 * auc - 1
        ks   = calcular_ks(y_test, prob_test)

        # Calibración
        brier = brier_score_loss(y_test, prob_test)
        hl, p_hl = hosmer_lemeshow(y_test.values, prob_test)

        # Estabilidad
        psi = calcular_psi(prob_train, prob_test)
        psi_status = (
            "estable" if psi < 0.1 else
            "monitorear" if psi < 0.25 else
            "INESTABLE"
        )

        print(f"\n  [{nombre.upper()}]")
        print(f"    AUC        = {auc:.4f}")
        print(f"    Gini       = {gini:.4f}")
        print(f"    KS         = {ks:.4f}")
        print(f"    Brier      = {brier:.4f}")
        print(f"    HL p-valor = {p_hl:.4f}")
        print(f"    PSI        = {psi:.4f} ({psi_status})")

        filas_metricas.append({
            "Modelo": nombre, "AUC": auc, "Gini": gini, "KS": ks,
            "Brier": brier, "HL_pvalor": p_hl, "PSI": psi,
            "PSI_estado": psi_status,
        })

        # Curva ROC
        fpr, tpr, _ = roc_curve(y_test, prob_test)
        resultados_roc[nombre] = (fpr, tpr, auc)

        # Backtesting
        df_bt = backtesting_deciles(y_test.values, prob_test, nombre)
        df_backtesting.append(df_bt)

    # Guardar resultados
    df_metricas = pd.DataFrame(filas_metricas).set_index("Modelo")
    ruta_met = TABLAS_PATH / "validacion_metricas.csv"
    df_metricas.to_csv(ruta_met)
    print(f"\n  Tabla de métricas guardada: {ruta_met}")

    df_bt_all = pd.concat(df_backtesting, ignore_index=True)
    ruta_bt = TABLAS_PATH / "validacion_backtesting.csv"
    df_bt_all.to_csv(ruta_bt, index=False)

    # Control 6.5: test binomial Z + intervalos de Wilson por decil (complemento
    # a Hosmer-Lemeshow, que pierde potencia discriminante a N > 400.000)
    df_ic = intervalos_calibracion(df_bt_all)
    ruta_ic = TABLAS_PATH / "validacion_calibracion_intervalos.csv"
    df_ic.to_csv(ruta_ic, index=False)
    print(f"  Intervalos de calibración (Wilson 95%) guardados: {ruta_ic}")

    # Gráficos
    graficar_curva_roc(resultados_roc)
    graficar_backtesting(df_bt_all)

    # Prioridad 3: backtesting de transiciones entre stages
    backtesting_transiciones()

    # Prioridad 4: backtesting de la curva Lifetime PD
    backtesting_lifetime_pd()

    print("\nPaso 6 completado.\n")
    return df_metricas


if __name__ == "__main__":
    main()
