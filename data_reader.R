install.packages('readr')
install.packages('stringr')

library(arrow)
setwd('C:/Users/sebat/Tesis Maestria/data/FreddieMAC')
library(data.table)
library(stringr)

base_path <- "C:/Users/sebat/Tesis Maestria/data/FreddieMAC"

# 2) Detectar todas las carpetas sample_YYYY
dirs_years <- list.dirs(base_path, full.names = TRUE, recursive = FALSE)
dirs_sample <- dirs_years[grepl("sample_\\d{4}$", basename(dirs_years))]

# 3) Función de lectura robusta para un archivo pipe-delimited sin header
read_pipe_noheader <- function(path) {
  if (!file.exists(path)) {
    stop(sprintf("No existe el archivo: %s", path))
  }
  # fread infiere tipos; header = FALSE (según User Guide no hay header)
  fread(
    path,
    sep = "|",
    header = FALSE,
    na.strings = c("", "NA", "NaN", "NULL"),
    showProgress = TRUE,
    data.table = TRUE
  )
}

# 4) Iterar por cada carpeta sample_YYYY y leer orig + svcg
lst_orig <- list()
lst_svcg <- list()

for (d in dirs_sample) {
  yr <- str_extract(basename(d), "\\d{4}")
  message(sprintf(">> Procesando año %s ...", yr))
  
  f_orig <- file.path(d, sprintf("sample_orig_%s.txt", yr))
  f_svcg <- file.path(d, sprintf("sample_svcg_%s.txt", yr))
  
  # Leer origination
  dt_o <- tryCatch(
    {
      read_pipe_noheader(f_orig)[, year := as.integer(yr)]
    },
    error = function(e) {
      warning(sprintf("No se pudo leer %s: %s", f_orig, e$message))
      NULL
    }
  )
  
  # Leer servicing (mensual)
  dt_s <- tryCatch(
    {
      read_pipe_noheader(f_svcg)[, year := as.integer(yr)]
    },
    error = function(e) {
      warning(sprintf("No se pudo leer %s: %s", f_svcg, e$message))
      NULL
    }
  )
  
  if (!is.null(dt_o)) lst_orig[[yr]] <- dt_o
  if (!is.null(dt_s)) lst_svcg[[yr]] <- dt_s
}

# 5) Concatenar todo
df_orig_all <- rbindlist(lst_orig, use.names = FALSE, fill = FALSE)
df_svcg_all <- rbindlist(lst_svcg, use.names = FALSE, fill = FALSE)

# 6) (Opcional) Renombrar columnas clave mínimas si quieres empezar a trabajar ya.
#    OJO: los nombres oficiales están en el User Guide (sección "File Layout & Data Dictionary").
#    Aquí te dejo un set mínimo ilustrativo para PERFORMANCE :
#    Solo si el número de columnas coincide con el formato esperado.
#    Ejemplo típico (parcial): LoanSequence, ReportingPeriod(YYYYMM), CurrentActualUPB, DelinqStatus, LoanAge, MonthsToMaturity, ModFlag, ZeroBalanceCode, ZeroBalanceEffDate, CurrentInterestRate, etc.
#
# if (ncol(df_svcg_all) >= 10) {
#   setnames(df_svcg_all, 1:10, c("LoanSeqNum","RptPeriod","CurrActualUPB","DelinqStatus",
#                                 "LoanAge","MonthsToMaturity","ModFlag","ZeroBalCode",
#                                 "ZeroBalEffDate","CurrInterestRate"))
# }
#
# Para ORIGINATION harías algo similar cuando definas el layout exacto.

# 7) Resultado
print(df_orig_all)
print(df_svcg_all)


# --- Mapeos desde el User Guide (añadiendo _V#) ---
orig_map <- setNames(
  c(
    "credit_score_V1",
    "first_payment_date_V2",
    "first_time_homebuyer_flag_V3",
    "maturity_date_V4",
    "msa_md_code_V5",
    "mi_percent_V6",
    "number_of_units_V7",
    "occupancy_status_V8",
    "original_cltv_V9",
    "original_dti_V10",
    "original_upb_V11",
    "original_ltv_V12",
    "original_interest_rate_V13",
    "channel_V14",
    "prepayment_penalty_flag_V15",
    "amortization_type_V16",
    "property_state_V17",
    "property_type_V18",
    "postal_code3_trunc_V19",
    "loan_sequence_number_V20",
    "loan_purpose_V21",
    "original_loan_term_V22",
    "number_of_borrowers_V23",
    "seller_name_V24",
    "servicer_name_V25",
    "super_conforming_flag_V26",
    "pre_relief_refi_loan_seq_num_V27",
    "special_eligibility_program_V28",
    "relief_refinance_indicator_V29",
    "property_valuation_method_V30",
    "interest_only_indicator_V31",
    "mi_cancellation_indicator_V32"
  ),
  paste0("V", 1:32)
)

perf_map <- setNames(
  c(
    "loan_sequence_number_V1",
    "monthly_reporting_period_V2",
    "current_actual_upb_V3",
    "current_loan_delinquency_status_V4",
    "loan_age_V5",
    "remaining_months_to_legal_maturity_V6",
    "defect_settlement_date_V7",
    "modification_flag_V8",
    "zero_balance_code_V9",
    "zero_balance_effective_date_V10",
    "current_interest_rate_V11",
    "current_non_interest_bearing_upb_V12",
    "ddlpi_due_date_last_paid_installment_V13",
    "mi_recoveries_V14",
    "net_sale_proceeds_V15",
    "non_mi_recoveries_V16",
    "total_expenses_V17",
    "legal_costs_V18",
    "maintenance_preservation_costs_V19",
    "taxes_and_insurance_V20",
    "misc_expenses_V21",
    "actual_loss_calculation_V22",
    "cumulative_modification_cost_V23",
    "step_modification_flag_V24",
    "payment_deferral_flag_V25",
    "estimated_loan_to_value_eltv_V26",
    "zero_balance_removal_upb_V27",
    "delinquent_accrued_interest_V28",
    "delinquency_due_to_disaster_flag_V29",
    "borrower_assistance_status_code_V30",
    "current_month_modification_cost_V31",
    "interest_bearing_upb_V32"
  ),
  paste0("V", 1:32)
)

# --- Función auxiliar para renombrar solo si las columnas existen ---
rename_by_map <- function(dt, map_named) {
  old <- intersect(names(dt), names(map_named))
  if (length(old)) {
    setnames(dt, old, unname(map_named[old]), skip_absent = TRUE)
  }
  invisible(dt)
}

# --- Aplicar a tus data.tables ---
rename_by_map(df_orig_all, orig_map)
rename_by_map(df_svcg_all, perf_map)

# Comprobación rápida
names(df_orig_all)[1:10]
names(df_svcg_all)[1:10]

write_parquet(df_orig_all, file.path(base_path, "orig_all.parquet"))
write_parquet(df_svcg_all, file.path(base_path, "svcg_all.parquet"))




