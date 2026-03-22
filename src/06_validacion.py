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
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH, FIGURAS_PATH,
    FEATURES_MODELO, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST,
)

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

    # Gráficos
    graficar_curva_roc(resultados_roc)
    graficar_backtesting(df_bt_all)

    print("\nPaso 6 completado.\n")
    return df_metricas


if __name__ == "__main__":
    main()
