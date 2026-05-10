Use the Plan subagent (subagent_type: "Plan") to design a step-by-step implementation plan for:

$ARGUMENTS

## Project context to pass to the agent

- **Goal:** IFRS 9 PD prediction thesis — predict 12-month default probability using ML on Freddie Mac Single-Family Loan-Level Data (vintages 2016–2024, no 2021)
- **Language:** Python only
- **Pipeline:** `data_reader.py` → `src/01` → `src/02` → `src/03` → `src/04` → `src/05` → `src/06` → `src/07`
- **Constants / features / paths:** always in `src/config.py` — any new parameters go there
- **Output directories:** `outputs/figuras/` · `outputs/modelos/` · `outputs/tablas/`
- **Temporal split (must be respected):** train vintages 2016–2020 · val 2022–2023 · test 2024 — split by `vintage_year`, never by random seed or row index
- **Target:** `default_12m` (binary, forward-looking 12 months, built in `src/02_definicion_default.py`)
- **Stage filter:** models only see Stage 1 and Stage 2 observations (`data/dataset_modelado.parquet`)
- **Memory constraints:** feature columns must be `float32`, not `float64`

## What the plan must cover

1. Which existing files to modify and exactly where
2. Which new files to create (if any) and where they fit in the pipeline order
3. Inputs and outputs of each new step (parquet names, column names)
4. Any risk of data leakage — flag it explicitly
5. Any dependency on `src/config.py` constants that need to be added
6. Estimated complexity: is this a one-script change or a multi-step refactor?
