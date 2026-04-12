"""
07_explicabilidad.py – Explicabilidad del modelo PD (SHAP + Importancia)
=========================================================================
Genera análisis de interpretabilidad en dos niveles, según exige la norma
IFRS 9 (EBA Guidelines on model governance, 2022):

  Nivel GLOBAL (comportamiento del modelo en toda la cartera):
    - Importancia por Gain (XGBoost nativa)
    - Importancia por Permutación
    - SHAP Summary Plot (beeswarm): efecto y magnitud de cada variable
    - SHAP Bar Plot: importancia media |SHAP|

  Nivel LOCAL (explicación de un préstamo individual):
    - SHAP Waterfall Plot: contribución de cada variable a la PD del préstamo
    - SHAP Force Plot: visualización compacta (exportable a HTML)

  Comparación entre modelos:
    - Top-10 variables más importantes por modelo

Entrada  : data/dataset_modelado.parquet, outputs/modelos/
Salida   : outputs/figuras/shap_*.png, outputs/tablas/importancia_*.csv
"""

import warnings

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap

from config import (
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH, FIGURAS_PATH,
    FEATURES_MODELO, TARGET,
    AÑOS_TEST,
)
import sys as _sys, os as _os
_sys.path.insert(0, str(_os.path.dirname(__file__)))
from importlib import import_module as _im
_p04 = _im("04_modelado")
ModeloCalibraado = _p04.ModeloCalibraado  # noqa: F401

warnings.filterwarnings("ignore")
plt.rcParams.update({"font.family": "serif", "font.size": 11})

# Tamaño de muestra para SHAP (calcular SHAP para todo el test puede ser lento)
N_MUESTRA_SHAP = 5_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def preparar_muestra_test(dataset: pd.DataFrame, features: list,
                          n: int = N_MUESTRA_SHAP) -> pd.DataFrame:
    """
    Toma una muestra estratificada del conjunto test para el análisis SHAP.
    Estratifica por variable objetivo para mantener la proporción de defaults.
    """
    test = dataset[dataset["vintage_year"].isin(AÑOS_TEST)].copy()
    features_disp = [f for f in features if f in test.columns]
    X_test = test[features_disp]

    if len(X_test) > n:
        # Muestra estratificada por target
        X_test = (
            test.groupby(TARGET, group_keys=False)
            .apply(lambda g: g.sample(
                min(len(g), int(n * len(g) / len(test))), random_state=42
            ))
        )[features_disp]

    return X_test


# ---------------------------------------------------------------------------
# SHAP para XGBoost (TreeExplainer – rápido)
# ---------------------------------------------------------------------------

def analisis_shap_xgboost(modelo_calibrado, X_muestra: pd.DataFrame) -> None:
    """
    Calcula y grafica SHAP values para el modelo XGBoost.
    Usa TreeExplainer (exacto, eficiente para modelos de árbol).
    """
    print("  Calculando SHAP values (XGBoost)...")

    # Extraer el XGBClassifier del pipeline base (ModeloCalibraado._base es un Pipeline)
    try:
        pipeline_base = getattr(modelo_calibrado, "_base", modelo_calibrado)
        xgb_model = pipeline_base.named_steps["modelo"]
        imputer   = pipeline_base.named_steps["imputer"]
        X_imp = pd.DataFrame(
            imputer.transform(X_muestra),
            columns=X_muestra.columns,
        )
    except (AttributeError, KeyError) as e:
        print(f"  No se pudo extraer el modelo XGBoost interno: {e}")
        return

    explainer = shap.TreeExplainer(xgb_model)
    shap_values = explainer.shap_values(X_imp)

    # 1. Summary plot (beeswarm) – efecto y dirección de cada variable
    plt.figure(figsize=(10, 8))
    shap.summary_plot(shap_values, X_imp, show=False, max_display=15)
    plt.title("SHAP Summary Plot – XGBoost (Top 15 variables)", pad=15)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "shap_summary_xgboost.png",
                dpi=150, bbox_inches="tight")
    plt.close()
    print("  Gráfico SHAP summary guardado.")

    # 2. Bar plot – importancia media |SHAP|
    plt.figure(figsize=(9, 7))
    shap.summary_plot(shap_values, X_imp, plot_type="bar", show=False,
                      max_display=15)
    plt.title("Importancia SHAP (|mean|) – XGBoost", pad=15)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "shap_barplot_xgboost.png",
                dpi=150, bbox_inches="tight")
    plt.close()
    print("  Gráfico SHAP bar guardado.")

    # 3. Tabla de importancias SHAP
    importancias = pd.DataFrame({
        "variable": X_muestra.columns,
        "shap_importancia_media": np.abs(shap_values).mean(axis=0),
    }).sort_values("shap_importancia_media", ascending=False)

    ruta = TABLAS_PATH / "importancia_shap_xgboost.csv"
    importancias.to_csv(ruta, index=False)
    print(f"  Tabla SHAP guardada: {ruta.name}")

    return shap_values, X_imp, explainer


def explicar_prestamo_individual(shap_values, X_muestra: pd.DataFrame,
                                 explainer, idx: int = 0) -> None:
    """
    Genera la explicación SHAP de un préstamo individual (waterfall plot).
    Muestra qué variables empujaron la PD hacia arriba o hacia abajo.
    idx : índice de la observación dentro de X_muestra.
    """
    plt.figure(figsize=(10, 6))
    shap.waterfall_plot(
        shap.Explanation(
            values=shap_values[idx],
            base_values=explainer.expected_value,
            data=X_muestra.iloc[idx],
            feature_names=X_muestra.columns.tolist(),
        ),
        show=False,
        max_display=15,
    )
    plt.title(f"Explicación individual – Préstamo #{idx} (SHAP Waterfall)")
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / f"shap_waterfall_prestamo_{idx}.png",
                dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Waterfall plot del préstamo {idx} guardado.")


# ---------------------------------------------------------------------------
# Importancia nativa de XGBoost (Gain)
# ---------------------------------------------------------------------------

def importancia_gain_xgboost(modelo_calibrado, features: list) -> None:
    """
    Extrae la importancia por Gain del XGBoost (métrica nativa del árbol).
    Gain = reducción total de la función de pérdida atribuida a cada feature.
    """
    try:
        pipeline_base = getattr(modelo_calibrado, "_base", modelo_calibrado)
        xgb_model = pipeline_base.named_steps["modelo"]
        scores = xgb_model.get_booster().get_score(importance_type="gain")
        df_imp = (
            pd.Series(scores, name="gain")
            .reset_index()
            .rename(columns={"index": "variable"})
            .sort_values("gain", ascending=False)
        )
        ruta = TABLAS_PATH / "importancia_gain_xgboost.csv"
        df_imp.to_csv(ruta, index=False)

        # Gráfico
        fig, ax = plt.subplots(figsize=(9, 7))
        top_n = df_imp.head(15)
        ax.barh(top_n["variable"][::-1], top_n["gain"][::-1], color="steelblue")
        ax.set_xlabel("Importancia (Gain)")
        ax.set_title("Top 15 variables – Importancia por Gain (XGBoost)")
        ax.grid(True, alpha=0.3, axis="x")
        plt.tight_layout()
        plt.savefig(FIGURAS_PATH / "importancia_gain_xgboost.png",
                    dpi=150, bbox_inches="tight")
        plt.close()
        print("  Gráfico importancia Gain guardado.")
    except Exception as e:
        print(f"  No se pudo calcular importancia Gain: {e}")


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 7 – Explicabilidad del modelo (SHAP)")
    print("=" * 60)

    dataset  = pd.read_parquet(DATASET_MOD_PARQUET)
    features = joblib.load(MODELOS_PATH / "features_lista.joblib")

    # Cargar modelo XGBoost (principal para explicabilidad)
    ruta_xgb = MODELOS_PATH / "modelo_xgboost.joblib"
    if not ruta_xgb.exists():
        print(f"  Modelo no encontrado: {ruta_xgb}")
        return

    modelo_xgb_raw = joblib.load(ruta_xgb)
    print(f"Modelo XGBoost cargado: {ruta_xgb.name}")
    # Extraer el pipeline base de ModeloCalibraado si corresponde
    modelo_xgb = getattr(modelo_xgb_raw, "_base", modelo_xgb_raw)

    # Muestra de test para SHAP
    X_muestra = preparar_muestra_test(dataset, features, n=N_MUESTRA_SHAP)
    print(f"Muestra para SHAP: {len(X_muestra):,} observaciones")

    # Análisis SHAP global
    resultado_shap = analisis_shap_xgboost(modelo_xgb, X_muestra)
    if resultado_shap is not None:
        shap_values, X_imp, explainer = resultado_shap

        # Explicación individual: préstamo de mayor PD predicha
        prob = modelo_xgb_raw.predict_proba(X_muestra)[:, 1]
        idx_alto_riesgo = np.argmax(prob)
        print(f"\n  Explicando préstamo de mayor riesgo (PD={prob[idx_alto_riesgo]:.4%})...")
        explicar_prestamo_individual(shap_values, X_imp, explainer, idx_alto_riesgo)

        # Explicación individual: préstamo de menor PD predicha
        idx_bajo_riesgo = np.argmin(prob)
        print(f"  Explicando préstamo de menor riesgo (PD={prob[idx_bajo_riesgo]:.4%})...")
        explicar_prestamo_individual(shap_values, X_imp, explainer, idx_bajo_riesgo)

    # Importancia Gain
    importancia_gain_xgboost(modelo_xgb, features)

    print("\nPaso 7 completado.\n")


if __name__ == "__main__":
    main()
