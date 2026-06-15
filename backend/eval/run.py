"""Evaluation harness CLI.

    python -m eval.run --dataset eval/datasets/smoke.jsonl                 # replay, gated
    python -m eval.run --dataset eval/datasets/smoke.jsonl --live --save-fixtures
    python -m eval.run --dataset eval/datasets/smoke.jsonl --semantic --no-gate

Replay mode (default) scores the ``generated_soap`` fixture stored on each case,
so runs are deterministic and free. ``--live`` regenerates notes through Groq.

The harness only touches DB-free services (SOAP gen, grounding, de-id), so it
runs anywhere the backend deps are installed. Safe env defaults are set below so
replay needs zero configuration.
"""
from __future__ import annotations

import os

# Set BEFORE importing anything that loads core.config. These are only used to
# satisfy the settings schema; replay mode never opens a DB/Redis connection.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "eval-harness-not-a-real-secret-0000000000")

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from .metrics import hallucination_rate, phi_leak_rate, rouge_l, semantic_sim, token_f1  # noqa: E402
from .report import build_report, print_table, write_reports  # noqa: E402
from .thresholds import Thresholds  # noqa: E402

SOAP_KEYS = ("subjective", "objective", "assessment", "plan")
_EVAL_DIR = Path(__file__).resolve().parent


def _load_dataset(path: Path) -> list[dict]:
    cases: list[dict] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{lineno}: invalid JSON — {exc}") from exc
    if not cases:
        raise SystemExit(f"{path}: no cases found")
    return cases


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 1.0


async def _generated_soap(case: dict, live: bool) -> dict:
    """Return the SOAP note to score: from Groq (live) or the stored fixture."""
    if live:
        from services.soap_generator import generate_soap  # local import

        return await generate_soap(case.get("transcript", []))
    fixture = case.get("generated_soap")
    if not fixture:
        raise SystemExit(
            f"case '{case.get('id')}' has no 'generated_soap' fixture; "
            f"run with --live --save-fixtures to record one"
        )
    return fixture


def _residual_after_roundtrip(generated: dict, transcript: list, patient) -> int:
    """De-identify the transcript, then count placeholders left in the note after
    re-identification (should be 0; non-zero means a mangled placeholder leaked)."""
    from services.deid import count_residual, deidentify_transcript, reidentify

    result = deidentify_transcript(transcript, patient)
    restored = reidentify(generated, result.mapping)
    return count_residual(restored, result.mapping)


async def _score_case(case: dict, *, live: bool, semantic: bool) -> dict:
    transcript = case.get("transcript", [])
    reference = case.get("reference_soap", {}) or {}
    planted = case.get("planted_phi", []) or []
    patient = SimpleNamespace(**(case.get("patient") or {}))

    generated = await _generated_soap(case, live)

    f1s: list[float] = []
    rouges: list[float] = []
    sems: list[float] = []
    for key in SOAP_KEYS:
        ref_text = str(reference.get(key, "") or "")
        if not ref_text.strip():
            continue
        pred_text = str((generated.get(key) or {}).get("text", "") or "")
        f1s.append(token_f1(pred_text, ref_text))
        rouges.append(rouge_l(pred_text, ref_text))
        if semantic:
            sems.append(semantic_sim(pred_text, ref_text))

    scored = {
        "id": case.get("id", "<unnamed>"),
        "token_f1": _mean(f1s),
        "rouge_l": _mean(rouges),
        "hallucination_rate": await hallucination_rate(generated, transcript),
        "phi_leak_rate": phi_leak_rate(transcript, patient, planted),
        "residual_placeholders": _residual_after_roundtrip(generated, transcript, patient),
    }
    if semantic:
        scored["semantic_sim"] = _mean(sems)
    if live:
        scored["_generated_soap"] = generated  # carried for --save-fixtures
    return scored


async def evaluate(
    dataset: Path,
    *,
    live: bool = False,
    semantic: bool = False,
    gated: bool = True,
    thresholds: Thresholds | None = None,
) -> dict:
    """Run the harness and return the report dict (no process exit)."""
    cases = _load_dataset(dataset)
    thresholds = thresholds or Thresholds()
    scored = [await _score_case(c, live=live, semantic=semantic) for c in cases]

    # Strip carried fixtures out of the persisted report.
    public = [{k: v for k, v in c.items() if not k.startswith("_")} for c in scored]
    report = build_report(public, "live" if live else "replay", thresholds, gated)
    report["_scored"] = scored  # internal: retains fixtures for --save-fixtures
    return report


def _save_fixtures(dataset: Path, scored: list[dict]) -> None:
    cases = _load_dataset(dataset)
    by_id = {c["id"]: c.get("_generated_soap") for c in scored}
    for case in cases:
        soap = by_id.get(case.get("id"))
        if soap is not None:
            case["generated_soap"] = soap
    dataset.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8",
    )
    print(f"  Saved {sum(1 for v in by_id.values() if v)} fixtures to {dataset}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MediScribe evaluation harness")
    parser.add_argument("--dataset", required=True, help="path to a JSONL dataset")
    parser.add_argument("--live", action="store_true", help="generate notes via Groq")
    parser.add_argument(
        "--save-fixtures", action="store_true",
        help="(with --live) write generated notes back into the dataset",
    )
    parser.add_argument("--semantic", action="store_true", help="add embedding cosine")
    parser.add_argument(
        "--no-gate", action="store_true", help="report only; never exit non-zero",
    )
    parser.add_argument("--min-f1", type=float, default=None)
    parser.add_argument("--min-rouge", type=float, default=None)
    parser.add_argument("--max-hallucination", type=float, default=None)
    parser.add_argument("--max-phi-leak", type=float, default=None)
    parser.add_argument(
        "--reports-dir", default=str(_EVAL_DIR / "reports"),
        help="where to write the JSON + Markdown report",
    )
    args = parser.parse_args(argv)

    if args.save_fixtures and not args.live:
        parser.error("--save-fixtures requires --live")

    base = Thresholds()
    thresholds = Thresholds(
        min_field_token_f1=args.min_f1 if args.min_f1 is not None else base.min_field_token_f1,
        min_rouge_l=args.min_rouge if args.min_rouge is not None else base.min_rouge_l,
        max_hallucination_rate=(
            args.max_hallucination if args.max_hallucination is not None
            else base.max_hallucination_rate
        ),
        max_phi_leak_rate=args.max_phi_leak if args.max_phi_leak is not None else base.max_phi_leak_rate,
    )

    dataset = Path(args.dataset)
    if not dataset.is_absolute():
        # Allow running from backend/ with eval/datasets/... paths.
        candidate = (Path.cwd() / dataset)
        dataset = candidate if candidate.exists() else (_EVAL_DIR.parent / dataset)
    if not dataset.exists():
        parser.error(f"dataset not found: {args.dataset}")

    report = asyncio.run(
        evaluate(
            dataset,
            live=args.live,
            semantic=args.semantic,
            gated=not args.no_gate,
            thresholds=thresholds,
        )
    )
    scored = report.pop("_scored", [])

    if args.save_fixtures:
        _save_fixtures(dataset, scored)

    json_path, md_path = write_reports(report, Path(args.reports_dir))
    print_table(report)
    print(f"  Report: {json_path}")
    print(f"          {md_path}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
