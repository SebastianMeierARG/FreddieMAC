"""
pipeline_completo.py – Ejecución secuencial de todo el pipeline de tesis
=========================================================================
Ejecuta todos los pasos del proyecto en orden. Útil para reproducibilidad total.

Uso:
    python pipeline_completo.py

Pasos:
    0.  Datos macroeconómicos FRED (FLI – IFRS 9 5.5.17c)   [requiere FRED_API_KEY]
    1.  Carga y merge de datos
    2.  Definición de default IFRS 9 + stages
    3.  Feature Engineering (incluye merge macro si paso 0 fue ejecutado)
    4.  Entrenamiento de modelos PD
    3b. SICR basado en PD (IFRS 9 5.5.9)                    [requiere paso 4]
    5.  Calibración PIT + Lifetime PD
    5b. Ponderación de escenarios macroeconómicos            [requiere paso 0 y 4]
    6.  Validación regulatoria (incluye backtesting transiciones + Lifetime PD)
    7.  Explicabilidad SHAP
"""

import os
import sys
import time
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def ejecutar_paso(numero, nombre: str, modulo_str: str, opcional: bool = False):
    separador = "=" * 60
    print(f"\n{separador}")
    print(f"INICIANDO PASO {numero}: {nombre}")
    print(separador)
    inicio = time.time()
    try:
        modulo = import_module(modulo_str)
        modulo.main()
    except Exception as exc:
        if opcional:
            print(f"Paso {numero} omitido ({type(exc).__name__}: {exc})")
            return
        raise
    elapsed = time.time() - inicio
    print(f"Paso {numero} completado en {elapsed:.1f} segundos.")


def main():
    inicio_total = time.time()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║  PIPELINE COMPLETO – TESIS IFRS 9 PD – FREDDIE MAC      ║")
    print("║  Predicción de Probabilidad de Default bajo IFRS 9      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # Paso 0 es opcional: requiere FRED_API_KEY; los pasos siguientes siguen
    # funcionando sin datos macro (los features macro quedan como NaN y son
    # imputados por SimpleImputer en el pipeline de sklearn).
    tiene_fred_key = bool(os.environ.get("FRED_API_KEY"))
    if tiene_fred_key:
        ejecutar_paso("0", "Datos macroeconómicos (FRED)", "00_macro_data")
    else:
        print("\nPASO 0 omitido: FRED_API_KEY no configurado.")
        print("  Para activar FLI: set FRED_API_KEY=tu_clave_aqui")

    pasos_principales = [
        (1, "Carga y merge de datos",                "01_carga_datos",          False),
        (2, "Definición de default IFRS 9 + stages", "02_definicion_default",   False),
        (3, "Feature Engineering",                   "03_feature_engineering",  False),
        (4, "Entrenamiento de modelos PD",            "04_modelado",             False),
        ("3b", "SICR basado en PD (IFRS 9 5.5.9)",   "03b_sicr_assessment",     False),
        (5, "Calibración PIT + Lifetime PD",          "05_calibracion_lifetime", False),
        ("5b", "Ponderación de escenarios macro",     "05b_scenario_weighting",  True),
        (6, "Validación regulatoria",                 "06_validacion",           False),
        (7, "Explicabilidad SHAP",                    "07_explicabilidad",       False),
    ]

    for numero, nombre, modulo, opcional in pasos_principales:
        ejecutar_paso(numero, nombre, modulo, opcional=opcional)

    total = time.time() - inicio_total
    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETO FINALIZADO en {total / 60:.1f} minutos.")
    print(f"Resultados en: outputs/")
    print("=" * 60)


if __name__ == "__main__":
    main()
