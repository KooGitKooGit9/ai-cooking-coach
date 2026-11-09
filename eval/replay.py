"""녹화 영상을 라이브와 똑같은 방식(같은 프레임 간격·프롬프트·발화 규칙)으로 Gemini에 다시 보여주고
AI 판단 시각을 ai_replay.json 에 저장한 뒤 사람 라벨과 비교해 채점한다.

    .venv/bin/python -m eval.replay <session_id> [<session_id> ...]
    .venv/bin/python -m eval.replay all            # 영상+라벨 있는 모든 세션
    .venv/bin/python -m eval.replay <id> --model gemini-3.5-flash-lite --interval 1.5

라이브와 다른 점: 영상 파일을 쓰므로 휴대폰-서버 네트워크 지연은 빠지고 Gemini 응답 지연만 더한다.
"""
import argparse
import asyncio
import time
from collections import deque

import cv2
import numpy as np

from server import config, storage
from server.engine import Engine
from server.gemini import Gemini
from server.recipes import get_recipe
from server.report import build_report


def resize(frame: np.ndarray, width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    return cv2.resize(frame, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)


def presence(frames: list[np.ndarray]) -> float:
    """web/app.js 의 peripheryMotion 과 같은 계산: 가운데(팬)를 뺀 주변부 움직임의 최댓값."""
    grays = [cv2.cvtColor(cv2.resize(f, (64, 36), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
             for f in frames]
    mask = np.ones((36, 64), bool)
    mask[9:27, 16:48] = False
    return max((float(np.abs(a - b)[mask].mean()) for a, b in zip(grays[1:], grays[:-1])), default=0.0)


def windows(path, interval: float, n: int, gap: float, width: int):
    """영상을 순서대로 읽으며 t = interval, 2*interval, ... 마다 [t-(n-1)*gap, ..., t] 프레임 묶음을 낸다."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"영상을 열 수 없어요: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    span = (n - 1) * gap
    buf: deque = deque()
    next_t = max(interval, span)
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if ts <= 0 and idx > 0:  # 일부 webm 은 타임스탬프가 비어 있음
            ts = idx / fps
        idx += 1
        buf.append((ts, resize(frame, width)))
        while buf and buf[0][0] < ts - span - 1:
            buf.popleft()
        while ts >= next_t:
            picks = [min(buf, key=lambda b: abs(b[0] - (next_t - k * gap)))[1] for k in reversed(range(n))]
            yield next_t, picks
            next_t += interval
    cap.release()


async def replay(sid: str, model: str | None, interval: float, verbose: bool) -> dict | None:
    d = storage.session_dir(sid)
    meta = storage.read_json(d / "meta.json")
    video = storage.find_video(sid)
    labels = storage.read_json(d / "labels.json", {})
    if not meta or not video or not video.exists():
        print(f"[{sid}] 영상이 없어 건너뜀")
        return None
    recipe = get_recipe(meta["recipe_id"])
    engine = Engine(recipe, "blind")
    engine.start(0.0)
    pending = sorted((t, eid) for eid, t in labels.items())
    gem = Gemini()
    model = model or config.VISION_MODEL
    print(f"[{sid}] {recipe['name']} · {model} · {interval}s 간격 · 라벨 {len(labels)}개")

    started = time.monotonic()
    calls = 0
    for t, frames in windows(video, interval, config.FRAMES_PER_CALL, config.FRAME_GAP, config.FRAME_WIDTH):
        while pending and pending[0][0] <= t:
            lt, eid = pending.pop(0)
            engine.command("label", lt, eid)
        if engine.done:
            break
        jpgs = [cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes() for f in frames]
        prompt = engine.prompt(t)
        t0 = time.monotonic()
        try:
            res = await gem.analyze(jpgs, prompt, model=model)
        except Exception as e:
            print(f"  {t:7.1f}s  Gemini 오류, 건너뜀: {e}")
            continue
        latency = time.monotonic() - t0
        calls += 1
        before = set(engine.fired)
        engine.on_analysis(res, t, latency, presence(frames))
        new = set(engine.fired) - before
        if verbose or new:
            mark = f"  ★ {', '.join(new)} 판단" if new else ""
            print(f"  {t:7.1f}s  [{engine.steps[min(engine.step_idx, len(engine.steps) - 1)]['event']['id']}] "
                  f"ready={res['event_ready']} conf={res['confidence']:.2f}  {res['observation']}{mark}")
    for lt, eid in pending:  # 영상 끝 이후 라벨
        engine.command("label", lt, eid)

    storage.write_json(d / "ai_replay.json", {
        "fired": engine.fired, "missed": sorted(engine.missed), "model": model, "interval": interval,
        "calls": calls, "elapsed_s": round(time.monotonic() - started, 1),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    (d / "log_replay.jsonl").unlink(missing_ok=True)
    storage.append_jsonl(d / "log_replay.jsonl", engine.log)
    report = build_report(recipe, engine.fired, labels)
    print_report(report)
    return report


def print_report(report: dict) -> None:
    status = {"pass": "✅ 성공", "early": "❌ 빠름", "late": "❌ 늦음", "miss": "❌ 못잡음", "unlabeled": "·  라벨없음"}
    for r in report["rows"]:
        h = "-" if r["human_t"] is None else f"{r['human_t']:.1f}"
        a = "-" if r["ai_t"] is None else f"{r['ai_t']:.1f}"
        diff = "" if r["diff"] is None else f"{r['diff']:+.1f}s"
        print(f"    {r['label']:<12} 사람 {h:>6}  AI {a:>6}  {diff:>7}  {status[r['status']]}")
    rate = "-" if report["pass_rate"] is None else f"{report['pass_rate'] * 100:.0f}%"
    print(f"    → ±{report['tolerance']:.0f}초 적중 {report['passed']}/{report['labeled']} ({rate}), 평균 오차 {report['mae']}초\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+", help="세션 id 들, 또는 all")
    ap.add_argument("--model", default=None)
    ap.add_argument("--interval", type=float, default=config.ANALYZE_INTERVAL)
    ap.add_argument("-v", "--verbose", action="store_true", help="모든 분석 결과 출력")
    args = ap.parse_args()
    sids = args.sessions
    if sids == ["all"]:
        sids = [s for s in storage.list_sessions()
                if storage.read_json(storage.session_dir(s) / "labels.json") and storage.find_video(s)]
    for sid in sids:
        asyncio.run(replay(sid, args.model, args.interval, args.verbose))


if __name__ == "__main__":
    main()
