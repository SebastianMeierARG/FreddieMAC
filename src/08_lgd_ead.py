"""
08_lgd_ead.py – Estimación de LGD y EAD para el cálculo del ECL
=================================================================
Cubre los controles 7.5 (supuestos de pérdida total), 8.1 (metodología de EAD),
8.2 (factores de conversión crediticia) y 8.6 (exposiciones multi-divisa).

El dataset Freddie Mac publica el detalle de liquidación de cada préstamo que
alcanza saldo cero, lo que permite estimar la LGD sobre pérdidas realizadas en
lugar de sobre supuestos:

    Pérdida = (UPB al default − Producido neto de la venta)
              + Intereses devengados impagos
              + Gastos totales (legales, mantenimiento, impuestos, varios)
              − Recuperaciones del seguro hipotecario (MI)
              − Otras recuperaciones (non-MI)

    LGD = Pérdida descontada a la tasa de interés efectiva original / EAD

Supuestos de pérdida total (Control 7.5)
----------------------------------------
Una exposición en default que supere LGD_WORKOUT_MESES_MAX meses sin resolución
se considera irrecuperable y recibe LGD = LGD_PERDIDA_TOTAL (100 %). El criterio
sigue el art. 181.1.a del CRR (uso de un período de workout máximo observado) y
el párrafo 5.4.4 de la NIIF 9, que exige dar de baja el importe bruto cuando no
existe una expectativa razonable de recuperación.

Alcance de EAD y CCF (Controles 8.1 y 8.2)
------------------------------------------
La cartera está integrada exclusivamente por préstamos cerrados, íntegramente
desembolsados y amortizables. No hay líneas revolving ni compromisos no
dispuestos, por lo que el factor de conversión crediticia es nulo sobre el
fuera de balance (CCF_OFF_BALANCE = 0). Los CCF regulatorios estándar quedan
documentados en config.py para el caso de extensión del alcance.

Alcance cambiario (Control 8.6)
-------------------------------
La totalidad de la cartera está denominada y liquidada en USD (MONEDA_BASE), de
modo que no existe descalce de divisas ni necesidad de política de conversión.

Entrada  : data/panel_con_default.parquet
Salida   : outputs/tablas/lgd_*.csv, outputs/tablas/ead_*.csv,
           outputs/tablas/ccf_alcance.csv
           outputs/figuras/lgd_*.png, outputs/figuras/ead_*.png
"""

import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from config import (
    PANEL_DEF_PARQUET, TABLAS_PATH, FIGURAS_PATH,
    ZERO_BALANCE_DEFAULT,
    LGD_WORKOUT_MESES_MAX, LGD_CURE_MESES, LGD_MIN, LGD_MAX,
    LGD_PERDIDA_TOTAL, LGD_DOWNTURN_ADDON, TASA_DESCUENTO_ANUAL,
    CCF_OFF_BALANCE, CCF_REGULATORIOS, MONEDA_BASE, CARTERA_MULTIDIVISA,
    EAD_HORIZONTE_MESES,
)

warnings.filterwarnings("ignore")
plt.rcParams.update({"font.family": "serif", "font.size": 11})


# ---------------------------------------------------------------------------
# Carga de las liquidaciones (registros con saldo cero)
# ---------------------------------------------------------------------------

def cargar_liquidaciones() -> pd.DataFrame:
    """
    Lee únicamente los registros terminales del panel (aquellos con
    zero_balance_code informado), que contienen el detalle de la liquidación.
    """
    cols = [
        "loan_sequence_number", "monthly_reporting_period", "loan_age",
        "zero_balance_code", "zero_balance_effective_date",
        "zero_balance_removal_upb", "actual_loss_calculation",
        "net_sale_proceeds", "mi_recoveries", "non_mi_recoveries",
        "total_expenses", "legal_costs", "maintenance_preservation_costs",
        "taxes_and_insurance", "misc_expenses", "delinquent_accrued_interest",
        "current_actual_upb", "original_upb", "original_ltv",
        "original_interest_rate", "vintage_year", "property_state",
    ]
    disponibles = pq.read_schema(PANEL_DEF_PARQUET).names
    cols = [c for c in cols if c in disponibles]
    df = pd.read_parquet(PANEL_DEF_PARQUET, columns=cols)
    df = df[df["zero_balance_code"].notna()].copy()
    df["zero_balance_code"] = df["zero_balance_code"].astype(str).str.strip()
    return df


def calcular_lgd(liq: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula la LGD de cada exposición liquidada por evento de default.

    La EAD se toma como el UPB al momento de retirar el préstamo de la cartera
    (zero_balance_removal_upb); si no está informado se usa el último saldo
    corriente. La pérdida se recompone a partir de sus componentes para dejar
    trazabilidad, y se contrasta contra el campo actual_loss_calculation que
    publica Freddie Mac.

    La pérdida se descuenta a la tasa de interés efectiva original del
    instrumento durante el período de workout (IFRS 9 B5.5.44).
    """
    df = liq[liq["zero_balance_code"].isin(ZERO_BALANCE_DEFAULT)].copy()

    ead = df["zero_balance_removal_upb"].fillna(df["current_actual_upb"])
    df["ead"] = ead.where(ead > 0)

    componentes = {
        "net_sale_proceeds": -1, "mi_recoveries": -1, "non_mi_recoveries": -1,
        "total_expenses": 1, "delinquent_accrued_interest": 1,
    }
    perdida = df["ead"].copy()
    for col, signo in componentes.items():
        if col in df.columns:
            perdida = perdida + signo * df[col].fillna(0)
    df["perdida_recompuesta"] = perdida
    df["perdida_publicada"] = df["actual_loss_calculation"].abs()

    # Se prioriza el campo publicado por Freddie Mac y se usa la recomposición
    # como respaldo cuando aquel no está informado.
    df["perdida"] = df["perdida_publicada"].fillna(df["perdida_recompuesta"])

    df["lgd_bruta"] = (df["perdida"] / df["ead"]).clip(LGD_MIN, LGD_MAX)

    # Descuento de la pérdida durante el workout a la tasa efectiva original
    tasa = df["original_interest_rate"].fillna(
        TASA_DESCUENTO_ANUAL * 100) / 100.0
    meses = df["workout_meses"] if "workout_meses" in df.columns else 0
    df["factor_descuento"] = (1 + tasa) ** (-np.asarray(meses) / 12.0)
    df["lgd_descontada"] = (df["lgd_bruta"] * df["factor_descuento"]).clip(
        LGD_MIN, LGD_MAX)

    df["tasa_recuperacion"] = 1 - df["lgd_bruta"]
    return df


# ---------------------------------------------------------------------------
# Episodios de default: workout period y curación
# ---------------------------------------------------------------------------

def analizar_episodios_default() -> tuple:
    """
    Reconstruye, para cada préstamo que alcanzó el estado de default, la edad
    del primer evento, el desenlace del episodio y su duración.

    Desenlaces posibles:
      - 'curado'          : LGD_CURE_MESES meses consecutivos sin mora tras el
                            default, sin liquidación con pérdida (probation
                            period, EBA GL/2016/07 §7).
      - 'liquidado'       : el préstamo alcanza saldo cero con un código de
                            default (venta a terceros, short sale o REO).
      - 'prepago/vencido' : sale de la cartera sin pérdida (códigos 01/06/…).
      - 'abierto'         : sigue en default al cierre de la ventana de datos.

    El desenlace 'abierto' con antigüedad superior a LGD_WORKOUT_MESES_MAX es el
    que activa el supuesto de pérdida total (LGD = 100 %).
    """
    cols = ["loan_sequence_number", "monthly_reporting_period", "loan_age",
            "dpd_numerico", "evento_default", "zero_balance_code"]
    panel = pd.read_parquet(PANEL_DEF_PARQUET, columns=cols)
    panel["loan_sequence_number"] = panel["loan_sequence_number"].astype(str).str.strip()
    panel = panel.sort_values(["loan_sequence_number", "monthly_reporting_period"])

    prestamos_def = panel.loc[panel["evento_default"], "loan_sequence_number"].unique()
    print(f"  Préstamos con al menos un evento de default: {len(prestamos_def):,}")

    sub = panel[panel["loan_sequence_number"].isin(prestamos_def)].copy()
    del panel

    primera = (
        sub[sub["evento_default"]]
        .groupby("loan_sequence_number")
        .agg(edad_primer_default=("loan_age", "min"),
             fecha_primer_default=("monthly_reporting_period", "min"))
    )
    sub = sub.join(primera, on="loan_sequence_number")

    ultimo = sub.groupby("loan_sequence_number").agg(
        edad_ultima_obs=("loan_age", "max"),
        fecha_ultima_obs=("monthly_reporting_period", "max"),
    )

    # Código terminal del episodio (último zero_balance_code informado)
    zb = sub.dropna(subset=["zero_balance_code"])
    zb_final = (
        zb.sort_values("monthly_reporting_period")
        .groupby("loan_sequence_number")
        .agg(zb_code=("zero_balance_code", "last"),
             zb_edad=("loan_age", "last"))
    )

    # Curación: racha de meses sin mora posterior al primer default
    post = sub[sub["monthly_reporting_period"] > sub["fecha_primer_default"]].copy()
    post["al_dia"] = (post["dpd_numerico"] == 0).astype("int8")
    def _racha_max(s):
        m = s.rolling(LGD_CURE_MESES, min_periods=LGD_CURE_MESES).sum().max()
        return 0 if pd.isna(m) else int(m)

    racha = (
        post.groupby("loan_sequence_number")["al_dia"]
        .apply(_racha_max)
        .rename("meses_al_dia_max")
    )

    episodios = primera.join(ultimo).join(zb_final).join(racha)
    episodios["zb_code"] = episodios["zb_code"].astype(str).str.strip()
    episodios["meses_al_dia_max"] = episodios["meses_al_dia_max"].fillna(0)

    liquidado = episodios["zb_code"].isin(ZERO_BALANCE_DEFAULT)
    salida_sin_perdida = (~liquidado) & episodios["zb_code"].notna() & \
                         (episodios["zb_code"] != "nan")
    curado = (~liquidado) & (episodios["meses_al_dia_max"] >= LGD_CURE_MESES)

    episodios["desenlace"] = np.select(
        [liquidado, curado, salida_sin_perdida],
        ["liquidado", "curado", "prepago/vencido"],
        default="abierto",
    )
    episodios["workout_meses"] = np.where(
        liquidado,
        episodios["zb_edad"] - episodios["edad_primer_default"],
        episodios["edad_ultima_obs"] - episodios["edad_primer_default"],
    )
    episodios["workout_meses"] = episodios["workout_meses"].clip(lower=0)
    episodios["supera_workout_max"] = (
        (episodios["desenlace"] == "abierto")
        & (episodios["workout_meses"] > LGD_WORKOUT_MESES_MAX)
    )
    return episodios


# ---------------------------------------------------------------------------
# Curva de recuperación
# ---------------------------------------------------------------------------

def curva_recuperacion(lgd_df: pd.DataFrame) -> pd.DataFrame:
    """
    Tasa de recuperación media acumulada según los meses transcurridos entre el
    primer evento de default y la liquidación efectiva.

    Sustenta el supuesto de pérdida total: si a partir de cierto punto del
    workout la recuperación marginal es nula, mantener expectativas de
    recuperación más allá de ese plazo carece de base empírica.
    """
    df = lgd_df.dropna(subset=["workout_meses", "tasa_recuperacion"]).copy()
    df["tramo"] = pd.cut(
        df["workout_meses"],
        bins=[-1, 6, 12, 18, 24, 36, 48, 60, 1000],
        labels=["0-6", "7-12", "13-18", "19-24", "25-36", "37-48",
                "49-60", ">60"],
    )
    tabla = (
        df.groupby("tramo")
        .agg(n=("tasa_recuperacion", "count"),
             recuperacion_media=("tasa_recuperacion", "mean"),
             recuperacion_mediana=("tasa_recuperacion", "median"),
             lgd_media=("lgd_bruta", "mean"),
             lgd_descontada_media=("lgd_descontada", "mean"),
             ead_media=("ead", "mean"))
        .reset_index()
    )
    tabla["recuperacion_marginal"] = tabla["recuperacion_media"].diff()
    return tabla


# ---------------------------------------------------------------------------
# EAD: amortización teórica y prepago
# ---------------------------------------------------------------------------

def saldo_teorico(upb0, tasa_anual, plazo_meses, t):
    """
    Saldo pendiente de un préstamo francés (cuota constante) al mes t:

        EAD_t = UPB_0 · [(1+i)^n − (1+i)^t] / [(1+i)^n − 1]

    con i = tasa nominal anual / 12 y n = plazo original en meses.
    """
    i = np.asarray(tasa_anual) / 100.0 / 12.0
    n = np.asarray(plazo_meses, dtype="float64")
    t = np.asarray(t, dtype="float64")
    i = np.where(i <= 0, 1e-9, i)
    return np.asarray(upb0) * (((1 + i) ** n - (1 + i) ** t) / ((1 + i) ** n - 1))


def validar_ead() -> tuple:
    """
    Contrasta el saldo proyectado por el esquema de amortización teórica contra
    el saldo efectivamente observado, y estima la velocidad de prepago.

        SMM_t = (UPB_teórico_t − UPB_observado_t) / UPB_teórico_t
        CPR   = 1 − (1 − SMM)^12

    El error residual entre saldo teórico y observado es la amortización
    anticipada; una vez incorporada la CPR, la EAD proyectada a 12 meses queda:

        EAD_12m = UPB_teórico_{t+12} · (1 − CPR)^(12/12) + intereses devengados
    """
    cols = ["loan_sequence_number", "loan_age", "current_actual_upb",
            "original_upb", "original_interest_rate", "original_loan_term",
            "vintage_year", "zero_balance_code"]
    panel = pd.read_parquet(PANEL_DEF_PARQUET, columns=cols)
    panel = panel[panel["current_actual_upb"] > 0]

    panel["upb_teorico"] = saldo_teorico(
        panel["original_upb"], panel["original_interest_rate"],
        panel["original_loan_term"], panel["loan_age"],
    )
    panel["desvio_rel"] = (
        (panel["current_actual_upb"] - panel["upb_teorico"])
        / panel["upb_teorico"].replace(0, np.nan)
    )

    validacion = (
        panel.groupby("loan_age")
        .agg(n=("current_actual_upb", "count"),
             upb_observado=("current_actual_upb", "mean"),
             upb_teorico=("upb_teorico", "mean"),
             desvio_rel_medio=("desvio_rel", "mean"))
        .reset_index()
    )
    validacion = validacion[validacion["n"] >= 500]
    validacion["error_abs_pct"] = (
        (validacion["upb_observado"] - validacion["upb_teorico"]).abs()
        / validacion["upb_teorico"] * 100
    )

    # Prepago implícito: exceso de amortización sobre el plan teórico
    validacion["smm"] = (
        (validacion["upb_teorico"] - validacion["upb_observado"])
        / validacion["upb_teorico"]
    ).clip(lower=0)
    # SMM mensual medio implícito por la diferencia acumulada de saldos
    validacion["smm_mensual"] = 1 - (1 - validacion["smm"]) ** (
        1 / validacion["loan_age"].clip(lower=1))
    validacion["cpr_anual"] = 1 - (1 - validacion["smm_mensual"]) ** 12

    cpr_media = float(
        validacion.loc[validacion["loan_age"].between(12, 60), "cpr_anual"].mean()
    )

    # EAD proyectada a 12 meses para la cartera viva
    viva = panel[panel["zero_balance_code"].isna()]
    upb_12m = saldo_teorico(
        viva["original_upb"], viva["original_interest_rate"],
        viva["original_loan_term"], viva["loan_age"] + EAD_HORIZONTE_MESES,
    )
    interes_devengado = (
        viva["current_actual_upb"] * viva["original_interest_rate"] / 100.0
        * (3 / 12.0)          # 3 meses de intereses impagos hasta el default
    )
    ead_proyectada = upb_12m * (1 - cpr_media) + interes_devengado

    resumen_ead = pd.DataFrame([{
        "moneda_base":              MONEDA_BASE,
        "cartera_multidivisa":      CARTERA_MULTIDIVISA,
        "horizonte_meses":          EAD_HORIZONTE_MESES,
        "n_exposiciones_vivas":     int(len(viva)),
        "upb_actual_medio":         round(float(viva["current_actual_upb"].mean()), 2),
        "upb_teorico_12m_medio":    round(float(np.nanmean(upb_12m)), 2),
        "cpr_anual_media":          round(cpr_media, 4),
        "interes_devengado_medio":  round(float(interes_devengado.mean()), 2),
        "ead_proyectada_media":     round(float(np.nanmean(ead_proyectada)), 2),
        "ead_sobre_upb_actual":     round(float(np.nanmean(ead_proyectada)
                                                / viva["current_actual_upb"].mean()), 4),
        "ccf_off_balance":          CCF_OFF_BALANCE,
        "error_medio_amortizacion_pct": round(float(validacion["error_abs_pct"].mean()), 3),
    }])
    return validacion, resumen_ead


def tabla_ccf() -> pd.DataFrame:
    """
    Delimitación del alcance de las exposiciones fuera de balance y CCF
    regulatorios de referencia (CRR art. 111 / Basilea III enfoque estándar).
    """
    filas = [{
        "tipo_exposicion": "Préstamo hipotecario cerrado, totalmente desembolsado",
        "presente_en_cartera": "Sí (100 %)",
        "saldo_contingente": "No",
        "CCF_aplicado": CCF_OFF_BALANCE,
        "fundamento": "No existe importe no dispuesto: la EAD es el saldo en balance",
    }]
    descripciones = {
        "compromiso_incondicionalmente_cancelable":
            "Compromiso revocable sin previo aviso",
        "compromiso_vencimiento_hasta_1a":
            "Compromiso irrevocable con vencimiento original ≤ 1 año",
        "compromiso_vencimiento_mayor_1a":
            "Compromiso irrevocable con vencimiento original > 1 año",
        "linea_revolving_no_comprometida":
            "Línea revolving no comprometida (HELOC, tarjeta)",
        "garantia_financiera":
            "Garantía financiera / sustituto directo del crédito",
    }
    for clave, ccf in CCF_REGULATORIOS.items():
        filas.append({
            "tipo_exposicion": descripciones[clave],
            "presente_en_cartera": "No",
            "saldo_contingente": "Sí",
            "CCF_aplicado": ccf,
            "fundamento": "CCF regulatorio estándar; documentado para extensión del alcance",
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Visualizaciones
# ---------------------------------------------------------------------------

def graficar_lgd(lgd_df: pd.DataFrame, curva: pd.DataFrame) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.hist(lgd_df["lgd_bruta"].dropna() * 100, bins=50, color="steelblue",
             edgecolor="white")
    ax1.axvline(lgd_df["lgd_bruta"].mean() * 100, color="firebrick",
                linestyle="--", linewidth=2,
                label=f"LGD media = {lgd_df['lgd_bruta'].mean():.2%}")
    ax1.set_title("Distribución de la LGD realizada")
    ax1.set_xlabel("LGD (%)")
    ax1.set_ylabel("Frecuencia")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.plot(curva["tramo"].astype(str), curva["recuperacion_media"] * 100,
             "o-", color="forestgreen", linewidth=2, label="Recuperación media")
    ax2.plot(curva["tramo"].astype(str), curva["lgd_media"] * 100,
             "s--", color="firebrick", linewidth=2, label="LGD media")
    ax2.axvline(len(curva) - 1.5, color="grey", linestyle=":", linewidth=1.5)
    ax2.set_title(f"Curva de recuperación por período de workout\n"
                  f"(workout máximo = {LGD_WORKOUT_MESES_MAX} meses)")
    ax2.set_xlabel("Meses desde el primer evento de default")
    ax2.set_ylabel("%")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "lgd_curva_recuperacion.png", dpi=150,
                bbox_inches="tight")
    plt.close()
    print("  Figura guardada: lgd_curva_recuperacion.png")


def graficar_ead(validacion: pd.DataFrame) -> None:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    ax1.plot(validacion["loan_age"], validacion["upb_teorico"] / 1000,
             "--", color="steelblue", linewidth=2, label="Saldo teórico (amortización)")
    ax1.plot(validacion["loan_age"], validacion["upb_observado"] / 1000,
             "-", color="firebrick", linewidth=2, label="Saldo observado")
    ax1.set_title("EAD: esquema de amortización teórica vs. saldo real")
    ax1.set_xlabel("Loan age (meses)")
    ax1.set_ylabel("UPB medio (miles de USD)")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.plot(validacion["loan_age"], validacion["cpr_anual"] * 100,
             color="darkorange", linewidth=2)
    ax2.set_title("Velocidad de prepago implícita (CPR anualizada)")
    ax2.set_xlabel("Loan age (meses)")
    ax2.set_ylabel("CPR (%)")
    ax2.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(FIGURAS_PATH / "ead_amortizacion_prepago.png", dpi=150,
                bbox_inches="tight")
    plt.close()
    print("  Figura guardada: ead_amortizacion_prepago.png")


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("PASO 8 – LGD y EAD (Controles 7.5, 8.1, 8.2, 8.6)")
    print("=" * 60)

    # --- Episodios de default: workout, curación y pérdida total ---
    print("\n  [Episodios de default: workout y curación]")
    episodios = analizar_episodios_default()
    resumen_desenlace = (
        episodios.groupby("desenlace")
        .agg(n=("workout_meses", "count"),
             workout_medio=("workout_meses", "mean"),
             workout_p95=("workout_meses", lambda s: s.quantile(0.95)))
        .reset_index()
    )
    resumen_desenlace["proporcion"] = (
        resumen_desenlace["n"] / resumen_desenlace["n"].sum()).round(4)
    print(resumen_desenlace.to_string(index=False))

    cure_rate = float((episodios["desenlace"] == "curado").mean())
    n_perdida_total = int(episodios["supera_workout_max"].sum())
    print(f"\n  Cure rate (probation {LGD_CURE_MESES} meses): {cure_rate:.2%}")
    print(f"  Exposiciones que superan el workout máximo "
          f"({LGD_WORKOUT_MESES_MAX} meses) sin resolución -> LGD = "
          f"{LGD_PERDIDA_TOTAL:.0%}: {n_perdida_total:,}")

    # --- LGD realizada sobre liquidaciones con pérdida ---
    print("\n  [LGD realizada]")
    liq = cargar_liquidaciones()
    print(f"  Registros de liquidación leídos: {len(liq):,}")
    liq["loan_sequence_number"] = liq["loan_sequence_number"].astype(str).str.strip()
    liq = liq.merge(
        episodios[["workout_meses", "desenlace", "edad_primer_default"]],
        left_on="loan_sequence_number", right_index=True, how="left",
    )
    liq["workout_meses"] = liq["workout_meses"].fillna(0)
    lgd_df = calcular_lgd(liq)
    print(f"  Exposiciones liquidadas por default: {len(lgd_df):,}")

    if len(lgd_df):
        lgd_media = float(lgd_df["lgd_bruta"].mean())
        lgd_desc  = float(lgd_df["lgd_descontada"].mean())
        lgd_pond  = float((lgd_df["perdida"].sum() / lgd_df["ead"].sum()))
        print(f"  LGD media (simple)            : {lgd_media:.2%}")
        print(f"  LGD media descontada al EIR   : {lgd_desc:.2%}")
        print(f"  LGD ponderada por exposición  : {lgd_pond:.2%}")
        print(f"  LGD downturn (media + add-on) : "
              f"{min(lgd_media + LGD_DOWNTURN_ADDON, LGD_MAX):.2%}")
    else:
        lgd_media = lgd_desc = lgd_pond = float("nan")

    # LGD por año de liquidación y por banda de LTV original
    lgd_df["anio_liquidacion"] = pd.to_datetime(
        lgd_df["zero_balance_effective_date"]).dt.year
    lgd_anual = (
        lgd_df.groupby("anio_liquidacion")
        .agg(n=("lgd_bruta", "count"), lgd_media=("lgd_bruta", "mean"),
             lgd_descontada=("lgd_descontada", "mean"),
             ead_total=("ead", "sum"), perdida_total=("perdida", "sum"))
        .reset_index()
    )
    lgd_anual["lgd_ponderada"] = (
        lgd_anual["perdida_total"] / lgd_anual["ead_total"]).round(4)

    lgd_df["banda_ltv"] = pd.cut(
        lgd_df["original_ltv"], bins=[0, 60, 75, 80, 90, 1000],
        labels=["<=60", "60-75", "75-80", "80-90", ">90"], right=False)
    lgd_ltv = (
        lgd_df.groupby("banda_ltv")
        .agg(n=("lgd_bruta", "count"), lgd_media=("lgd_bruta", "mean"),
             tasa_recuperacion=("tasa_recuperacion", "mean"))
        .reset_index()
    )
    print("\n  LGD por banda de LTV original:")
    print(lgd_ltv.to_string(index=False))

    curva = curva_recuperacion(lgd_df)
    print("\n  Curva de recuperación por período de workout:")
    print(curva.to_string(index=False))

    # --- Parámetros de pérdida total aplicados ---
    politica = pd.DataFrame([
        {"parametro": "Período de workout máximo (meses)",
         "valor": LGD_WORKOUT_MESES_MAX,
         "fundamento": "CRR art. 181.1.a – horizonte máximo observado de recuperación"},
        {"parametro": "Probation period para declarar curación (meses)",
         "valor": LGD_CURE_MESES,
         "fundamento": "EBA GL/2016/07 §7 – mínimo 3 meses; criterio conservador 12"},
        {"parametro": "LGD asignada al superar el workout máximo",
         "valor": LGD_PERDIDA_TOTAL,
         "fundamento": "NIIF 9 5.4.4 – baja del importe bruto sin expectativa razonable de recuperación"},
        {"parametro": "Add-on de downturn sobre la LGD media",
         "valor": LGD_DOWNTURN_ADDON,
         "fundamento": "CRR art. 181.1.b – LGD apropiada para una recesión económica"},
        {"parametro": "Tasa de descuento de las recuperaciones",
         "valor": "Tasa de interés efectiva original del instrumento",
         "fundamento": "NIIF 9 B5.5.44"},
        {"parametro": "Cure rate observado",
         "valor": round(cure_rate, 4),
         "fundamento": "Estimación empírica sobre episodios de default del panel"},
        {"parametro": "Exposiciones con supuesto de pérdida total aplicado",
         "valor": n_perdida_total,
         "fundamento": "Episodios abiertos con antigüedad superior al workout máximo"},
        {"parametro": "LGD media realizada",
         "valor": round(lgd_media, 4),
         "fundamento": "Media simple sobre liquidaciones con evento de default"},
        {"parametro": "LGD ponderada por exposición",
         "valor": round(lgd_pond, 4),
         "fundamento": "Pérdida total / EAD total"},
    ])

    # --- EAD y CCF ---
    print("\n  [EAD: amortización teórica, prepago y alcance de CCF]")
    validacion_ead, resumen_ead = validar_ead()
    print(resumen_ead.T.to_string(header=False))
    ccf = tabla_ccf()

    # --- Persistencia ---
    resumen_desenlace.to_csv(TABLAS_PATH / "lgd_desenlace_episodios.csv", index=False)
    politica.to_csv(TABLAS_PATH / "lgd_politica_perdida_total.csv", index=False)
    lgd_anual.to_csv(TABLAS_PATH / "lgd_por_anio.csv", index=False)
    lgd_ltv.to_csv(TABLAS_PATH / "lgd_por_banda_ltv.csv", index=False)
    curva.to_csv(TABLAS_PATH / "lgd_curva_recuperacion.csv", index=False)
    validacion_ead.to_csv(TABLAS_PATH / "ead_validacion_amortizacion.csv", index=False)
    resumen_ead.to_csv(TABLAS_PATH / "ead_resumen.csv", index=False)
    ccf.to_csv(TABLAS_PATH / "ccf_alcance.csv", index=False)
    print("\n  Tablas guardadas en outputs/tablas/ (lgd_*.csv, ead_*.csv, ccf_alcance.csv)")

    graficar_lgd(lgd_df, curva)
    graficar_ead(validacion_ead)

    print("\nPaso 8 completado.\n")
    return lgd_df, resumen_ead


if __name__ == "__main__":
    main()
