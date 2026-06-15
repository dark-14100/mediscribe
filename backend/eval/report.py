"""Render evaluation results as a console table, a JSON report, and a Markdown
scorecard. Pure formatting — no scoring logic lives here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .thresholds import Thresholds


def aggregate(cases: list[dict]) -> dict[str, float]:
    """Mean each metric across cases. Empty input => all zeros."""
    if not cases:
        return {
            "token_f1": 0.0,
            "rouge_l": 0.0,
            "hallucination_rate": 0.0,
            "phi_leak_rate": 0.0,
            "residual_placeholders": 0.0,
        }
    n = len(cases)
    keys = ("token_f1", "rouge_l", "hallucination_rate", "phi_leak_rate")
    agg = {k: sum(c[k] for c in cases) / n for k in keys}
    agg["residual_placeholders"] = sum(c.get("residual_placeholders", 0) for c in cases)
    if "semantic_sim" in cases[0]:
        agg["semantic_sim"] = sum(c["semantic_sim"] for c in cases) / n
    return agg


def build_report(
    cases: list[dict], mode: str, thresholds: Thresholds, gated: bool
) -> dict:
    agg = aggregate(cases)
    breaches = thresholds.breaches(agg)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "case_count": len(cases),
        "aggregate": agg,
        "thresholds": {
            "min_field_token_f1": thresholds.min_field_token_f1,
            "min_rouge_l": thresholds.min_rouge_l,
            "max_hallucination_rate": thresholds.max_hallucination_rate,
            "max_phi_leak_rate": thresholds.max_phi_leak_rate,
        },
        "breaches": breaches,
        "gated": gated,
        "passed": not (gated and breaches),
        "cases": cases,
    }


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def print_table(report: dict) -> None:
    agg = report["aggregate"]
    print()
    print(f"  Eval scorecard  ({report['mode']} mode, {report['case_count']} cases)")
    print("  " + "-" * 58)
    print(f"  {'case':<28}{'F1':>7}{'ROUGE':>8}{'halluc':>8}{'phi':>6}")
    print("  " + "-" * 58)
    for c in report["cases"]:
        print(
            f"  {c['id'][:28]:<28}"
            f"{_fmt(c['token_f1']):>7}"
            f"{_fmt(c['rouge_l']):>8}"
            f"{_fmt(c['hallucination_rate']):>8}"
            f"{_fmt(c['phi_leak_rate']):>6}"
        )
    print("  " + "-" * 58)
    print(
        f"  {'MEAN':<28}"
        f"{_fmt(agg['token_f1']):>7}"
        f"{_fmt(agg['rouge_l']):>8}"
        f"{_fmt(agg['hallucination_rate']):>8}"
        f"{_fmt(agg['phi_leak_rate']):>6}"
    )
    if "semantic_sim" in agg:
        print(f"  semantic_sim (mean): {_fmt(agg['semantic_sim'])}")
    print(f"  residual placeholders: {int(agg['residual_placeholders'])}")
    print()
    if report["breaches"]:
        print("  THRESHOLD BREACHES:")
        for b in report["breaches"]:
            print(f"    - {b}")
    status = "PASS" if report["passed"] else ("FAIL" if report["gated"] else "REPORT-ONLY")
    print(f"  Result: {status}")
    print()


def _markdown(report: dict) -> str:
    agg = report["aggregate"]
    lines = [
        "# Evaluation Scorecard",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Mode: `{report['mode']}`",
        f"- Cases: {report['case_count']}",
        f"- Result: **{'PASS' if report['passed'] else ('FAIL' if report['gated'] else 'REPORT-ONLY')}**",
        "",
        "## Aggregate",
        "",
        "| Metric | Value | Threshold |",
        "|---|---|---|",
        f"| Token-F1 (mean field) | {_fmt(agg['token_f1'])} | >= {report['thresholds']['min_field_token_f1']} |",
        f"| ROUGE-L (mean) | {_fmt(agg['rouge_l'])} | >= {report['thresholds']['min_rouge_l']} |",
        f"| Hallucination rate | {_fmt(agg['hallucination_rate'])} | <= {report['thresholds']['max_hallucination_rate']} |",
        f"| PHI leak rate | {_fmt(agg['phi_leak_rate'])} | <= {report['thresholds']['max_phi_leak_rate']} |",
        f"| Residual placeholders | {int(agg['residual_placeholders'])} | = 0 |",
    ]
    if "semantic_sim" in agg:
        lines.append(f"| Semantic similarity | {_fmt(agg['semantic_sim'])} | — |")
    lines += ["", "## Per-case", "", "| Case | Token-F1 | ROUGE-L | Hallucination | PHI leak |", "|---|---|---|---|---|"]
    for c in report["cases"]:
        lines.append(
            f"| {c['id']} | {_fmt(c['token_f1'])} | {_fmt(c['rouge_l'])} "
            f"| {_fmt(c['hallucination_rate'])} | {_fmt(c['phi_leak_rate'])} |"
        )
    if report["breaches"]:
        lines += ["", "## Threshold breaches", ""]
        lines += [f"- {b}" for b in report["breaches"]]
    return "\n".join(lines) + "\n"


def write_reports(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"{stamp}.json"
    md_path = out_dir / f"{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path
