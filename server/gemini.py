"""Gemini 호출: (1) 프레임 → 타이밍 판단 JSON, (2) 음성 질문 → 짧은 답변."""
import json

from google import genai
from google.genai import types

from . import config

VISION_SYSTEM = """너는 한식 요리 코치의 '눈'이다.
휴대폰이 레인지후드 아래에서 팬을 위에서 내려다보며 찍은 연속 프레임(시간순, 약 0.5초 간격)을 받는다.
할 일: 지금 장면이 '감시 중인 이벤트'의 타이밍 조건을 만족하는지 판단한다.

원칙
- 조건이 화면에서 분명히 보일 때만 event_ready=true. 곧 될 것 같으면 approaching=true.
- 조건을 이미 지나쳤다면(너무 익음, 너무 탐) event_ready=true 이고 overdue=true. 늦는 것이 가장 나쁘다.
- 거품 위치 변화, 기름 표면의 일렁임처럼 프레임 사이의 변화가 정지 이미지보다 중요한 단서다.
- 열화상 센서는 없다. 온도는 시각 단서(일렁임, 연기, 거품, 색)로만 추정한다.
- 손·뒤집개·김이 가려서 판단이 어려우면 confidence를 낮춘다.
- observation 은 한국어 30자 이내로, 지금 보이는 핵심만 쓴다.
- hazard: 넘치기 직전/넘침=boil_over, 기름 연기=smoke, 불꽃이 팬 위로=fire, 재료가 검게 탐=burning.
- heat_advice: 화면 단서상 불이 너무 세면 lower, 너무 약해서 진행이 안 되면 raise, 즉시 꺼야 하면 turn_off, 그 외 none.
"""

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "observation": {"type": "string"},
        "event_ready": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "approaching": {"type": "boolean"},
        "overdue": {"type": "boolean"},
        "heat_advice": {"type": "string", "enum": ["none", "lower", "raise", "turn_off"]},
        "heat_reason": {"type": "string"},
        "hazard": {"type": "string", "enum": ["none", "boil_over", "smoke", "fire", "burning"]},
        "pan_visible": {"type": "boolean"},
        "hands_visible": {"type": "boolean"},
        "ingredients_seen": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "observation", "event_ready", "confidence", "approaching", "overdue",
        "heat_advice", "hazard", "pan_visible", "hands_visible", "ingredients_seen",
    ],
}

CHAT_SYSTEM = """너는 처음 요리하는 사람 옆에서 도와주는 한식 요리 코치다.
답은 스피커로 읽히므로 1~3문장, 구어체 존댓말로 짧게 말한다. 이모지·마크다운·목록 기호는 쓰지 않는다.
사진이 함께 오면 지금 팬 상태를 보고 답한다. 확실하지 않으면 확인하는 방법(색, 소리, 젓가락 테스트 등)을 알려준다.
안전 문제(기름에 불, 연기)가 보이면 그것부터 말한다."""


class Gemini:
    def __init__(self) -> None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY 가 없습니다. .env 파일을 확인하세요.")
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)

    def _config(self, **kw) -> types.GenerateContentConfig:
        if config.THINKING_LEVEL:
            kw["thinking_config"] = types.ThinkingConfig(thinking_level=config.THINKING_LEVEL)
        return types.GenerateContentConfig(**kw)

    async def analyze(self, frames: list[bytes], prompt: str, model: str | None = None) -> dict:
        parts = [types.Part.from_bytes(data=f, mime_type="image/jpeg") for f in frames]
        resp = await self.client.aio.models.generate_content(
            model=model or config.VISION_MODEL,
            contents=[*parts, prompt],
            config=self._config(
                system_instruction=VISION_SYSTEM,
                response_mime_type="application/json",
                response_json_schema=VISION_SCHEMA,
                temperature=0.2,
            ),
        )
        return json.loads(resp.text)

    async def chat(self, context: str, history: list[dict], text: str, frame: bytes | None) -> str:
        contents = [
            types.Content(role=h["role"], parts=[types.Part.from_text(text=h["text"])]) for h in history
        ]
        parts = [types.Part.from_text(text=text)]
        if frame:
            parts.insert(0, types.Part.from_bytes(data=frame, mime_type="image/jpeg"))
        contents.append(types.Content(role="user", parts=parts))
        resp = await self.client.aio.models.generate_content(
            model=config.CHAT_MODEL,
            contents=contents,
            config=self._config(system_instruction=CHAT_SYSTEM + "\n\n" + context, temperature=0.6),
        )
        return (resp.text or "").strip()
