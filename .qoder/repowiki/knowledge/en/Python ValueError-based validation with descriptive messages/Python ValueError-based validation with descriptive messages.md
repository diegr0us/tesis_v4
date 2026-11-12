---
kind: error_handling
name: Python ValueError-based validation with descriptive messages
category: error_handling
scope:
    - '**'
---

## Approach

The repository has no custom exception hierarchy, no error-code enum, no logging framework, and no middleware. Error handling is uniformly expressed as **standard-library `ValueError` exceptions** raised at call sites to signal invalid arguments, out-of-range indices, malformed input data, or failed numerical assumptions.

There is no `try/except` block outside of one location: `degradation/failure_box.py` wraps a downstream call in `try/except ValueError` and re-raises it with a component/day context via `raise ... from error`. All other code paths simply raise directly.

## Key Files

- `degradation/failure_box.py` — the only file that both raises and catches errors; defines `FailureBox`, `build_component_index`, `load_cdf`, `rld_box`.
- `pca/pca.py` — raises `ValueError` at module import time to validate forecast/historical data alignment and after each major numerical step (SVD, bias subtraction, quantile computation).

## Conventions Observed

1. **Single exception type**: Every assertion-like check raises `ValueError` with a human-readable message. No subclassing of `Exception`, no sentinel constants, no `logging` calls.
2. **Messages include diagnostic context**: values such as shapes (`f"e_p tiene forma {e_p.shape}"`), available ranges (`f"El componente {component} no está en {self.data_dir} (hay {available[0]}–{available[-1]})."`), and suggested fixes (`f"Usa un α mayor que {2.0 * (1.0 - maximum):.4f}."`).
3. **Input validation happens early**: parameter bounds (`0.0 < alpha < 1.0`) are checked at function entry before any computation.
4. **Data-file validation on load**: `build_component_index` validates directory existence, filename pattern (`cdf_<señal>_<componente>.xlsx`), component range (`1..N_COMPONENTS=100`), duplicates, and presence of at least one file; `load_cdf` validates shape `(n_días, 500)` against `CDF_SUPPORT_DAYS`.
5. **Chained exceptions for context enrichment**: In `FailureBox.box`, a low-level `ValueError` from `rld_box` is caught and re-raised with component/day context using `from error` so the original traceback is preserved.
6. **No global error handler**: There is no top-level `try/except` wrapping script execution; failures propagate to the interpreter.
7. **No logging integration**: Errors are not logged; they terminate the process unless caught by an external caller.
8. **Module-level validation**: `pca/pca.py` performs its data loading and consistency checks at import time (lines 24–33, 71–72), so importing the module itself can fail if the CSVs are misaligned.

## Rules Enforced by the Code

- Argument `alpha` must satisfy `0.0 < alpha < 1.0` (enforced in `FailureBox.__init__` and `rld_box`).
- Component identifiers must be integers in `1..100` (enforced in `build_component_index`).
- CDF files must follow the naming convention `cdf_<señal>_<componente>.xlsx` and contain exactly 500 columns (enforced in `build_component_index` and `load_cdf`).
- Forecast and historical timestamps must align by day-of-week (enforced at module import in `pca/pca.py`).
- Wind and demand forecasts must share identical `source_timestamp` index (enforced at module import in `pca/pca.py`).
- PCA bases `L_p`, `L_d` must be orthonormal and retained variance must reach `DEFAULT_VARIANCE_THRESHOLD = 0.95` (enforced after SVD in `pca/pca.py`).
- Uncertainty-set radii `a` must be strictly positive (enforced in `_presupuestos`).

## What Is Absent

- No custom exception classes.
- No error codes or structured error payloads.
- No `logging` module usage.
- No `try/except` blocks except the single re-wrap in `FailureBox.box`.
- No middleware, request/response error pipeline, or HTTP error handling (the repo contains no web server code).
- No `panic`/`recover` equivalent (this is Python, not Go/Rust).