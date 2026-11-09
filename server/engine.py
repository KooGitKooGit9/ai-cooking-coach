"""요리 코치 상태 머신.

라이브(휴대폰)와 오프라인 리플레이(eval/replay.py)가 똑같은 이 클래스를 쓴다.
시간 t 는 항상 '세션 시작(=녹화 시작) 후 몇 초' 기준이라 영상 타임라인과 바로 비교할 수 있다.

모드
- coach: 실제 코칭. 타이밍이 오면 음성으로 알려주고 다음 단계로 넘어간다.
- blind: 정확도 테스트. AI는 조용히 판단 시각만 기록하고, 요리하는 사람이 직접 행동할 때
  '했어요' 버튼(라벨)을 누른다. 나중에 둘을 비교해 ±10초 안에 맞혔는지 본다.
  안전 경보(넘침·연기·자리 비움)는 blind 모드에서도 말한다.
"""
from collections import deque
from dataclasses import dataclass, field

HAZARD_SAY = {
    "fire": "불이 붙었어요! 가스 불을 끄고 뚜껑이나 젖은 수건으로 덮으세요. 물은 절대 붓지 마세요!",
    "boil_over": "끓어 넘치려고 해요! 불을 줄여주세요!",
    "smoke": "기름에서 연기가 나요! 불을 줄이거나 팬을 잠깐 내려주세요.",
    "burning": "타고 있어요! 불을 줄이고 바로 저어주세요.",
}
HEAT_SAY = {
    "lower": "불을 조금 줄여주세요.",
    "raise": "불을 조금 올려도 돼요.",
    "turn_off": "지금 불을 꺼주세요.",
}
UNATTENDED_SAY = "불 켜두고 자리를 비우셨나요? 가스레인지를 확인해 주세요!"


@dataclass
class EngineConfig:
    fire_conf: float = 0.6          # 이 이상이어야 '준비됨'으로 셈
    fire_consecutive: int = 2       # 연속 몇 번 '준비됨'이면 발화
    instant_conf: float = 0.85      # 한 번만 나와도 바로 발화하는 확신도
    grace_s: float = 10.0           # blind: 사람이 먼저 행동한 뒤 AI를 더 기다려주는 시간
    pre_say_min_s: float = 5.0      # 단계 시작 후 이 시간 전에는 '곧' 안내 안 함
    advice_cooldown_s: float = 25.0
    hazard_cooldown_s: float = 15.0
    unattended_s: float = 120.0
    unattended_repeat_s: float = 30.0
    presence_motion: float = 4.0    # 주변부 움직임(0~255 평균 차이) 이 이상이면 사람 있음


@dataclass
class Engine:
    recipe: dict
    mode: str = "coach"
    cfg: EngineConfig = field(default_factory=EngineConfig)

    def __post_init__(self) -> None:
        self.step_idx = 0
        self.step_started = 0.0
        self.streak = 0
        self.pre_said = False
        self.history: deque = deque(maxlen=4)
        self.seen: set[str] = set()
        self.fired: dict[str, float] = {}     # AI 판단 시각
        self.labels: dict[str, float] = {}    # 사람 행동 시각 (blind)
        self.manual: dict[str, float] = {}    # coach 모드에서 '다음'으로 넘긴 시각
        self.missed: set[str] = set()
        self.grace_until: float | None = None
        self.hazard_streak: dict[str, int] = {}
        self.last_said: dict[str, float] = {}
        self.last_presence = 0.0
        self.done = False
        self.log: list[dict] = []

    # ---------- 공용 ----------
    @property
    def coach(self) -> bool:
        return self.mode == "coach"

    @property
    def steps(self) -> list[dict]:
        return self.recipe["steps"]

    @property
    def step(self) -> dict | None:
        return None if self.done else self.steps[self.step_idx]

    def _say(self, text: str, priority: str = "normal") -> dict:
        return {"type": "say", "text": text, "priority": priority}

    def _cooldown_ok(self, key: str, t: float, cooldown: float) -> bool:
        if t - self.last_said.get(key, -1e9) < cooldown:
            return False
        self.last_said[key] = t
        return True

    def _event_index(self, event_id: str) -> int:
        return next(i for i, s in enumerate(self.steps) if s["event"]["id"] == event_id)

    def state(self) -> dict:
        s = self.step
        return {
            "step_idx": self.step_idx,
            "n_steps": len(self.steps),
            "instruction": s["instruction"] if s else self.recipe.get("outro", ""),
            "event_id": s["event"]["id"] if s else None,
            "event_label": s["event"]["label"] if s else None,
            "done": self.done,
            "fired": self.fired,
            "labels": self.labels,
            "missed": sorted(self.missed),
            "in_grace": self.grace_until is not None,
        }

    def start(self, t: float = 0.0) -> list[dict]:
        self.step_started = t
        self.last_presence = t
        self.log.append({"t": t, "kind": "start", "mode": self.mode})
        if not self.coach:
            return []
        return [self._say(self.recipe["intro"]), self._say(self.steps[0]["instruction"])]

    # ---------- 프롬프트 ----------
    def prompt(self, t: float) -> str:
        s = self.step
        ev = s["event"]
        hist = "\n".join(f"- {t - ht:.0f}초 전: {obs}" for ht, obs in self.history) or "- (없음)"
        ings = ", ".join(f"{i['id']}({i['name']})" for i in self.recipe["ingredients"] if i.get("visible"))
        return f"""요리: {self.recipe['name']}
현재 단계 ({self.step_idx + 1}/{len(self.steps)}): {s['instruction']}
이 단계가 시작된 지 {t - self.step_started:.0f}초.

감시 중인 이벤트: {ev['label']}
- 지금 해야 할 때(조건): {ev['cue']}
- 아직 아닐 때: {ev.get('not_yet', '')}

최근 관찰:
{hist}

ingredients_seen 에는 화면(팬 안)에 보이는 재료 id만 넣어라. 후보: {ings}
"""

    # ---------- 분석 결과 반영 ----------
    def on_analysis(self, res: dict, t_frame: float, latency: float, presence: float | None = None) -> list[dict]:
        if self.done:
            return []
        t = round(t_frame + latency, 2)  # 사용자가 실제로 안내를 듣게 되는 시각
        acts: list[dict] = []
        s = self.step
        ev = s["event"]
        conf = float(res.get("confidence", 0))
        self.history.append((t_frame, res.get("observation", "")))
        self.seen.update(res.get("ingredients_seen", []))
        self.log.append({"t": t, "t_frame": t_frame, "latency": round(latency, 2), "kind": "analysis",
                         "step": self.step_idx, "event": ev["id"], "presence": presence, **res})

        acts += self._safety(res, t, presence)

        ready = bool(res.get("event_ready")) and conf >= self.cfg.fire_conf
        self.streak = self.streak + 1 if ready else 0
        if ready and (self.streak >= self.cfg.fire_consecutive or conf >= self.cfg.instant_conf
                      or res.get("overdue")):
            self.fired[ev["id"]] = t
            self.log.append({"t": t, "kind": "fire", "event": ev["id"], "confidence": conf})
            if self.coach:
                acts.append(self._say(ev["say"], "high"))
                missing = [i for i in s.get("expect_in_pan", []) if i not in self.seen]
                if missing:
                    names = ", ".join(self._ing_name(i) for i in missing)
                    acts.append(self._say(f"참, 혹시 {names} 넣으셨나요? 화면에서 잘 안 보여서요."))
            return acts + self._advance(t, "ai")

        if self.grace_until is not None and t > self.grace_until:
            self.missed.add(ev["id"])
            self.log.append({"t": t, "kind": "miss", "event": ev["id"]})
            return acts + self._advance(t, "grace_expired")

        if (self.coach and res.get("approaching") and not self.pre_said and ev.get("pre_say")
                and t - self.step_started >= self.cfg.pre_say_min_s):
            self.pre_said = True
            acts.append(self._say(ev["pre_say"]))
        elif self.coach and res.get("heat_advice", "none") != "none":
            adv = res["heat_advice"]
            if self._cooldown_ok("heat", t, self.cfg.advice_cooldown_s):
                acts.append(self._say(f"{HEAT_SAY[adv]} {res.get('heat_reason', '')}".strip()))
        return acts

    def _safety(self, res: dict, t: float, presence: float | None) -> list[dict]:
        acts = []
        hz = res.get("hazard", "none")
        for k in HAZARD_SAY:
            self.hazard_streak[k] = self.hazard_streak.get(k, 0) + 1 if hz == k else 0
        # 불은 즉시, 나머지는 2번 연속일 때만 (오경보 줄이기)
        if hz in HAZARD_SAY and (hz == "fire" or self.hazard_streak[hz] >= 2):
            if self._cooldown_ok(f"hazard:{hz}", t, self.cfg.hazard_cooldown_s):
                self.log.append({"t": t, "kind": "hazard", "hazard": hz})
                acts.append(self._say(HAZARD_SAY[hz], "urgent"))

        if res.get("hands_visible") or (presence is not None and presence >= self.cfg.presence_motion):
            self.last_presence = t
        elif t - self.last_presence > self.cfg.unattended_s:
            if self._cooldown_ok("unattended", t, self.cfg.unattended_repeat_s):
                self.log.append({"t": t, "kind": "hazard", "hazard": "unattended"})
                acts.append(self._say(UNATTENDED_SAY, "urgent"))
        return acts

    def _ing_name(self, ing_id: str) -> str:
        return next((i["name"] for i in self.recipe["ingredients"] if i["id"] == ing_id), ing_id)

    def _advance(self, t: float, reason: str) -> list[dict]:
        self.log.append({"t": t, "kind": "advance", "from": self.step_idx, "reason": reason})
        self.step_idx += 1
        self.step_started = t
        self.streak = 0
        self.pre_said = False
        self.grace_until = None
        self.history.clear()
        if self.step_idx >= len(self.steps):
            self.done = True
            self.step_idx = len(self.steps) - 1
            return ([self._say(self.recipe.get("outro", "완성이에요!"))] if self.coach else []) + [{"type": "done"}]
        return [self._say(self.steps[self.step_idx]["instruction"])] if self.coach else []

    # ---------- 사용자 입력 ----------
    def command(self, cmd: str, t: float, event_id: str | None = None) -> list[dict]:
        self.log.append({"t": t, "kind": "command", "cmd": cmd, "event": event_id})
        if cmd == "repeat":
            s = self.step
            return [self._say(s["instruction"] if s else self.recipe.get("outro", ""))]
        if self.done:
            return []
        if cmd == "next":
            self.manual[self.step["event"]["id"]] = t
            return self._advance(t, "manual")
        if cmd == "prev":
            if self.step_idx > 0:
                self.step_idx -= 1
                self.step_started, self.streak, self.pre_said, self.grace_until = t, 0, False, None
                self.history.clear()
            return [self._say(self.step["instruction"])] if self.coach else []
        if cmd == "label" and event_id:
            return self._label(event_id, t)
        return []

    def _label(self, event_id: str, t: float) -> list[dict]:
        self.labels[event_id] = t = round(t, 2)
        if event_id in self.fired or event_id in self.missed:
            return []
        j = self._event_index(event_id)
        if j < self.step_idx:
            return []
        # 사람이 AI보다 먼저 움직임: 건너뛴 이벤트는 미감지 처리하고, 이 이벤트는 grace_s 동안 더 지켜본다
        for k in range(self.step_idx, j):
            self.missed.add(self.steps[k]["event"]["id"])
        if j != self.step_idx:
            self.step_idx, self.step_started, self.streak = j, t, 0
            self.history.clear()
        self.grace_until = t + self.cfg.grace_s
        return []
