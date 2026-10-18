"""
Validation module.

Post-load data-quality validation for the edgartools path lives in `quality.py`
(hard integrity gates + soft warnings + per-filing quality report). The old heuristic
validator stack (checks/completeness/validator/…) was removed in the re-architecture — see
docs/REARCHITECTURE.md.
"""
from .quality import QualityReport, validate, write_report

__all__ = ["QualityReport", "validate", "write_report"]
