"""
04_modelado.py – Entrenamiento de modelos de Probabilidad de Default
======================================================================
Entrena y compara tres modelos bajo el enfoque IFRS 9 PIT (Point-In-Time):

  1. Regresión Logística  → modelo regulatorio de referencia (interpretable)
  2. XGBoost              → modelo principal (alta performance)
  3. Random Forest        → ensemble alternativo

Partición temporal (out-of-time):
  - Entrenamiento : vintages 2016–2020
  - Validación    : vintages 2022–2023
  - Test          : vintage  2024

Nota: el vintage 2021 no existe en el dataset Freddie Mac descargado.

Entrada  : data/dataset_modelado.parquet
Salida   : outputs/modelos/  (archivos .joblib por modelo)
           outputs/tablas/resultados_modelos.csv
"""

import joblib
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from config import (
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH,
    FEATURES_MODELO, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST,
)

warnings.filterwarnings("ignore")


class ModeloCalibraado:
    """Pipeline + calibrador isotónico, serializable con joblib."""
    def __init__(self, base_pipeline, calibrador_iso):
        self._base  = base_pipeline
        self._calib = calibrador_iso

    def predict_proba(self, X):
        raw = self._base.predict_proba(X)[:, 1]
        cal = self._calib.predict(raw)
        return np.column_stack([1 - cal, cal])


# ---------------------------------------------------------------------------
# Función de utilidad: métricas básicas
# ---------------------------------------------------------------------------

def calcular_metricas(y_true, y_prob, nombre: str) -> dict:
    """Calcula AUC, Gini y Brier Score para un conjunto de predicciones."""
    auc    = roc_auc_score(y_true, y_prob)
    gini   = 2 * auc - 1
    brier  = brier_score_loss(y_true, y_prob)
    pos    = y_true.sum()
    neg    = len(y_true) - pos
    return {
        "modelo":    nombre,
        "AUC":       round(auc,   4),
        "Gini":      round(gini,  4),
        "Brier":     round(brier, 4),
        "defaults":  int(pos),
        "no_def":    int(neg),
        "tasa_def":  round(pos / len(y_true), 4),
    }


# ---------------------------------------------------------------------------
# Preparación de datos
# ---------------------------------------------------------------------------

def preparar_particiones(dataset: pd.DataFrame):
    """
    Divide el dataset en entrenamiento, validación y test usando
    la variable vintage_year (partición temporal out-of-time).
    Retorna (X_train, y_train, X_val, y_val, X_test, y_test).
    """
    # Usar solo features que existen en el dataset
    features_disp = [f for f in FEATURES_MODELO if f in dataset.columns]
    faltantes = set(FEATURES_MODELO) - set(features_disp)
    if faltantes:
        print(f"  ADVERTENCIA: features no disponibles (ignoradas): {faltantes}")

    train = dataset[dataset["vintage_year"].isin(AÑOS_ENTRENAMIENTO)]
    val   = dataset[dataset["vintage_year"].isin(AÑOS_VALIDACION)]
    test  = dataset[dataset["vintage_year"].isin(AÑOS_TEST)]

    print(f"  Entrenamiento : {len(train):>10,} obs | "
          f"tasa default = {train[TARGET].mean():.4%}")
    print(f"  Validación    : {len(val):>10,} obs | "
          f"tasa default = {val[TARGET].mean():.4%}")
    print(f"  Test          : {len(test):>10,} obs | "
          f"tasa default = {test[TARGET].mean():.4%}")

    X_train, y_train = train[features_disp], train[TARGET].astype(int)
    X_val,   y_val   = val[features_disp],   val[TARGET].astype(int)
    X_test,  y_test  = test[features_disp],  test[TARGET].astype(int)

    return X_train, y_train, X_val, y_val, X_test, y_test, features_disp


# ---------------------------------------------------------------------------
# Definición de pipelines
# ---------------------------------------------------------------------------

def pipeline_logistica(scale_pos_weight: float) -> Pipeline:
    """
    Pipeline de Regresión Logística:
      1. Imputación de NaN con la mediana (robusto a outliers)
      2. Estandarización de variables (necesario para LR)
      3. Regresión Logística con regularización L2 (C=0.1)

    El parámetro class_weight='balanced' compensa el desbalance de clases
    (típico en crédito: pocos defaults vs. muchos pagadores).
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("modelo",  LogisticRegression(
            C=0.1,
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )),
    ])


def pipeline_xgboost(scale_pos_weight: float) -> Pipeline:
    """
    Pipeline de XGBoost:
      1. Imputación de NaN con -999 (XGBoost puede aprender de valores faltantes)
      2. XGBClassifier con scale_pos_weight para manejar desbalance

    scale_pos_weight = n_negativos / n_positivos (ratio de clases).
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value=-999)),
        ("modelo",  XGBClassifier(
            n_estimators=500,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos_weight,
            objective="binary:logistic",
            eval_metric="auc",
            use_label_encoder=False,
            random_state=42,
            n_jobs=-1,
            verbosity=0,
        )),
    ])


def pipeline_random_forest(scale_pos_weight: float) -> Pipeline:
    """
    Pipeline de Random Forest:
      1. Imputación de NaN con la mediana
      2. RandomForestClassifier con class_weight='balanced'
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("modelo",  RandomForestClassifier(
            n_estimators=300,
            max_depth=10,
            min_samples_leaf=50,    # evita sobreajuste en datos muy desbalanceados
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )),
    ])


# ---------------------------------------------------------------------------
# Entrenamiento y evaluación
# ---------------------------------------------------------------------------

def entrenar_evaluar(nombre, pipeline, X_train, y_train,
                     X_val, y_val, X_test, y_test) -> dict:
    """
    Entrena un pipeline, evalúa en validación y test, guarda el modelo.
    Retorna diccionario con métricas para el reporte comparativo.
    """
    print(f"\n  [{nombre}] Entrenando...")
    pipeline.fit(X_train, y_train)

    # Calibración isotónica en el conjunto de validación
    # (sklearn >= 1.2 ya no acepta cv="prefit" en CalibratedClassifierCV)
    raw_proba_val  = pipeline.predict_proba(X_val)[:, 1]
    calibrador_iso = IsotonicRegression(out_of_bounds="clip")
    calibrador_iso.fit(raw_proba_val, y_val)
    calibrado = ModeloCalibraado(pipeline, calibrador_iso)

    # Predicciones
    prob_val  = calibrado.predict_proba(X_val)[:, 1]
    prob_test = calibrado.predict_proba(X_test)[:, 1]

    met_val  = calcular_metricas(y_val,  prob_val,  nombre)
    met_test = calcular_metricas(y_test, prob_test, nombre)

    print(f"    Validación : AUC={met_val['AUC']:.4f} | "
          f"Gini={met_val['Gini']:.4f} | Brier={met_val['Brier']:.4f}")
    print(f"    Test       : AUC={met_test['AUC']:.4f} | "
          f"Gini={met_test['Gini']:.4f} | Brier={met_test['Brier']:.4f}")

    # Guardar modelo calibrado
    ruta = MODELOS_PATH / f"modelo_{nombre.lower().replace(' ', '_')}.joblib"
    joblib.dump(calibrado, ruta)
    print(f"    Guardado: {ruta.name}")

    return {"validacion": met_val, "test": met_test}


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 4 – Entrenamiento de modelos PD")
    print("=" * 60)

    dataset = pd.read_parquet(DATASET_MOD_PARQUET)
    print(f"Dataset cargado: {len(dataset):,} filas\n")

    X_train, y_train, X_val, y_val, X_test, y_test, features = \
        preparar_particiones(dataset)

    # Ratio de desbalance (para XGBoost y referencia)
    n_pos = y_train.sum()
    n_neg = len(y_train) - n_pos
    ratio = n_neg / n_pos
    print(f"\n  Ratio de desbalance (neg/pos): {ratio:.1f}x")

    # Subsampleo del conjunto de entrenamiento para evitar OOM en máquinas con
    # poca RAM. 1.000.000 de observaciones con la tasa de default observada
    # (~1.3%) entrega ~13.000 eventos: suficiente para modelos robustos.
    # (El dataset completo de 11.5M filas requeriría ~2.2 GB en float64.)
    MAX_TRAIN = 1_000_000
    if len(X_train) > MAX_TRAIN:
        idx = np.random.RandomState(42).choice(len(X_train), MAX_TRAIN, replace=False)
        X_train = X_train.iloc[idx]
        y_train = y_train.iloc[idx]
        print(f"  Submuestreo entrenamiento: {MAX_TRAIN:,} obs (de {len(y_train)+MAX_TRAIN:,})")

    # Definir modelos
    modelos = {
        "Logistica":     pipeline_logistica(ratio),
        "XGBoost":       pipeline_xgboost(ratio),
        "Random_Forest": pipeline_random_forest(ratio),
    }

    resultados = []
    for nombre, pipe in modelos.items():
        metricas = entrenar_evaluar(
            nombre, pipe,
            X_train, y_train,
            X_val,   y_val,
            X_test,  y_test,
        )
        resultados.append({
            "Modelo":         nombre,
            "AUC_val":        metricas["validacion"]["AUC"],
            "Gini_val":       metricas["validacion"]["Gini"],
            "Brier_val":      metricas["validacion"]["Brier"],
            "AUC_test":       metricas["test"]["AUC"],
            "Gini_test":      metricas["test"]["Gini"],
            "Brier_test":     metricas["test"]["Brier"],
        })

    # Tabla comparativa
    df_res = pd.DataFrame(resultados).set_index("Modelo")
    print("\n  === RESUMEN COMPARATIVO ===")
    print(df_res.to_string())

    ruta_tabla = TABLAS_PATH / "resultados_modelos.csv"
    df_res.to_csv(ruta_tabla)
    print(f"\nTabla guardada en: {ruta_tabla}")
    print("Paso 4 completado.\n")

    # Guardar también la lista de features para uso posterior
    joblib.dump(features, MODELOS_PATH / "features_lista.joblib")

    return df_res


if __name__ == "__main__":
    main()
