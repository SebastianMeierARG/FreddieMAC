"""
pipeline_completo.py – Ejecución secuencial de todo el pipeline de tesis
=========================================================================
Ejecuta los 7 pasos del proyecto en orden. Útil para reproducibilidad total.

Uso:
    python pipeline_completo.py

Pasos:
    1. Carga y merge de datos                  (01_carga_datos.py)
    2. Definición de default IFRS 9 + stages   (02_definicion_default.py)
    3. Feature engineering                      (03_feature_engineering.py)
    4. Entrenamiento de modelos                 (04_modelado.py)
    5. Calibración PIT + Lifetime PD            (05_calibracion_lifetime.py)
    6. Validación regulatoria                   (06_validacion.py)
    7. Explicabilidad SHAP                      (07_explicabilidad.py)
"""

import sys
import time
from pathlib import Path

# Asegurar que el directorio src esté en el path
sys.path.insert(0, str(Path(__file__).parent))

import paso_01 as paso_01_mod
import paso_02 as paso_02_mod
import paso_03 as paso_03_mod
import paso_04 as paso_04_mod
import paso_05 as paso_05_mod
import paso_06 as paso_06_mod
import paso_07 as paso_07_mod

# Importamos los módulos directamente
from importlib import import_module


def ejecutar_paso(numero: int, nombre: str, modulo_str: str):
    """Ejecuta un paso del pipeline midiendo el tiempo."""
    separador = "=" * 60
    print(f"\n{separador}")
    print(f"INICIANDO PASO {numero}: {nombre}")
    print(separador)
    inicio = time.time()

    modulo = import_module(modulo_str)
    modulo.main()

    elapsed = time.time() - inicio
    print(f"Paso {numero} completado en {elapsed:.1f} segundos.")


def main():
    inicio_total = time.time()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║  PIPELINE COMPLETO – TESIS IFRS 9 PD – FREDDIE MAC      ║")
    print("║  Predicción de Probabilidad de Default bajo IFRS 9      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    pasos = [
        (1, "Carga y merge de datos",               "01_carga_datos"),
        (2, "Definición de default IFRS 9 + stages","02_definicion_default"),
        (3, "Feature Engineering",                  "03_feature_engineering"),
        (4, "Entrenamiento de modelos PD",           "04_modelado"),
        (5, "Calibración PIT + Lifetime PD",         "05_calibracion_lifetime"),
        (6, "Validación regulatoria",                "06_validacion"),
        (7, "Explicabilidad SHAP",                   "07_explicabilidad"),
    ]

    for numero, nombre, modulo in pasos:
        ejecutar_paso(numero, nombre, modulo)

    total = time.time() - inicio_total
    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETO FINALIZADO en {total / 60:.1f} minutos.")
    print(f"Resultados en: outputs/")
    print("=" * 60)


if __name__ == "__main__":
    main()
