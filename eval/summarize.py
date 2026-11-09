"""모든 세션의 채점 결과를 레시피·이벤트별로 모아 '시작해도 되는가' 판단 자료를 만든다.

    .venv/bin/python -m eval.summarize               # 라이브(블라인드)+리플레이 모두
    .venv/bin/python -m eval.summarize --source replay --target 0.8

결과는 터미널과 data/summary.md 에 저장된다.
"""
import argparse
from collections import defaultdict

from server import config, storage
from server.recipes import get_recipe
from server.report import build_report


def collect(source: str):
    rows = []
    for sid in storage.list_sessions():
        d = storage.session_dir(sid)
        meta = storage.read_json(d / "meta.json")
        labels = storage.read_json(d / "labels.json", {})
        if not labels:
            continue
        recipe = get_recipe(meta["recipe_id"])
        for kind in (["live", "replay"] if source == "all" else [source]):
            ai = storage.read_json(d / f"ai_{kind}.json")
            # 코치 모드 라이브 결과는 사람이 AI 안내를 듣고 움직였으므로 독립 비교가 아님 → 제외
            if not ai or (kind == "live" and meta.get("mode") != "blind"):
                continue
            for r in build_report(recipe, ai["fired"], labels)["rows"]:
                if r["status"] != "unlabeled":
                    rows.append({**r, "sid": sid, "kind": kind, "recipe": recipe["name"]})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["all", "live", "replay"], default="all")
    ap.add_argument("--target", type=float, default=0.8, help="이벤트별 목표 적중률")
    args = ap.parse_args()

    rows = collect(args.source)
    if not rows:
        print("채점할 결과가 없어요. 블라인드 테스트를 하거나, 영상 라벨링 후 eval.replay 를 돌려주세요.")
        return

    groups = defaultdict(list)
    for r in rows:
        groups[(r["kind"], r["recipe"], r["label"])].append(r)

    tol = config.TOLERANCE_S
    lines = [f"# 타이밍 정확도 요약 (±{tol:.0f}초, 목표 적중률 {args.target:.0%})", "",
             "| 소스 | 요리 | 이벤트 | N | 적중률 | 평균오차 | 빠름 | 늦음 | 못잡음 | 판정 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for (kind, recipe, label), rs in sorted(groups.items()):
        n = len(rs)
        p = sum(r["status"] == "pass" for r in rs)
        diffs = [abs(r["diff"]) for r in rs if r["diff"] is not None]
        mae = f"{sum(diffs) / len(diffs):.1f}s" if diffs else "-"
        cnt = {k: sum(r["status"] == k for r in rs) for k in ("early", "late", "miss")}
        verdict = "OK" if p / n >= args.target else "부족"
        if n < 5:
            verdict += " (표본<5)"
        lines.append(f"| {kind} | {recipe} | {label} | {n} | {p / n:.0%} | {mae} | "
                     f"{cnt['early']} | {cnt['late']} | {cnt['miss']} | {verdict} |")

    total_p = sum(r["status"] == "pass" for r in rows)
    lines += ["", f"전체: {total_p}/{len(rows)} = {total_p / len(rows):.0%} "
                  f"(세션 {len({r['sid'] for r in rows})}개)"]
    text = "\n".join(lines)
    print(text)
    out = config.ROOT / "data" / "summary.md"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\n→ {out.relative_to(config.ROOT)} 저장")


if __name__ == "__main__":
    main()
