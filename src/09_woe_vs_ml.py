"""
09_woe_vs_ml.py – Costo de la Regulación vs. Machine Learning
=================================================================
Compara dos arquitecturas de modelado de PD bajo el mismo marco IFRS 9:

  Familia A – Scorecard regulatorio (WoE)
    Cada variable se transforma a su Weight of Evidence (WoE) sobre bins
    ajustados en TRAIN, y se entrena Regresión Logística, XGBoost y Random
    Forest sobre esa matriz transformada. Es el enfoque clásico de scorecard
    de riesgo de crédito (Siddiqi, 2006; Thomas et al., 2017): monotonía y
    linealidad impuestas por diseño, alta interpretabilidad, IV por variable.

  Familia B – ML sin restricciones (Raw)
    XGBoost y Random Forest entrenados directamente sobre las variables
    originales (continuas + categóricas codificadas + relativas a cohorte),
    permitiendo interacciones y no linealidades libres. Son los modelos ya
    optimizados en 04_modelado.py (con restricciones de monotonía sobre los
    drivers de riesgo, pero sin discretización previa) — se reutilizan tal
    cual, calibrados isotónicamente.

Ambas familias se evalúan bajo idéntica partición temporal (train 2016-2020,
val 2022-2023, test 2024 OOT) para una comparación de "costo de la
regulación": cuánta capacidad predictiva se sacrifica (o se gana en
gobernabilidad) al imponer la estructura WoE tradicional frente al ML sin
restricciones, y cómo se traduce esa diferencia en provisiones de ECL y en
la tasa de falsos positivos de la migración a Stage 2 (SICR).

Metodología SICR por modelo (Sección 13.5 / IFRS 9 5.5.9):
  Para cada familia se entrena además un modelo de PD en originación (mismas
  variables de FEATURES_ORIGINACION_EXT, misma transformación WoE/raw) que
  sirve de referencia t=0. El criterio de SICR (k, delta, backstop) definido
  en config.py se aplica de forma idéntica a las cinco combinaciones
  PD-corriente / PD-originación, de modo que las diferencias en Stage 2 y en
  ECL sean atribuibles exclusivamente a la arquitectura de modelado.

Entrada  : data/dataset_modelado.parquet
           outputs/modelos/modelo_xgboost.joblib, modelo_random_forest.joblib,
           modelo_pd_originacion.joblib (familia Raw, ya entrenados en 04/03b)
           outputs/tablas/lgd_politica_perdida_total.csv (LGD ponderada)
Salida   : outputs/modelos/modelo_{lr,xgb,rf}_woe.joblib
           outputs/modelos/modelo_pd_originacion_woe.joblib
           outputs/tablas/woe_bins_iv.csv
           outputs/tablas/comparacion_woe_vs_raw_metricas.csv
           outputs/tablas/comparacion_woe_vs_raw_sicr.csv
           outputs/tablas/comparacion_woe_vs_raw_ecl.csv
           outputs/figuras/woe_vs_raw_roc.png
           outputs/figuras/woe_vs_raw_ecl_provisiones.png
"""

import warnings

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve
from xgboost import XGBClassifier

from config import (
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH, FIGURAS_PATH,
    FEATURES_MODELO, FEATURES_ORIGINACION_EXT, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST, AÑO_EARLY_STOPPING,
    MAX_TRAIN_OBS, HORIZONTE_PD_MESES,
    SICR_RELATIVE_THRESHOLD, SICR_ABSOLUTE_THRESHOLD, SICR_BACKSTOP_DPD,
    LGD_DOWNTURN_ADDON, LGD_MAX,
)

import sys as _sys, os as _os
_sys.path.insert(0, str(_os.path.dirname(__file__)))
from importlib import import_module as _im
_p04 = _im("04_modelado")
ModeloCalibraado = _p04.ModeloCalibraado  # noqa: F401

# modelo_pd_originacion.joblib (familia Raw, generado por 03b_sicr_assessment.py)
# fue serializado mientras ese script corría como __main__, por lo que su clase
# _ModeloOrigCal quedó registrada bajo el módulo "__main__" en el pickle. Para
# poder deserializarlo desde este script se inyecta la clase en el __main__
# actual antes de cualquier joblib.load.
_p03b = _im("03b_sicr_assessment")
_sys.modules["__main__"]._ModeloOrigCal = _p03b._ModeloOrigCal  # noqa: F401

warnings.filterwarnings("ignore")
plt.rcParams.update({"font.family": "serif", "font.size": 11})

CATEGORICAS_WOE = ["loan_purpose", "property_type", "occupancy_status", "channel",
                  "number_of_borrowers", "number_of_units", "amortization_type"]


# ---------------------------------------------------------------------------
# Weight of Evidence: ajuste y aplicación
# ---------------------------------------------------------------------------

class TransformadorWoE:
    """
    Ajusta bins de Weight of Evidence sobre el conjunto de entrenamiento y los
    aplica de forma consistente a cualquier partición posterior (sin fuga:
    los cortes y los WoE se calculan una única vez, sobre train).

    WoE_bin = ln( (%no-default en el bin) / (%default en el bin) )
    IV      = sum_bin (%no-default - %default) * WoE_bin

    Variables continuas: 10 bins por cuantiles (ajustados en train).
    Variables categóricas (ya label-encoded): un bin por categoría.
    Missing: bin propio ("Missing"), nunca imputado antes del binning.
    Se aplica suavizado de Laplace (+0.5 eventos) para evitar log(0) en bins
    con cero defaults, dada la baja tasa de eventos de la cartera (~1.3%).
    """
    N_BINS = 10
    LAPLACE = 0.5

    def __init__(self, features: list, categoricas: list):
        self.features = features
        self.categoricas = [f for f in categoricas if f in features]
        self.edges_: dict = {}
        self.woe_map_: dict = {}
        self.woe_missing_: dict = {}
        self.iv_: dict = {}

    def _woe_tabla(self, bin_ids: pd.Series, y: pd.Series) -> dict:
        total_good = (y == 0).sum()
        total_bad  = (y == 1).sum()
        tabla = {}
        iv = 0.0
        for b in bin_ids.dropna().unique():
            mask = bin_ids == b
            n_good = (y[mask] == 0).sum() + self.LAPLACE
            n_bad  = (y[mask] == 1).sum() + self.LAPLACE
            pct_good = n_good / (total_good + self.LAPLACE)
            pct_bad  = n_bad  / (total_bad  + self.LAPLACE)
            woe = float(np.log(pct_good / pct_bad))
            tabla[b] = woe
            iv += (pct_good - pct_bad) * woe
        return tabla, float(iv)

    def fit(self, X: pd.DataFrame, y: pd.Series):
        for feat in self.features:
            serie = X[feat]
            faltante = serie.isna()
            if feat in self.categoricas:
                bin_ids = serie.where(~faltante)
                self.edges_[feat] = None
            else:
                _, edges = pd.qcut(serie[~faltante], q=self.N_BINS,
                                   duplicates="drop", retbins=True)
                edges = np.unique(edges)
                edges[0], edges[-1] = -np.inf, np.inf
                self.edges_[feat] = edges
                bin_ids = pd.Series(np.digitize(serie.where(~faltante), edges[1:-1]),
                                    index=serie.index).where(~faltante)

            tabla, iv = self._woe_tabla(bin_ids, y)
            self.woe_map_[feat] = tabla
            self.iv_[feat] = iv
            # WoE del bin "Missing": tratado como una categoría más
            if faltante.any():
                tabla_missing, _ = self._woe_tabla(
                    pd.Series(np.where(faltante, -999, np.nan), index=serie.index), y)
                self.woe_missing_[feat] = tabla_missing.get(-999, 0.0)
            else:
                self.woe_missing_[feat] = 0.0
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=X.index)
        for feat in self.features:
            serie = X[feat]
            faltante = serie.isna()
            if feat in self.categoricas:
                bin_ids = serie
            else:
                edges = self.edges_[feat]
                bin_ids = pd.Series(np.digitize(serie, edges[1:-1]), index=serie.index)
            woe_default = float(np.mean(list(self.woe_map_[feat].values()))) \
                if self.woe_map_[feat] else 0.0
            woe_col = bin_ids.map(self.woe_map_[feat]).astype("float64")
            woe_col = woe_col.fillna(woe_default)
            woe_col[faltante] = self.woe_missing_[feat]
            out[f"{feat}_woe"] = woe_col.astype("float32")
        return out

    def tabla_iv(self) -> pd.DataFrame:
        fuerza = {}
        for feat, iv in self.iv_.items():
            if iv < 0.02:
                fuerza[feat] = "no predictivo"
            elif iv < 0.10:
                fuerza[feat] = "débil"
            elif iv < 0.30:
                fuerza[feat] = "medio"
            elif iv < 0.50:
                fuerza[feat] = "fuerte"
            else:
                fuerza[feat] = "sospechoso (revisar)"
        return (pd.DataFrame({"variable": list(self.iv_.keys()),
                              "IV": list(self.iv_.values())})
                .assign(fuerza=lambda d: d["variable"].map(fuerza))
                .sort_values("IV", ascending=False)
                .reset_index(drop=True))


# ---------------------------------------------------------------------------
# Calibración y conversión a Lifetime PD (idéntica a 03b_sicr_assessment.py)
# ---------------------------------------------------------------------------

def calibrar(pipeline, X_val, y_val) -> ModeloCalibraado:
    raw_val = pipeline.predict_proba(X_val)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_val, y_val)
    return ModeloCalibraado(pipeline, iso)


def a_lifetime(pd_12m: np.ndarray, horizonte_meses: np.ndarray) -> np.ndarray:
    años = np.clip(horizonte_meses, 1, None) / HORIZONTE_PD_MESES
    return 1 - (1 - np.clip(pd_12m, 0, 0.999999)) ** años


# ---------------------------------------------------------------------------
# Entrenamiento de la familia WoE
# ---------------------------------------------------------------------------

def entrenar_familia_woe(dataset: pd.DataFrame, features: list) -> dict:
    """Ajusta el transformador WoE en train y entrena LR/XGB/RF-WoE."""
    train = dataset[dataset["vintage_year"].isin(AÑOS_ENTRENAMIENTO)]
    val   = dataset[dataset["vintage_year"].isin(AÑOS_VALIDACION)]

    woe = TransformadorWoE(features, CATEGORICAS_WOE).fit(
        train[features], train[TARGET].astype(int))

    if len(train) > MAX_TRAIN_OBS:
        idx = np.random.RandomState(42).choice(len(train), MAX_TRAIN_OBS, replace=False)
        train_sub = train.iloc[idx]
    else:
        train_sub = train

    Xtr_woe = woe.transform(train_sub[features])
    Xva_woe = woe.transform(val[features])
    ytr, yva = train_sub[TARGET].astype(int), val[TARGET].astype(int)

    modelos = {}

    lr = LogisticRegression(C=0.1, class_weight="balanced", max_iter=1000, random_state=42)
    lr.fit(Xtr_woe, ytr)
    modelos["LR_WoE"] = calibrar(lr, Xva_woe, yva)

    xgb = XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05,
                        min_child_weight=50, reg_lambda=5.0, subsample=0.8,
                        colsample_bytree=0.8, objective="binary:logistic",
                        eval_metric="auc", random_state=42, n_jobs=-1, verbosity=0)
    xgb.fit(Xtr_woe, ytr)
    modelos["XGB_WoE"] = calibrar(xgb, Xva_woe, yva)

    rf = RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=50,
                                class_weight="balanced", random_state=42, n_jobs=-1)
    rf.fit(Xtr_woe, ytr)
    modelos["RF_WoE"] = calibrar(rf, Xva_woe, yva)

    return {"woe": woe, "modelos": modelos}


def entrenar_originacion_woe(dataset: pd.DataFrame) -> tuple:
    """PD de originación bajo transformación WoE, análoga a 03b para la familia Raw."""
    features_orig = [f for f in FEATURES_ORIGINACION_EXT if f in dataset.columns]
    train = dataset[dataset["vintage_year"].isin(AÑOS_ENTRENAMIENTO)]
    val   = dataset[dataset["vintage_year"].isin(AÑOS_VALIDACION)]

    woe = TransformadorWoE(features_orig, CATEGORICAS_WOE).fit(
        train[features_orig], train[TARGET].astype(int))

    if len(train) > MAX_TRAIN_OBS:
        idx = np.random.RandomState(42).choice(len(train), MAX_TRAIN_OBS, replace=False)
        train = train.iloc[idx]

    Xtr = woe.transform(train[features_orig])
    Xva = woe.transform(val[features_orig])
    lr = LogisticRegression(C=0.1, class_weight="balanced", max_iter=1000, random_state=42)
    lr.fit(Xtr, train[TARGET].astype(int))
    modelo = calibrar(lr, Xva, val[TARGET].astype(int))
    return modelo, woe, features_orig


# ---------------------------------------------------------------------------
# Evaluación comparativa
# ---------------------------------------------------------------------------

def metricas_discriminacion(y_true, y_prob) -> dict:
    auc = roc_auc_score(y_true, y_prob)
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    ks = float(np.max(tpr - fpr))
    brier = brier_score_loss(y_true, y_prob)
    return {"AUC": auc, "Gini": 2 * auc - 1, "KS": ks, "Brier": brier}


def evaluar_modelo_sicr(nombre: str, pd_current_12m: np.ndarray,
                        pd_orig_12m: np.ndarray, plazo_residual: np.ndarray,
                        dpd_numerico: np.ndarray, y_true: np.ndarray,
                        ead: np.ndarray, lgd_downturn: float) -> dict:
    """
    Reclasifica Stage 1/2 con el criterio de SICR de config.py usando la PD de
    ESTE modelo (corriente vs. originación), y calcula el ECL de cartera bajo
    esa propia clasificación: aísla el efecto de la arquitectura de modelado
    sobre la migración a Stage 2 y sobre la provisión resultante.
    """
    pd_lifetime_current = a_lifetime(pd_current_12m, plazo_residual)
    pd_lifetime_orig     = a_lifetime(pd_orig_12m, plazo_residual)

    ratio = pd_lifetime_current / np.where(pd_lifetime_orig == 0, np.nan, pd_lifetime_orig)
    diff  = pd_lifetime_current - pd_lifetime_orig
    backstop = dpd_numerico >= SICR_BACKSTOP_DPD

    stage2 = (
        (np.nan_to_num(ratio, nan=0.0) >= SICR_RELATIVE_THRESHOLD)
        | (diff >= SICR_ABSOLUTE_THRESHOLD)
        | backstop
    )

    tasa_s2 = float(y_true[stage2].mean()) if stage2.sum() else np.nan
    tasa_s1 = float(y_true[~stage2].mean()) if (~stage2).sum() else np.nan
    fp_rate = 1 - tasa_s2 if not np.isnan(tasa_s2) else np.nan  # flag sin default en 12m

    ecl_s1 = pd_current_12m[~stage2] * lgd_downturn * ead[~stage2]
    ecl_s2 = pd_lifetime_current[stage2] * lgd_downturn * ead[stage2]
    ecl_total = float(ecl_s1.sum() + ecl_s2.sum())
    ead_total = float(ead.sum())

    return {
        "modelo":                nombre,
        "pct_stage2":            round(float(stage2.mean()), 4),
        "tasa_default_stage2":   round(tasa_s2, 6) if not np.isnan(tasa_s2) else np.nan,
        "tasa_default_stage1":   round(tasa_s1, 6) if not np.isnan(tasa_s1) else np.nan,
        "sicr_falsos_positivos": round(fp_rate, 4) if not np.isnan(fp_rate) else np.nan,
        "ecl_total_usd":         round(ecl_total, 2),
        "ead_total_usd":         round(ead_total, 2),
        "ecl_sobre_ead_bps":     round(ecl_total / ead_total * 10000, 2) if ead_total else np.nan,
    }


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 9 – Costo de la Regulación (WoE) vs. Machine Learning (Raw)")
    print("=" * 60)

    features = [f for f in FEATURES_MODELO
               if f in pq.read_schema(DATASET_MOD_PARQUET).names]
    columnas = sorted(set(features + FEATURES_ORIGINACION_EXT
                          + [TARGET, "vintage_year", "loan_age",
                             "original_loan_term", "dpd_numerico",
                             "current_actual_upb"]))
    disponibles = pq.read_schema(DATASET_MOD_PARQUET).names
    dataset = pd.read_parquet(DATASET_MOD_PARQUET,
                              columns=[c for c in columnas if c in disponibles])
    print(f"Dataset cargado: {len(dataset):,} filas | {len(features)} features")

    # ------------------------------------------------------------------
    # 1. Familia WoE: ajuste y entrenamiento
    # ------------------------------------------------------------------
    print("\n  [Familia A – Scorecard WoE] Ajustando bins y entrenando LR/XGB/RF...")
    familia_woe = entrenar_familia_woe(dataset, features)
    woe, modelos_woe = familia_woe["woe"], familia_woe["modelos"]

    tabla_iv = woe.tabla_iv()
    print(tabla_iv.head(15).to_string(index=False))
    tabla_iv.to_csv(TABLAS_PATH / "woe_bins_iv.csv", index=False)

    print("\n  [Familia A] Entrenando modelo de PD en originación (WoE)...")
    modelo_orig_woe, woe_orig, features_orig = entrenar_originacion_woe(dataset)

    for nombre, modelo in modelos_woe.items():
        joblib.dump(modelo, MODELOS_PATH / f"modelo_{nombre.lower()}.joblib")
    joblib.dump(modelo_orig_woe, MODELOS_PATH / "modelo_pd_originacion_woe.joblib")
    print("  Modelos WoE guardados en outputs/modelos/.")

    # ------------------------------------------------------------------
    # 2. Familia Raw: cargar modelos ya entrenados (04_modelado.py, 03b)
    # ------------------------------------------------------------------
    print("\n  [Familia B – ML sin restricciones (Raw)] Cargando modelos ya calibrados...")
    modelo_xgb_raw = joblib.load(MODELOS_PATH / "modelo_xgboost.joblib")
    modelo_rf_raw  = joblib.load(MODELOS_PATH / "modelo_random_forest.joblib")
    modelo_orig_raw = joblib.load(MODELOS_PATH / "modelo_pd_originacion.joblib")

    # ------------------------------------------------------------------
    # 3. Evaluación conjunta sobre test (2024, out-of-time)
    # ------------------------------------------------------------------
    test = dataset[dataset["vintage_year"].isin(AÑOS_TEST)].copy()
    y_test = test[TARGET].astype(int).to_numpy()
    plazo_residual = (test["original_loan_term"] - test["loan_age"]).clip(lower=1).to_numpy()
    dpd_test = test["dpd_numerico"].to_numpy()
    ead_test = test["current_actual_upb"].fillna(0).to_numpy()

    Xtest_woe_full = woe.transform(test[features])
    Xtest_woe_orig = woe_orig.transform(test[features_orig])
    Xtest_raw_full = test[features]
    Xtest_raw_orig = test[features_orig]

    lgd_pol = pd.read_csv(TABLAS_PATH / "lgd_politica_perdida_total.csv")
    lgd_ponderada = float(
        lgd_pol.loc[lgd_pol["parametro"] == "LGD ponderada por exposición", "valor"].iloc[0]
    )
    lgd_downturn = min(lgd_ponderada + LGD_DOWNTURN_ADDON, LGD_MAX)
    print(f"\n  LGD downturn aplicada al ECL comparativo: {lgd_downturn:.2%} "
          f"(ponderada {lgd_ponderada:.2%} + add-on {LGD_DOWNTURN_ADDON:.0%})")

    especificaciones = [
        ("LR_WoE",  modelos_woe["LR_WoE"], Xtest_woe_full, modelo_orig_woe, Xtest_woe_orig),
        ("XGB_WoE", modelos_woe["XGB_WoE"], Xtest_woe_full, modelo_orig_woe, Xtest_woe_orig),
        ("RF_WoE",  modelos_woe["RF_WoE"], Xtest_woe_full, modelo_orig_woe, Xtest_woe_orig),
        ("XGB_Raw_Calibrado", modelo_xgb_raw, Xtest_raw_full, modelo_orig_raw, Xtest_raw_orig),
        ("RF_Raw_Calibrado",  modelo_rf_raw,  Xtest_raw_full, modelo_orig_raw, Xtest_raw_orig),
    ]

    filas_metricas, filas_sicr, curvas_roc = [], [], {}
    for nombre, modelo, X_current, modelo_orig, X_orig in especificaciones:
        pd_current = modelo.predict_proba(X_current)[:, 1]
        pd_orig    = modelo_orig.predict_proba(X_orig)[:, 1]

        met = metricas_discriminacion(y_test, pd_current)
        oe = float(pd_current.mean() / y_test.mean())
        filas_metricas.append({
            "modelo": nombre, **{k: round(v, 4) for k, v in met.items()},
            "PD_media_predicha": round(float(pd_current.mean()), 6),
            "tasa_default_observada": round(float(y_test.mean()), 6),
            "ratio_O_E": round(oe, 3),
        })
        fpr, tpr, _ = roc_curve(y_test, pd_current)
        curvas_roc[nombre] = (fpr, tpr, met["AUC"])

        filas_sicr.append(evaluar_modelo_sicr(
            nombre, pd_current, pd_orig, plazo_residual, dpd_test, y_test,
            ead_test, lgd_downturn,
        ))
        print(f"  [{nombre:20s}] AUC={met['AUC']:.4f} Gini={met['Gini']:.4f} "
              f"KS={met['KS']:.4f} Brier={met['Brier']:.4f} O/E={oe:.3f}")

    df_metricas = pd.DataFrame(filas_metricas)
    df_sicr = pd.DataFrame(filas_sicr)
    df_ecl = df_sicr[["modelo", "pct_stage2", "ecl_total_usd", "ead_total_usd",
                      "ecl_sobre_ead_bps"]].copy()
    df_ecl["ecl_relativo_vs_min"] = (
        df_ecl["ecl_total_usd"] / df_ecl["ecl_total_usd"].min()
    ).round(3)

    print("\n  === Comparación de discriminación y calibración (test 2024) ===")
    print(df_metricas.to_string(index=False))
    print("\n  === Migración a Stage 2 (SICR) y falsos positivos por modelo ===")
    print(df_sicr.to_string(index=False))
    print("\n  === Provisión de ECL de cartera bajo la propia clasificación de cada modelo ===")
    print(df_ecl.to_string(index=False))

    df_metricas.to_csv(TABLAS_PATH / "comparacion_woe_vs_raw_metricas.csv", index=False)
    df_sicr.to_csv(TABLAS_PATH / "comparacion_woe_vs_raw_sicr.csv", index=False)
    df_ecl.to_csv(TABLAS_PATH / "comparacion_woe_vs_raw_ecl.csv", index=False)
    print("\n  Tablas guardadas: comparacion_woe_vs_raw_{metricas,sicr,ecl}.csv")

    # ------------------------------------------------------------------
    # 4. Figuras
    # ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    colores = {"LR_WoE": "#2166ac", "XGB_WoE": "#4393c3", "RF_WoE": "#92c5de",
              "XGB_Raw_Calibrado": "#d6604d", "RF_Raw_Calibrado": "#b2182b"}
    for nombre, (fpr, tpr, auc_v) in curvas_roc.items():
        ax.plot(fpr, tpr, label=f"{nombre} (AUC={auc_v:.4f})",
                color=colores.get(nombre), linewidth=2)
    ax.plot([0, 1], [0, 1], "k--", linewidth=1, label="Aleatorio")
    ax.set_xlabel("Tasa de Falsos Positivos (FPR)")
    ax.set_ylabel("Tasa de Verdaderos Positivos (TPR)")
    ax.set_title("Curva ROC – Scorecard WoE vs. ML sin restricciones (test 2024)")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "woe_vs_raw_roc.png", dpi=150, bbox_inches="tight")
    plt.close()

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    orden = df_ecl.sort_values("ecl_sobre_ead_bps")
    axes[0].barh(orden["modelo"], orden["ecl_sobre_ead_bps"],
                color=[colores.get(m) for m in orden["modelo"]])
    axes[0].set_xlabel("ECL / EAD (puntos básicos)")
    axes[0].set_title("Provisión de ECL de cartera por modelo\n(bajo su propia clasificación de stage)")
    axes[0].grid(True, axis="x", alpha=0.3)

    orden2 = df_sicr.sort_values("pct_stage2")
    axes[1].barh(orden2["modelo"], orden2["pct_stage2"] * 100,
                color=[colores.get(m) for m in orden2["modelo"]])
    axes[1].set_xlabel("% de la cartera en Stage 2")
    axes[1].set_title("Tasa de migración a Stage 2 (SICR) por modelo")
    axes[1].grid(True, axis="x", alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "woe_vs_raw_ecl_provisiones.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Figuras guardadas: woe_vs_raw_roc.png, woe_vs_raw_ecl_provisiones.png")

    print("\nPaso 9 completado.\n")
    return df_metricas, df_sicr, df_ecl


if __name__ == "__main__":
    main()
