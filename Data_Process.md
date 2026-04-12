# Data Process – Technical Documentation

**Project:** IFRS 9 PD Prediction – Freddie Mac Single-Family Loan-Level Dataset  
**Scope:** All data transformations from raw `.txt` files to `dataset_modelado.parquet` (the input to the ML models).

---

## Overview

The data pipeline consists of four sequential stages:

```
data_sample_year/sample_YYYY/*.txt
        │
        ▼  data_reader.py
data/orig_all.parquet
data/svcg_all.parquet
        │
        ▼  01_carga_datos.py
data/panel.parquet
        │
        ▼  02_definicion_default.py
data/panel_con_default.parquet
        │
        ▼  03_feature_engineering.py
data/dataset_modelado.parquet   ← input to the ML models
```

---

## Stage 0 – Raw Data Ingestion (`data_reader.py`)

### Source files

Freddie Mac distributes two pipe-delimited (`|`) text files per vintage year, with **no header row**, under `data_sample_year/sample_YYYY/`:

| File | Description | Rows per year |
|---|---|---|
| `sample_orig_YYYY.txt` | Origination data – one row per loan | ~50,000 |
| `sample_svcg_YYYY.txt` | Monthly performance data – one row per loan × month | ~3–5M |

Both files conform to **Release 44 (July 2025)** of the Freddie Mac User Guide, with 32 columns each.

### Read strategy

All columns are initially read as `dtype=str` to avoid pandas type inference errors on mixed-type fields (e.g., `current_loan_delinquency_status` which can be `"0"`, `"RA"`, or `NaN`). Only explicit blanks (`""`) are treated as `NaN` at read time; all other sentinel values are handled in a dedicated step.

```python
pd.read_csv(path, sep="|", header=None, names=col_names,
            dtype=str, na_values=[""], keep_default_na=False)
```

### Sentinel replacement

The User Guide defines numeric sentinel codes that mean "Not Available" rather than a real measurement. These are replaced with `pd.NA` before numeric casting.

**Origination sentinels:**

| Column | Sentinel | Meaning |
|---|---|---|
| `credit_score` | `9999` | FICO not available |
| `mi_percent` | `999` | MI percentage not available |
| `number_of_units` | `99` | Number of units not available |
| `occupancy_status` | `9` | Occupancy not available |
| `original_cltv` | `999` | CLTV not available |
| `original_dti` | `999` | DTI not available |
| `original_ltv` | `999` | LTV not available |
| `channel` | `9` | Channel not available |
| `property_type` | `99` | Property type not available |
| `number_of_borrowers` | `99` | Borrower count not available |
| `property_valuation_method` | `9` | Valuation method not available |
| `loan_purpose` | `9` | Loan purpose not available |

**Performance sentinels:**

| Column | Sentinel | Meaning |
|---|---|---|
| `estimated_loan_to_value_eltv` | `999` | ELTV not available |
| `net_sale_proceeds` | `"U"` | Net sale proceeds unknown |

> **Note:** `current_loan_delinquency_status = "0"` means *current* (no delinquency), not missing. It is NOT a sentinel.

### Numeric casting

After sentinel replacement, designated columns are cast from `str` to `float` using `pd.to_numeric(..., errors="coerce")`. Any unparseable residual value becomes `NaN`.

**Origination numeric columns:** `credit_score`, `msa_md_code`, `mi_percent`, `number_of_units`, `original_cltv`, `original_dti`, `original_upb`, `original_ltv`, `original_interest_rate`, `original_loan_term`, `number_of_borrowers`, `property_valuation_method`

**Performance numeric columns:** `current_actual_upb`, `loan_age`, `remaining_months_to_legal_maturity`, `current_interest_rate`, `current_non_interest_bearing_upb`, `mi_recoveries`, `non_mi_recoveries`, `total_expenses`, `legal_costs`, `maintenance_preservation_costs`, `taxes_and_insurance`, `misc_expenses`, `actual_loss_calculation`, `cumulative_modification_cost`, `estimated_loan_to_value_eltv`, `zero_balance_removal_upb`, `delinquent_accrued_interest`, `current_month_modification_cost`, `interest_bearing_upb`

### Column added at read time

- `vintage_year` (int): year extracted from the folder name `sample_YYYY/`, added to both origination and performance DataFrames before concatenation.

### Multi-year concatenation

All vintage DataFrames are concatenated in a single pass:

```python
pd.concat(lst_orig, ignore_index=True)  → orig_all.parquet
pd.concat(lst_svcg, ignore_index=True)  → svcg_all.parquet
```

**Output schema:**
- `orig_all.parquet`: 32 columns + `vintage_year` | ~450,000 rows (9 years × ~50K loans)
- `svcg_all.parquet`: 32 columns + `vintage_year` | ~30–40M rows

---

## Stage 1 – Load and Build Panel (`01_carga_datos.py`)

### Column normalization

Parquets generated via the legacy R reader (`data_reader.R`) carry version suffixes on column names (e.g., `credit_score_V1`). A regex strip removes them:

```python
df.columns = [re.sub(r"_V\d+$", "", c) for c in df.columns]
```

Additionally, the column `year` is renamed to `vintage_year` if the suffixed name is absent.

### Additional sentinel cleanup (origination)

A second pass of sentinel replacement is applied to the origination parquet as a safety net (in case the parquet was generated by the R reader, which does not apply all sentinel replacements). The mappings mirror those in `data_reader.py`:

| Column | Sentinel → NaN |
|---|---|
| `credit_score` | 9999 |
| `mi_percent` | 999 |
| `number_of_units` | 99 |
| `original_cltv` | 999 |
| `original_dti` | 999 |
| `original_ltv` | 999 |
| `number_of_borrowers` | 99 |
| `property_valuation_method` | 9 |

### Date parsing

Date columns stored as YYYYMM integers or strings are converted to `datetime64` (first day of the month) using:

```python
pd.to_datetime(col.astype(str).str[:6], format="%Y%m", errors="coerce")
```

**Origination date columns parsed:** `first_payment_date`, `maturity_date`  
**Performance date columns parsed:** `monthly_reporting_period`, `zero_balance_effective_date`, `defect_settlement_date`, `ddlpi_due_date_last_paid_installment`

### Postal code normalization

`postal_code3_trunc` is zero-padded to 5 characters as string (`str.zfill(5)`) to preserve the `###00` format intended by Freddie Mac (last 2 digits are always `00`).

> This column is NOT used as a model feature. Only `property_state` is used for geographic analysis.

### Join key normalization

`loan_sequence_number` is cast to `str` and stripped of whitespace in both DataFrames before the join to avoid silent key mismatches.

### Panel construction (left join)

The longitudinal panel is built as a **left join** of performance onto origination:

```
panel = svcg LEFT JOIN orig ON loan_sequence_number
```

This keeps all monthly performance observations, attaching static origination attributes to each row. If a loan has no origination record (data quality issue), origination columns will be NaN.

The resulting panel has one row per `(loan_sequence_number, monthly_reporting_period)`.

**`vintage_year` resolution:** if the merge produces both `vintage_year` (from performance) and `vintage_year_orig` (from origination), the origination value is kept as the authoritative vintage and the performance version is dropped.

### Temporal ordering

The panel is sorted by `(loan_sequence_number, monthly_reporting_period)` ascending. This ordering is required for all subsequent rolling-window operations (Step 3).

**Output:** `data/panel.parquet`

---

## Stage 2 – IFRS 9 Default Definition (`02_definicion_default.py`)

### DPD numeric conversion

`current_loan_delinquency_status` is an alphanumeric field. Valid values:

| Value | Meaning |
|---|---|
| `"0"` | Current (no delinquency) |
| `"1"`, `"2"`, … | Months delinquent (DPD bucket) |
| `"RA"` | REO Acquisition (real estate owned) |

**Transformation:**
- `"RA"` → `99` (treated as severe default, above the 3-bucket threshold)
- All numeric strings → `int`
- Unparseable values → `NaN`

```python
pd.to_numeric(serie.replace("RA", 99), errors="coerce")
```

New column: **`dpd_numerico`** (`float`, nullable)

### Default event flag

A binary default event is defined for each observation using two independent criteria (union):

```
evento_default = (dpd_numerico >= 3)  OR  (zero_balance_code IN {"02","03","09"})
```

| Criterion | Threshold | Regulatory basis |
|---|---|---|
| DPD bucket | ≥ 3 (equivalent to 90+ days past due) | IFRS 9 / Basel III |
| Zero Balance Code | `02` = Third Party Sale | IFRS 9 |
|  | `03` = Short Sale or Charge-Off | IFRS 9 |
|  | `09` = REO Disposition | IFRS 9 |

`NaN` in either field is treated as non-default (`fillna(False)`).

New column: **`evento_default`** (`bool`)

### IFRS 9 Stage assignment

Each monthly observation is classified into one of three IFRS 9 stages:

| Stage | Condition | Economic meaning |
|---|---|---|
| Stage 1 | DPD = 0 | No significant credit deterioration |
| Stage 2 | 1 ≤ DPD ≤ 2 (SICR) | Significant Increase in Credit Risk |
| Stage 3 | `evento_default = True` | Credit-impaired (in default) |

```python
stage = 1  (default)
stage = 2  where dpd_numerico in {1, 2}
stage = 3  where evento_default == True
```

New column: **`ifrs9_stage`** (`Int8`)

### Forward-looking target variable: `default_12m`

For each observation `(loan, t)`, the binary target is:

```
default_12m(t) = 1  if  ∃ s ∈ (t, t+12] such that evento_default(loan, s) = 1
             = 0  otherwise
```

This is implemented with a **vectorized O(N) algorithm** (no Python loops):

1. Cast `evento_default` to `int` → `_ev_int`
2. Within each loan group, reverse the time series
3. Apply a rolling max over a window of 12 periods on the reversed series
4. Shift by 1 to exclude the current period (lookahead only)
5. Reverse back to original order

```python
def _lookahead_max(x):
    rev   = x.iloc[::-1]
    roll  = rev.rolling(window=12, min_periods=1).max()
    shift = roll.shift(1)          # exclude current period
    return shift.iloc[::-1]
```

Result is clipped to `[0, 1]` and cast to `int`.

> **Design decision:** the current period itself is excluded from the lookahead window (`shift(1)`). This ensures the model only predicts *future* defaults, not the current state already captured by `dpd_numerico` and `ifrs9_stage`.

New column: **`default_12m`** (`int`, 0 or 1)

**Output:** `data/panel_con_default.parquet`

---

## Stage 3 – Feature Engineering (`03_feature_engineering.py`)

### Column selection and memory optimization

Only the 26 columns needed for modeling are read from the parquet (using `pyarrow`'s column projection), reducing peak RAM usage significantly vs. loading the full ~64-column panel.

All `float64` columns are downcast to `float32` immediately after loading:

```python
for col in df.select_dtypes("float64").columns:
    df[col] = df[col].astype("float32")
```

This reduces memory footprint by ~50% with no loss of precision for the model.

---

### F1 – Rolling DPD features (behavioral, lookback windows)

Three features capture the maximum delinquency bucket observed in the recent history of each loan. Windows are backward-looking (historial), applied within each loan group in chronological order.

| Feature | Formula | Window |
|---|---|---|
| `max_dpd_3m` | `max(dpd_numerico)` over last 3 months | 3 periods |
| `max_dpd_6m` | `max(dpd_numerico)` over last 6 months | 6 periods |
| `max_dpd_12m` | `max(dpd_numerico)` over last 12 months | 12 periods |

```python
grp = df.groupby("loan_sequence_number", sort=False)["dpd_numerico"]
df["max_dpd_3m"]  = grp.transform(lambda x: x.rolling(3,  min_periods=1).max())
df["max_dpd_6m"]  = grp.transform(lambda x: x.rolling(6,  min_periods=1).max())
df["max_dpd_12m"] = grp.transform(lambda x: x.rolling(12, min_periods=1).max())
```

`min_periods=1` ensures that early loan observations (loan age < window size) still receive a value based on available history.

**Predictive rationale:** recency and persistence of delinquency are among the strongest predictors of future default. The three windows capture short-term (3M), medium-term (6M), and long-term (12M) behavioral risk signals.

---

### F2 – Interest rate spread (`spread_tasa`)

```python
spread_tasa = current_interest_rate - original_interest_rate
```

| Value | Interpretation |
|---|---|
| `spread_tasa < 0` | Rate was reduced (loan modification, HAMP-type program) |
| `spread_tasa = 0` | No change (fixed-rate, unmodified ARM) |
| `spread_tasa > 0` | Rate increased (ARM reset or step modification) |

**Predictive rationale:** a negative spread indicates the servicer has already intervened to reduce the borrower's payment burden, which signals prior distress. A positive spread (ARM reset) signals increasing payment burden.

---

### F3 – Relative UPB amortization (`amortizacion_upb`)

```python
amortizacion_upb = 1.0 - (current_actual_upb / original_upb)
amortizacion_upb = clip(amortizacion_upb, 0, 1)
```

| Value | Interpretation |
|---|---|
| ≈ 0 | Loan barely amortized (early life or interest-only) |
| ≈ 1 | Loan nearly paid off |

Division by zero is avoided by replacing `original_upb = 0` with `NaN` before the operation. The clip `[0, 1]` corrects for floating-point rounding that could produce values slightly outside this range.

**Predictive rationale:** loans with low amortization have higher outstanding balances relative to original value, contributing to higher loss severity and, in some segments, higher default propensity.

---

### F4 – Binary flags

**`fue_modificado`** – loan has ever been modified:

```python
fue_modificado = 1  if  modification_flag in {"Y", "P"}  else 0
```

| Flag value | Meaning |
|---|---|
| `Y` | Modified in current period |
| `P` | Modified in a prior period |
| blank / other | Never modified |

**`tiene_deferral`** – loan has deferred payments (COVID / disaster-related):

```python
tiene_deferral = 1  if  payment_deferral_flag in {"Y", "P"}  else 0
```

Both are cast to `Int8` (nullable integer).

**Predictive rationale:** both flags indicate that the borrower has experienced financial stress severe enough to require servicer intervention. They act as permanent marks in the loan history, not transient states.

---

### F5 – ELTV treatment

`estimated_loan_to_value_eltv` (Estimated Loan-to-Value) is an AVM-derived value added by Freddie Mac starting in **April 2017**. Observations before that date have structurally missing ELTV.

The additional sentinel `999` (= "Unknown" in the User Guide) is replaced with `NaN`:

```python
df["estimated_loan_to_value_eltv"] = df["estimated_loan_to_value_eltv"].replace(999, np.nan)
```

No imputation is performed at this stage. The downstream sklearn pipeline handles ELTV missingness via `SimpleImputer`. The rationale for not imputing here is to preserve the distinction between "pre-2017 structural absence" and "post-2017 unknown".

---

### F6 – Categorical encoding

Five categorical features are label-encoded using pandas `Categorical.codes`. This maps each category string to a non-negative integer, with `-1` assigned to `NaN`.

```python
for col in ["loan_purpose", "property_type", "occupancy_status",
            "channel", "amortization_type"]:
    df[col] = pd.Categorical(df[col]).codes
```

| Feature | Original values | Encoded |
|---|---|---|
| `loan_purpose` | `P` (purchase), `C` / `N` (refinance) | 0, 1, 2 |
| `property_type` | `SF`, `CO`, `PU`, `MH`, … | 0, 1, 2, … |
| `occupancy_status` | `P` (primary), `I` (investment), `S` (second home) | 0, 1, 2 |
| `channel` | `R` (retail), `B` (broker), `C` (correspondent) | 0, 1, 2 |
| `amortization_type` | `FRM`, `ARM` | 0, 1 |

> **Note for Logistic Regression:** the sklearn pipeline for the logistic model applies `OneHotEncoder` on top of these codes to avoid imposing ordinal relationships. XGBoost and Random Forest handle integer-coded categoricals natively.

---

### F7 – Observation filter (Stage 1 and 2 only)

The final dataset retains **only Stage 1 and Stage 2 observations**. Stage 3 rows (loans currently in default) are excluded because:

1. The target `default_12m` is always 1 for Stage 3 (the loan is already in default), adding no predictive information.
2. IFRS 9 ECL for Stage 3 is calculated as the full lifetime loss (not PD-based), so these loans fall outside the model's intended use.

```python
df = df[df["ifrs9_stage"].isin([1, 2])]
```

---

## Final dataset schema (`dataset_modelado.parquet`)

### Identifier and metadata columns (not used as features)

| Column | Type | Description |
|---|---|---|
| `loan_sequence_number` | str | Loan identifier |
| `monthly_reporting_period` | datetime | Observation date |
| `vintage_year` | int | Year of loan origination |
| `ifrs9_stage` | Int8 | Stage 1 or 2 |

### Target variable

| Column | Type | Values | Description |
|---|---|---|---|
| `default_12m` | int | 0 / 1 | Default event within next 12 months |

### Feature set – origination (static, fixed at loan origination)

| Feature | Type | Source | Notes |
|---|---|---|---|
| `credit_score` | float32 | `orig` | FICO at origination; NaN if sentinel 9999 |
| `original_ltv` | float32 | `orig` | LTV at origination |
| `original_cltv` | float32 | `orig` | Combined LTV at origination |
| `original_dti` | float32 | `orig` | Debt-to-income at origination |
| `original_interest_rate` | float32 | `orig` | Nominal rate at origination |
| `original_loan_term` | float32 | `orig` | Term in months |
| `original_upb` | float32 | `orig` | Original unpaid principal balance |
| `number_of_borrowers` | float32 | `orig` | Count of borrowers (1 or 2) |
| `loan_purpose` | int8 | `orig` | Label-encoded: purchase / refinance |
| `property_type` | int8 | `orig` | Label-encoded: SF, CO, PU, MH… |
| `occupancy_status` | int8 | `orig` | Label-encoded: primary / investment / second |
| `channel` | int8 | `orig` | Label-encoded: retail / broker / correspondent |
| `number_of_units` | float32 | `orig` | 1–4 residential units |

### Feature set – behavioral (dynamic, updated each month)

| Feature | Type | Source | Derived | Notes |
|---|---|---|---|---|
| `loan_age` | float32 | `perf` | No | Months since first payment |
| `current_interest_rate` | float32 | `perf` | No | Current rate (post-modification) |
| `current_actual_upb` | float32 | `perf` | No | Current outstanding balance |
| `estimated_loan_to_value_eltv` | float32 | `perf` | No | AVM-based LTV; NaN before Apr 2017 |
| `dpd_numerico` | float32 | `perf` | Partial | Numeric DPD; "RA" → 99 |
| `max_dpd_3m` | float32 | `perf` | **Yes** | Max DPD over last 3 months |
| `max_dpd_6m` | float32 | `perf` | **Yes** | Max DPD over last 6 months |
| `max_dpd_12m` | float32 | `perf` | **Yes** | Max DPD over last 12 months |
| `fue_modificado` | Int8 | `perf` | **Yes** | Ever modified flag |
| `tiene_deferral` | Int8 | `perf` | **Yes** | Payment deferral flag |
| `spread_tasa` | float32 | `perf` | **Yes** | current_rate − original_rate |
| `amortizacion_upb` | float32 | `perf` | **Yes** | 1 − (current_upb / original_upb) |

---

## Temporal partitioning

The dataset is split by `vintage_year` for out-of-time validation (no data leakage across partitions):

| Partition | Vintages | Purpose |
|---|---|---|
| Training | 2016, 2017, 2018, 2019, 2020 | Model fitting |
| Validation | 2022, 2023 | Hyperparameter tuning, early stopping |
| Test | 2024 | Final out-of-time evaluation |

> Vintage 2021 does not exist in the downloaded dataset and is excluded from all partitions.

---

## Missing value handling summary

| Column | Source of missingness | Strategy |
|---|---|---|
| `credit_score` | Sentinel 9999 → NaN at read | `SimpleImputer(median)` in sklearn pipeline |
| `original_dti` | Sentinel 999 → NaN at read | `SimpleImputer(median)` |
| `original_ltv`, `original_cltv` | Sentinel 999 → NaN at read | `SimpleImputer(median)` |
| `estimated_loan_to_value_eltv` | Structural (pre-Apr 2017) + sentinel 999 | `SimpleImputer(median)` |
| `number_of_borrowers` | Sentinel 99 → NaN at read | `SimpleImputer(most_frequent)` |
| `max_dpd_*` | Cannot be NaN after rolling (min_periods=1) | N/A |
| `spread_tasa` | NaN if either rate is NaN | Propagated NaN → imputed in pipeline |
| `amortizacion_upb` | NaN if `original_upb = 0` | Rare edge case; imputed in pipeline |
| Categorical codes | `-1` assigned to original NaN | Treated as a separate category by tree models |

---

## Invariants enforced throughout the pipeline

1. `loan_sequence_number` is always `str.strip()` before any join or group operation.
2. All date parsing uses `errors="coerce"` — unparseable dates become `NaT`, never crash.
3. Sentinel values are replaced **before** numeric casting, so no sentinel appears as a numeric value in the final dataset.
4. The target `default_12m` is built exclusively from forward-looking information: no future data leaks into the feature set.
5. Stage 3 observations are removed before saving, ensuring the model is never trained on loans that are already in default.
6. Float columns use `float32` throughout the feature engineering step to bound RAM usage.
