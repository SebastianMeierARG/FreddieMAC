"""
03b_sicr_assessment.py – Evaluación de SICR basada en PD (IFRS 9 5.5.9)
=========================================================================
Implementa la clasificación de Significant Increase in Credit Risk (SICR)
comparando la PD corriente contra la PD estimada en originación.

Marco regulatorio:
  IFRS 9 5.5.9: el criterio primario de SICR es el incremento relativo de la
  Lifetime PD, no el umbral DPD (que es solo un backstop – párrafo 5.5.11).
  EBA GL 135-138: el backstop 30 DPD no debe ser el indicador principal de SICR.

Metodología:
  1. Entrenar una Regresión Logística sobre variables de originación (train set)
     para estimar la PD al momento de concesión del préstamo (pd_origination).
  2. Obtener la PD corriente (pd_current) del modelo XGBoost ya entrenado (paso 04).
  3. Clasificar SICR si se cumple alguna de las siguientes condiciones:
       pd_current / pd_origination > SICR_RELATIVE_THRESHOLD  (2.5x), O
       pd_current - pd_origination > SICR_ABSOLUTE_THRESHOLD  (0.5pp), O
       dpd_numerico >= 1  (backstop 30 DPD per IFRS 9 5.5.11)
  4. Actualizar ifrs9_stage en dataset_modelado.parquet:
       Stage 1 → NOT sicr_pd_flag AND NOT en_default
       Stage 2 → sicr_pd_flag AND NOT en_default
       Stage 3 → en_default

Este paso debe ejecutarse DESPUÉS del paso 04 (necesita el modelo XGBoost).

Entrada  : data/dataset_modelado.parquet
           outputs/modelos/modelo_xgboost.joblib
           outputs/modelos/features_lista.joblib
Salida   : data/dataset_modelado.parquet  (columnas añadidas: pd_origination,
           pd_current, sicr_pd_flag, ifrs9_stage_sicr)
           outputs/modelos/modelo_pd_originacion.joblib
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
    DATASET_MOD_PARQUET, MODELOS_PATH,
    FEATURES_ORIGINACION, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION,
    SICR_RELATIVE_THRESHOLD, SICR_ABSOLUTE_THRESHOLD,
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
    features_orig = [f for f in FEATURES_ORIGINACION if f in dataset.columns]
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


def main():
    print("=" * 60)
    print("PASO 3b – SICR basado en PD (IFRS 9 5.5.9)")
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

    # --- 3. SICR flag ---
    pd_ratio = dataset["pd_current"] / dataset["pd_origination"].replace(0, np.nan)
    pd_diff  = dataset["pd_current"] - dataset["pd_origination"]
    backstop = dataset["dpd_numerico"] >= 1

    dataset["sicr_pd_flag"] = (
        (pd_ratio > SICR_RELATIVE_THRESHOLD) |
        (pd_diff  > SICR_ABSOLUTE_THRESHOLD) |
        backstop
    ).fillna(False).astype("Int8")

    # --- 4. Stages actualizados con SICR PD (nuevo campo, no sobreescribe el original) ---
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
    print(f"\n  Stage 1(DPD) → Stage 2(PD-SICR): {reclasif_1a2:,} obs")
    print(f"  Stage 2(DPD) → Stage 1(PD-SICR): {reclasif_2a1:,} obs")

    pd_stats = dataset[["pd_origination", "pd_current"]].describe().round(6)
    print(f"\n  PD media en originación: {dataset['pd_origination'].mean():.4%}")
    print(f"  PD media corriente:      {dataset['pd_current'].mean():.4%}")

    dataset.to_parquet(DATASET_MOD_PARQUET, index=False)
    print(f"\nDataset actualizado guardado en: {DATASET_MOD_PARQUET}")
    print("Paso 3b completado.\n")
    return dataset


if __name__ == "__main__":
    main()
