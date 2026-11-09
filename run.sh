#!/usr/bin/env bash
# 서버 실행: 휴대폰과 맥이 같은 와이파이에 있어야 한다.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  .env 를 만들었어요. GEMINI_API_KEY 를 채워주세요."
fi

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
if [ -z "$IP" ]; then
  echo "❌ 맥의 와이파이 IP를 못 찾았어요. 와이파이에 연결했는지 확인하세요."
  exit 1
fi
PORT="${PORT:-8443}"
CA_PORT="${CA_PORT:-8080}"
if [ ! -f certs/ca.key ] || ! grep -qx "$IP" certs/ip.txt 2>/dev/null; then
  ./scripts/make_cert.sh "$IP"
fi

# 아이폰이 CA 인증서를 받아갈 수 있게 http 로 certs/public 만 열어둔다 (개인키는 이 폴더에 없음)
.venv/bin/python -m http.server "$CA_PORT" --bind 0.0.0.0 --directory certs/public >/dev/null 2>&1 &
CA_PID=$!
trap 'kill $CA_PID 2>/dev/null' EXIT

cat <<EOF

  📱 휴대폰 브라우저에서 접속:  https://${IP}:${PORT}

  처음 한 번만 (아이폰): 인증서 설치
    1) Safari로  http://${IP}:${CA_PORT}/cooking-coach-ca.crt  열기 → '허용'
    2) 설정 앱 맨 위 '프로파일이 다운로드됨' → 설치
    3) 설정 → 일반 → 정보 → 맨 아래 '인증서 신뢰 설정' → AI Cooking Coach Local CA 켜기
  안드로이드: 경고 화면에서 '고급 → 계속' 으로 들어가면 됩니다.

EOF
.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port "$PORT" \
  --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
