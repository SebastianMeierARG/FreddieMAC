Review the code changed in this session (or the files specified in $ARGUMENTS) against this project's conventions. Then fix every issue found.

## What to check

**Bloat**
- Remove abstractions, helpers, or utilities used only once
- Remove error handling for scenarios that cannot occur inside the pipeline
- Remove docstrings, comments, or type hints on code you did not change
- Remove backwards-compatibility hacks (renamed `_vars`, re-exports, `# removed` comments)

**Constants and paths**
- Replace any hardcoded path, feature name, or IFRS 9 parameter with the equivalent from `src/config.py`
- If a new constant is needed, add it to `src/config.py` — not inline

**Memory / types**
- Downcast `float64` to `float32` for any feature column (behavioral or origination)
- Do not upcast back to `float64` without a documented reason

**Data leakage**
- Flag any code that uses vintages 2022, 2023, or 2024 during model training or feature selection
- Flag any imputation logic that belongs in the sklearn pipeline but was done ad-hoc in a script

**Output conventions**
- Figures → `outputs/figuras/`
- Trained models → `outputs/modelos/`
- Tables and metrics → `outputs/tablas/`
- All three directories are created automatically by importing `src/config.py`

## After reviewing
Show a concise summary: what was wrong, what was changed, and why. If nothing needs fixing, say so explicitly.
