Use the Explore subagent (subagent_type: "Explore") to thoroughly investigate the following question or area:

$ARGUMENTS

## Codebase context to pass to the agent

- **Root:** `FreddieMAC/` — Python thesis project, IFRS 9 PD prediction with Freddie Mac data
- **Pipeline order:** `data_reader.py` → `src/01_carga_datos.py` → `src/02_definicion_default.py` → `src/03_feature_engineering.py` → `src/04_modelado.py` → `src/05_calibracion_lifetime.py` → `src/06_validacion.py` → `src/07_explicabilidad.py`
- **Single source of truth for constants and features:** `src/config.py`
- **ML-ready dataset:** `data/dataset_modelado.parquet` (Stage 1 + 2 only)
- **JOIN key everywhere:** `loan_sequence_number` — always `str.strip()` before joins or groupby
- **Target variable:** `default_12m` — binary, 1 if default occurs in next 12 months (built in step 02)
- **Temporal split:** train 2016–2020 · val 2022–2023 · test 2024 (by `vintage_year`)

## Instructions for the agent

Search across `src/`, `data_reader.py`, `CLAUDE.md`, and `Data_Process.md` as needed.
Report findings with exact file paths and line numbers.
Be thorough — use "very thorough" exploration level.
