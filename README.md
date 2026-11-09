# AI Cooking Coach — phone prototype

**English summary.** A phone browser films the pan, a server on a Mac asks Gemini whether it is time for the next step, and the phone speaks the instruction (for example, "pour the egg now"). The first goal of this prototype is an accuracy test: does the AI's timing land within ±10 s of a person's judgment? `eval/replay.py` replays recorded sessions and `eval/summarize.py` reports the timing error. Recorded sessions (`data/`) and API keys (`.env`) are not included in this repository.

---

# AI 요리 코치 — 휴대폰 프로토타입

레인지후드 아래 기기 대신 **휴대폰 하나**로 카메라·스피커·마이크를 모두 대신합니다.
휴대폰 브라우저가 팬을 찍고, 맥에서 도는 서버가 Gemini로 타이밍을 판단해서
"지금 계란물 부으세요", "지금 불 끄세요" 같은 안내를 휴대폰 스피커로 말해줍니다.

이 프로토타입의 첫 번째 목적은 **⚠️ 시작 전에 정확도 테스트하기**입니다:
AI 타이밍이 사람 기준 ±10초 안에 들어오는지 계란말이·소스 볶기로 측정합니다.

## 실행

```bash
cp .env.example .env      # GEMINI_API_KEY 채우기 (https://aistudio.google.com/apikey)
./run.sh
```

1. 맥과 휴대폰을 **같은 와이파이**에 연결합니다.
2. 터미널에 나온 `https://<맥IP>:8443` 으로 휴대폰에서 접속합니다.
3. 브라우저는 https 에서만 카메라를 열어줘서, `run.sh` 가 집 안에서만 쓰는 로컬 인증기관(CA)과 인증서를 만듭니다.
   - **iPhone (처음 한 번만):** iOS Safari는 경고 화면에서 "방문"을 눌러도 통과가 안 되는 경우가 있어서 CA를 설치합니다.
     1. Safari로 `http://<맥IP>:8080/cooking-coach-ca.crt` 열기 → **허용**
     2. 설정 앱 맨 위 **프로파일이 다운로드됨** → **설치**
     3. 설정 → 일반 → 정보 → 맨 아래 **인증서 신뢰 설정** → `AI Cooking Coach Local CA` 켜기
   - **Android Chrome:** 경고 화면에서 **고급 → 계속**
   - 맥 IP가 바뀌어도 서버 인증서만 자동으로 다시 만들어지고, 아이폰에 CA를 다시 설치할 필요는 없습니다.
4. 카메라 권한을 허용합니다.

## 휴대폰 설치

- 집게형 플렉시블 거치대로 **팬 바로 위 40~60cm**에서 내려다보게 고정합니다.
- 김이 렌즈에 바로 닿지 않게 살짝 비스듬히 둡니다.
- 화면 꺼짐 방지는 앱이 자동으로 켭니다. 소리는 크게 켜두세요.

## 두 가지 모드

| | 🗣️ 코치 모드 | 🧪 정확도 테스트 (블라인드) |
|---|---|---|
| AI 음성 안내 | 타이밍·불 세기·재료 빠뜨림 | 끔 (안전 경보만 켜짐) |
| 사람이 할 일 | 안내 따라 요리 | 평소처럼 요리하다가 행동하는 순간 큰 버튼 **"✋ 했어요"** 탭 (또는 "했어"라고 말하기) |
| 결과 | 영상·프레임 저장 | 이벤트별 AI vs 사람 시각 차이, ±10초 적중률 |

블라인드 모드가 필요한 이유: 코치 모드에서는 사람이 AI 말을 듣고 움직이므로
"AI가 맞혔는지"를 독립적으로 잴 수 없습니다.

공통 기능
- **끓어 넘침·연기·불·탐** 경보 (2번 연속 보일 때 경보, 불은 바로 경보)
- **자리 비움** 경보: 손도 안 보이고 화면 가장자리 움직임도 없이 2분이 지나면 경보
- **🎤 질문하기**: "이거 다 익었어요?" → 지금 화면을 같이 보고 Gemini가 답변
- **계속 듣기**: "코치야, ○○" 로 질문, "다음" / "다시" / "이전" 음성 명령

## 1주일 정확도 테스트 방법

1. 각자 집에서 **정확도 테스트 모드**로 계란말이·고추장 소스를 각각 3번 이상 만듭니다.
   - 버튼을 누르기 어려우면 영상만 녹화돼도 괜찮습니다. 나중에 라벨링 페이지에서 찍으면 됩니다.
   - 앱 없이 그냥 휴대폰 카메라로 위에서 찍어도 됩니다 → `기록 · 라벨링` 페이지에서 영상 올리기.
2. `기록 · 라벨링` 페이지에서 영상을 보며 사람 기준 시각을 확인·수정합니다.
3. 맥에서 리플레이 채점을 돌립니다. 라이브와 같은 방식(2초마다, 0.5초 간격 3장)으로 영상을 다시 판단합니다.
   프롬프트나 모델을 바꿀 때마다 요리를 다시 할 필요 없이 같은 영상으로 비교할 수 있습니다.

   ```bash
   .venv/bin/python -m eval.replay all
   ```

   ```bash
   .venv/bin/python -m eval.replay all --model gemini-3.5-flash-lite
   ```

4. 전체 요약 (이벤트별 적중률, 평균 오차, 빠름/늦음/못잡음):

   ```bash
   .venv/bin/python -m eval.summarize --target 0.8
   ```

   `data/summary.md` 에 표로 저장됩니다. 이벤트별 표본이 5개 미만이면 `(표본<5)` 로 표시됩니다.

채점 규칙
- `AI 시각 − 사람 시각`이 ±10초 안이면 성공. AI 시각에는 Gemini 응답 지연이 포함됩니다 (사용자가 실제로 듣는 시각).
- 사람이 먼저 행동하면 AI를 10초 더 기다려줍니다. 그래도 판단이 안 나오면 "못 잡음".

## 구조

```
web/              휴대폰 웹앱 (카메라, TTS, 음성인식, 녹화)
  index.html/app.js     요리 화면
  sessions.html/.js     기록 · 라벨링 · 결과
server/
  main.py         FastAPI (웹앱 제공, Gemini 중계, 세션 저장)
  engine.py       타이밍 상태 머신 — 라이브와 리플레이가 같은 코드를 씀
  gemini.py       프레임 → 판단 JSON / 질문 → 답변
  recipes/*.json  레시피: 단계별 "지금 해야 할 때" 시각 단서(cue), 안내 문구
eval/
  replay.py       녹화 영상 → AI 판단 재현 → 채점
  summarize.py    전체 세션 집계
data/sessions/<id>/    영상, 라벨, AI 판단, 로그, Gemini에 보낸 프레임
```

레시피 추가/수정은 `server/recipes/*.json` 만 고치면 됩니다. 정확도에 가장 큰 영향을 주는 건
각 이벤트의 `cue`(지금 해야 할 때)와 `not_yet`(아직 아닐 때) 문장입니다.

판단 민감도는 `server/engine.py` 의 `EngineConfig` 에서 조절합니다
(`fire_conf` 확신도 기준, `fire_consecutive` 연속 횟수, `instant_conf` 즉시 발화 기준).

## 원래 설계와 다른 점 (휴대폰이라서)

| 원래 계획 | 지금 프로토타입 |
|---|---|
| 라즈베리파이 + 카메라 | 휴대폰 카메라 (브라우저) |
| 기기 안 작은 AI가 매 순간 판단 | Gemini Flash가 2초마다 판단 (클라우드) |
| 열화상 센서로 팬 온도 | 없음. 기름 일렁임·연기·거품 같은 **시각 단서로만** 불 세기 조언 |
| 스피커 | 휴대폰 TTS |
| Gemini 음성 대화 | 브라우저 음성인식 → Gemini 텍스트 답변 → TTS |

`SAVE_FRAMES=1`(기본값)이면 Gemini에 보낸 모든 프레임과 판단 결과, 사람 라벨이 쌓입니다.
이게 나중에 라즈베리파이용 작은 모델을 학습시킬 데이터가 됩니다.

## 알려진 한계

- iPhone은 처음에 CA 인증서 설치가 필요합니다 (위 실행 3번). 번거로우면 `cloudflared tunnel` 같은 터널로 정식 https 주소를 만들 수도 있지만, 그 주소는 인터넷에 공개됩니다.
- iPhone은 음성인식 연속 듣기가 가끔 끊깁니다. 그럴 땐 🎤 버튼을 쓰세요.
- 녹화에는 소리가 들어가지 않습니다 (음성인식과 마이크가 충돌하는 브라우저가 있어서).
  지글거리는 소리도 좋은 단서라서 나중에 따로 넣어볼 만합니다.
- 서버를 재시작하면 진행 중인 세션은 끊깁니다 (저장된 기록은 남음).
