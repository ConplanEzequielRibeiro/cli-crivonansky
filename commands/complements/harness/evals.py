"""Evals determinísticos do brief (M5)."""

import json
import os
from datetime import datetime

from . import briefing, graphdb
from commands.complements.harness_core.util import workspace

GOLD = (
    {
        "id": "aluguel-status",
        "anchor": "table",
        "value": "tb_alugueis",
        "expected": [
            "codigo-fonte/aluguel/alugar.php",
            "codigo-fonte/aluguel/devolver.php",
        ],
    },
    {
        "id": "veiculos-writes",
        "anchor": "table",
        "value": "tb_veiculos",
        "expected": [
            "codigo-fonte/aluguel/alugar.php",
            "codigo-fonte/aluguel/devolver.php",
            "codigo-fonte/cadastro/veiculo.php",
        ],
    },
    {
        "id": "clientes",
        "anchor": "table",
        "value": "tb_clientes",
        "expected": [
            "codigo-fonte/cadastro/cliente.php",
            "codigo-fonte/aluguel/alugar.php",
        ],
    },
    {
        "id": "categorias",
        "anchor": "table",
        "value": "tb_categorias",
        "expected": [
            "codigo-fonte/aluguel/alugar.php",
            "codigo-fonte/cadastro/veiculo.php",
        ],
    },
    {
        "id": "pagamentos",
        "anchor": "table",
        "value": "tb_pagamentos",
        "expected": ["codigo-fonte/aluguel/devolver.php"],
    },
)


def evaluate(ctx, gold=None, budget: int = 6000, max_paths: int = 5) -> dict:
    cases = []
    conn = graphdb.connect(ctx)
    try:
        baseline_paths = [row["path"] for row in conn.execute(
            "SELECT path FROM files ORDER BY path LIMIT ?", (max_paths,)
        ).fetchall()]
    finally:
        conn.close()
    for case in gold or GOLD:
        packet = briefing.build(
            ctx,
            {
                case["anchor"]: case["value"],
                "budget": budget,
                "max_paths": max_paths,
            },
        )
        if packet.get("error"):
            cases.append({"id": case["id"], "error": packet["error"]})
            continue
        paths = [item["path"] for item in packet.get("read_first") or []]
        expected = list(case.get("expected") or [])
        found = [path for path in paths if path in expected]
        baseline_found = [path for path in baseline_paths if path in expected]
        cases.append(
            {
                "id": case["id"],
                "anchor": f"{case['anchor']}:{case['value']}",
                "expected": expected,
                "read_first": paths,
                "first_correct_file_at_1": bool(paths and paths[0] in expected),
                "recall_at_5": round(len(found) / len(expected), 3) if expected else 0.0,
                "irrelevant_reads": len([path for path in paths if path not in expected]),
                "missed_validation": 0 if packet.get("validation") else 1,
                "brief_tokens": int((packet.get("budget") or {}).get("estimated") or 0),
                "truncated": bool((packet.get("budget") or {}).get("truncated")),
                "baseline": {
                    "read_first": baseline_paths,
                    "first_correct_file_at_1": bool(
                        baseline_paths and baseline_paths[0] in expected
                    ),
                    "recall_at_5": round(len(baseline_found) / len(expected), 3)
                    if expected
                    else 0.0,
                    "irrelevant_reads": len(
                        [path for path in baseline_paths if path not in expected]
                    ),
                },
            }
        )

    valid = [case for case in cases if "error" not in case]
    total_expected = sum(len(case["expected"]) for case in valid)
    total_found = sum(
        len([path for path in case["read_first"] if path in case["expected"]])
        for case in valid
    )
    baseline_found = sum(
        len([path for path in case["baseline"]["read_first"] if path in case["expected"]])
        for case in valid
    )
    aggregate = {
        "tasks": len(cases),
        "first_correct_at_1": sum(1 for case in valid if case["first_correct_file_at_1"]),
        "recall_at_5": round(total_found / total_expected, 3) if total_expected else 0.0,
        "irrelevant_reads": sum(case["irrelevant_reads"] for case in valid),
        "missed_validation": sum(case["missed_validation"] for case in valid),
        "brief_tokens_total": sum(case["brief_tokens"] for case in valid),
        "truncated": sum(1 for case in valid if case["truncated"]),
        "baseline_first_correct_at_1": sum(
            1 for case in valid if case["baseline"]["first_correct_file_at_1"]
        ),
        "baseline_recall_at_5": round(baseline_found / total_expected, 3)
        if total_expected
        else 0.0,
        "baseline_irrelevant_reads": sum(
            case["baseline"]["irrelevant_reads"] for case in valid
        ),
    }
    return {
        "schema": "harness.evals.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "budget": budget,
        "max_paths": max_paths,
        "cases": cases,
        "aggregate": aggregate,
    }


def run(ctx, gold=None, write: bool = True) -> tuple[dict, str | None]:
    data = evaluate(ctx, gold)
    path = None
    if write:
        folder = os.path.join(workspace(ctx), "runs", "evals")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"brief-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return data, path


def describe(data: dict) -> str:
    agg = data["aggregate"]
    lines = [
        f"evals: {agg['tasks']} tarefa(s)",
        f"- first_correct@1: {agg['first_correct_at_1']}/{agg['tasks']}",
        f"- recall@5: {agg['recall_at_5']}",
        f"- leituras irrelevantes: {agg['irrelevant_reads']}",
        f"- validação perdida: {agg['missed_validation']}",
        f"- tokens de brief: {agg['brief_tokens_total']}",
        f"- truncados: {agg['truncated']}",
        f"- baseline: first@1 {agg['baseline_first_correct_at_1']}/{agg['tasks']}, "
        f"recall@5 {agg['baseline_recall_at_5']}, "
        f"irrelevantes {agg['baseline_irrelevant_reads']}",
        "",
    ]
    for case in data["cases"]:
        if "error" in case:
            lines.append(f"- {case['id']}: erro ({case['error']})")
            continue
        lines.append(
            f"- {case['id']}: first={case['first_correct_file_at_1']} "
            f"recall={case['recall_at_5']} tokens={case['brief_tokens']}"
        )
    return "\n".join(lines)
