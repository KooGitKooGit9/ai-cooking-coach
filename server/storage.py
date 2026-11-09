"""세션 파일 저장 구조 (data/sessions/<id>/)

meta.json        레시피, 모드, 생성시각, 영상 파일명
labels.json      사람 기준 시각 {event_id: t}
ai_live.json     라이브에서 AI가 판단한 시각 {fired, missed}
ai_replay.json   녹화 영상을 리플레이해서 AI가 판단한 시각
log.jsonl        엔진 로그 (모든 Gemini 응답 포함)
frames/          Gemini에 보낸 프레임 + 응답 (나중에 온디바이스 모델 학습 데이터)
"""
import json
import time
import uuid
from pathlib import Path

from . import config


def new_session_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def session_dir(sid: str) -> Path:
    if "/" in sid or ".." in sid:
        raise ValueError("bad session id")
    return config.DATA_DIR / sid


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def list_sessions() -> list[str]:
    if not config.DATA_DIR.exists():
        return []
    return sorted((p.name for p in config.DATA_DIR.iterdir() if (p / "meta.json").exists()), reverse=True)


def find_video(sid: str) -> Path | None:
    meta = read_json(session_dir(sid) / "meta.json", {})
    name = meta.get("video")
    return session_dir(sid) / name if name else None
