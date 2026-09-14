"""
03b_sicr_assessment.py – Evaluación de SICR basada en PD (IFRS 9 5.5.9)
=========================================================================
Implementa la clasificación de Significant Increase in Credit Risk (SICR)
comparando la Lifetime PD corriente contra la Lifetime PD estimada en la
originación para el mismo horizonte residual.

Marco regulatorio
-----------------
IFRS 9 5.5.9: el criterio primario de SICR es el incremento significativo del
riesgo de default a lo largo de la vida esperada del instrumento, evaluado
comparando el riesgo a la fecha de reporte contra el riesgo estimado en el
reconocimiento inicial.
IFRS 9 5.5.11: los 30 días de mora son una presunción refutable, es decir, un
BACKSTOP prudencial y no el indicador primario.
EBA GL/2017/16 §5.5 (135-138): el backstop de 30 DPD no debe emplearse como
indicador principal de SICR; la entidad debe disponer de indicadores basados en
PD que detecten el deterioro con anterioridad.

Formulación del umbral (Control 11.3)
-------------------------------------
Se declara SICR cuando se verifica cualquiera de las tres condiciones:

  (1) Criterio relativo (primario)
          PD_lifetime_t / PD_lifetime_orig  ≥  k        con k = SICR_RELATIVE_THRESHOLD

  (2) Criterio absoluto (complementario, para PD de originación muy bajas,
      donde el cociente relativo se dispara sin relevancia económica)
          PD_lifetime_t − PD_lifetime_orig  ≥  Δ        con Δ = SICR_ABSOLUTE_THRESHOLD

  (3) Backstop prudencial (refuerzo cualitativo, IFRS 9 5.5.11)
          DPD ≥ SICR_BACKSTOP_DPD  (bucket 1 = 30 días)

Ambas Lifetime PD se calculan sobre el MISMO horizonte residual T_res mediante
extrapolación de hazard constante a partir de la PD a 12 meses:

    PD_lifetime = 1 − (1 − PD_12m)^(T_res / 12)

de modo que la comparación es homogénea y la condición (1) resulta invariante
frente a la duración residual del contrato.

El valor de k se calibra empíricamente: el módulo reporta, para una grilla de
umbrales, la proporción de cartera en Stage 2, la tasa de default observada de
ese Stage 2 y la cobertura de los defaults futuros (sensibilidad del disparador),
junto con la contribución marginal del backstop de 30 DPD.

Metodología
-----------
  1. Entrenar una Regresión Logística sobre variables disponibles en la
     concesión (train set) para estimar la PD de originación.
  2. Obtener la PD corriente del modelo XGBoost ya entrenado (paso 04).
  3. Convertir ambas a Lifetime PD sobre el horizonte residual.
  4. Clasificar SICR y actualizar el stage.

Este paso debe ejecutarse DESPUÉS del paso 04 (necesita el modelo XGBoost).

Entrada  : data/dataset_modelado.parquet
           outputs/modelos/modelo_xgboost.joblib
           outputs/modelos/features_lista.joblib
Salida   : data/dataset_modelado.parquet  (columnas añadidas: pd_origination,
           pd_current, pd_lifetime_orig, pd_lifetime_current, sicr_ratio,
           sicr_pd_flag, ifrs9_stage_sicr)
           outputs/modelos/modelo_pd_originacion.joblib
           outputs/tablas/sicr_umbral_calibracion.csv
           outputs/tablas/sicr_resumen.csv
"""

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import (
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH,
    FEATURES_ORIGINACION_EXT, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION,
    SICR_RELATIVE_THRESHOLD, SICR_ABSOLUTE_THRESHOLD,
    SICR_BACKSTOP_DPD, SICR_GRID_K, SICR_GRID_DELTA, HORIZONTE_PD_MESES,
)

import sys as _sys, os as _os
_sys.path.insert(0, str(_os.path.dirname(__file__)))
from importlib import import_module as _im
_p04 = _im("04_modelado")
ModeloCalibraado = _p04.ModeloCalibraado  # noqa: F401


class _ModeloOrigCal:
    """Pipeline logístico + calibrador isotónico para PD de originación."""
    def __init__(self, pipeline: Pipeline, calibrador: IsotonicRegression):
        self._pipe  = pipeline
        self._calib = calibrador

    def predict_proba(self, X) -> np.ndarray:
        raw = self._pipe.predict_proba(X)[:, 1]
        cal = self._calib.predict(raw)
        return np.column_stack([1 - cal, cal])


def entrenar_modelo_originacion(dataset: pd.DataFrame) -> tuple:
    """
    Entrena un modelo simple de PD usando solo variables disponibles al momento
    de la originación del préstamo.
    Se calibra isotónicamente en el conjunto de validación para evitar data leakage.
    """
    features_orig = [f for f in FEATURES_ORIGINACION_EXT if f in dataset.columns]
    train = dataset[dataset["vintage_year"].isin(AÑOS_ENTRENAMIENTO)]
    val   = dataset[dataset["vintage_year"].isin(AÑOS_VALIDACION)]

    pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("model",   LogisticRegression(
            C=0.1, class_weight="balanced", max_iter=1000, random_state=42,
        )),
    ])
    pipe.fit(train[features_orig], train[TARGET].astype(int))

    raw_val   = pipe.predict_proba(val[features_orig])[:, 1]
    calibrador = IsotonicRegression(out_of_bounds="clip")
    calibrador.fit(raw_val, val[TARGET].astype(int))

    return _ModeloOrigCal(pipe, calibrador), features_orig


def a_lifetime(pd_12m: pd.Series, horizonte_meses: pd.Series) -> pd.Series:
    """
    Convierte una PD a 12 meses en Lifetime PD sobre el horizonte residual
    asumiendo hazard constante:

        PD_lifetime = 1 − (1 − PD_12m)^(T_res / 12)

    El supuesto de hazard constante es el más conservador disponible sin
    imponer una forma funcional a la curva de supervivencia, y garantiza que la
    comparación entre la PD corriente y la de originación se realice sobre el
    mismo horizonte temporal.
    """
    años = (horizonte_meses.clip(lower=1) / HORIZONTE_PD_MESES).astype("float32")
    return (1 - (1 - pd_12m.clip(0, 0.999999)) ** años).astype("float32")


def calibrar_umbral(dataset: pd.DataFrame) -> pd.DataFrame:
    """
    Sensibilidad conjunta de la clasificación en Stage 2 frente al umbral
    relativo k y al umbral absoluto delta (grilla cruzada completa).

    Para cada combinación (k, delta) se reporta:
      - proporción de cartera clasificada en Stage 2;
      - tasa de default a 12 meses observada dentro del Stage 2 (precisión);
      - proporción de los defaults futuros capturados por el disparador
        (sensibilidad / cobertura);
      - contribución marginal del backstop de 30 DPD, es decir, qué fracción de
        los Stage 2 se debe exclusivamente al backstop. Un valor alto indicaría
        que el criterio basado en PD no está detectando el deterioro con
        antelación, contrariamente a EBA GL/2017/16 §5.5;
      - participación del criterio relativo puro (rel_share): qué fracción del
        Stage 2 se explica por el ratio k y no por el delta absoluto. Un valor
        cercano a 0 indica que el umbral absoluto satura la clasificación y
        que el criterio relativo, pese a ser el primario según IFRS 9 5.5.9,
        no está aportando información adicional.
    """
    backstop = dataset["dpd_numerico"] >= SICR_BACKSTOP_DPD
    diff = dataset["pd_lifetime_current"] - dataset["pd_lifetime_orig"]
    total_def = dataset[TARGET].sum()

    filas = []
    for delta in SICR_GRID_DELTA:
        for k in SICR_GRID_K:
            crit_rel = dataset["sicr_ratio"] >= k
            crit_abs = diff >= delta
            criterio_pd = crit_rel | crit_abs
            flag = criterio_pd | backstop
            n_flag = int(flag.sum())
            solo_backstop = int((backstop & ~criterio_pd).sum())
            solo_relativo = int((crit_rel & ~crit_abs & ~backstop).sum())
            filas.append({
                "k_relativo":              k,
                "delta_absoluto":          delta,
                "pct_cartera_stage2":      round(n_flag / len(dataset), 4),
                "tasa_default_stage2":     round(float(dataset.loc[flag, TARGET].mean()), 6),
                "tasa_default_stage1":     round(float(dataset.loc[~flag, TARGET].mean()), 6),
                "cobertura_defaults":      round(float(dataset.loc[flag, TARGET].sum() / total_def), 4),
                "pct_solo_por_backstop":   round(solo_backstop / max(n_flag, 1), 4),
                "rel_share":               round(solo_relativo / max(n_flag, 1), 4),
                "lift_stage2_vs_stage1":   round(float(dataset.loc[flag, TARGET].mean()
                                                       / max(dataset.loc[~flag, TARGET].mean(), 1e-9)), 2),
            })
    return pd.DataFrame(filas)


def main():
    print("=" * 60)
    print("PASO 3b – SICR basado en Lifetime PD (IFRS 9 5.5.9)")
    print("=" * 60)

    dataset = pd.read_parquet(DATASET_MOD_PARQUET)
    print(f"Dataset cargado: {len(dataset):,} filas")

    # --- 1. Modelo de PD en originación ---
    print("\n  Entrenando modelo de PD en originación (Logistic Regression)...")
    modelo_orig, features_orig = entrenar_modelo_originacion(dataset)
    joblib.dump(modelo_orig, MODELOS_PATH / "modelo_pd_originacion.joblib")
    print(f"  Features de originación usadas: {len(features_orig)}")

    dataset["pd_origination"] = modelo_orig.predict_proba(
        dataset[features_orig]
    )[:, 1].astype("float32")

    # --- 2. PD corriente desde el modelo XGBoost ---
    print("  Cargando modelo XGBoost para PD corriente...")
    modelo_xgb   = joblib.load(MODELOS_PATH / "modelo_xgboost.joblib")
    features_xgb = joblib.load(MODELOS_PATH / "features_lista.joblib")
    feats_disp   = [f for f in features_xgb if f in dataset.columns]

    dataset["pd_current"] = modelo_xgb.predict_proba(
        dataset[feats_disp]
    )[:, 1].astype("float32")

    # --- 3. Conversión a Lifetime PD sobre el horizonte residual ---
    plazo_residual = (dataset["original_loan_term"] - dataset["loan_age"]).clip(lower=1)
    dataset["plazo_residual_meses"]  = plazo_residual.astype("int32")
    dataset["pd_lifetime_current"]   = a_lifetime(dataset["pd_current"], plazo_residual)
    dataset["pd_lifetime_orig"]      = a_lifetime(dataset["pd_origination"], plazo_residual)
    dataset["sicr_ratio"] = (
        dataset["pd_lifetime_current"]
        / dataset["pd_lifetime_orig"].replace(0, np.nan)
    ).astype("float32")

    # --- 4. SICR flag ---
    criterio_relativo = dataset["sicr_ratio"] >= SICR_RELATIVE_THRESHOLD
    criterio_absoluto = (
        dataset["pd_lifetime_current"] - dataset["pd_lifetime_orig"]
    ) >= SICR_ABSOLUTE_THRESHOLD
    backstop = dataset["dpd_numerico"] >= SICR_BACKSTOP_DPD

    dataset["sicr_pd_flag"] = (
        criterio_relativo | criterio_absoluto | backstop
    ).fillna(False).astype("Int8")

    # --- 5. Stages actualizados con SICR PD (nuevo campo, no sobreescribe el original) ---
    en_default = dataset["ifrs9_stage"] == 3
    stage_sicr = pd.Series(1, index=dataset.index, dtype="Int8")
    stage_sicr[dataset["sicr_pd_flag"] == 1] = 2
    stage_sicr[en_default] = 3
    dataset["ifrs9_stage_sicr"] = stage_sicr

    # --- Estadísticas ---
    print("\n  Comparación de clasificación de stages:")
    print("  [DPD-based]")
    for s, cnt in dataset["ifrs9_stage"].value_counts().sort_index().items():
        print(f"    Stage {s}: {cnt:>10,} ({cnt/len(dataset):.1%})")
    print("  [PD-based SICR]")
    for s, cnt in dataset["ifrs9_stage_sicr"].value_counts().sort_index().items():
        print(f"    Stage {s}: {cnt:>10,} ({cnt/len(dataset):.1%})")

    reclasif_1a2 = ((dataset["ifrs9_stage"] == 1) & (dataset["ifrs9_stage_sicr"] == 2)).sum()
    reclasif_2a1 = ((dataset["ifrs9_stage"] == 2) & (dataset["ifrs9_stage_sicr"] == 1)).sum()
    print(f"\n  Stage 1(DPD) -> Stage 2(PD-SICR): {reclasif_1a2:,} obs")
    print(f"  Stage 2(DPD) -> Stage 1(PD-SICR): {reclasif_2a1:,} obs")

    solo_backstop = int((backstop & ~(criterio_relativo | criterio_absoluto)).sum())
    n_stage2 = int((dataset["sicr_pd_flag"] == 1).sum())
    print(f"\n  Disparadores del SICR (umbral k={SICR_RELATIVE_THRESHOLD}, "
          f"delta={SICR_ABSOLUTE_THRESHOLD}):")
    print(f"    Criterio relativo  : {int(criterio_relativo.sum()):>10,}")
    print(f"    Criterio absoluto  : {int(criterio_absoluto.sum()):>10,}")
    print(f"    Backstop {SICR_BACKSTOP_DPD*30} DPD    : {int(backstop.sum()):>10,}")
    print(f"    Solo por backstop  : {solo_backstop:>10,} "
          f"({solo_backstop / max(n_stage2,1):.1%} del Stage 2)")

    print(f"\n  PD media en originación : {dataset['pd_origination'].mean():.4%}")
    print(f"  PD media corriente      : {dataset['pd_current'].mean():.4%}")
    print(f"  Lifetime PD originación : {dataset['pd_lifetime_orig'].mean():.4%}")
    print(f"  Lifetime PD corriente   : {dataset['pd_lifetime_current'].mean():.4%}")

    # --- 6. Calibración empírica del umbral ---
    print("\n  Calibración del umbral relativo k:")
    tabla_k = calibrar_umbral(dataset)
    print(tabla_k.to_string(index=False))
    tabla_k.to_csv(TABLAS_PATH / "sicr_umbral_calibracion.csv", index=False)

    resumen = pd.DataFrame([
        {"parametro": "Criterio primario",
         "valor": "PD_lifetime_t / PD_lifetime_orig ≥ k (mismo horizonte residual)",
         "referencia": "IFRS 9 5.5.9"},
        {"parametro": "Umbral relativo k", "valor": SICR_RELATIVE_THRESHOLD,
         "referencia": "Calibrado empíricamente (ver sicr_umbral_calibracion.csv)"},
        {"parametro": "Umbral absoluto Δ", "valor": SICR_ABSOLUTE_THRESHOLD,
         "referencia": "Complemento para PD de originación muy bajas"},
        {"parametro": "Backstop", "valor": f"{SICR_BACKSTOP_DPD*30} DPD",
         "referencia": "IFRS 9 5.5.11 – presunción refutable, uso estrictamente prudencial"},
        {"parametro": "Conversión a lifetime",
         "valor": "1 − (1 − PD_12m)^(T_res/12)  (hazard constante)",
         "referencia": "Horizonte homogéneo para ambas PD"},
        {"parametro": "% cartera en Stage 2 (SICR PD)",
         "valor": round(n_stage2 / len(dataset), 4), "referencia": "Resultado"},
        {"parametro": "% del Stage 2 activado solo por el backstop",
         "valor": round(solo_backstop / max(n_stage2, 1), 4),
         "referencia": "EBA GL/2017/16 §5.5 – debe ser minoritario"},
    ])
    resumen.to_csv(TABLAS_PATH / "sicr_resumen.csv", index=False)
    print("\n  Tablas guardadas: sicr_umbral_calibracion.csv, sicr_resumen.csv")

    dataset.to_parquet(DATASET_MOD_PARQUET, index=False)
    print(f"\nDataset actualizado guardado en: {DATASET_MOD_PARQUET}")
    print("Paso 3b completado.\n")
    return dataset


if __name__ == "__main__":
    main()
