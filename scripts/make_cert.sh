#!/usr/bin/env bash
# 휴대폰 브라우저는 https 에서만 카메라를 열어준다.
# iOS Safari 는 자체 서명 인증서를 '방문'으로 통과시켜 주지 않는 경우가 있어서,
# 로컬 인증기관(CA)을 한 번 만들고 → 아이폰에 그 CA를 설치·신뢰 → CA로 서명한 서버 인증서를 쓴다.
# CA는 한 번만 만들고, 맥 IP가 바뀌면 서버 인증서만 다시 만든다 (아이폰 재설치 불필요).
set -e
cd "$(dirname "$0")/.."
IP="${1:?usage: make_cert.sh <mac-ip>}"
mkdir -p certs/public

if [ ! -f certs/ca.key ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 820 \
    -keyout certs/ca.key -out certs/public/cooking-coach-ca.crt \
    -subj "/CN=AI Cooking Coach Local CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
  echo "로컬 CA 생성: certs/public/cooking-coach-ca.crt (아이폰에 한 번 설치 필요)"
fi

cat > certs/server.ext <<EOF
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:${IP},IP:127.0.0.1,DNS:localhost
EOF
openssl req -new -newkey rsa:2048 -nodes -sha256 \
  -keyout certs/key.pem -out certs/server.csr -subj "/CN=${IP}" 2>/dev/null
openssl x509 -req -in certs/server.csr -sha256 -days 397 \
  -CA certs/public/cooking-coach-ca.crt -CAkey certs/ca.key -CAserial certs/ca.srl -CAcreateserial \
  -extfile certs/server.ext -out certs/cert.pem 2>/dev/null
rm -f certs/server.csr certs/server.ext
echo "$IP" > certs/ip.txt
echo "서버 인증서 생성: certs/cert.pem (IP ${IP})"
