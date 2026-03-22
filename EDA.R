#### EDA
library(arrow)
setwd('C:/Users/sebat/Tesis Maestria/data/FreddieMAC')
library(data.table)
library(stringr)
library(pROC)
library(arrow)


base_path <- "C:/Users/sebat/Tesis Maestria/data/FreddieMAC"
df_orig_all=read_parquet("C:/Users/sebat/Tesis Maestria/data/FreddieMAC/orig_all.parquet")
df_svcg_all = read_parquet("C:/Users/sebat/Tesis Maestria/data/FreddieMAC/svcg_all.parquet")

# install.packages('dplyr')
# install.packages('ROCR')
# 
# install.packages('scales')
summary(df_orig_all)
summary(df_svcg_all)

# 
# Primary keys (and joins)
# 
# Origination file (df_orig_all)
# 
# Loan key: loan_sequence_number_V20
# 
# One row per loan.
# 
# Performance/servicing file (df_svcg_all)
# 
# Composite key: loan_sequence_number_V1 + monthly_reporting_period_V2 (YYYYMM)
# 
# One row per loan per month (occasionally you may find duplicates from data corrections—see checks below).
# Asume data.table
setDT(df_orig_all); setDT(df_svcg_all)

# --- helpers: localizar columnas por nombre "bonito" o V# si aún no renombraste ---
col_or <- function(...) {
  # devuelve la primera columna existente de las opciones
  opts <- unlist(list(...))
  opts[opts %in% names(df_orig_all)][1]
}
col_sv <- function(...) {
  opts <- unlist(list(...))
  opts[opts %in% names(df_svcg_all)][1]
}

# Campos clave (origination)
loan_id_or    <- col_or("loan_sequence_number_V20", "V20")          # Loan ID en ORIG
fico_col      <- col_or("credit_score_V1", "V1")
first_pay_col <- col_or("first_payment_date_V2", "V2")
maturity_col  <- col_or("maturity_date_V4", "V4")
ltv_col       <- col_or("original_ltv_V12", "V12")
dti_col       <- col_or("original_dti_V10", "V10")
upb0_col      <- col_or("original_upb_V11", "V11")

# Campos clave (servicing / performance)
loan_id_sv    <- col_sv("loan_sequence_number_V1", "V1")
per_col       <- col_sv("monthly_reporting_period_V2", "V2")        # YYYYMM
upb_col       <- col_sv("current_actual_upb_V3", "V3")
dlq_col       <- col_sv("current_loan_delinquency_status_V4", "V4") # 0,1,2,3... o letras ('R', etc.)
age_col       <- col_sv("loan_age_V5", "V5")
rem_col       <- col_sv("remaining_months_to_legal_maturity_V6", "V6")
zbc_col       <- col_sv("zero_balance_code_V9", "V9")
zbe_col       <- col_sv("zero_balance_effective_date_V10", "V10")
mod_flag_col  <- col_sv("modification_flag_V8", "V8")
assist_col    <- col_sv("borrower_assistance_status_code_V30", "V30")
paydef_col    <- col_sv("payment_deferral_flag_V25", "V25")

# --- EDA básico: origination ---
cat("\n--- ORIGINATION EDA ---\n")
cat("Loans (origination):", df_orig_all[, .N], "\n")
if (!is.null(loan_id_or)) {
  cat("Distinct loans (origination):", df_orig_all[, uniqueN(get(loan_id_or))], "\n")
}
if (!is.null(first_pay_col)) {
  cat("First payment (min..max):", df_orig_all[, range(get(first_pay_col), na.rm=TRUE)], "\n")
}
if (!is.null(maturity_col)) {
  cat("Maturity (min..max):", df_orig_all[, range(get(maturity_col), na.rm=TRUE)], "\n")
}
if (!is.null(fico_col)) {
  cat("FICO (min..p50..max):", df_orig_all[, quantile(get(fico_col), c(.01,.5,.99), na.rm=TRUE)], "\n")
}
if (!is.null(ltv_col)) {
  cat("Orig LTV (p5..p50..p95):", df_orig_all[, quantile(get(ltv_col), c(.05,.5,.95), na.rm=TRUE)], "\n")
}
if (!is.null(dti_col)) {
  cat("DTI (p5..p50..p95):", df_orig_all[, quantile(get(dti_col), c(.05,.5,.95), na.rm=TRUE)], "\n")
}

# --- Preparar PERFORMANCE: coerciones útiles ---
# Asegurar tipos básicos
if (!is.null(per_col))  df_svcg_all[, (per_col) := as.integer(get(per_col))]
if (!is.null(upb_col))  df_svcg_all[, (upb_col) := as.numeric(get(upb_col))]
if (!is.null(age_col))  df_svcg_all[, (age_col) := as.integer(get(age_col))]
if (!is.null(rem_col))  df_svcg_all[, (rem_col) := as.integer(get(rem_col))]
if (!is.null(zbc_col))  df_svcg_all[, (zbc_col) := as.character(get(zbc_col))]

# DPD numérico desde el status (0,1,2,3..) -> 0,30,60,90...
# Nota: algunos códigos no son números (p. ej. 'R'); conviértelos a NA
df_svcg_all[, dlq_num := suppressWarnings(as.integer(get(dlq_col)))]
df_svcg_all[, dpd := fifelse(is.na(dlq_num), NA_integer_, pmax(0L, 30L * dlq_num))]

# Default “rápido” IFRS 9: 90+ DPD O (opcional) ciertos zero balance de pérdida
# Puedes empezar solo con 90+ DPD; abajo incluyo también ZB codes 02/03/09 como “eventos de pérdida”
loss_like_zb <- c("02","03","09")  # Third Party Sale, Short Sale/Charge-Off, REO Disposition (ejemplos)
df_svcg_all[
  , default_flag_quick := as.integer( (dpd >= 90) | (!is.na(get(zbc_col)) & get(zbc_col) %in% loss_like_zb) )
]

# --- EDA rápido de performance ---
cat("\n--- PERFORMANCE EDA ---\n")
cat("Rows (performance):", df_svcg_all[, .N], "\n")
cat("Distinct loans (performance):", df_svcg_all[, uniqueN(get(loan_id_sv))], "\n")
cat("Period (min..max):", df_svcg_all[, range(get(per_col), na.rm=TRUE)], "\n")
cat("Current UPB (p50..p95):", df_svcg_all[, quantile(get(upb_col), c(.5,.95), na.rm=TRUE)], "\n")
cat("Share DPD>=90 (overall):", df_svcg_all[, mean(dpd >= 90, na.rm=TRUE)], "\n")

# Por mes: población, share 90+, share default_quick
eda_month <- df_svcg_all[,
                         .(
                           loans = uniqueN(get(loan_id_sv)),
                           rows  = .N,
                           share_dpd90 = mean(dpd >= 90, na.rm=TRUE),
                           share_default_quick = mean(default_flag_quick == 1L, na.rm=TRUE),
                           upb_sum = sum(get(upb_col), na.rm=TRUE)
                         ),
                         by = get(per_col)
][order(get)]

setnames(eda_month, "get", "yyyymm")
print(head(eda_month, 12))
print(tail(eda_month, 12))

# --- (Opcional) unirte a ORIG para features estáticas ---
# Join por loan_sequence_number
if (!is.null(loan_id_or) && !is.null(loan_id_sv)) {
  orig_min <- df_orig_all[, .SD, .SDcols = unique(na.omit(c(loan_id_or, fico_col, ltv_col, dti_col, upb0_col)))]
  setnames(orig_min, loan_id_or, "LoanSeq")
  perf_min <- df_svcg_all[, .SD, .SDcols = unique(na.omit(c(loan_id_sv, per_col, upb_col, "dpd", "default_flag_quick")))]
  setnames(perf_min, loan_id_sv, "LoanSeq")
  setnames(perf_min, per_col, "yyyymm")
  panel <- perf_min[orig_min, on = "LoanSeq"]
  cat("\nPanel merged rows:", nrow(panel), "\n")
  # Ejemplo: default rate 12m “proxy” (muy simple) o cortes por score/ltv
  # (para análisis serio, construye etiqueta 12m mirando hacia adelante)
  quick_by_score <- panel[
    , .(rate_default = mean(default_flag_quick == 1L, na.rm=TRUE)), by = cut(credit_score_V1, breaks=c(300,620,660,700,740,780,850,9999), right=FALSE)
  ]
  print(quick_by_score)
}

data.table::setDT(df_orig_all)
a <- df_orig_all[loan_sequence_number_V20 == "F16Q10025477"]
a_sv <- df_svcg_all[loan_sequence_number_V1 == "F16Q10025477"]

loan_sequence_number_V1


names(df_orig_all)
colnames(df_orig_all)[grepl("loan_sequence", names(df_orig_all))]





library(ggplot2)
library(dplyr)
library(scales)
set.seed(123)

# Subsample for speed (optional)
df_plot <- df_svcg_all %>% sample_n(min(500000, nrow(df_svcg_all)))

# 1️⃣  Balance distribution
ggplot(df_plot, aes(x = current_actual_upb_V3 / 1e3)) +
  geom_histogram(bins = 60, fill = "#2E86C1", color = "white") +
  scale_x_continuous(labels = label_comma()) +
  labs(
    title = "Distribution of Current Loan Balances",
    x = "Current Balance (thousands USD)",
    y = "Number of observations"
  ) +
  theme_minimal()

# 2️⃣  DPD (delinquency) distribution
ggplot(df_plot %>% filter(dpd>0 & dpd <450), aes(x = dpd)) +
  geom_histogram(binwidth = 30, fill = "#CD6155", color = "white") +
  labs(
    title = "Distribution of Days Past Due (DPD)",
    x = "Days Past Due",
    y = "Count"
  ) +
  theme_minimal()

# 3️⃣  Share of loans in default (90+ DPD) over time
df_month <- df_svcg_all %>%
  mutate(month_date = as.Date(paste0(monthly_reporting_period_V2, "01"), "%Y%m%d")) %>%
  group_by(month_date) %>%
  summarise(
    share_default = mean(default_flag_quick == 1, na.rm = TRUE),
    avg_dpd = mean(dpd, na.rm = TRUE),
    tot_balance = sum(current_actual_upb_V3, na.rm = TRUE)
  )

ggplot(df_month, aes(x = month_date, y = share_default)) +
  geom_line(color = "#1E8449", size = 1) +
  scale_y_continuous(labels = percent_format(accuracy = 0.1)) +
  labs(
    title = "Default Rate (90+ DPD or Loss Event) Over Time",
    x = "Month",
    y = "Share of Defaults"
  ) +
  theme_minimal()

# 4️⃣  Average DPD vs. Balance
ggplot(df_plot, aes(x = dpd, y = current_actual_upb_V3 / 1e3)) +
  geom_boxplot(fill = "#AF7AC5", outlier.alpha = 0.2) +
  labs(
    title = "Balance by Days Past Due",
    x = "Days Past Due",
    y = "Current Balance (thousands USD)"
  ) +
  theme_minimal()

# 5️⃣  Vintage analysis (first payment year vs. default rate)
df_vintage <- df_orig_all %>%
  mutate(vintage = substr(first_payment_date_V2, 1, 4)) %>%
  left_join(
    df_svcg_all %>%
      group_by(loan_sequence_number_V1) %>%
      summarise(ever_default = max(default_flag_quick, na.rm = TRUE)),
    by = c("loan_sequence_number_V20" = "loan_sequence_number_V1")
  ) %>%
  group_by(vintage) %>%
  summarise(default_rate = mean(ever_default == 1, na.rm = TRUE))

ggplot(df_vintage, aes(x = vintage, y = default_rate)) +
  geom_col(fill = "#5DADE2") +
  scale_y_continuous(labels = percent_format(accuracy = 0.1)) +
  labs(
    title = "Lifetime Default Rate by Vintage",
    x = "Origination Year",
    y = "Default Rate"
  ) +
  theme_minimal()


