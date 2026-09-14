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

Decisiones metodológicas (ver config.py):
  - Los modelos operan sobre variables relativas a la cohorte de originación en
    lugar de niveles absolutos (tasas, UPB), que no son estacionarios entre
    vintages y anulan la capacidad de extrapolación de los modelos de árboles.
  - XGBoost incorpora restricciones de monotonía sobre los drivers de riesgo
    (EBA GL/2017/16 §5.3.1: plausibilidad económica).
  - El número de árboles se fija por early stopping sobre un holdout temporal
    INTERNO al set de entrenamiento (vintage 2020). Validación y test nunca
    intervienen en el ajuste.
  - La Regresión Logística aplica OneHotEncoder sobre las categóricas: sus
    códigos enteros no admiten lectura ordinal.

Entrada  : data/dataset_modelado.parquet
Salida   : outputs/modelos/  (archivos .joblib por modelo)
           outputs/tablas/resultados_modelos.csv
"""

import joblib
import warnings

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from xgboost import XGBClassifier

from config import (
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH,
    FEATURES_MODELO, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST,
    MONOTONE_CONSTRAINTS, XGB_PARAMS, XGB_MAX_ESTIMATORS, XGB_EARLY_STOPPING,
    AÑO_EARLY_STOPPING, RF_PARAMS, MAX_TRAIN_OBS,
)

warnings.filterwarnings("ignore")

# Categóricas label-encoded en el paso 03: requieren one-hot para modelos lineales
CATEGORICAS = ["loan_purpose", "property_type", "occupancy_status", "channel"]


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
    Retorna (X_train, y_train, X_val, y_val, X_test, y_test, features, vintage_train).
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
    vintage_train    = train["vintage_year"]

    return (X_train, y_train, X_val, y_val, X_test, y_test,
            features_disp, vintage_train)


# ---------------------------------------------------------------------------
# Definición de pipelines
# ---------------------------------------------------------------------------

def pipeline_logistica(features: list) -> Pipeline:
    """
    Pipeline de Regresión Logística:
      1. Categóricas → imputación por moda + OneHotEncoder
      2. Numéricas   → imputación por mediana + estandarización
      3. Regresión Logística con regularización L2 (C=0.1)

    El parámetro class_weight='balanced' compensa el desbalance de clases
    (típico en crédito: pocos defaults vs. muchos pagadores).
    """
    categoricas = [c for c in CATEGORICAS if c in features]
    numericas   = [c for c in features if c not in categoricas]

    preproceso = ColumnTransformer([
        ("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler",  StandardScaler()),
        ]), numericas),
        ("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot",  OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), categoricas),
    ])

    return Pipeline([
        ("preproceso", preproceso),
        ("modelo",  LogisticRegression(
            C=0.1,
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )),
    ])


def restricciones_monotonas(features: list) -> str:
    """
    Traduce MONOTONE_CONSTRAINTS al formato de tupla que espera XGBoost,
    alineado con el orden de las columnas del dataset.
    """
    return "(" + ",".join(str(MONOTONE_CONSTRAINTS.get(f, 0)) for f in features) + ")"


def pipeline_xgboost(features: list, n_estimators: int) -> Pipeline:
    """
    Pipeline de XGBoost:
      1. Imputación de NaN con -999 (XGBoost puede aprender de valores faltantes)
      2. XGBClassifier con restricciones de monotonía sobre los drivers de riesgo

    No se aplica scale_pos_weight: el re-pesado de clases distorsiona el nivel
    de las probabilidades, que bajo IFRS 9 debe ser interpretable como PD.
    El desbalance se corrige por calibración isotónica posterior.
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="constant", fill_value=-999)),
        ("modelo",  XGBClassifier(
            n_estimators=n_estimators,
            monotone_constraints=restricciones_monotonas(features),
            objective="binary:logistic",
            eval_metric="auc",
            random_state=42,
            n_jobs=-1,
            verbosity=0,
            **XGB_PARAMS,
        )),
    ])


def pipeline_random_forest(features: list) -> Pipeline:
    """
    Pipeline de Random Forest:
      1. Imputación de NaN con la mediana
      2. RandomForestClassifier con class_weight='balanced'
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("modelo",  RandomForestClassifier(
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
            **RF_PARAMS,
        )),
    ])


# ---------------------------------------------------------------------------
# Early stopping sobre holdout temporal interno al entrenamiento
# ---------------------------------------------------------------------------

def calibrar_n_arboles(X_train, y_train, vintage_train, features: list) -> int:
    """
    Determina el número óptimo de árboles de XGBoost por early stopping usando
    el último vintage del conjunto de entrenamiento (AÑO_EARLY_STOPPING) como
    holdout temporal interno.

    Ni validación ni test intervienen, de modo que la partición out-of-time
    permanece libre de contaminación (EBA GL/2017/16 §8.2).
    """
    mask_es  = (vintage_train == AÑO_EARLY_STOPPING).to_numpy()
    mask_fit = ~mask_es

    imputer = SimpleImputer(strategy="constant", fill_value=-999)
    X_fit = imputer.fit_transform(X_train[mask_fit])
    X_es  = imputer.transform(X_train[mask_es])

    modelo = XGBClassifier(
        n_estimators=XGB_MAX_ESTIMATORS,
        early_stopping_rounds=XGB_EARLY_STOPPING,
        monotone_constraints=restricciones_monotonas(features),
        objective="binary:logistic",
        eval_metric="auc",
        random_state=42,
        n_jobs=-1,
        verbosity=0,
        **XGB_PARAMS,
    )
    modelo.fit(X_fit, y_train[mask_fit],
               eval_set=[(X_es, y_train[mask_es])], verbose=False)

    n_optimo = max(int(modelo.best_iteration) + 1, 50)
    print(f"  Early stopping (holdout interno vintage {AÑO_EARLY_STOPPING}): "
          f"{n_optimo} árboles | AUC holdout = {modelo.best_score:.4f}")
    return n_optimo


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

    columnas = list(FEATURES_MODELO) + [TARGET, "vintage_year"]
    disponibles = pq.read_schema(DATASET_MOD_PARQUET).names
    dataset = pd.read_parquet(
        DATASET_MOD_PARQUET, columns=[c for c in columnas if c in disponibles]
    )
    print(f"Dataset cargado: {len(dataset):,} filas\n")

    (X_train, y_train, X_val, y_val, X_test, y_test,
     features, vintage_train) = preparar_particiones(dataset)

    # Ratio de desbalance (referencia descriptiva)
    n_pos = y_train.sum()
    n_neg = len(y_train) - n_pos
    print(f"\n  Ratio de desbalance (neg/pos): {n_neg / n_pos:.1f}x")

    # Subsampleo del conjunto de entrenamiento para evitar OOM en máquinas con
    # poca RAM. 1.000.000 de observaciones con la tasa de default observada
    # (~1.3%) entrega ~13.000 eventos: suficiente para modelos robustos.
    n_train_original = len(X_train)
    if n_train_original > MAX_TRAIN_OBS:
        idx = np.random.RandomState(42).choice(
            n_train_original, MAX_TRAIN_OBS, replace=False
        )
        X_train       = X_train.iloc[idx]
        y_train       = y_train.iloc[idx]
        vintage_train = vintage_train.iloc[idx]
        print(f"  Submuestreo entrenamiento: {MAX_TRAIN_OBS:,} obs "
              f"(de {n_train_original:,})")

    # Número de árboles de XGBoost por early stopping temporal interno
    print()
    n_arboles = calibrar_n_arboles(X_train, y_train, vintage_train, features)

    # Definir modelos
    modelos = {
        "Logistica":     pipeline_logistica(features),
        "XGBoost":       pipeline_xgboost(features, n_arboles),
        "Random_Forest": pipeline_random_forest(features),
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
