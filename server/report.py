"""AI 판단 시각 vs 사람 기준 시각 비교 (±TOLERANCE_S 초 안이면 성공)."""
from . import config


def build_report(recipe: dict, fired: dict, labels: dict, tolerance: float = config.TOLERANCE_S) -> dict:
    rows = []
    for step in recipe["steps"]:
        ev = step["event"]
        ai, human = fired.get(ev["id"]), labels.get(ev["id"])
        diff = None
        if human is None:
            status = "unlabeled"
        elif ai is None:
            status = "miss"
        else:
            diff = round(ai - human, 1)
            status = "pass" if abs(diff) <= tolerance else ("early" if diff < 0 else "late")
        rows.append({"event_id": ev["id"], "label": ev["label"], "ai_t": ai, "human_t": human,
                     "diff": diff, "status": status})

    labeled = [r for r in rows if r["status"] != "unlabeled"]
    diffs = [abs(r["diff"]) for r in rows if r["diff"] is not None]
    passed = sum(r["status"] == "pass" for r in rows)
    return {
        "tolerance": tolerance,
        "rows": rows,
        "labeled": len(labeled),
        "passed": passed,
        "pass_rate": round(passed / len(labeled), 3) if labeled else None,
        "mae": round(sum(diffs) / len(diffs), 1) if diffs else None,
    }
