"""
05_calibracion_lifetime.py – Calibración PIT-TTC y curva Lifetime PD
=======================================================================
Genera dos productos regulatorios clave bajo IFRS 9:

  1. PD Point-In-Time (PIT)  : probabilidad de default en los próximos 12 meses,
                                sensible al ciclo económico actual.
  2. Lifetime PD              : curva de PD marginal mes a mes durante la vida
                                restante del préstamo, requerida para Stage 2.

Metodología:
  - PIT 12m : output directo del modelo XGBoost calibrado.
  - Lifetime : cadena de PD marginales por "loan age" (curvas de supervivencia).
               PD_lifetime = 1 - ∏(1 - PD_marginal_t) para t=1…T_restante

Nota regulatoria (IFRS 9 párr. 5.5.17):
  Stage 1 → ECL = PD_12m × LGD × EAD
  Stage 2 → ECL = PD_lifetime × LGD × EAD  (pérdida durante toda la vida)

Entrada  : data/dataset_modelado.parquet, outputs/modelos/
Salida   : outputs/tablas/curva_pd_lifetime.csv
           outputs/figuras/curva_pd_marginal.png
"""

import joblib
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression

from config import (
    DATASET_MOD_PARQUET, MODELOS_PATH, TABLAS_PATH, FIGURAS_PATH,
    FEATURES_MODELO, TARGET,
    AÑOS_ENTRENAMIENTO, AÑOS_VALIDACION, AÑOS_TEST,
)
# Importar clase de modelo para que joblib pueda deserializarlo
import sys as _sys, os as _os
_sys.path.insert(0, str(_os.path.dirname(__file__)))
from importlib import import_module as _im
_p04 = _im("04_modelado")
ModeloCalibraado = _p04.ModeloCalibraado  # noqa: F401

warnings.filterwarnings("ignore")

# Fuente uniforme para gráficos de tesis
plt.rcParams.update({"font.family": "serif", "font.size": 11})


# ---------------------------------------------------------------------------
# Calibración isotónica (post-hoc)
# ---------------------------------------------------------------------------

def calibrar_platt_isotonica(y_true, y_prob) -> IsotonicRegression:
    """
    Ajusta una regresión isotónica para calibrar las probabilidades del modelo.
    Garantiza que probabilidades mayores correspondan a mayor riesgo real.
    Se aplica sobre el conjunto de validación.
    """
    ir = IsotonicRegression(out_of_bounds="clip")
    ir.fit(y_prob, y_true)
    return ir


# ---------------------------------------------------------------------------
# Curva de PD marginal por loan_age (survival approach)
# ---------------------------------------------------------------------------

def calcular_pd_marginal_por_edad(dataset: pd.DataFrame,
                                  modelo_calibrado) -> pd.DataFrame:
    """
    Calcula la PD marginal promedio para cada mes de vida del préstamo (loan_age).

    Enfoque:
      - Para cada valor de loan_age (1, 2, 3, … max),
        promediamos la PD_12m predicha de las observaciones con esa edad.
      - Esto produce una "curva de riesgo por edad" que captura el perfil
        de siniestralidad a lo largo del ciclo de vida hipotecario.

    Limitación: asume que el perfil de riesgo es estacionario en el tiempo.
    Para un enfoque más sofisticado, ver stress testing macroeconómico.
    """
    features = joblib.load(MODELOS_PATH / "features_lista.joblib")
    features_disp = [f for f in features if f in dataset.columns]

    X = dataset[features_disp]
    y_prob = modelo_calibrado.predict_proba(X)[:, 1]
    dataset = dataset.copy()
    dataset["pd_12m_pred"] = y_prob

    # PD marginal promedio por edad del préstamo
    pd_por_edad = (
        dataset.groupby("loan_age")["pd_12m_pred"]
        .agg(["mean", "count"])
        .rename(columns={"mean": "pd_marginal", "count": "n_obs"})
        .reset_index()
    )

    # Filtrar edades con suficientes observaciones (≥ 100)
    pd_por_edad = pd_por_edad[pd_por_edad["n_obs"] >= 100].copy()

    return pd_por_edad


def calcular_pd_lifetime(pd_marginal: pd.DataFrame,
                         horizonte_max: int = 360) -> pd.DataFrame:
    """
    Computa la PD acumulada (Lifetime PD) usando la fórmula de supervivencia:
        PD_lifetime(t) = 1 - ∏_{s=1}^{t} (1 - pd_marginal_s)

    Args:
        pd_marginal : DataFrame con columnas [loan_age, pd_marginal]
        horizonte_max : máximo número de meses a proyectar

    Returns:
        DataFrame con [loan_age, pd_marginal, pd_lifetime_acum]
    """
    df = pd_marginal.sort_values("loan_age").copy()
    df = df[df["loan_age"] <= horizonte_max]

    # Supervivencia acumulada: ∏(1 - pd_s)
    df["supervivencia"] = (1 - df["pd_marginal"]).cumprod()
    df["pd_lifetime_acum"] = 1 - df["supervivencia"]

    return df[["loan_age", "pd_marginal", "pd_lifetime_acum", "n_obs"]]


# ---------------------------------------------------------------------------
# Visualización
# ---------------------------------------------------------------------------

def graficar_curva_pd(df_lifetime: pd.DataFrame) -> None:
    """
    Genera el gráfico de PD marginal y Lifetime PD acumulada por loan_age.
    Publicable en la tesis como evidencia de la curva de riesgo hipotecario.
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # PD marginal mensual
    ax1.plot(df_lifetime["loan_age"], df_lifetime["pd_marginal"] * 100,
             color="steelblue", linewidth=2)
    ax1.set_title("PD Marginal por Antigüedad del Préstamo")
    ax1.set_xlabel("Loan Age (meses)")
    ax1.set_ylabel("PD Marginal 12m (%)")
    ax1.grid(True, alpha=0.3)

    # Lifetime PD acumulada
    ax2.plot(df_lifetime["loan_age"], df_lifetime["pd_lifetime_acum"] * 100,
             color="firebrick", linewidth=2)
    ax2.set_title("Lifetime PD Acumulada (curva de supervivencia)")
    ax2.set_xlabel("Loan Age (meses)")
    ax2.set_ylabel("Lifetime PD Acumulada (%)")
    ax2.grid(True, alpha=0.3)

    plt.suptitle(
        "Curvas de Probabilidad de Default – Freddie Mac Dataset\n"
        "Modelo XGBoost calibrado (IFRS 9 PIT)",
        fontsize=12,
    )
    plt.tight_layout()

    ruta = FIGURAS_PATH / "curva_pd_lifetime.png"
    plt.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Gráfico guardado: {ruta}")


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 5 – Calibración PIT y Lifetime PD")
    print("=" * 60)

    dataset  = pd.read_parquet(DATASET_MOD_PARQUET)
    ruta_mod = MODELOS_PATH / "modelo_xgboost.joblib"
    modelo   = joblib.load(ruta_mod)
    print(f"Modelo cargado: {ruta_mod.name}")

    # PD marginal por loan_age
    print("\n  Calculando PD marginal por antigüedad del préstamo...")
    pd_marginal = calcular_pd_marginal_por_edad(dataset, modelo)
    print(f"  Edades cubiertas: {pd_marginal['loan_age'].min()} "
          f"a {pd_marginal['loan_age'].max()} meses")

    # Lifetime PD
    print("\n  Calculando Lifetime PD acumulada...")
    df_lifetime = calcular_pd_lifetime(pd_marginal)

    # Estadísticas clave
    print("\n  === Puntos de referencia de la curva ===")
    for edad in [12, 24, 36, 60, 120, 240]:
        fila = df_lifetime[df_lifetime["loan_age"] <= edad].iloc[-1] \
               if len(df_lifetime[df_lifetime["loan_age"] <= edad]) > 0 else None
        if fila is not None:
            print(f"    Edad {edad:>3} meses: "
                  f"PD_marginal={fila['pd_marginal']:.4%} | "
                  f"Lifetime_PD={fila['pd_lifetime_acum']:.4%}")

    # Guardar tabla
    ruta_tabla = TABLAS_PATH / "curva_pd_lifetime.csv"
    df_lifetime.to_csv(ruta_tabla, index=False)
    print(f"\n  Tabla guardada: {ruta_tabla}")

    # Gráfico
    graficar_curva_pd(df_lifetime)

    print("Paso 5 completado.\n")
    return df_lifetime


if __name__ == "__main__":
    main()
