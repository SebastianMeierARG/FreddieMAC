"""
FreddieMAC Single-Family Loan-Level Dataset – Python data reader
Reads sample_orig_YYYY.txt and sample_svcg_YYYY.txt from data_sample_year/
Outputs orig_all.parquet and svcg_all.parquet to data/

User Guide: Release 44 (July 2025) – 32 columns each file, pipe-delimited, no header.
"""

import re
import warnings
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_PATH = Path(__file__).parent
DATA_SAMPLE_PATH = BASE_PATH / "data_sample_year"
OUTPUT_PATH = BASE_PATH / "data"

# ---------------------------------------------------------------------------
# Column names – exactly as in User Guide (positions 1–32)
# ---------------------------------------------------------------------------
ORIG_COLS = [
    "credit_score",                   # 1  Numeric 4
    "first_payment_date",             # 2  Date YYYYMM
    "first_time_homebuyer_flag",      # 3  Alpha 1
    "maturity_date",                  # 4  Date YYYYMM
    "msa_md_code",                    # 5  Numeric 5
    "mi_percent",                     # 6  Numeric 3
    "number_of_units",                # 7  Numeric 2
    "occupancy_status",               # 8  Alpha 1
    "original_cltv",                  # 9  Numeric 3
    "original_dti",                   # 10 Numeric 3
    "original_upb",                   # 11 Numeric 12
    "original_ltv",                   # 12 Numeric 3
    "original_interest_rate",         # 13 Numeric literal decimal
    "channel",                        # 14 Alpha 1
    "prepayment_penalty_flag",        # 15 Alpha 1
    "amortization_type",              # 16 Alpha 5
    "property_state",                 # 17 Alpha 2
    "property_type",                  # 18 Alpha 2
    "postal_code3_trunc",             # 19 Numeric 5 (###00, keep as string)
    "loan_sequence_number",           # 20 Alpha-numeric 12 (JOIN key)
    "loan_purpose",                   # 21 Alpha 1
    "original_loan_term",             # 22 Numeric 3
    "number_of_borrowers",            # 23 Numeric 2
    "seller_name",                    # 24 Alpha-numeric 60
    "servicer_name",                  # 25 Alpha-numeric 60
    "super_conforming_flag",          # 26 Alpha 1
    "pre_relief_refi_loan_seq_num",   # 27 Alpha-numeric 12
    "special_eligibility_program",    # 28 Alpha-numeric 1
    "relief_refinance_indicator",     # 29 Alpha 1
    "property_valuation_method",      # 30 Numeric 1
    "interest_only_indicator",        # 31 Alpha 1
    "mi_cancellation_indicator",      # 32 Alpha/Numeric 1
]

PERF_COLS = [
    "loan_sequence_number",                    # 1  Alpha-numeric 12 (JOIN key)
    "monthly_reporting_period",                # 2  Date YYYYMM
    "current_actual_upb",                      # 3  Numeric literal decimal
    "current_loan_delinquency_status",         # 4  Alpha-numeric 3 (0,1,2…,RA)
    "loan_age",                                # 5  Numeric 3
    "remaining_months_to_legal_maturity",      # 6  Numeric 3
    "defect_settlement_date",                  # 7  Date YYYYMM
    "modification_flag",                       # 8  Alpha 1
    "zero_balance_code",                       # 9  Numeric 2
    "zero_balance_effective_date",             # 10 Date YYYYMM
    "current_interest_rate",                   # 11 Numeric literal decimal
    "current_non_interest_bearing_upb",        # 12 Numeric 12
    "ddlpi_due_date_last_paid_installment",    # 13 Date YYYYMM
    "mi_recoveries",                           # 14 Numeric literal decimal
    "net_sale_proceeds",                       # 15 Alpha-numeric ($ or "U")
    "non_mi_recoveries",                       # 16 Numeric literal decimal
    "total_expenses",                          # 17 Numeric literal decimal
    "legal_costs",                             # 18 Numeric literal decimal
    "maintenance_preservation_costs",          # 19 Numeric literal decimal
    "taxes_and_insurance",                     # 20 Numeric literal decimal
    "misc_expenses",                           # 21 Numeric literal decimal
    "actual_loss_calculation",                 # 22 Numeric literal decimal
    "cumulative_modification_cost",            # 23 Numeric literal decimal
    "step_modification_flag",                  # 24 Alpha 1
    "payment_deferral_flag",                   # 25 Alpha 1
    "estimated_loan_to_value_eltv",            # 26 Numeric literal (from Apr 2017)
    "zero_balance_removal_upb",                # 27 Numeric literal decimal
    "delinquent_accrued_interest",             # 28 Numeric literal decimal
    "delinquency_due_to_disaster_flag",        # 29 Alpha 1 (from Jan 2014)
    "borrower_assistance_status_code",         # 30 Alpha 1 (from Jan 2014)
    "current_month_modification_cost",         # 31 Numeric literal decimal
    "interest_bearing_upb",                    # 32 Numeric literal decimal
]

# ---------------------------------------------------------------------------
# Sentinel → NaN mappings per column (from User Guide "Valid Values")
# These are "Not Available" sentinel codes, NOT real data values.
# ---------------------------------------------------------------------------
ORIG_SENTINELS = {
    "credit_score":              ["9999"],
    "mi_percent":                ["999"],
    "number_of_units":           ["99"],
    "occupancy_status":          ["9"],
    "original_cltv":             ["999"],
    "original_dti":              ["999"],
    "original_ltv":              ["999"],
    "channel":                   ["9"],
    "property_type":             ["99"],
    "number_of_borrowers":       ["99"],
    "property_valuation_method": ["9"],
    "special_eligibility_program": ["9"],
    "mi_cancellation_indicator": ["9"],
    "loan_purpose":              ["9"],
}

PERF_SENTINELS = {
    # delinquency status 0 means "current" – NOT missing; no sentinel needed
    "zero_balance_code":          [],   # all codes are meaningful
    "estimated_loan_to_value_eltv": ["999"],
    "net_sale_proceeds":          ["U"],   # keep as string, "U" = unknown
}

# ---------------------------------------------------------------------------
# Numeric columns to cast after sentinel replacement
# ---------------------------------------------------------------------------
ORIG_NUMERIC = [
    "credit_score", "msa_md_code", "mi_percent", "number_of_units",
    "original_cltv", "original_dti", "original_upb", "original_ltv",
    "original_interest_rate", "original_loan_term", "number_of_borrowers",
    "property_valuation_method",
]

PERF_NUMERIC = [
    "current_actual_upb", "loan_age", "remaining_months_to_legal_maturity",
    "current_interest_rate", "current_non_interest_bearing_upb",
    "mi_recoveries", "non_mi_recoveries", "total_expenses",
    "legal_costs", "maintenance_preservation_costs", "taxes_and_insurance",
    "misc_expenses", "actual_loss_calculation", "cumulative_modification_cost",
    "estimated_loan_to_value_eltv", "zero_balance_removal_upb",
    "delinquent_accrued_interest", "current_month_modification_cost",
    "interest_bearing_upb",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def apply_sentinels(df: pd.DataFrame, sentinel_map: dict) -> pd.DataFrame:
    """Replace field-specific sentinel codes with NaN."""
    for col, codes in sentinel_map.items():
        if col in df.columns and codes:
            df[col] = df[col].replace(codes, pd.NA)
    return df


def cast_numeric(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    """Convert columns to numeric (float), coercing unparseable values to NaN."""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def read_pipe_file(path: Path, col_names: list) -> pd.DataFrame:
    """Read a FreddieMAC pipe-delimited file with no header."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_csv(
        path,
        sep="|",
        header=None,
        names=col_names,
        dtype=str,           # read everything as string to avoid inference errors
        na_values=[""],      # only blank → NaN at read time; sentinels handled later
        keep_default_na=False,
        low_memory=False,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_PATH.mkdir(exist_ok=True)

    lst_orig = []
    lst_svcg = []

    sample_dirs = sorted(
        d for d in DATA_SAMPLE_PATH.iterdir()
        if d.is_dir() and re.match(r"sample_\d{4}$", d.name)
    )

    if not sample_dirs:
        raise RuntimeError(f"No sample_YYYY directories found in {DATA_SAMPLE_PATH}")

    for d in sample_dirs:
        yr = re.search(r"\d{4}", d.name).group()
        print(f">> Processing year {yr} ...")

        # --- Origination ---
        f_orig = d / f"sample_orig_{yr}.txt"
        try:
            df_o = read_pipe_file(f_orig, ORIG_COLS)
            df_o = apply_sentinels(df_o, ORIG_SENTINELS)
            df_o = cast_numeric(df_o, ORIG_NUMERIC)
            df_o["vintage_year"] = int(yr)
            lst_orig.append(df_o)
            print(f"   orig: {len(df_o):,} rows, {df_o.shape[1]} cols")
        except Exception as e:
            warnings.warn(f"Could not read {f_orig}: {e}")

        # --- Servicing / Performance ---
        f_svcg = d / f"sample_svcg_{yr}.txt"
        try:
            df_s = read_pipe_file(f_svcg, PERF_COLS)
            df_s = apply_sentinels(df_s, PERF_SENTINELS)
            df_s = cast_numeric(df_s, PERF_NUMERIC)
            df_s["vintage_year"] = int(yr)
            lst_svcg.append(df_s)
            print(f"   svcg: {len(df_s):,} rows, {df_s.shape[1]} cols")
        except Exception as e:
            warnings.warn(f"Could not read {f_svcg}: {e}")

    print("\n>> Concatenating all years ...")
    df_orig_all = pd.concat(lst_orig, ignore_index=True)
    df_svcg_all = pd.concat(lst_svcg, ignore_index=True)

    print(f"   orig_all : {len(df_orig_all):,} rows x {df_orig_all.shape[1]} cols")
    print(f"   svcg_all : {len(df_svcg_all):,} rows x {df_svcg_all.shape[1]} cols")

    # --- Save ---
    orig_out = OUTPUT_PATH / "orig_all.parquet"
    svcg_out = OUTPUT_PATH / "svcg_all.parquet"

    print(f"\n>> Saving to {OUTPUT_PATH} ...")
    df_orig_all.to_parquet(orig_out, index=False)
    df_svcg_all.to_parquet(svcg_out, index=False)
    print(f"   Saved: {orig_out.name}")
    print(f"   Saved: {svcg_out.name}")
    print("Done.")

    return df_orig_all, df_svcg_all


if __name__ == "__main__":
    main()
