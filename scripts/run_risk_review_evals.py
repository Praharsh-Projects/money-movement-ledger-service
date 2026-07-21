from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from money_movement.risk_review.evaluation import EvaluationReport, evaluate, load_evaluation_cases
from money_movement.risk_review.gateway import PolicyAwareBaselineGateway
from money_movement.risk_review.retrieval import PolicyRetriever
from money_movement.risk_review.workflow import RiskReviewWorkflow


async def run(cases_path: Path) -> EvaluationReport:
    workflow = RiskReviewWorkflow(PolicyAwareBaselineGateway(), PolicyRetriever.from_package())
    return await evaluate(workflow, load_evaluation_cases(cases_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic financial-risk workflow evaluations")
    parser.add_argument("--cases", type=Path, default=Path("evals/risk_review_cases.json"))
    parser.add_argument("--report-directory", type=Path)
    arguments = parser.parse_args()
    report = asyncio.run(run(arguments.cases))
    print(report.markdown(), end="")
    if arguments.report_directory is not None:
        arguments.report_directory.mkdir(parents=True, exist_ok=True)
        (arguments.report_directory / "risk_review_evaluation.json").write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (arguments.report_directory / "risk_review_evaluation.md").write_text(
            report.markdown(), encoding="utf-8"
        )
    return 0 if report.quality_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
