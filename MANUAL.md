# Manual del Proyecto – Tesis IFRS 9 PD (Freddie Mac)

**Tesis:** Predicción de la Probabilidad de Default bajo el marco regulatorio IFRS 9 utilizando técnicas de aprendizaje automático y datos crediticios abiertos de Freddie Mac  
**Autor:** Sebastian Emiliano Meier  
**Director:** Mag. Ing. Gustavo Denicolay  
**Institución:** UTN Facultad Regional Paraná – Maestría en Minería de Datos

---

## Estructura del proyecto

```
FreddieMAC/
├── data/                         # Parquets procesados (generados por el pipeline)
│   ├── orig_all.parquet          # Dataset de originación combinado (todos los años)
│   ├── svcg_all.parquet          # Dataset de performance mensual combinado
│   ├── panel.parquet             # Panel longitudinal (loan × mes) – generado en paso 1
│   ├── panel_con_default.parquet # Panel + variable de default IFRS 9 – generado en paso 2
│   └── dataset_modelado.parquet  # Dataset final con features – generado en paso 3
│
├── data_sample_year/             # Datos crudos originales de Freddie Mac (txt por año)
│   └── sample_YYYY/              # Carpetas por vintage (2016–2024, sin 2021)
│
├── src/                          # Código fuente
│   ├── config.py                 # Configuración global (rutas, parámetros, features)
│   ├── pipeline_completo.py      # Ejecutor secuencial de todos los pasos
│   ├── 00_eda.py                 # Análisis exploratorio de datos
│   ├── 01_carga_datos.py         # Paso 1: carga y merge
│   ├── 02_definicion_default.py  # Paso 2: definición de default IFRS 9
│   ├── 03_feature_engineering.py # Paso 3: ingeniería de variables
│   ├── 04_modelado.py            # Paso 4: entrenamiento de modelos
│   ├── 05_calibracion_lifetime.py# Paso 5: calibración PIT + Lifetime PD
│   ├── 06_validacion.py          # Paso 6: validación regulatoria
│   ├── 07_explicabilidad.py      # Paso 7: explicabilidad SHAP
│   └── crear_tesis.py            # Generador del documento de tesis
│
└── outputs/
    ├── figuras/                  # Gráficos generados (PNG)
    ├── modelos/                  # Modelos entrenados (joblib)
    └── tablas/                   # Resultados y métricas (CSV)
```

---

## Datos

**Fuente:** Freddie Mac Single-Family Loan-Level Dataset (muestra pública)  
**Cobertura:** Vintages 2016–2024 (**el año 2021 no está disponible en el dataset**)  
**Clave de join:** `loan_sequence_number`

| Archivo | Descripción |
|---|---|
| `orig_all.parquet` | Variables de originación del préstamo (estáticas) |
| `svcg_all.parquet` | Reporte mensual de performance por préstamo (dinámicas) |

**Definición de default (IFRS 9):**
- DPD bucket ≥ 3 (equivalente a 90+ días de mora)
- `zero_balance_code` en `{02, 03, 09}` (venta a tercero, short sale/charge-off, REO)

---

## Configuración (`src/config.py`)

Centraliza todas las constantes del proyecto. Los módulos importan desde aquí.

| Parámetro | Valor | Descripción |
|---|---|---|
| `UMBRAL_DPD_DEFAULT` | 3 | Bucket DPD mínimo para considerar default |
| `HORIZONTE_PD_MESES` | 12 | Horizonte de predicción en meses |
| `ZERO_BALANCE_DEFAULT` | `{02, 03, 09}` | Códigos de cierre que constituyen default |
| `SENTINEL_CREDIT_SCORE` | 9999 | Valor centinela de FICO sin dato (→ NaN) |
| `AÑOS_ENTRENAMIENTO` | 2016–2020 | Partición temporal train |
| `AÑOS_VALIDACION` | 2022–2023 | Partición temporal validación |
| `AÑOS_TEST` | 2024 | Partición temporal test |

---

## Ejecución del pipeline

### Opción 1 – Pipeline completo (recomendada)

```bash
cd src
python pipeline_completo.py
```

Ejecuta los 7 pasos en orden, mide el tiempo de cada uno y guarda todos los resultados en `outputs/`.

### Opción 2 – Paso a paso

```bash
cd src
python 01_carga_datos.py
python 02_definicion_default.py
python 03_feature_engineering.py
python 04_modelado.py
python 05_calibracion_lifetime.py
python 06_validacion.py
python 07_explicabilidad.py
```

Cada paso lee el archivo de salida del paso anterior. Si se modifica un paso, solo es necesario re-ejecutar ese paso y los siguientes.

### Análisis exploratorio (opcional, no requerido por el pipeline)

```bash
cd src
python 00_eda.py
```

---

## Descripción de cada paso

### Paso 0 – EDA (`00_eda.py`)
Análisis exploratorio del dataset. Genera distribuciones de FICO, UPB, DPD, tasa de default por vintage y la relación LTV–default.

**Salida:** `outputs/figuras/eda_*.png`, `outputs/tablas/eda_*.csv`

---

### Paso 1 – Carga de datos (`01_carga_datos.py`)
- Lee `orig_all.parquet` y `svcg_all.parquet`
- Corrige valores centinela (FICO=9999 → NaN, DTI=999 → NaN, etc.)
- Parsea fechas en formato YYYYMM
- Construye el **panel longitudinal** (join left de performance con originación)
- Ordena por `loan_sequence_number` + `monthly_reporting_period`

**Entrada:** `data/orig_all.parquet`, `data/svcg_all.parquet`  
**Salida:** `data/panel.parquet`

---

### Paso 2 – Definición de default IFRS 9 (`02_definicion_default.py`)
- Crea la variable objetivo `default_12m`: indica si el préstamo entra en default dentro de los próximos 12 meses
- Asigna el **Stage IFRS 9** a cada observación mensual:
  - Stage 1: sin deterioro significativo
  - Stage 2: deterioro significativo (incremento de riesgo)
  - Stage 3: en default

**Entrada:** `data/panel.parquet`  
**Salida:** `data/panel_con_default.parquet`

---

### Paso 3 – Feature engineering (`03_feature_engineering.py`)
Genera las variables predictoras. Se dividen en dos grupos:

**Variables de originación** (estáticas, fijas al momento del préstamo):

| Variable | Descripción |
|---|---|
| `credit_score` | FICO al momento de originación |
| `original_ltv` | LTV original |
| `original_cltv` | CLTV original |
| `original_dti` | DTI original |
| `original_interest_rate` | Tasa nominal original |
| `original_loan_term` | Plazo en meses |
| `original_upb` | Monto original del préstamo |
| `number_of_borrowers` | Cantidad de deudores |
| `loan_purpose` | Propósito (P=compra, C/N=refinanciación) |
| `property_type` | Tipo de propiedad (SF, CO, PU…) |
| `occupancy_status` | Ocupación (P=primaria, I=inversión, S=segunda) |
| `channel` | Canal (R=retail, B=broker, C=correspondent) |
| `number_of_units` | Unidades (1–4) |

**Variables de comportamiento** (dinámicas, cambian cada mes):

| Variable | Descripción |
|---|---|
| `loan_age` | Edad del préstamo en meses |
| `current_interest_rate` | Tasa corriente (puede cambiar por modificación) |
| `current_actual_upb` | Saldo actual |
| `estimated_loan_to_value_eltv` | LTV estimado por AVM (disponible desde abril 2017) |
| `dpd_numerico` | DPD del período actual |
| `max_dpd_3m` | Máximo DPD en los últimos 3 meses |
| `max_dpd_6m` | Máximo DPD en los últimos 6 meses |
| `max_dpd_12m` | Máximo DPD en los últimos 12 meses |
| `fue_modificado` | Flag: el préstamo fue modificado alguna vez |
| `tiene_deferral` | Flag: tiene diferimiento de pagos |
| `spread_tasa` | Tasa corriente − tasa original |
| `amortizacion_upb` | Amortización relativa del saldo |

**Nota:** `eltv` solo está disponible desde abril 2017; los períodos anteriores quedan como NaN (no se imputa).

**Entrada:** `data/panel_con_default.parquet`  
**Salida:** `data/dataset_modelado.parquet`

---

### Paso 4 – Modelado (`04_modelado.py`)
Entrena y compara tres modelos con calibración isotónica:

| Modelo | Rol |
|---|---|
| Regresión Logística | Referencia regulatoria (interpretable) |
| XGBoost | Modelo principal (alta performance) |
| Random Forest | Ensemble alternativo |

- **Partición:** out-of-time (train: 2016–2020, val: 2022–2023, test: 2024)
- **Calibración:** IsotonicRegression post-hoc sobre el output de probabilidad
- **Métricas:** AUC-ROC, Brier Score

**Entrada:** `data/dataset_modelado.parquet`  
**Salida:** `outputs/modelos/*.joblib`, `outputs/tablas/resultados_modelos.csv`

---

### Paso 5 – Calibración Lifetime PD (`05_calibracion_lifetime.py`)
Genera los dos productos regulatorios clave de IFRS 9:

1. **PD Point-In-Time (PIT):** probabilidad de default en los próximos 12 meses, sensible al ciclo económico actual. Salida directa del modelo XGBoost calibrado.

2. **Lifetime PD:** curva de PD marginal mes a mes durante la vida restante del préstamo.  
   Fórmula: `PD_lifetime = 1 − ∏(1 − PD_marginal_t)` para `t = 1…T_restante`

**Referencia regulatoria:**
- Stage 1 → `ECL = PD_12m × LGD × EAD`
- Stage 2 → `ECL = PD_lifetime × LGD × EAD`

**Entrada:** `data/dataset_modelado.parquet`, `outputs/modelos/`  
**Salida:** `outputs/tablas/curva_pd_lifetime.csv`, `outputs/figuras/curva_pd_lifetime.png`

---

### Paso 6 – Validación regulatoria (`06_validacion.py`)
Calcula las métricas requeridas por IFRS 9, EBA y BCBS:

| Categoría | Métrica | Descripción |
|---|---|---|
| Discriminación | AUC / Gini | Separación defaulters vs. no-defaulters |
| Discriminación | KS | Máxima separación entre distribuciones acumuladas |
| Calibración | Brier Score | Error cuadrático medio de probabilidades |
| Calibración | Hosmer-Lemeshow | Bondad de ajuste por deciles de riesgo |
| Estabilidad | PSI | Deriva de la distribución del score (< 0.1 estable) |
| Backtesting | PD predicha vs. observada | Por decil de riesgo |

**PSI:** < 0.10 estable · 0.10–0.25 monitorear · > 0.25 inestable

**Entrada:** `data/dataset_modelado.parquet`, `outputs/modelos/`  
**Salida:** `outputs/tablas/validacion_*.csv`, `outputs/figuras/validacion_*.png`

---

### Paso 7 – Explicabilidad SHAP (`07_explicabilidad.py`)
Análisis de interpretabilidad en dos niveles (requerido por EBA Guidelines on Model Governance 2022):

**Nivel global** (comportamiento del modelo en toda la cartera):
- Importancia por Gain (nativa de XGBoost)
- Importancia por Permutación
- SHAP Summary Plot (beeswarm)
- SHAP Bar Plot (media |SHAP|)

**Nivel local** (explicación individual de un préstamo):
- SHAP Waterfall Plot (contribución de cada variable a la PD del préstamo)
- SHAP Force Plot (exportable a HTML)

Muestra de `5.000` observaciones del conjunto de test para SHAP (por eficiencia).

**Entrada:** `data/dataset_modelado.parquet`, `outputs/modelos/`  
**Salida:** `outputs/figuras/shap_*.png`, `outputs/tablas/importancia_*.csv`

---

## Archivos de salida generados

### Modelos (`outputs/modelos/`)
| Archivo | Descripción |
|---|---|
| `modelo_logistica.joblib` | Pipeline de Regresión Logística calibrada |
| `modelo_xgboost.joblib` | Pipeline de XGBoost calibrado (modelo principal) |
| `modelo_random_forest.joblib` | Pipeline de Random Forest calibrado |
| `features_lista.joblib` | Lista de features usados en el entrenamiento |

### Tablas (`outputs/tablas/`)
| Archivo | Descripción |
|---|---|
| `resultados_modelos.csv` | AUC y Brier Score por modelo y partición |
| `curva_pd_lifetime.csv` | PD marginal por loan age (curva Lifetime) |
| `validacion_metricas.csv` | Métricas regulatorias completas |
| `validacion_backtesting.csv` | PD predicha vs. observada por decil |
| `importancia_gain_xgboost.csv` | Importancia por Gain del modelo XGBoost |
| `importancia_shap_xgboost.csv` | Importancia media SHAP por variable |
| `eda_stats_originacion.csv` | Estadísticas descriptivas de originación |
| `eda_composicion_cartera.csv` | Composición de la cartera por categorías |

### Figuras (`outputs/figuras/`)
| Archivo | Descripción |
|---|---|
| `curva_pd_lifetime.png` | Curva de PD marginal Lifetime |
| `validacion_roc.png` | Curva ROC del modelo en test |
| `validacion_backtesting.png` | Backtesting PD predicha vs. observada |
| `shap_summary_xgboost.png` | SHAP beeswarm plot (importancia global) |
| `shap_barplot_xgboost.png` | SHAP bar plot (media |SHAP|) |
| `importancia_gain_xgboost.png` | Importancia por Gain (top variables) |
| `shap_waterfall_prestamo_*.png` | Explicación local de préstamos individuales |
| `eda_*.png` | Gráficos del análisis exploratorio |

---

## Dependencias principales

```
pandas
numpy
scikit-learn
xgboost
shap
matplotlib
joblib
pyarrow   # para leer/escribir parquet
```

---

## Notas importantes

- **No imputar ELTV:** el campo `estimated_loan_to_value_eltv` solo existe desde abril 2017. Los NaN anteriores son estructurales, no errores.
- **No usar código postal a nivel granular:** `postal_code3_trunc` está truncado a 3 dígitos; usar `property_state` para análisis geográficos.
- **El año 2021 no existe** en el dataset descargado de Freddie Mac.
- Todos los módulos deben ejecutarse desde la carpeta `src/` o con `src/` en el `sys.path`, ya que `config.py` usa rutas relativas al `__file__`.
