"""Regression-gate thresholds for the evaluation harness.

Defaults are deliberately conservative placeholders — the first live run on a
real dataset should calibrate them. Override any of them via CLI flags on
``eval.run`` (e.g. ``--min-f1 0.5``).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # Mean per-field token-F1 must be >= this.
    min_field_token_f1: float = 0.45
    # Mean ROUGE-L must be >= this.
    min_rouge_l: float = 0.35
    # Average unsupported-claim fraction must be <= this.
    max_hallucination_rate: float = 0.15
    # Zero planted identifiers may survive de-identification.
    max_phi_leak_rate: float = 0.0

    def breaches(self, agg: dict[str, float]) -> list[str]:
        """Return human-readable descriptions of every threshold breach."""
        failures: list[str] = []
        if agg["token_f1"] < self.min_field_token_f1:
            failures.append(
                f"token_f1 {agg['token_f1']:.3f} < min {self.min_field_token_f1}"
            )
        if agg["rouge_l"] < self.min_rouge_l:
            failures.append(
                f"rouge_l {agg['rouge_l']:.3f} < min {self.min_rouge_l}"
            )
        if agg["hallucination_rate"] > self.max_hallucination_rate:
            failures.append(
                f"hallucination_rate {agg['hallucination_rate']:.3f} "
                f"> max {self.max_hallucination_rate}"
            )
        if agg["phi_leak_rate"] > self.max_phi_leak_rate:
            failures.append(
                f"phi_leak_rate {agg['phi_leak_rate']:.3f} "
                f"> max {self.max_phi_leak_rate}"
            )
        return failures
