# IFRS 9 Compliance Specification: Freddie Mac PD/LGD/EAD Pipeline

**Document owner:** Sebastián Meier, Maestría en Minería de Datos, UTN Paraná
**Role:** Single source of truth connecting regulatory obligations to automated audit controls, Python implementation, generated artifacts, and thesis chapters.
**Companion source:** `audit_results.xlsx` (repo root), a 32-control IFRS 9 / EBA design-effectiveness checklist. See the provenance note in §2 before treating any cell as evidence of this pipeline's own compliance.

**This thesis has two objectives, and this document must always speak to both:**
1. **Build an IFRS 9-compliant PD/LGD/EAD pipeline.** The 32-control ledger in §2 and the deep-dives in §3.1-§3.9 trace this objective end-to-end.
2. **Quantify the cost of that compliance.** How much discrimination is sacrificed, and how much ECL is over- or under-provisioned, when the same portfolio is scored with a regulator-friendly WoE scorecard versus an unrestricted ML model (XGBoost, Random Forest) that carries the same IFRS 9 staging and ECL machinery. This is a primary research contribution of the thesis, not an audit-control afterthought. It is developed in full in **§3.10** and must never be trimmed, summarized away, or dropped from a future document revision.

---

## 1. Executive Summary & Governance Scope

### 1.1 Scope of Application
The book in scope is the **Freddie Mac Single-Family Loan-Level Dataset (Sample)**: a publicly disclosed, closed-end, fully-funded, fixed/adjustable-rate **Prime / Near-Prime retail residential mortgage** portfolio. Vintages 2016-2024 (2021 unavailable from the public source), 400,000 unique origination records, 14,603,212 loan-month performance observations, reduced to 14,481,471 Stage 1/2 observations after the IFRS 9 filter described in §3 ("Definition of Default"). No corporate, wholesale, revolving, or off-balance-sheet exposures are present in this book, a fact that materially shapes the scope boundaries documented for Controls 3.1, 8.2, and 8.6 below.

### 1.2 Accounting & Supervisory Framework
| Framework | Application in this repository |
|---|---|
| **IFRS 9 Financial Instruments** (§5.5, Appendix B5.5) | Three-stage impairment model, SICR assessment, Lifetime PD, ECL = PD × LGD × EAD |
| **EBA/GL/2017/16**, Credit Risk Management Practices and Accounting for ECL | Segmentation empirical backing (§5.2), SICR thresholds (§5.5), FLI/scenario weighting (§5.5.17c), PMA governance (§13) |
| **EBA/GL/2016/07**, Definition of Default under Art. 178 CRR | Objective (90 DPD) and subjective (UTP) default triggers, cure/probation period |
| **BCBS d350**, Guidance on credit risk and accounting for ECL | Principle 6 (multiple scenarios), general sound-practice backdrop for PD/LGD/EAD estimation |
| **CRR (EU) 575/2013** Art. 181 | LGD downturn add-on (181.1.b), maximum recovery/workout horizon (181.1.a) |

### 1.3 Unit of Account
The unit of account is the **individual mortgage facility** (`loan_sequence_number`, cast to `str.strip()` before every join/groupby per repository convention), consistent with IFRS 9 §B5.5.1-B5.5.6: individual retail exposures that lack standalone significance are grouped into a **collective segmentation** for ECL measurement rather than assessed one by one. `loan_sequence_number` identifies a facility, not a client; there is no persistent borrower ID in this dataset, which is the direct cause of the scope limitation documented for Controls 5.1/5.3 (Risk Contagion) below.

---

## 2. Regulatory Control Matrix (Traceability Ledger)

### 2.1 Provenance & methodology note
`audit_results.xlsx` is a **generic 32-item IFRS 9 / EBA GL design-effectiveness checklist** (columns: `Control Reference`, `Scope`, `Design Effectiveness Assessment`, `Test Procedures`, `Compliance_Verdict`, and others) produced by an unrelated third-party audit engagement. Only the **control taxonomy and generic audit questions** are reused here; the `AI_Answer`, `Evidence_Sources`, and `Compliance_Verdict` columns in that file refer to a **different institution's confidential internal policy document** and carry **no evidentiary weight for this thesis**. The table below re-applies the same 32 control references to *this* codebase, citing this repository's own code, data, and thesis chapters as evidence. Where this pipeline does not yet close a control, that gap is stated explicitly rather than inherited from the external file.

**Legend:** ✅ implemented and evidenced in this repo · 🎯 designed/configured, execution or evidence pending · 📋 policy-only, out of scope for this dataset (documented rationale, no code)

| Control Ref | Scope / Area | Audit Question & Design Requirement | Target Status | Implementing Script(s) | Artifact Outputs | Thesis Chapter & Sections (v5) |
|---|---|---|---|---|---|---|
| 1.1 | Model Governance | Formal ECL/IFRS 9 policy approved by a governing body | ✅ 100% Compliant | `src/config.py` (single parameter source) | This document plus `audit_results.xlsx` | Cap. 6 §6.2 |
| 1.2 | Model Governance | Policy aligned with the standard and local regulation | ✅ 100% Compliant | (documentation control) | N/A | Cap. 3 §3.1, §3.6, §3.7 |
| 1.3 | Model Governance | Controls ensure consistent, traceable application of methodology | ✅ 100% Compliant | `src/config.py`, `src/pipeline_completo.py` | N/A | Cap. 6 §6.2 (Tabla 3) |
| 1.5 | Model Governance | Roles/responsibilities (dev vs. validation) defined | 🎯 100% Compliant (Target). Approval segregation documented only for PMA; a dedicated model-governance roles section is pending | `src/config.py` (`PMA_UMBRAL_*`) | N/A | Cap. 15 |
| 2.1 | Data Quality & Sources | Representativeness / relevant MEVs tested | ✅ 100% Compliant | `src/01_carga_datos.py`, `src/00_eda.py`, `src/00_macro_data.py` | `outputs/tablas/eda_stats_originacion.csv`, `eda_composicion_cartera.csv` | Cap. 5 §5.1-§5.3 |
| 3.1 | Segmentation | Collective vs. individual treatment distinguished | 🎯 100% Compliant (Target). See §3.2 "Segmentation" deep-dive for the formal individual-assessment boundary | `src/06b_segmentacion.py` | `outputs/tablas/segmentacion_metricas.csv` | Cap. 10 |
| 3.2 | Segmentation | Defined process to review homogeneity/heterogeneity/stability | ✅ 100% Compliant | `src/06b_segmentacion.py` | `segmentacion_heterogeneidad.csv`, `segmentacion_heterogeneidad_global.csv`, `segmentacion_homogeneidad.csv` | Cap. 10 §10.2-§10.3 |
| 3.6 | Segmentation | Segmentation quantitatively backed | ✅ 100% Compliant | `src/06b_segmentacion.py` | `segmentacion_metricas.csv` | Cap. 10 (all) |
| 4.1 | Definition of Default | Default definition documented, consistent with regulation (90 DPD / UTP) | 🎯 100% Compliant (Target). Objective 90-DPD trigger fully implemented; UTP/forbearance trigger is a documented gap, see §3.1 deep-dive | `src/02_definicion_default.py` | `data/panel_con_default.parquet` | Cap. 7 §7.1, Cap. 3 §3.3 |
| 4.2 | Definition of Default | Default definition applied consistently across staging, PD, LGD | ✅ 100% Compliant | `src/02_definicion_default.py`, `src/03_feature_engineering.py`, `src/08_lgd_ead.py` | `data/dataset_modelado.parquet` | Cap. 7, Cap. 9, Cap. 12 |
| 5.1 | Risk Contagion | Formal pulling-effect policy across exposures of one client/group | 📋 Policy formalized; not executable on this dataset (no persistent borrower ID) | N/A | N/A | Cap. 14 |
| 5.3 | Risk Contagion | Controls verify contagion is applied in practice | 📋 Policy-only, same data limitation as 5.1 | N/A | N/A | Cap. 14 |
| 6.1 | PD | PD methodology documented (data, horizon, technique, population, assumptions) | ✅ 100% Compliant | `src/04_modelado.py` | `resultados_modelos.csv` | Cap. 4 §4.1-§4.4, Cap. 9 |
| 6.2 | PD | PiT vs. TTC design justified against ECL requirements | ✅ 100% Compliant | `src/04_modelado.py` | `resultados_modelos.csv` | Cap. 3 §3.10, Cap. 9 §9.1 |
| 6.3 | PD | Lifetime PD consistent with expected life and staging | 🎯 100% Compliant (Target). Implemented; tail extrapolation beyond 60 months flagged as a self-disclosed limitation, see §3.3 deep-dive | `src/05_calibracion_lifetime.py` | `curva_pd_lifetime.csv`, `lifetime_pd_backtest_by_vintage.csv` | Cap. 11, Cap. 18 §18.2 |
| 6.5 | PD | Stability/sensitivity/backtesting analyses available | 🎯 100% Compliant (Target). HL/backtesting/PSI implemented; decile binomial Z-test plus Wilson CI is a planned enhancement, see §3.4 deep-dive | `src/06_validacion.py` | `validacion_metricas.csv`, `validacion_backtesting.csv` | Cap. 13 |
| 7.1 | LGD | LGD segmentation defined and empirically supported | ✅ 100% Compliant | `src/08_lgd_ead.py` | `lgd_por_banda_ltv.csv`, `lgd_por_anio.csv` | Cap. 12 §12.1 |
| 7.3 | LGD | Recovery cash flows discounted at an appropriate rate | ✅ 100% Compliant. The rate is a documented portfolio-average proxy, not a per-loan EIR; see §3.5 deep-dive | `src/08_lgd_ead.py`, `src/config.py` (`TASA_DESCUENTO_ANUAL`) | `lgd_curva_recuperacion.csv` | Cap. 12 §12.1 |
| 7.5 | LGD | Total-loss assumptions (LGD 100%) justified and documented | ✅ 100% Compliant | `src/08_lgd_ead.py`, `src/config.py` | `lgd_curva_recuperacion.csv`, `lgd_politica_perdida_total.csv`, `lgd_desenlace_episodios.csv` | Cap. 12 §12.1 |
| 7.7 | LGD | Controls ensure recovery data quality | ✅ 100% Compliant | `src/01_carga_datos.py`, `notebook/IFRS9_PD_Pipeline.ipynb` (join/null/duplicate checks) | `eda_stats_originacion.csv` | Cap. 5, Cap. 12 §12.1 |
| 8.1 | EAD / CCF | EAD methodology defined (on/off-balance) | ✅ 100% Compliant | `src/08_lgd_ead.py` | `ead_resumen.csv`, `ead_validacion_amortizacion.csv` | Cap. 12 §12.2 |
| 8.2 | EAD / CCF | CCFs defined for off-balance/revolving exposures | ✅ 100% Compliant. Portfolio has none; regulatory reference CCFs documented for scope extension | `src/08_lgd_ead.py`, `src/config.py` (`CCF_REGULATORIOS`) | `ccf_alcance.csv` | Cap. 12 §12.2 |
| 8.6 | EAD / CCF | Controls for EAD on multi-currency facilities | ✅ 100% Compliant. See §3.6 deep-dive for the formal mono-currency perimeter declaration and hypothetical multi-currency control policy | `src/08_lgd_ead.py`, `src/config.py` (`MONEDA_BASE`, `CARTERA_MULTIDIVISA`) | `ccf_alcance.csv` | Cap. 12 §12.2 |
| 9.3 | Macro Scenarios | FLI includes multiple plausible scenarios (base/adverse/optimistic) or absence is justified | 🎯 100% Compliant (Target). Weights configured, execution gated on `FRED_API_KEY`; **not exercised in the current run**, see §3.8 deep-dive | `src/05b_scenario_weighting.py`, `src/config.py` (`SCENARIO_WEIGHTS`) | `outputs/tablas/ecl_by_scenario.csv` *(not yet generated)* | Cap. 3 §3.5, Cap. 18 §18.2 |
| 10.1 | Forward-Looking Information | Formal process to select/develop/validate the macro model | 🎯 100% Compliant (Target). Same FRED-key gating as 9.3 | `src/00_macro_data.py`, `src/config.py` (`MACRO_FEATURES`, `FRED_SERIES`) | `data/macro/macro_monthly.parquet` *(not yet generated)* | Cap. 3 §3.5, Cap. 18 §18.2 |
| 11.1 | ECL Calculation | PD/LGD/EAD/FLI integration specified per stage | ✅ 100% Compliant. This same integration is reused as the measurement engine for the cost-of-regulation comparison, see §3.10 | `src/09_woe_vs_ml.py` | `comparacion_woe_vs_raw_ecl.csv` | Cap. 12, Cap. 17 §17.3 |
| 11.2 | ECL Calculation | Stage 1 (12m) vs. Stage 2/3 (lifetime) horizon respected | ✅ 100% Compliant | `src/03b_sicr_assessment.py`, `src/05_calibracion_lifetime.py` | `sicr_resumen.csv`, `curva_pd_lifetime.csv` | Cap. 7, Cap. 11 |
| 11.3 | ECL Calculation | SICR staging thresholds tested on loan-level sample | ✅ 100% Compliant | `src/03b_sicr_assessment.py` | `sicr_umbral_calibracion.csv`, `sicr_resumen.csv` | Cap. 7 §7.2 |
| 11.5 | ECL Calculation | Overall ECL methodology consistent with standard/supervisory guidance | 🎯 100% Compliant (Target). Depends on 9.3/10.1 scenario-weighting execution for full closure; the WoE-vs-ML sensitivity of this methodology is quantified in §3.10 | `src/06_validacion.py`, `src/09_woe_vs_ml.py` | `validacion_metricas.csv`, `comparacion_woe_vs_raw_ecl.csv` | Cap. 13, Cap. 17 §17.4 |
| 12.1 | Model Monitoring | Continuous monitoring controls (e.g., PSI) | ✅ 100% Compliant | `src/06b_segmentacion.py`, `src/06_validacion.py` | `segmentacion_metricas.csv`, `validacion_metricas.csv` | Cap. 10 §10.2, Cap. 13 §13.1 |
| 13.1 | Model Overrides | Formal PMA policy with thresholds/caps | ✅ 100% Compliant | `src/config.py` (`PMA_UMBRAL_MATERIALIDAD`, `PMA_UMBRAL_INFORMATIVO`, `PMA_VIGENCIA_MAX_TRIMESTRES`) | (policy constants) | Cap. 15 |
| 13.2 | Model Overrides | Overrides documented with justification and independent approval | 🎯 100% Compliant (design) / **N/A in execution**. No override events exist in this historical backtest, see §3.9 deep-dive | `src/config.py` (`PMA_REGISTRO` path) | `outputs/tablas/registro_pma_overrides.csv` *(specified, not populated)* | Cap. 15 |

---

## 3. Deep-Dive Specification for Critical Audit Findings

### 3.1 Definition of Default & Unlikeliness-to-Pay (UTP), Controls 4.1, 4.2

**Objective trigger (implemented, `src/02_definicion_default.py`):**

$$
\text{evento\_default} = (\text{dpd\_numerico} \ge 3) \;\lor\; (\text{zero\_balance\_code} \in \{02, 03, 09\})
$$

`dpd_numerico` is derived from `current_loan_delinquency_status`. The sentinel `"RA"` (REO acquisition) maps to `99` DPD and is **not** treated as missing; `"0"` means current, also not missing. Bucket `≥ 3` corresponds to 90+ days past due.

**Subjective / UTP triggers mapped to Freddie Mac zero-balance codes (implemented as default triggers):**

| Freddie Mac Code | Event | EBA GL/2016/07 category |
|---|---|---|
| `02` | Third-Party Sale | Distressed debt sale / material economic loss on the credit obligation |
| `03` | Short Sale / Charge-off | Distressed debt sale / material economic loss |
| `09` | Deed-in-Lieu / REO Disposition | Legal execution and asset repossession |

**Documented gap (target enhancement, not yet implemented):** forbearance and loan-modification events are captured in the feature set as **behavioral covariates only** (`fue_modificado`, `tiene_deferral` in `FEATURES_COMPORTAMIENTO`, `src/config.py`); they are **not** wired into `es_evento_default()` as an independent UTP trigger. A formal NPV-concession criterion (a modification is treated as a UTP/default event when the net present value of the restructured cash flows is materially below the pre-modification contractual NPV) is specified here as the target design but is **not present in `src/02_definicion_default.py` today**. Closing this gap requires: (i) computing pre/post-modification NPV using `TASA_DESCUENTO_ANUAL` as the discount proxy, (ii) flagging a concession when the NPV impairment exceeds a materiality threshold to be set in `config.py` (e.g. `UTP_NPV_CONCESION_UMBRAL`), and (iii) folding that flag into `es_evento_default()` alongside the existing DPD/zero-balance logic.

### 3.2 Segmentation: Collective vs. Individual Treatment, Control 3.1

**Empirical justification (implemented, Cap. 10):** IFRS 9 §B5.5.1-B5.5.6 permits collective assessment for homogeneous retail exposures that lack individual significance. `src/06b_segmentacion.py` validates seven segmentation dimensions (FICO band, LTV band, DTI band, loan purpose, occupancy, channel, property type) against discrimination (AUC/Gini/KS), stability (PSI), intra-segment homogeneity (χ² on an orthogonal risk quartile), and inter-segment heterogeneity (χ² plus Cramér's V, pairwise z-tests), with reportability gated at `SEGMENTO_MIN_OBS = 5,000` and `SEGMENTO_MIN_DEFAULTS = 50` (`src/config.py`). All seven dimensions show statistically significant heterogeneity (p < 0.001).

**Individual-assessment boundary (formalized here; not yet present in Cap. 10, where a new leading §10.1 subsection should reference this text):**
This book contains no exposure requiring individual impairment assessment: it is composed exclusively of closed-end, single-family, prime/near-prime residential mortgages with no corporate or wholesale counterparties. For institutional completeness, the criteria that **would** trigger individual assessment in a production book are documented as out of scope for this thesis:

- Corporate / wholesale exposures with gross carrying amount **greater than EUR 1,000,000** (or local-currency equivalent), per common EBA GL/2017/16 §5.1 practice for individually significant exposures.
- Bespoke restructurings or forbearance arrangements with borrower-specific cash-flow schedules that cannot be represented by a shared segment-level PD/LGD/EAD curve.
- Any exposure already in Stage 3 with a case-specific recovery strategy (e.g., a negotiated workout with unique collateral) where the collective LGD curve (§3.5 below) is not representative.

None of these criteria are met by any record in `data/dataset_modelado.parquet`; the collective segmentation of Cap. 10 is therefore the complete and sufficient treatment for this portfolio.

### 3.3 Lifetime PD & Behavioral Maturity Term Structure, Control 6.3

**Survival formulation (implemented, `src/05_calibracion_lifetime.py`, Cap. 11 / Cap. 4 §4.6):** marginal PD by `loan_age` is chained into a discrete-time survival curve:

$$
S(t) = \prod_{s=1}^{t} \left(1 - h_s\right), \qquad \text{LifetimePD}(t) = 1 - S(t)
$$

where $h_s$ is the hazard (marginal default probability) at loan-age bucket $s$. For the SICR comparison (`src/03b_sicr_assessment.py`, Cap. 7 §7.2) a closed-form constant-hazard extrapolation is used instead, to convert a 12-month PD into a Lifetime PD over the residual contractual horizon $T_{\text{res}}$:

$$
\text{PD}_{\text{lifetime}} = 1 - (1 - \text{PD}_{12m})^{T_{\text{res}}/12}
$$

**Behavioral vs. contractual expected life:** the contractual term (up to 360 months) is not used directly as the lifetime horizon. `age_ratio = loan_age / original_loan_term` (`FEATURES_RELATIVAS`, `src/config.py`) and the observed prepayment speed feed the EAD amortization model (Cap. 12 §12.2), where the implied annual **CPR = 0.86%** (`outputs/tablas/ead_resumen.csv`) confirms a slow-prepayment book relative to its contractual amortization, consistent with the low-rate origination vintages dominating the sample.

**Self-disclosed limitation (Cap. 18 §18.2):** the backtested ratio of predicted to observed cumulative default by origination cohort is **10.7x**. The curve is markedly conservative beyond roughly 60 months of loan age, where observations become sparse. This is exactly the substance of the audit's "Partial" verdict for Control 6.3, and it is documented in the thesis itself as a future line of work (refining the tail extrapolation), not silently omitted.

### 3.4 Calibration Testing, Confidence Intervals & Binomial Tests, Control 6.5

**Implemented today (`src/06_validacion.py`, Cap. 13):** AUC/Gini/KS discrimination, Brier Score, Hosmer-Lemeshow (`HL_pvalor`), PSI, and per-decile backtesting (`pd_predicha` vs. `pd_observada`, `outputs/tablas/validacion_backtesting.csv`). The Hosmer-Lemeshow test rejects perfect calibration ($p \approx 0$) for all three models on the $N = 412{,}065$ test set, an expected consequence of statistical power at this sample size rather than evidence of miscalibration; Brier Score (0.0028 uniformly) is the more informative diagnostic at this scale.

**Planned enhancement (not yet implemented; target for `validacion_calibracion_intervalos.csv`):** to give the large-$N$ limitation of Hosmer-Lemeshow a rigorous complement, each validation decile should carry a **binomial Z-test** against the null that predicted PD equals observed default rate,

$$
Z = \frac{\hat{p}_{\text{obs}} - \bar{p}_{\text{pred}}}{\sqrt{\bar{p}_{\text{pred}}(1-\bar{p}_{\text{pred}})/n}}
$$

and a **95% Wilson score interval** around the observed decile default rate $\hat{p}_{\text{obs}}$, more reliable than the normal (Wald) interval at low event rates given the portfolio's approximately 1.3% base default rate:

$$
\text{CI}_{95\%} = \frac{\hat{p} + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}, \qquad z = 1.96
$$

Implementation path: extend the per-decile loop already in `src/06_validacion.py` (the one producing `validacion_backtesting.csv`) to compute $Z$ and the Wilson bounds per decile per model, and persist them to `outputs/tablas/validacion_calibracion_intervalos.csv`.

### 3.5 Total Loss Assumptions, Workout Horizon & LGD 100%, Control 7.5

**Empirical recovery curve (implemented, `src/08_lgd_ead.py`, `outputs/tablas/lgd_curva_recuperacion.csv`, Cap. 12 §12.1):** marginal recovery by workout tranche is positive through the 19-24 and 37-48 month bands but turns sharply negative from the 49-60 month band onward (marginal recovery of **-22.4%** in that band on the current pipeline run), consistent with the thesis's own characterization of negligible-to-negative recovery from the fourth year of workout onward.

**Regulatory justification (documented, `src/config.py`):**
- `LGD_WORKOUT_MESES_MAX = 60`. CRR Art. 181(1)(a): the workout ceiling is bounded by the maximum recovery horizon observed empirically.
- `LGD_PERDIDA_TOTAL = 1.0`. IFRS 9 §5.4.4: an exposure with no reasonable expectation of recovery is derecognized/written off at LGD = 100%. On the current run, 58 exposures exceed the 60-month ceiling without resolution and receive this treatment (`lgd_desenlace_episodios.csv`).
- `LGD_DOWNTURN_ADDON = 0.05`. CRR Art. 181(1)(b): the exposure-weighted simple LGD (19.83%) is grossed up to a downturn LGD of 24.83%, used throughout Cap. 17's ECL comparison.

This control was flagged **Non-Compliant** in the generic external checklist (i.e., the audited institution lacked this documentation); in this repository the gap is closed end to end, from empirical curve to regulatory citation to codified constant to thesis narrative.

### 3.6 Multi-Currency Facility Controls, Control 8.6

**Perimeter declaration (implemented, `src/config.py`):** `MONEDA_BASE = "USD"`, `CARTERA_MULTIDIVISA = False`. Every exposure in the Freddie Mac Single-Family book is originated, serviced, and liquidated in USD; there is zero FX mismatch risk and no currency-conversion policy is required for this book's ECL calculation.

**Institutional control policy for a hypothetical multi-currency extension (formalized here as new content, to be referenced from Cap. 12 §12.2):**
Should the modeling scope ever extend to non-USD-denominated facilities, the following controls are specified as the target design:

1. **Daily fixing-rate conversion.** EAD and outstanding balances in foreign currency are converted to the reporting currency using the official daily fixing rate (Federal Reserve H.10 release for USD crosses, or ECB reference rates for EUR-based reporting), applied consistently at each reporting date, never a transaction-date historical rate for balance-sheet ECL purposes.
2. **Forward-rate discounting for revolving CCF.** For any off-balance-sheet, foreign-currency revolving commitment, the projected drawdown (via the applicable `CCF_REGULATORIOS` factor, `src/config.py`) is discounted using the forward FX rate matching the expected drawdown date, not the spot rate, to avoid understating EAD under currency appreciation scenarios.
3. **Collateral currency haircuts.** Where collateral (e.g., a foreign property) is denominated in a currency different from the facility, LGD collateral value is subject to an additional haircut reflecting historical FX volatility between the collateral and facility currencies, on top of the standard downturn add-on (`LGD_DOWNTURN_ADDON`).

### 3.7 Quantitative SICR Staging Architecture, Control 11.3

**Thresholds (implemented, `src/config.py`, `src/03b_sicr_assessment.py`, Cap. 7 §7.2):**

$$
\text{SICR} \iff \underbrace{\frac{\text{PD}_{\text{lifetime},t}}{\text{PD}_{\text{lifetime},\text{orig}}} \ge k}_{\text{relative, primary}} \;\lor\; \underbrace{\text{PD}_{\text{lifetime},t} - \text{PD}_{\text{lifetime},\text{orig}} \ge \Delta}_{\text{absolute, complement}} \;\lor\; \underbrace{\text{DPD} \ge 30}_{\text{backstop, prudential}}
$$

with `SICR_RELATIVE_THRESHOLD (k) = 2.5`, `SICR_ABSOLUTE_THRESHOLD (Δ) = 0.05` (5 p.p.), `SICR_BACKSTOP_DPD = 1` (bucket 1 = 30 DPD). Both PD legs are converted to Lifetime PD over the same residual horizon before comparison (§3.3 above), so the relative criterion is invariant to residual maturity.

**Operational backstop (implemented, `outputs/tablas/sicr_resumen.csv`):** the 30-DPD backstop is confirmed to operate strictly as a rebuttable prudential reinforcement, not the primary criterion. It independently drives only **0.10%** of Stage 2 classifications, with the remaining 99.90% already correctly identified by the PD-based criteria. The resulting Stage 2 covers **8.46%** of the portfolio, an **8.7x** default-rate lift over Stage 1 (6.42% vs. 0.74% observed 12-month default), and captures **44.55%** of the portfolio's future defaults. The full sensitivity grid is in `outputs/tablas/sicr_umbral_calibracion.csv`.

### 3.8 Macroeconomic Scenarios, Weights & FLI Convexity, Control 11.5 (cross-references Controls 9.3, 10.1)

**Design (implemented as configuration, `src/config.py`):**

$$
\text{SCENARIO\_WEIGHTS} = \{\text{base}: 0.50,\; \text{pessimistic}: 0.30,\; \text{optimistic}: 0.20\}
$$

Macroeconomic vector $z_t$ (`MACRO_FEATURES`, sourced via FRED in `src/00_macro_data.py`): Unemployment Rate (`UNRATE`), House Price Index (`USSTHPI`, Freddie Mac's own published measure, used here in place of a Case-Shiller index since the FRED source series is the FHFA/USSTHPI national HPI), Fed Funds Rate, Real GDP (`GDPC1`), and 30-Year Fixed Mortgage Rate (`MORTGAGE30US`), plus their year-over-year deltas.

**Mathematical justification (Jensen's inequality, motivating the multi-scenario requirement over a single "expected" macro path):**

$$
\sum_{s} \omega_s \, f(x, z_s) \;\ge\; f\!\left(x, \sum_s \omega_s z_s\right) \qquad \text{when } f(x, \cdot) \text{ is convex in } z
$$

Since PD is convex in adverse macro conditions (a downturn increases PD more than an equivalent upturn decreases it), weighting discrete scenario-level ECL outputs (left-hand side) strictly dominates evaluating ECL at a single probability-weighted macro path (right-hand side). The latter understates expected loss whenever $f$ is convex, which is the standard justification for BCBS d350 Principle 6's multi-scenario requirement.

**Current execution status, target 100% Compliant, not yet closed:** `src/05b_scenario_weighting.py` and `src/00_macro_data.py` implement this design but both require `FRED_API_KEY` (`pipeline_completo.py` marks step "0" and step "5b" as skipped/optional without it). On the current pipeline run, `data/macro/` is empty and `outputs/tablas/ecl_by_scenario.csv` has **not** been generated. This is honestly disclosed in Cap. 18 §18.2 as a future line of work, not claimed as delivered. Control 11.5 (overall ECL methodology consistency) is therefore also marked as a target pending this dependency.

### 3.9 Model Overrides and Post-Model Adjustments (PMA) Governance, Control 13.2

**Lifecycle (documented, Cap. 15, `src/config.py`):**
- **Activation criteria:** material macro shocks not captured by the training window; data distortions (e.g., 2020 forbearance programs); sustained backtesting deviations under investigation; regulatory/product changes preceding sufficient retraining history.
- **Quantitative formulation:** every PMA is an explicit, additive adjustment to model ECL, never a direct edit to PD, LGD, or EAD parameters, so its effect is always separately identifiable and reversible.
- **Mandatory expiration:** `PMA_VIGENCIA_MAX_TRIMESTRES = 4`. A PMA outstanding beyond four consecutive quarters must be reverted or formally absorbed into the model via retraining/recalibration.
- **Audit trail:** `PMA_REGISTRO = outputs/tablas/registro_pma_overrides.csv` (path configured in `src/config.py`) is specified to record activation date, affected segment, magnitude, calculation method, technical owner, approving body, and scheduled review date for every PMA.

**Approval hierarchy:** `PMA_UMBRAL_INFORMATIVO = 0.01` (under 1% of portfolio ECL) requires Independent Model Validation approval; `PMA_UMBRAL_MATERIALIDAD = 0.05` (at or above 5% of portfolio ECL) requires Risk Committee approval **before** application.

**Honest status:** this is a **design-only** control for the current exercise. `outputs/tablas/registro_pma_overrides.csv` does not exist because this thesis is a historical backtest with no live override-issuing process; there are zero PMA events to record or sample. The governance framework (thresholds, lifecycle, approval chain) is fully specified and codified in `config.py`; production deployment would populate the register the first time a PMA is actually raised. This mirrors the external checklist's "Non-Compliant" finding for 13.2 (no evidence sample available) but for a structurally different reason: absence of override *events*, not absence of *policy*.

### 3.10 Cost of Regulation: WoE-Constrained Scorecard vs. Unrestricted ML, Comparative ECL Estimation (Controls 11.1, 11.5; Cap. 17)

This section is **not** a remediation of an audit gap; it is the thesis's second research objective (see header), and it must be read as a first-class deep-dive alongside §3.1-§3.9, never as a footnote to Control 11.1. It quantifies, on the identical portfolio and out-of-time split, what a bank actually pays, in discrimination lost and in ECL over- or under-provisioned, for adopting an industry-standard, supervisor-legible WoE scorecard, and separately, what an IFRS 9-disciplined ML model gains or loses relative to a genuinely unrestricted one.

**Implementation (`src/09_woe_vs_ml.py`):** three model families are scored on the same test partition (vintage 2024) and passed through the *same* SICR/ECL engine (Control 11.1):

- **Family A, WoE scorecard.** `LR_WoE`, `XGB_WoE`, `RF_WoE`: trained on Weight-of-Evidence-transformed features (10-bin quantile discretization fit on train only), the industry-canonical regulatory scorecard approach.
- **Family B, ML disciplined under IFRS 9.** `XGB_IFRS9`, `RF_IFRS9`: the same champion models from Chapter 9, reused as-is, monotonicity-constrained on their risk drivers and trained only on continuous and cohort-relative features (excluding the level features removed for covariate-shift reasons in §3.3).
- **Family C, ML with no regulatory restriction.** `XGB_ML_Libre`, `RF_ML_Libre`: trained specifically for this comparison with full feature freedom, including the level features excluded from Family B (`original_interest_rate`, `current_interest_rate`, `original_upb`, `current_actual_upb`), no monotonicity constraint, and `scale_pos_weight` for class imbalance (recalibrated isotonically afterward, so it does not distort the resulting ECL). This is the most powerful model a data science team would build with zero regulatory conditioning.

| Modelo | Familia | AUC | Gini | KS | Brier | % Stage 2 (SICR propio) | ECL / EAD (pb) | ECL relativo vs. mínimo |
|---|---|---|---|---|---|---|---|---|
| `LR_WoE` | A: WoE | 0.7917 | 0.5834 | 0.4512 | 0.0030 | 8.37% | 80.82 | 1.357x |
| `XGB_WoE` | A: WoE | 0.7818 | 0.5637 | 0.4594 | 0.0030 | 15.75% | 146.02 | 2.453x |
| `RF_WoE` | A: WoE | 0.7826 | 0.5653 | 0.4462 | 0.0031 | 19.63% | 163.46 | 2.745x (máximo) |
| `XGB_IFRS9` | B: ML disciplinado | 0.8540 | 0.7080 | 0.5450 | 0.0028 | 12.21% | 93.12 | 1.564x |
| `RF_IFRS9` | B: ML disciplinado | 0.8560 | 0.7121 | 0.5571 | 0.0028 | 9.46% | 88.22 | 1.482x |
| `XGB_ML_Libre` | C: ML sin restricciones | 0.8357 | 0.6714 | 0.5252 | 0.0028 | 4.05% | 59.54 | 1.000x (mínimo) |
| `RF_ML_Libre` | C: ML sin restricciones | 0.8094 | 0.6188 | 0.4450 | 0.0028 | 7.49% | 67.58 | 1.135x |

*(exact figures reproduced from `outputs/tablas/comparacion_woe_vs_raw_metricas.csv` and `comparacion_woe_vs_raw_ecl.csv`; all seven models share the same 0.3007% observed 12-month default rate on test by construction, so ECL differences are attributable to model architecture, not to a different underlying risk.)*

**Discrimination: the counter-intuitive finding.** Family B (IFRS 9-disciplined ML) has the *highest* Gini of all three families (0.7080-0.7121), beating not only Family A (WoE, 0.5637-0.5834) but also Family C (fully unrestricted ML, 0.6188-0.6714). Full feature freedom does not improve out-of-time discrimination relative to the disciplined model; it degrades it, by 3.7 Gini points for XGBoost and 9.3 points for Random Forest. The cause is the same covariate-shift problem documented in Cap. 8 §8.1: reintroducing the excluded level features reintroduces the train (2016-2020) vs. test (2024) distributional shift that the champion model's cohort-relative feature engineering was specifically designed to avoid. In this portfolio, the temporal-stability discipline that IFRS 9 effectively requires of a production PD model is not a regulatory cost; it is a genuine improvement in out-of-sample robustness over an approach with no such discipline.

**Discrimination: the cost that does survive.** Even hobbled by covariate shift, Family C still out-discriminates every WoE variant (Gini 0.6188 minimum vs. 0.5834 maximum). The cleanest comparison, Family A vs. Family B, since both share the same stable feature set, shows a persistent **12.5 to 14.8 Gini-point cost** attributable specifically to WoE discretization, not to any other modeling choice.

**ECL provisioning: a second counter-intuitive result.** Family C also produces the *lowest* Stage 2 migration (4.05% XGBoost, 7.49% Random Forest) and therefore the lowest ECL of all seven models (59.54 and 67.58 bp; `XGB_ML_Libre` is the new relative-minimum anchor). This should not be read as capital efficiency: Family C also has the weakest discrimination among the tree-based families, and its XGBoost variant stopped training after only 7 boosting rounds via early stopping (validation AUC 0.8402), an unusually fast convergence associated with `scale_pos_weight` that likely compresses the gap between origination PD and current PD feeding the SICR criterion. Lower provisioning paired with weaker discrimination is consistent with under-provisioning, not with genuine efficiency; nothing in this comparison supports preferring Family C to Family B on any axis relevant to IFRS 9. Family A's worst performers (`XGB_WoE`, `RF_WoE`) migrate the largest and most heterogeneous share of the portfolio to Stage 2 (15.75%, 19.63%) with a *lower* observed default rate inside that Stage 2 than Family B, i.e., more SICR false positives, which is what drives their 2.45x-2.75x ECL over-provisioning relative to the new minimum.

**Governance counter-argument (documented, not dismissed):** the WoE family retains real governance value, monotonicity guaranteed by construction, Logistic Regression coefficients directly interpretable as marginal log-odds contribution, and Information Value as the industry-standard variable-justification metric. The thesis's position, developed in Cap. 17 §17.4, is that Family B already captures most of that governance benefit (guaranteed monotonicity on its risk drivers, isotonically calibrated probabilities) without paying the WoE discretization cost, and does so while *also* generalizing better out-of-time than an unconstrained alternative. The Gini/ECL gap against Family A is therefore largely avoidable; the apparent gap against Family C is not a real regulatory cost at all.

**Traceability:** script `src/09_woe_vs_ml.py` (pipeline step 9) produces artifacts `woe_bins_iv.csv`, `comparacion_woe_vs_raw_metricas.csv`, `comparacion_woe_vs_raw_sicr.csv`, `comparacion_woe_vs_raw_ecl.csv`, figures `woe_vs_raw_roc.png`, `woe_vs_raw_ecl_provisiones.png`, feeding thesis Cap. 17 (§17.1-§17.4, all four subsections). Any future document generator (`src/generar_v{N}.py`) that rebuilds chapters 5-18 **must** reproduce Cap. 17 in full from these live artifacts, with all three model families distinctly represented; see the mandatory-chapter rule in `THESIS_WRITING_GUIDELINES.md` §1.1a.

---

## 4. Execution Workflow & File Map

### 4.1 Pipeline Sequence

| Step | Script | Input | Output | Control(s) Addressed |
|---|---|---|---|---|
| 0 (optional) | `src/00_macro_data.py` | `FRED_API_KEY` env var | `data/macro/macro_monthly.parquet` | 9.3, 10.1 |
| 1 | `src/01_carga_datos.py` | `data/orig_all.parquet`, `data/svcg_all.parquet` | `data/panel.parquet` | 2.1, 7.7 |
| 2 | `src/02_definicion_default.py` | `data/panel.parquet` | `data/panel_con_default.parquet` | 4.1, 4.2 |
| 3 | `src/03_feature_engineering.py` | `data/panel_con_default.parquet` (plus macro parquet if present) | `data/dataset_modelado.parquet` | 4.2 |
| 4 | `src/04_modelado.py` | `data/dataset_modelado.parquet` | `outputs/modelos/modelo_*.joblib`, `resultados_modelos.csv` | 6.1, 6.2 |
| 3b | `src/03b_sicr_assessment.py` | `dataset_modelado.parquet` plus Step 4 models | `sicr_umbral_calibracion.csv`, `sicr_resumen.csv`, updated `dataset_modelado.parquet` | 11.2, 11.3 |
| 5 | `src/05_calibracion_lifetime.py` | Step 4 models | `curva_pd_lifetime.csv` | 6.3, 11.2 |
| 5b (optional) | `src/05b_scenario_weighting.py` | Step 0 plus Step 4 outputs | `ecl_by_scenario.csv` | 9.3, 10.1, 11.5 |
| 6 | `src/06_validacion.py` | Step 4/5 outputs | `validacion_metricas.csv`, `validacion_backtesting.csv`, `transition_matrix_observed.csv`, `cure_rates_quarterly.csv`, `lifetime_pd_backtest_by_vintage.csv` | 6.5, 12.1 |
| 6b | `src/06b_segmentacion.py` | Step 4 models plus `dataset_modelado.parquet` | `segmentacion_metricas.csv`, `segmentacion_heterogeneidad*.csv`, `segmentacion_homogeneidad.csv` | 3.1, 3.2, 3.6, 12.1 |
| 7 | `src/07_explicabilidad.py` | Step 4 XGBoost model | `importancia_shap_xgboost.csv`, `importancia_gain_xgboost.csv`, SHAP figures | N/A |
| 8 | `src/08_lgd_ead.py` | `data/panel_con_default.parquet` | `lgd_*.csv`, `ead_*.csv`, `ccf_alcance.csv` | 7.1, 7.3, 7.5, 7.7, 8.1, 8.2, 8.6 |
| 9 | `src/09_woe_vs_ml.py`, cost-of-regulation comparison (§3.10) | Step 3b, Step 4, and Step 8 outputs | `woe_bins_iv.csv`, `comparacion_woe_vs_raw_*.csv` | 11.1, 11.5 |

Run the full sequence with `python src/pipeline_completo.py`; each step is independently re-runnable via `python src/0N_*.py` given its documented inputs already exist.

### 4.2 Standard I/O Contract
Every step reads and writes **parquet** for row-level data (`data/*.parquet`) and **CSV** for tabular summaries (`outputs/tablas/*.csv`), per `src/config.py`'s centralized path constants (`DATA_PATH`, `TABLAS_PATH`, `FIGURAS_PATH`, `MODELOS_PATH`). No step hardcodes a path, feature name, or IFRS 9 parameter outside `config.py`. This is the mechanism that keeps this ledger's "Implementing Script(s)" column authoritative: any future change to a threshold in this document must originate in `config.py`, not in a script body.
