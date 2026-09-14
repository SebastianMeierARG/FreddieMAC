"""
01_carga_datos.py – Carga y merge del dataset Freddie Mac
==========================================================
Carga los parquets de originación y performance, aplica correcciones
de sentinel values, y genera el panel longitudinal (loan × mes).

Entrada  : data/orig_all.parquet, data/svcg_all.parquet
Salida   : data/panel.parquet
"""

import re
import pandas as pd
import numpy as np

from config import (
    ORIG_PARQUET, SVCG_PARQUET, PANEL_PARQUET,
    SENTINEL_CREDIT_SCORE,
)


# ---------------------------------------------------------------------------
# Normalización de nombres de columnas
# Los parquets generados por data_reader.R tienen sufijo _V# (ej: credit_score_V1)
# Esta función elimina ese sufijo y renombra 'year' → 'vintage_year'
# ---------------------------------------------------------------------------
def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [re.sub(r"_V\d+$", "", c) for c in df.columns]
    if "year" in df.columns and "vintage_year" not in df.columns:
        df = df.rename(columns={"year": "vintage_year"})
    return df


# ---------------------------------------------------------------------------
# Correcciones de sentinel values (por si el parquet fue generado con R)
# El data_reader.py en Python ya los trata, pero validamos de todas formas.
# ---------------------------------------------------------------------------
SENTINELS_ORIG = {
    "credit_score":              SENTINEL_CREDIT_SCORE,
    "mi_percent":                999,
    "number_of_units":           99,
    "original_cltv":             999,
    "original_dti":              999,
    "original_ltv":              999,
    "number_of_borrowers":       99,
    "property_valuation_method": 9,
}


def limpiar_sentinels_orig(df: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza valores centinela numéricos por NaN en el dataset de originación."""
    for col, centinela in SENTINELS_ORIG.items():
        if col in df.columns:
            df[col] = df[col].replace(centinela, np.nan)
    return df


def parsear_fechas_yyyymm(df: pd.DataFrame, columnas: list) -> pd.DataFrame:
    """Convierte columnas YYYYMM (str/int) a dtype datetime (primer día del mes)."""
    for col in columnas:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col].astype(str).str[:6],   # toma solo primeros 6 chars
                format="%Y%m",
                errors="coerce",
            )
    return df


def cargar_originacion() -> pd.DataFrame:
    """Carga y prepara el dataset de originación."""
    print("  Cargando originación...")
    orig = pd.read_parquet(ORIG_PARQUET)
    orig = normalizar_columnas(orig)
    print(f"    Filas: {len(orig):,} | Columnas: {orig.shape[1]}")

    # Sentinel → NaN (garantía adicional)
    orig = limpiar_sentinels_orig(orig)

    # Parsear fechas
    orig = parsear_fechas_yyyymm(
        orig, ["first_payment_date", "maturity_date"]
    )

    # Aseguramos que el código postal sea string con ceros (###00)
    if "postal_code3_trunc" in orig.columns:
        orig["postal_code3_trunc"] = (
            orig["postal_code3_trunc"].astype(str).str.zfill(5)
        )

    # loan_sequence_number como clave de join
    orig["loan_sequence_number"] = orig["loan_sequence_number"].astype(str).str.strip()

    return orig


def normalizar_zero_balance_code(df: pd.DataFrame) -> pd.DataFrame:
    """
    zero_balance_code debe quedar como código de 2 dígitos con cero a la
    izquierda (ej. "02", "03", "09"), que es el formato que espera
    ZERO_BALANCE_DEFAULT en config.py. Algunos parquets crudos lo traen como
    float (ej. 2.0) por inferencia de tipo aguas arriba, lo que rompe
    silenciosamente el filtro zero_balance_code.isin({"02","03","09"}) en
    02_definicion_default.py (astype(str) de un float da "2.0", no "02").
    """
    if "zero_balance_code" in df.columns:
        col = df["zero_balance_code"]
        if pd.api.types.is_numeric_dtype(col):
            df["zero_balance_code"] = (
                col.round().astype("Int64").astype(str)
                .str.zfill(2).replace("<NA>", np.nan)
            )
        else:
            df["zero_balance_code"] = col.astype(str).str.strip().str.zfill(2)
    return df


def cargar_performance() -> pd.DataFrame:
    """Carga y prepara el dataset de performance mensual."""
    print("  Cargando performance...")
    svcg = pd.read_parquet(SVCG_PARQUET)
    svcg = normalizar_columnas(svcg)
    svcg = normalizar_zero_balance_code(svcg)
    print(f"    Filas: {len(svcg):,} | Columnas: {svcg.shape[1]}")

    # Parsear fechas
    svcg = parsear_fechas_yyyymm(
        svcg,
        [
            "monthly_reporting_period",
            "zero_balance_effective_date",
            "defect_settlement_date",
            "ddlpi_due_date_last_paid_installment",
        ],
    )

    # current_loan_delinquency_status puede ser "RA" (REO) → lo preservamos como str
    svcg["loan_sequence_number"] = svcg["loan_sequence_number"].astype(str).str.strip()

    # ELTV: solo disponible desde abril 2017 → NaN antes de esa fecha es correcto
    # No imputamos; se usará con cuidado en feature engineering.

    # net_sale_proceeds: puede contener "U" (desconocido) → convertir a numérico
    # cuando sea posible, dejar NaN si "U"
    if "net_sale_proceeds" in svcg.columns:
        svcg["net_sale_proceeds"] = pd.to_numeric(
            svcg["net_sale_proceeds"].replace("U", np.nan),
            errors="coerce",
        )

    return svcg


def construir_panel(orig: pd.DataFrame, svcg: pd.DataFrame) -> pd.DataFrame:
    """
    Genera el panel longitudinal (loan × mes) uniendo originación y performance.
    Cada fila = un préstamo en un período mensual específico.
    """
    print("  Construyendo panel longitudinal...")

    # Columnas de originación a llevar al panel (evitamos traer 'vintage_year'
    # del svcg si ya está en orig – lo renombramos para evitar colisión)
    panel = svcg.merge(
        orig,
        on="loan_sequence_number",
        how="left",
        suffixes=("", "_orig"),
    )

    # El vintage_year de performance puede diferir del de originación si hay
    # datos de refinanciaciones; usamos el de orig como referencia
    if "vintage_year_orig" in panel.columns:
        panel["vintage_year"] = panel["vintage_year_orig"]
        panel.drop(columns=["vintage_year_orig"], inplace=True)

    print(f"    Panel: {len(panel):,} filas | {panel.shape[1]} columnas")
    print(f"    Préstamos únicos: {panel['loan_sequence_number'].nunique():,}")
    print(f"    Período: {panel['monthly_reporting_period'].min()} "
          f"a {panel['monthly_reporting_period'].max()}")

    # Nota de cobertura temporal por vintage
    cobertura = (
        panel.groupby("vintage_year")["monthly_reporting_period"]
        .agg(["min", "max", "count"])
        .rename(columns={"count": "observaciones"})
    )
    print("\n  Cobertura por vintage year:")
    print(cobertura.to_string())
    print()

    return panel


def main():
    print("=" * 60)
    print("PASO 1 – Carga y merge de datos")
    print("=" * 60)

    orig  = cargar_originacion()
    svcg  = cargar_performance()
    panel = construir_panel(orig, svcg)

    # Ordenar para facilitar operaciones de ventana (lag/rolling) posteriores
    panel.sort_values(
        ["loan_sequence_number", "monthly_reporting_period"],
        inplace=True,
    )
    panel.reset_index(drop=True, inplace=True)

    print(f"\nGuardando panel en: {PANEL_PARQUET}")
    panel.to_parquet(PANEL_PARQUET, index=False)
    print("Paso 1 completado.\n")

    return panel


if __name__ == "__main__":
    main()
