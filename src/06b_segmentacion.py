"""
06b_segmentacion.py – Validación empírica de la segmentación de cartera
=========================================================================
Control 3.6 (respaldo cuantitativo de la segmentación).

IFRS 9 5.5.4 exige que, cuando la evaluación del riesgo no pueda hacerse de
forma individual, se agrupen los instrumentos sobre la base de características
de riesgo crediticio compartidas. La EBA (GL/2017/16 §5.2) añade que la
segmentación debe demostrarse empíricamente: los segmentos han de ser
internamente homogéneos y mutuamente heterogéneos, y el modelo debe conservar
poder discriminante y estabilidad dentro de cada uno de ellos.

Este módulo produce la evidencia cuantitativa correspondiente:

  1. Discriminación por segmento : AUC, Gini y KS del modelo campeón dentro de
     cada segmento, sobre la partición out-of-time.
  2. Estabilidad por segmento    : PSI de la distribución del score entre el
     período de referencia (entrenamiento) y el de monitoreo (test).
  3. Homogeneidad intra-segmento : test chi-cuadrado de independencia entre el
     default observado y una subpartición del propio segmento. Un p-valor alto
     indica que el segmento no esconde subgrupos de riesgo diferenciado.
  4. Heterogeneidad inter-segmento: chi-cuadrado global sobre la tasa de default
     entre segmentos, V de Cramér y tests z de dos proporciones para cada par
     de segmentos contiguos, más la comparación de curvas de default acumuladas.

Entrada  : data/dataset_modelado.parquet, outputs/modelos/modelo_xgboost.joblib
Salida   : outputs/tablas/segmentacion_metricas.csv
           outputs/tablas/segmentacion_homogeneidad.csv
           outputs/tablas/segmentacion_heterogeneidad.csv
           outputs/figuras/segmentacion_curvas_default.png
           outputs/figuras/segmentacion_discriminacion.png
"""

import warnings

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import chi2_contingency, norm
from sklearn.metrics import roc_auc_score, roc_curve

from config import (
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH, FIGURAS_PATH,
    TARGET, AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST,
    SEGMENTOS_CORTES, SEGMENTO_MIN_OBS, SEGMENTO_MIN_DEFAULTS,
    ALFA_SIGNIFICACION,
)

import sys as _sys, os as _os
_sys.path.insert(0, str(_os.path.dirname(__file__)))
from importlib import import_module as _im
_p04 = _im("04_modelado")
ModeloCalibraado = _p04.ModeloCalibraado  # noqa: F401

warnings.filterwarnings("ignore")
plt.rcParams.update({"font.family": "serif", "font.size": 11})

# Etiquetas legibles de las variables categóricas label-encoded en el paso 03.
# pd.Categorical asigna los códigos en orden alfabético de la categoría original.
ETIQUETAS_CATEGORICAS = {
    "loan_purpose":    {0: "C (refi cash-out)", 1: "N (refi no cash-out)", 2: "P (compra)"},
    "occupancy_status": {0: "I (inversión)", 1: "P (primaria)", 2: "S (segunda vivienda)"},
    "channel":         {0: "B (broker)", 1: "C (correspondent)", 2: "R (retail)", 3: "T (TPO)"},
    "property_type":   {0: "CO (condominio)", 1: "CP (cooperativa)", 2: "MH (manufacturada)",
                        3: "PU (PUD)", 4: "SF (unifamiliar)"},
}


# ---------------------------------------------------------------------------
# Construcción de los segmentos
# ---------------------------------------------------------------------------

def asignar_segmentos(df: pd.DataFrame) -> list:
    """
    Crea una columna por cada dimensión de segmentación definida en config.py.
    Retorna la lista de nombres de columna creadas.
    """
    creadas = []
    for nombre, spec in SEGMENTOS_CORTES.items():
        var = spec["var"]
        if var not in df.columns:
            print(f"  Segmentación '{nombre}' omitida: falta la variable {var}")
            continue

        col = f"seg_{nombre}"
        if spec.get("categorica"):
            mapa = ETIQUETAS_CATEGORICAS.get(var, {})
            df[col] = df[var].map(lambda c: mapa.get(int(c), f"cod_{int(c)}")
                                  if pd.notna(c) else "sin_dato")
        else:
            df[col] = pd.cut(df[var], bins=spec["cortes"],
                             labels=spec["etiquetas"], right=False)
            df[col] = df[col].astype(object).fillna("sin_dato")
        creadas.append(col)
    return creadas


# ---------------------------------------------------------------------------
# Métricas por segmento
# ---------------------------------------------------------------------------

def calcular_ks(y_true, y_prob) -> float:
    """Máxima distancia entre las CDF de defaulters y no defaulters."""
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    return float(np.max(tpr - fpr))


def calcular_psi(ref_scores: np.ndarray, new_scores: np.ndarray,
                 n_bins: int = 10) -> float:
    """
    Population Stability Index entre el período de referencia y el de monitoreo.
    Los cortes se fijan sobre los deciles del período de referencia.
    """
    bins = np.percentile(ref_scores, np.linspace(0, 100, n_bins + 1))
    bins = np.unique(bins)
    if len(bins) < 3:
        return float("nan")
    bins[0], bins[-1] = -np.inf, np.inf

    def frecuencias(x):
        counts, _ = np.histogram(x, bins=bins)
        return np.clip(counts / len(x), 1e-6, None)

    ref_pct, new_pct = frecuencias(ref_scores), frecuencias(new_scores)
    return float(np.sum((new_pct - ref_pct) * np.log(new_pct / ref_pct)))


def metricas_por_segmento(df: pd.DataFrame, col_seg: str) -> pd.DataFrame:
    """
    Discriminación (AUC, Gini, KS), calibración (PD predicha vs. observada) y
    estabilidad (PSI) del modelo dentro de cada nivel del segmento.

    La discriminación se mide sobre la partición out-of-time; el PSI compara la
    distribución del score de entrenamiento contra la de test.
    """
    filas = []
    for nivel in sorted(df[col_seg].dropna().unique(), key=str):
        sub = df[df[col_seg] == nivel]
        sub_tr = sub[sub["particion"] == "train"]
        sub_te = sub[sub["particion"] == "test"]
        sub_va = sub[sub["particion"] == "val"]

        n_te, d_te = len(sub_te), int(sub_te[TARGET].sum())
        reportable = n_te >= SEGMENTO_MIN_OBS and d_te >= SEGMENTO_MIN_DEFAULTS

        def _auc(s):
            if len(s) == 0 or s[TARGET].nunique() < 2:
                return np.nan
            return roc_auc_score(s[TARGET], s["score"])

        auc_te = _auc(sub_te)
        auc_va = _auc(sub_va)
        ks_te  = (calcular_ks(sub_te[TARGET], sub_te["score"])
                  if not np.isnan(auc_te) else np.nan)
        psi = (calcular_psi(sub_tr["score"].to_numpy(), sub_te["score"].to_numpy())
               if len(sub_tr) > 100 and len(sub_te) > 100 else np.nan)

        pd_pred = float(sub_te["score"].mean()) if n_te else np.nan
        pd_obs  = float(sub_te[TARGET].mean()) if n_te else np.nan

        filas.append({
            "segmentacion":  col_seg.replace("seg_", ""),
            "segmento":      str(nivel),
            "n_train":       len(sub_tr),
            "n_test":        n_te,
            "defaults_test": d_te,
            "tasa_def_train": round(float(sub_tr[TARGET].mean()), 6) if len(sub_tr) else np.nan,
            "tasa_def_test":  round(pd_obs, 6) if n_te else np.nan,
            "AUC_val":       round(auc_va, 4) if not np.isnan(auc_va) else np.nan,
            "AUC_test":      round(auc_te, 4) if not np.isnan(auc_te) else np.nan,
            "Gini_test":     round(2 * auc_te - 1, 4) if not np.isnan(auc_te) else np.nan,
            "KS_test":       round(ks_te, 4) if not np.isnan(ks_te) else np.nan,
            "PD_predicha":   round(pd_pred, 6) if n_te else np.nan,
            "ratio_obs_pred": round(pd_obs / pd_pred, 3) if n_te and pd_pred > 0 else np.nan,
            "PSI":           round(psi, 4) if not np.isnan(psi) else np.nan,
            "PSI_estado":    ("estable" if psi < 0.10 else
                              "monitorear" if psi < 0.25 else "INESTABLE")
                             if not np.isnan(psi) else "sin_dato",
            "reportable":    reportable,
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Homogeneidad intra-segmento
# ---------------------------------------------------------------------------

def test_homogeneidad(df: pd.DataFrame, col_seg: str,
                      var_control: str = "credit_score") -> pd.DataFrame:
    """
    Test chi-cuadrado de independencia entre el default observado y una
    subpartición interna del segmento.

    Un segmento es homogéneo si, al dividirlo en cuartiles de un driver de
    riesgo secundario, la tasa de default no difiere significativamente entre
    esos cuartiles (p > alfa). Si difiere, el segmento agrupa perfiles de riesgo
    distintos y la partición debería refinarse.

    Para la segmentación por bandas de FICO el control es el LTV original (y
    viceversa), de modo que la subpartición sea siempre ortogonal al criterio
    que define el segmento.
    """
    spec = SEGMENTOS_CORTES[col_seg.replace("seg_", "")]
    if spec["var"] == var_control:
        var_control = "original_ltv"

    filas = []
    for nivel in sorted(df[col_seg].dropna().unique(), key=str):
        sub = df[df[col_seg] == nivel]
        if len(sub) < SEGMENTO_MIN_OBS or sub[TARGET].sum() < SEGMENTO_MIN_DEFAULTS:
            continue

        cuartiles = pd.qcut(sub[var_control], q=4, labels=False, duplicates="drop")
        tabla = pd.crosstab(cuartiles, sub[TARGET])
        if tabla.shape[0] < 2 or tabla.shape[1] < 2:
            continue

        chi2, p, gl, _ = chi2_contingency(tabla)
        tasas = sub.groupby(cuartiles)[TARGET].mean()
        n_total = tabla.to_numpy().sum()
        cramer_v = np.sqrt(chi2 / (n_total * (min(tabla.shape) - 1)))

        filas.append({
            "segmentacion":   col_seg.replace("seg_", ""),
            "segmento":       str(nivel),
            "var_control":    var_control,
            "n":              int(n_total),
            "tasa_def_min":   round(float(tasas.min()), 6),
            "tasa_def_max":   round(float(tasas.max()), 6),
            "dispersion_rel": round(float(tasas.std() / tasas.mean()), 4)
                              if tasas.mean() > 0 else np.nan,
            "chi2":           round(float(chi2), 2),
            "gl":             int(gl),
            "p_valor":        round(float(p), 6),
            "V_Cramer":       round(float(cramer_v), 4),
            "homogeneo":      bool(p > ALFA_SIGNIFICACION),
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Heterogeneidad inter-segmento
# ---------------------------------------------------------------------------

def test_dos_proporciones(x1, n1, x2, n2) -> tuple:
    """Test z de dos proporciones (bilateral). Retorna (z, p_valor)."""
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return np.nan, np.nan
    z = (p1 - p2) / se
    return float(z), float(2 * (1 - norm.cdf(abs(z))))


def test_heterogeneidad(df: pd.DataFrame, col_seg: str) -> tuple:
    """
    Contrasta que los segmentos presenten perfiles de riesgo efectivamente
    distintos entre sí:

      - Chi-cuadrado global de independencia entre segmento y default, con
        V de Cramér como medida del tamaño del efecto.
      - Test z de dos proporciones para cada par de segmentos contiguos
        (ordenados por tasa de default observada).

    Retorna (resumen_global, comparaciones_por_pares).
    """
    niveles = [n for n in sorted(df[col_seg].dropna().unique(), key=str)
               if len(df[df[col_seg] == n]) >= SEGMENTO_MIN_OBS]
    sub = df[df[col_seg].isin(niveles)]

    tabla = pd.crosstab(sub[col_seg], sub[TARGET])
    chi2, p, gl, _ = chi2_contingency(tabla)
    n_total = tabla.to_numpy().sum()
    cramer_v = np.sqrt(chi2 / (n_total * (min(tabla.shape) - 1)))

    resumen = {
        "segmentacion": col_seg.replace("seg_", ""),
        "n_segmentos":  len(niveles),
        "n":            int(n_total),
        "chi2_global":  round(float(chi2), 2),
        "gl":           int(gl),
        "p_valor":      float(p),
        "V_Cramer":     round(float(cramer_v), 4),
        "heterogeneo":  bool(p < ALFA_SIGNIFICACION),
    }

    resumen_niveles = (
        sub.groupby(col_seg)[TARGET].agg(["count", "sum", "mean"])
        .sort_values("mean")
    )
    pares = []
    for (a, fa), (b, fb) in zip(resumen_niveles.iloc[:-1].iterrows(),
                                resumen_niveles.iloc[1:].iterrows()):
        z, pv = test_dos_proporciones(fa["sum"], fa["count"],
                                      fb["sum"], fb["count"])
        pares.append({
            "segmentacion":  col_seg.replace("seg_", ""),
            "segmento_a":    str(a),
            "segmento_b":    str(b),
            "tasa_def_a":    round(float(fa["mean"]), 6),
            "tasa_def_b":    round(float(fb["mean"]), 6),
            "ratio_b_a":     round(float(fb["mean"] / fa["mean"]), 3)
                             if fa["mean"] > 0 else np.nan,
            "z":             round(z, 3) if not np.isnan(z) else np.nan,
            "p_valor":       float(pv) if not np.isnan(pv) else np.nan,
            "difieren":      bool(pv < ALFA_SIGNIFICACION) if not np.isnan(pv) else False,
        })
    return resumen, pd.DataFrame(pares)


# ---------------------------------------------------------------------------
# Curvas de default acumuladas por segmento
# ---------------------------------------------------------------------------

def curvas_default_acumuladas(df: pd.DataFrame, col_seg: str) -> pd.DataFrame:
    """
    Tasa de default acumulada por antigüedad del préstamo dentro de cada
    segmento, calculada como 1 − ∏(1 − tasa marginal por loan_age).

    Es la evidencia gráfica de la heterogeneidad: curvas separadas y sin cruces
    confirman un ordenamiento de riesgo estable a lo largo de la vida.
    """
    marg = (
        df.groupby([col_seg, "loan_age"])[TARGET]
        .agg(["mean", "count"]).reset_index()
        .rename(columns={"mean": "tasa_marginal", "count": "n"})
    )
    marg = marg[marg["n"] >= 500]
    marg = marg.sort_values([col_seg, "loan_age"])
    marg["acumulada"] = (
        1 - marg.groupby(col_seg)["tasa_marginal"]
        .transform(lambda x: (1 - x).cumprod())
    )
    return marg


def graficar_segmentacion(curvas: dict, metricas: pd.DataFrame) -> None:
    """Curvas de default acumuladas y AUC por segmento."""
    dims = list(curvas.keys())
    fig, axes = plt.subplots(1, len(dims), figsize=(6 * len(dims), 5))
    if len(dims) == 1:
        axes = [axes]
    for ax, dim in zip(axes, dims):
        datos = curvas[dim]
        col = f"seg_{dim}"
        for nivel in sorted(datos[col].dropna().unique(), key=str):
            s = datos[datos[col] == nivel]
            ax.plot(s["loan_age"], s["acumulada"] * 100, linewidth=2, label=str(nivel))
        ax.set_title(f"Default acumulado – {dim}")
        ax.set_xlabel("Loan age (meses)")
        ax.set_ylabel("Tasa de default acumulada (%)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)
    plt.suptitle("Heterogeneidad inter-segmento: curvas de default acumuladas",
                 fontsize=12)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "segmentacion_curvas_default.png",
                dpi=150, bbox_inches="tight")
    plt.close()
    print("  Figura guardada: segmentacion_curvas_default.png")

    rep = metricas[metricas["reportable"]].copy()
    rep["etiqueta"] = rep["segmentacion"] + " | " + rep["segmento"]
    rep = rep.sort_values("AUC_test")
    fig, ax = plt.subplots(figsize=(9, max(4, 0.32 * len(rep))))
    ax.barh(rep["etiqueta"], rep["AUC_test"], color="steelblue")
    ax.axvline(0.70, color="firebrick", linestyle="--", linewidth=1.2,
               label="Umbral mínimo AUC = 0,70")
    ax.set_xlim(0.5, 1.0)
    ax.set_xlabel("AUC out-of-time (vintage 2024)")
    ax.set_title("Discriminación del modelo por segmento")
    ax.legend(fontsize=9)
    ax.grid(True, axis="x", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "segmentacion_discriminacion.png",
                dpi=150, bbox_inches="tight")
    plt.close()
    print("  Figura guardada: segmentacion_discriminacion.png")


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 6b – Validación empírica de la segmentación (Control 3.6)")
    print("=" * 60)

    features = joblib.load(MODELOS_PATH / "features_lista.joblib")
    vars_seg = [s["var"] for s in SEGMENTOS_CORTES.values()]
    columnas = sorted(set(features + vars_seg +
                          [TARGET, "vintage_year", "loan_age"]))
    disponibles = pq.read_schema(DATASET_MOD_PARQUET).names
    df = pd.read_parquet(DATASET_MOD_PARQUET,
                         columns=[c for c in columnas if c in disponibles])
    print(f"Dataset cargado: {len(df):,} filas")

    modelo = joblib.load(MODELOS_PATH / "modelo_xgboost.joblib")
    df["score"] = modelo.predict_proba(df[[f for f in features
                                           if f in df.columns]])[:, 1]
    df["particion"] = np.select(
        [df["vintage_year"].isin(AÑOS_ENTRENAMIENTO),
         df["vintage_year"].isin(AÑOS_VALIDACION),
         df["vintage_year"].isin(AÑOS_TEST)],
        ["train", "val", "test"], default="otro",
    )

    cols_seg = asignar_segmentos(df)
    print(f"Dimensiones de segmentación evaluadas: {len(cols_seg)}")

    metricas, homogeneidad, pares, resumenes, curvas = [], [], [], [], {}
    for col in cols_seg:
        dim = col.replace("seg_", "")
        print(f"\n  [{dim}]")
        met = metricas_por_segmento(df, col)
        metricas.append(met)
        print(met[["segmento", "n_test", "defaults_test", "tasa_def_test",
                   "AUC_test", "KS_test", "PSI"]].to_string(index=False))

        homo = test_homogeneidad(df, col)
        homogeneidad.append(homo)
        if len(homo):
            n_homo = int(homo["homogeneo"].sum())
            print(f"    Homogeneidad intra-segmento: {n_homo}/{len(homo)} "
                  f"segmentos homogéneos (chi², alfa={ALFA_SIGNIFICACION})")

        resumen, par = test_heterogeneidad(df, col)
        resumenes.append(resumen)
        pares.append(par)
        print(f"    Heterogeneidad inter-segmento: chi2={resumen['chi2_global']:.1f} "
              f"(gl={resumen['gl']}) p={resumen['p_valor']:.3g} "
              f"V={resumen['V_Cramer']:.4f} -> "
              f"{'segmentos diferenciados' if resumen['heterogeneo'] else 'SIN diferencias'}")

        curvas[dim] = curvas_default_acumuladas(df, col)

    df_met = pd.concat(metricas, ignore_index=True)
    df_hom = pd.concat(homogeneidad, ignore_index=True)
    df_par = pd.concat(pares, ignore_index=True)
    df_res = pd.DataFrame(resumenes)

    df_met.to_csv(TABLAS_PATH / "segmentacion_metricas.csv", index=False)
    df_hom.to_csv(TABLAS_PATH / "segmentacion_homogeneidad.csv", index=False)
    df_par.to_csv(TABLAS_PATH / "segmentacion_heterogeneidad.csv", index=False)
    df_res.to_csv(TABLAS_PATH / "segmentacion_heterogeneidad_global.csv", index=False)
    print("\n  Tablas guardadas: segmentacion_metricas.csv, "
          "segmentacion_homogeneidad.csv, segmentacion_heterogeneidad.csv, "
          "segmentacion_heterogeneidad_global.csv")

    graficar_segmentacion({k: curvas[k] for k in list(curvas)[:3]}, df_met)

    rep = df_met[df_met["reportable"]]
    print(f"\n  Segmentos reportables: {len(rep)}/{len(df_met)}")
    print(f"  AUC out-of-time mínimo por segmento : {rep['AUC_test'].min():.4f}")
    print(f"  AUC out-of-time mediano por segmento: {rep['AUC_test'].median():.4f}")
    print(f"  Segmentos con PSI > 0,25            : "
          f"{int((rep['PSI'] > 0.25).sum())}")
    print("\nPaso 6b completado.\n")
    return df_met


if __name__ == "__main__":
    main()
