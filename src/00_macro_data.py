"""
00_macro_data.py – Descarga y consolidación de datos macroeconómicos (FRED)
============================================================================
Descarga las series macro requeridas para Forward-Looking Information (FLI)
bajo IFRS 9 5.5.17(c) / BIS d350 Principio 6 (paras 62-68).

Series descargadas:
  USSTHPI      → House Price Index         (trimestral → mensual por ffill)
  UNRATE       → Tasa de desempleo         (mensual)
  FEDFUNDS     → Fed Funds Rate            (mensual)
  GDPC1        → GDP real encadenado       (trimestral → mensual por ffill)
  MORTGAGE30US → Mortgage rate 30 años     (semanal → mensual por promedio)

Requiere: variable de entorno FRED_API_KEY.
  Clave gratuita en: https://fred.stlouisfed.org/docs/api/api_key.html
  Windows: set FRED_API_KEY=tu_clave_aqui

Salida: data/macro/macro_monthly.parquet
"""

import os
import pandas as pd
from fredapi import Fred

from config import FRED_SERIES, MACRO_PARQUET, MACRO_PATH

# Inicio de descarga: 2 años antes del primer año de entrenamiento para
# cubrir el cálculo de variaciones YoY (necesita 12 meses hacia atrás)
START_DATE = "2014-01-01"

# Series que son de frecuencia trimestral (se interpolan a mensual con ffill)
SERIES_TRIMESTRALES = {"USSTHPI", "GDPC1"}
# Series de frecuencia semanal (se promedian a mensual)
SERIES_SEMANALES = {"MORTGAGE30US"}


def descargar_serie(fred: Fred, series_id: str, nombre: str) -> pd.Series:
    print(f"  Descargando {series_id} → {nombre}...")
    serie = fred.get_series(series_id, observation_start=START_DATE)
    serie.name = nombre
    return serie


def resamplear_a_mensual(serie: pd.Series, series_id: str) -> pd.Series:
    if series_id in SERIES_TRIMESTRALES:
        # Forward-fill: el valor trimestral se mantiene para los dos meses siguientes
        return serie.resample("MS").ffill()
    elif series_id in SERIES_SEMANALES:
        # Promedio de todas las observaciones semanales del mes
        return serie.resample("MS").mean()
    else:
        # Mensual: normalizar al primer día del mes
        return serie.resample("MS").last()


def main():
    print("=" * 60)
    print("PASO 0 – Datos macroeconómicos (FRED)")
    print("=" * 60)

    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "Variable de entorno FRED_API_KEY no encontrada.\n"
            "Obtener clave gratuita en: https://fred.stlouisfed.org/docs/api/api_key.html\n"
            "Windows: set FRED_API_KEY=tu_clave_aqui"
        )
    fred = Fred(api_key=api_key)

    series_mensuales = {}
    for series_id, nombre in FRED_SERIES.items():
        serie = descargar_serie(fred, series_id, nombre)
        series_mensuales[nombre] = resamplear_a_mensual(serie, series_id)

    df = pd.DataFrame(series_mensuales)
    df.index.name = "date"
    df = df.reset_index()
    df = df.sort_values("date").reset_index(drop=True)

    # Variaciones interanuales (YoY) para features prospectivos
    df["hpi_yoy_change"]          = df["hpi"].pct_change(12) * 100
    df["unemployment_yoy_change"] = df["unemployment_rate"].diff(12)

    for col in df.select_dtypes("float64").columns:
        df[col] = df[col].astype("float32")

    MACRO_PATH.mkdir(parents=True, exist_ok=True)
    df.to_parquet(MACRO_PARQUET, index=False)

    print(f"\nDatos macro guardados: {MACRO_PARQUET}")
    print(f"Rango: {df['date'].min().date()} – {df['date'].max().date()}")
    print(f"Filas: {len(df):,} | Columnas: {list(df.columns)}")
    print("Paso 0 completado.\n")
    return df


if __name__ == "__main__":
    main()
