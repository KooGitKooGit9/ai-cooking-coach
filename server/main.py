"""FastAPI 서버: 휴대폰 웹앱 제공 + Gemini 중계 + 세션/라벨 저장.

실행: ./run.sh  (HTTPS 인증서 생성 후 https://<맥IP>:8443 으로 접속)
"""
import asyncio
import time
from dataclasses import dataclass, field

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, storage
from .engine import Engine
from .gemini import Gemini
from .recipes import all_recipes, get_recipe
from .report import build_report

app = FastAPI(title="AI 요리 코치")
_gemini: Gemini | None = None


def gemini() -> Gemini:
    global _gemini
    if _gemini is None:
        try:
            _gemini = Gemini()
        except RuntimeError as e:
            raise HTTPException(503, str(e))
    return _gemini


@dataclass
class Live:
    sid: str
    engine: Engine
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    chat: list[dict] = field(default_factory=list)
    log_flushed: int = 0

    def flush_log(self) -> None:
        d = storage.session_dir(self.sid)
        storage.append_jsonl(d / "log.jsonl", self.engine.log[self.log_flushed:])
        self.log_flushed = len(self.engine.log)


LIVE: dict[str, Live] = {}


def live(sid: str) -> Live:
    if sid not in LIVE:
        raise HTTPException(404, "세션이 없거나 서버가 재시작됐어요. 처음부터 다시 시작해 주세요.")
    return LIVE[sid]


# ---------------- 설정 / 레시피 ----------------
@app.get("/api/config")
def get_config():
    return {
        "analyze_interval": config.ANALYZE_INTERVAL,
        "frames_per_call": config.FRAMES_PER_CALL,
        "frame_gap": config.FRAME_GAP,
        "frame_width": config.FRAME_WIDTH,
        "tolerance": config.TOLERANCE_S,
        "model": config.VISION_MODEL,
        "gemini_ready": bool(config.GEMINI_API_KEY),
    }


@app.get("/api/recipes")
def recipes():
    return list(all_recipes().values())


# ---------------- 라이브 세션 ----------------
class StartReq(BaseModel):
    recipe_id: str
    mode: str = "coach"  # coach | blind


@app.post("/api/sessions")
def start_session(req: StartReq):
    try:
        recipe = get_recipe(req.recipe_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    if req.mode not in ("coach", "blind"):
        raise HTTPException(400, "mode must be coach or blind")
    sid = storage.new_session_id()
    storage.write_json(storage.session_dir(sid) / "meta.json", {
        "id": sid, "recipe_id": recipe["id"], "mode": req.mode, "source": "live",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "model": config.VISION_MODEL, "video": None,
    })
    s = Live(sid, Engine(recipe, req.mode))
    LIVE[sid] = s
    actions = s.engine.start(0.0)
    s.flush_log()
    return {"session_id": sid, "actions": actions, "state": s.engine.state()}


@app.post("/api/sessions/{sid}/frames")
async def frames(sid: str, t: float = Form(...), presence: float | None = Form(None),
                 frames: list[UploadFile] = File(...)):
    s = live(sid)
    if s.lock.locked():
        raise HTTPException(429, "이전 분석이 아직 진행 중")
    async with s.lock:
        if s.engine.done:
            return {"actions": [], "state": s.engine.state(), "analysis": None}
        imgs = [await f.read() for f in frames]
        prompt = s.engine.prompt(t)
        t0 = time.monotonic()
        try:
            res = await gemini().analyze(imgs, prompt)
        except HTTPException:
            raise
        except Exception as e:  # 네트워크/쿼터 오류는 이번 프레임만 건너뜀
            raise HTTPException(502, f"Gemini 오류: {e}")
        latency = time.monotonic() - t0
        actions = s.engine.on_analysis(res, t, latency, presence)
        if config.SAVE_FRAMES:
            fdir = storage.session_dir(sid) / "frames"
            fdir.mkdir(parents=True, exist_ok=True)
            for i, img in enumerate(imgs):
                (fdir / f"{t:08.2f}_{i}.jpg").write_bytes(img)
        s.flush_log()
        return {"actions": actions, "state": s.engine.state(), "analysis": res, "latency": round(latency, 2)}


class CommandReq(BaseModel):
    cmd: str  # next | prev | repeat | label
    t: float
    event_id: str | None = None


@app.post("/api/sessions/{sid}/command")
async def command(sid: str, req: CommandReq):
    s = live(sid)
    actions = s.engine.command(req.cmd, req.t, req.event_id)
    s.flush_log()
    return {"actions": actions, "state": s.engine.state()}


@app.post("/api/sessions/{sid}/chat")
async def chat(sid: str, text: str = Form(...), t: float = Form(0), frame: UploadFile | None = File(None)):
    s = live(sid)
    e = s.engine
    step = e.step
    recent = " / ".join(obs for _, obs in e.history) or "없음"
    ctx = (f"레시피: {e.recipe['name']}\n재료: "
           + ", ".join(f"{i['name']} {i['amount']}" for i in e.recipe["ingredients"])
           + f"\n전체 단계: " + " → ".join(st["event"]["label"] for st in e.steps)
           + f"\n지금 단계: {step['instruction'] if step else '완료'}\n최근 화면 관찰: {recent}")
    if not e.coach:
        ctx += "\n(정확도 테스트 중이므로 '지금 넣으세요' 같은 타이밍 판단은 말하지 말 것)"
    img = await frame.read() if frame else None
    try:
        answer = await gemini().chat(ctx, s.chat[-8:], text, img)
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(502, f"Gemini 오류: {ex}")
    s.chat += [{"role": "user", "text": text}, {"role": "model", "text": answer}]
    e.log.append({"t": t, "kind": "chat", "q": text, "a": answer})
    s.flush_log()
    return {"answer": answer}


class FinishReq(BaseModel):
    t: float


@app.post("/api/sessions/{sid}/finish")
def finish(sid: str, req: FinishReq):
    s = live(sid)
    e = s.engine
    e.log.append({"t": req.t, "kind": "finish"})
    s.flush_log()
    d = storage.session_dir(sid)
    storage.write_json(d / "ai_live.json", {"fired": e.fired, "missed": sorted(e.missed), "manual": e.manual})
    labels = storage.read_json(d / "labels.json", {})
    labels.update(e.labels)
    storage.write_json(d / "labels.json", labels)
    meta = storage.read_json(d / "meta.json")
    meta["duration"] = req.t
    storage.write_json(d / "meta.json", meta)
    return {"report": build_report(e.recipe, e.fired, labels)}


@app.post("/api/sessions/{sid}/video")
async def upload_video(sid: str, file: UploadFile = File(...)):
    d = storage.session_dir(sid)
    meta = storage.read_json(d / "meta.json")
    if meta is None:
        raise HTTPException(404, "no session")
    ext = (file.filename or "video.webm").rsplit(".", 1)[-1].lower()
    name = f"video.{ext if ext in ('webm', 'mp4', 'mov', 'm4v') else 'webm'}"
    with (d / name).open("wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    meta["video"] = name
    storage.write_json(d / "meta.json", meta)
    return {"ok": True, "video": name}


# ---------------- 세션 목록 / 라벨링 ----------------
@app.post("/api/videos")
async def new_video_session(recipe_id: str = Form(...), file: UploadFile = File(...)):
    """앱 없이 찍은 영상(일반 카메라)을 올려서 라벨링 + 리플레이 평가용 세션으로 만든다."""
    get_recipe(recipe_id)
    sid = storage.new_session_id()
    storage.write_json(storage.session_dir(sid) / "meta.json", {
        "id": sid, "recipe_id": recipe_id, "mode": "blind", "source": "upload",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"), "video": None, "filename": file.filename,
    })
    await upload_video(sid, file)
    return {"session_id": sid}


def _session_summary(sid: str) -> dict:
    d = storage.session_dir(sid)
    meta = storage.read_json(d / "meta.json")
    recipe = get_recipe(meta["recipe_id"])
    labels = storage.read_json(d / "labels.json", {})
    out = {**meta, "recipe_name": recipe["name"], "labels": labels}
    for kind in ("live", "replay"):
        ai = storage.read_json(d / f"ai_{kind}.json")
        out[f"report_{kind}"] = build_report(recipe, ai["fired"], labels) if ai else None
    return out


@app.get("/api/sessions")
def sessions():
    return [_session_summary(sid) for sid in storage.list_sessions()]


@app.get("/api/sessions/{sid}")
def session(sid: str):
    if not (storage.session_dir(sid) / "meta.json").exists():
        raise HTTPException(404, "no session")
    return _session_summary(sid)


class LabelsReq(BaseModel):
    labels: dict[str, float]


@app.put("/api/sessions/{sid}/labels")
def put_labels(sid: str, req: LabelsReq):
    storage.write_json(storage.session_dir(sid) / "labels.json", req.labels)
    return _session_summary(sid)


@app.get("/api/sessions/{sid}/video")
def get_video(sid: str):
    path = storage.find_video(sid)
    if not path or not path.exists():
        raise HTTPException(404, "영상 없음")
    return FileResponse(path)


@app.get("/")
def index():
    return RedirectResponse("/index.html")


app.mount("/", StaticFiles(directory=config.WEB_DIR), name="web")
