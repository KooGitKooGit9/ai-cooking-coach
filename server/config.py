"""환경 설정. 값은 프로젝트 루트의 .env 로 바꿀 수 있다."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.8-flash")
CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", VISION_MODEL)
# "minimal" | "low" | "medium" | "high" | "" (빈 값이면 모델 기본값)
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "low")

# 프레임 샘플링: ANALYZE_INTERVAL 초마다 한 번 Gemini 호출,
# 호출마다 FRAME_GAP 간격으로 찍은 FRAMES_PER_CALL 장을 보낸다 (보글거림 같은 움직임 판단용).
ANALYZE_INTERVAL = _f("ANALYZE_INTERVAL", 2.0)
FRAMES_PER_CALL = int(_f("FRAMES_PER_CALL", 3))
FRAME_GAP = _f("FRAME_GAP", 0.5)
FRAME_WIDTH = int(_f("FRAME_WIDTH", 512))

TOLERANCE_S = _f("TOLERANCE_S", 10.0)
SAVE_FRAMES = os.getenv("SAVE_FRAMES", "1") == "1"

DATA_DIR = ROOT / "data" / "sessions"
RECIPE_DIR = ROOT / "server" / "recipes"
WEB_DIR = ROOT / "web"
