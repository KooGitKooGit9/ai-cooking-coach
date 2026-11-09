// AI 요리 코치 — 휴대폰 웹앱
// 휴대폰 = 카메라(눈) + 스피커(TTS) + 마이크(STT). 판단은 서버를 거쳐 Gemini가 한다.
const $ = s => document.querySelector(s);

const S = {
  cfg: null, recipes: [], recipe: null, mode: 'coach', record: true,
  stream: null, facing: 'environment', sid: null, t0: 0, running: false,
  frames: [], prevSmall: null, inFlight: false, timers: [], calls: 0, errors: 0,
  recorder: null, chunks: [], mime: '', state: null, wakeLock: null,
};
const now = () => (performance.now() - S.t0) / 1000;

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const err = new Error(body.detail || r.statusText);
    err.status = r.status;
    throw err;
  }
  return r.json();
}
const post = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

function show(id) {
  document.querySelectorAll('.screen').forEach(el => el.classList.toggle('active', el.id === id));
  window.scrollTo(0, 0);
}
let toastTimer;
function toast(msg, ms = 3000) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), ms);
}

// ---------------- 음성 출력 (TTS) ----------------
const Speech = {
  voice: null,
  init() {
    const pick = () => {
      const vs = speechSynthesis.getVoices().filter(v => v.lang.replace('_', '-').startsWith('ko'));
      this.voice = vs.find(v => /premium|enhanced|yuna|google/i.test(v.name)) || vs[0] || null;
    };
    pick();
    speechSynthesis.onvoiceschanged = pick;
  },
  unlock() { // iOS: 사용자 터치 안에서 한 번 말해야 이후 자동 발화가 된다
    const u = new SpeechSynthesisUtterance(' ');
    u.volume = 0;
    speechSynthesis.speak(u);
  },
  say(text, priority = 'normal') {
    if (!text) return;
    if (priority === 'urgent' || priority === 'high') speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ko-KR';
    if (this.voice) u.voice = this.voice;
    u.rate = priority === 'urgent' ? 1.15 : 1.05;
    u.onstart = () => Listener.pause();
    u.onend = () => { if (!speechSynthesis.pending) Listener.resume(); };
    speechSynthesis.speak(u);
    if (text === $('#instruction').textContent) return; // 화면에 이미 큰 글씨로 떠 있음
    const cap = $('#caption');
    cap.textContent = text;
    cap.className = 'caption ' + priority;
    if ((priority === 'urgent' || priority === 'high') && navigator.vibrate) navigator.vibrate([200, 100, 200]);
  },
};

// ---------------- 음성 입력 (STT) ----------------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const Listener = {
  rec: null, handsfree: false, busy: false, paused: false,
  available: !!SR,
  make() {
    const rec = new SR();
    rec.lang = 'ko-KR';
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.continuous = false;
    rec.onresult = e => {
      const text = e.results[e.results.length - 1][0].transcript.trim();
      if (text) handleUtterance(text, this.handsfree);
    };
    rec.onerror = e => { if (e.error !== 'no-speech' && e.error !== 'aborted') toast('음성 인식 오류: ' + e.error); };
    rec.onend = () => {
      this.busy = false;
      $('#btnAsk').classList.remove('listening');
      if (this.handsfree && !this.paused && S.running) setTimeout(() => this.listen(), 300);
    };
    return rec;
  },
  listen() {
    if (!this.available) {
      const text = prompt('질문을 입력하세요 (이 브라우저는 음성 인식을 지원하지 않아요)');
      if (text) handleUtterance(text, false);
      return;
    }
    if (this.busy) return;
    this.rec = this.rec || this.make();
    try {
      this.rec.start();
      this.busy = true;
      $('#btnAsk').classList.add('listening');
    } catch (_) { /* 이미 시작됨 */ }
  },
  pause() { this.paused = true; if (this.busy) this.rec.abort(); },
  resume() { this.paused = false; if (this.handsfree && S.running) this.listen(); },
  setHandsfree(on) {
    this.handsfree = on;
    if (on) this.listen(); else if (this.busy) this.rec.abort();
  },
};

async function handleUtterance(text, fromHandsfree) {
  const short = text.replace(/\s/g, '').length <= 8;
  if (short && /다음|넘어가/.test(text)) return command('next');
  if (short && /이전|뒤로/.test(text)) return command('prev');
  if (short && /다시|뭐라고/.test(text)) return command('repeat');
  if (S.mode === 'blind' && short && /했어|했다|넣었|부었|껐어|줄였/.test(text)) return labelNow('voice');
  // 계속 듣기 모드에서는 "코치"를 부를 때만 질문으로 처리 (잡담·소음 오인식 방지)
  if (fromHandsfree && !/코치/.test(text)) return;
  await ask(text.replace(/^.*?코치(야|님)?[,\s]*/, '') || text);
}

async function ask(text) {
  toast('🤔 ' + text);
  const fd = new FormData();
  fd.append('text', text);
  fd.append('t', now().toFixed(2));
  const last = S.frames[S.frames.length - 1];
  if (last) fd.append('frame', last.blob, 'frame.jpg');
  try {
    const r = await api(`/api/sessions/${S.sid}/chat`, { method: 'POST', body: fd });
    Speech.say(r.answer);
  } catch (e) {
    toast('답변 실패: ' + e.message);
  }
}

// ---------------- 카메라 ----------------
async function openCamera() {
  if (S.stream) S.stream.getTracks().forEach(t => t.stop());
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('카메라를 쓸 수 없어요. https:// 주소로 접속했는지 확인하세요.');
  }
  S.stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: S.facing }, width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  });
  const v = $('#video');
  v.srcObject = S.stream;
  await v.play().catch(() => {});
}

const big = document.createElement('canvas');
const bigCtx = big.getContext('2d');
const small = document.createElement('canvas');
small.width = 64; small.height = 36;
const smallCtx = small.getContext('2d', { willReadFrequently: true });

// 주변부(가운데 팬 영역 제외) 움직임 = 사람이 근처에 있는지. eval/replay.py 의 presence() 와 같은 계산.
function peripheryMotion(cur, prev) {
  let sum = 0, n = 0;
  for (let y = 0; y < 36; y++) {
    for (let x = 0; x < 64; x++) {
      if (x >= 16 && x < 48 && y >= 9 && y < 27) continue;
      const i = (y * 64 + x);
      sum += Math.abs(cur[i] - prev[i]);
      n++;
    }
  }
  return sum / n;
}

function grabFrame() {
  const v = $('#video');
  if (!v.videoWidth) return;
  const w = S.cfg.frame_width, h = Math.round(v.videoHeight * w / v.videoWidth);
  big.width = w; big.height = h;
  bigCtx.drawImage(v, 0, 0, w, h);
  smallCtx.drawImage(v, 0, 0, 64, 36);
  const px = smallCtx.getImageData(0, 0, 64, 36).data;
  const gray = new Float32Array(64 * 36);
  for (let i = 0; i < gray.length; i++) gray[i] = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2];
  const motion = S.prevSmall ? peripheryMotion(gray, S.prevSmall) : 0;
  S.prevSmall = gray;
  const t = now();
  big.toBlob(blob => {
    S.frames.push({ t, blob, motion });
    while (S.frames.length > S.cfg.frames_per_call) S.frames.shift();
  }, 'image/jpeg', 0.75);
}

// ---------------- 분석 루프 ----------------
async function analyze() {
  if (!S.running || S.inFlight || S.frames.length < S.cfg.frames_per_call) return;
  const frames = S.frames.slice();
  const fd = new FormData();
  fd.append('t', frames[frames.length - 1].t.toFixed(2));
  fd.append('presence', Math.max(...frames.slice(1).map(f => f.motion)).toFixed(2));
  frames.forEach((f, i) => fd.append('frames', f.blob, `f${i}.jpg`));
  S.inFlight = true;
  try {
    const r = await api(`/api/sessions/${S.sid}/frames`, { method: 'POST', body: fd });
    S.calls++;
    render(r.state, r.analysis, r.latency);
    runActions(r.actions);
  } catch (e) {
    if (e.status !== 429) {
      S.errors++;
      toast('분석 실패: ' + e.message);
    }
  } finally {
    S.inFlight = false;
  }
}

function runActions(actions = []) {
  for (const a of actions) {
    if (a.type === 'say') Speech.say(a.text, a.priority);
    if (a.type === 'done') setTimeout(() => { if (S.running) toast('완성! "요리 끝내기"를 눌러 결과를 확인하세요', 6000); }, 500);
  }
}

function render(state, analysis, latency) {
  if (state) {
    S.state = state;
    $('#instruction').textContent = state.instruction;
    $('#stepBadge').textContent = state.done ? '완료' : `${state.step_idx + 1}/${state.n_steps}`;
    const next = nextLabelEvent();
    $('#btnLabel').disabled = !next;
    $('#labelName').textContent = next ? next.label : '모두 기록됨';
  }
  if (analysis && S.mode === 'coach') {
    $('#obs').textContent = analysis.observation;
    const c = Math.round((analysis.confidence || 0) * 100);
    $('#confFill').style.width = (analysis.event_ready ? c : Math.min(c, 40)) + '%';
    $('#confFill').className = analysis.event_ready ? 'ready' : (analysis.approaching ? 'near' : '');
    const bits = [`${S.state.event_label}: ${analysis.event_ready ? '지금!' : analysis.approaching ? '곧' : '아직'} (${c}%)`];
    if (analysis.heat_advice !== 'none') bits.push('불: ' + analysis.heat_advice);
    if (analysis.hazard !== 'none') bits.push('⚠️ ' + analysis.hazard);
    bits.push(`${latency}s`);
    $('#aiMeta').textContent = bits.join(' · ');
  }
  if (S.mode === 'blind') {
    $('#blindInfo').textContent = `AI가 조용히 기록 중 · 분석 ${S.calls}회${S.errors ? ` · 오류 ${S.errors}` : ''}`;
  }
}

// 블라인드 모드: 사람이 아직 기록하지 않은 첫 이벤트
function nextLabelEvent() {
  if (!S.recipe) return null;
  const labels = S.state?.labels || {};
  return S.recipe.steps.map(s => s.event).find(ev => !(ev.id in labels)) || null;
}

async function command(cmd, eventId = null) {
  try {
    const r = await post(`/api/sessions/${S.sid}/command`, { cmd, t: now(), event_id: eventId });
    render(r.state);
    runActions(r.actions);
  } catch (e) {
    toast(e.message);
  }
}

async function labelNow(source = 'tap') {
  const ev = nextLabelEvent();
  if (!ev) return;
  if (navigator.vibrate) navigator.vibrate(80);
  toast(`✋ "${ev.label}" 기록 (${fmtT(now())})${source === 'voice' ? ' · 음성' : ''}`);
  await command('label', ev.id);
}

// ---------------- 녹화 ----------------
function startRecorder() {
  if (!S.record || !window.MediaRecorder) return;
  const types = ['video/mp4;codecs=avc1', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
  S.mime = types.find(t => MediaRecorder.isTypeSupported(t)) || '';
  S.chunks = [];
  S.recorder = new MediaRecorder(S.stream, { mimeType: S.mime || undefined, videoBitsPerSecond: 2_500_000 });
  S.recorder.ondataavailable = e => { if (e.data.size) S.chunks.push(e.data); };
  S.recorder.start(1000);
  $('#recBadge').classList.remove('hidden');
}

function stopRecorder() {
  return new Promise(resolve => {
    if (!S.recorder || S.recorder.state === 'inactive') return resolve(null);
    S.recorder.onstop = () => resolve(new Blob(S.chunks, { type: S.recorder.mimeType || S.mime }));
    S.recorder.stop();
  });
}

function uploadVideo(blob) {
  return new Promise((resolve, reject) => {
    const ext = blob.type.includes('mp4') ? 'mp4' : 'webm';
    const fd = new FormData();
    fd.append('file', blob, `video.${ext}`);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/sessions/${S.sid}/video`);
    xhr.upload.onprogress = e => {
      const p = Math.round(100 * e.loaded / e.total);
      $('#uploadPct').textContent = p + '%';
      $('#uploadFill').style.width = p + '%';
    };
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(xhr.statusText)));
    xhr.onerror = () => reject(new Error('네트워크 오류'));
    xhr.send(fd);
  });
}

// ---------------- 화면 꺼짐 방지 ----------------
async function keepAwake() {
  try { S.wakeLock = await navigator.wakeLock?.request('screen'); } catch (_) { /* 미지원 */ }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && S.running) keepAwake();
});

// ---------------- 흐름 ----------------
async function startCooking() {
  Speech.unlock();
  const btn = $('#btnStart');
  btn.disabled = true;
  try {
    const r = await post('/api/sessions', { recipe_id: S.recipe.id, mode: S.mode });
    S.sid = r.session_id;
    startRecorder();
    S.t0 = performance.now();   // 시간 0 = 녹화 시작 (영상 타임라인과 일치)
    S.running = true;
    S.calls = S.errors = 0;
    S.frames = [];
    S.prevSmall = null;
    $('#videoSlot').appendChild($('#video'));
    $('#video').play().catch(() => {}); // DOM 이동 시 재생이 멈춤
    const blind = S.mode === 'blind';
    $('#aiBox').classList.toggle('hidden', blind);
    $('#blindBox').classList.toggle('hidden', !blind);
    $('#btnLabel').classList.toggle('hidden', !blind);
    $('#btnNext').classList.toggle('hidden', blind);
    $('#btnPrev').classList.toggle('hidden', blind);
    $('#caption').textContent = '';
    show('cook');
    keepAwake();
    render(r.state);
    runActions(r.actions);
    if (blind) toast('행동할 때마다 큰 버튼을 누르거나 "했어"라고 말해주세요', 6000);
    S.timers.push(setInterval(grabFrame, S.cfg.frame_gap * 1000));
    S.timers.push(setInterval(analyze, S.cfg.analyze_interval * 1000));
    S.timers.push(setInterval(() => { $('#clock').textContent = fmtT(now()).replace(/\.\d$/, ''); }, 500));
  } catch (e) {
    toast('시작 실패: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

async function finishCooking() {
  if (!confirm('요리를 끝낼까요?')) return;
  S.running = false;
  S.timers.forEach(clearInterval);
  S.timers = [];
  Listener.setHandsfree(false);
  $('#optHandsfree').checked = false;
  speechSynthesis.cancel();
  S.wakeLock?.release?.();
  const t = now();
  const blob = await stopRecorder();
  $('#recBadge').classList.add('hidden');
  S.stream?.getTracks().forEach(tr => tr.stop());
  S.stream = null;
  show('result');
  $('#reportBox').innerHTML = '<p class="muted">결과 계산 중…</p>';
  try {
    const r = await post(`/api/sessions/${S.sid}/finish`, { t });
    $('#reportBox').innerHTML = S.mode === 'blind'
      ? renderReport(r.report, `${S.recipe.name} · 정확도 테스트`)
      : `<p class="muted">코치 모드는 사람 기준 시각이 없어 점수를 내지 않아요. 영상을 라벨링하면 리플레이로 채점할 수 있어요.</p>`;
  } catch (e) {
    $('#reportBox').innerHTML = `<p class="warn">결과 저장 실패: ${e.message}</p>`;
  }
  $('#linkSession').href = `sessions.html#${S.sid}`;
  if (blob && blob.size) {
    $('#uploadBox').classList.remove('hidden');
    try {
      await uploadVideo(blob);
      $('#uploadBox').innerHTML = `<p>✅ 영상 저장 완료 (${(blob.size / 1e6).toFixed(1)}MB)</p>`;
    } catch (e) {
      $('#uploadBox').innerHTML = `<p class="warn">영상 업로드 실패: ${e.message}</p>`;
    }
  }
}

async function init() {
  Speech.init();
  [S.cfg, S.recipes] = await Promise.all([api('/api/config'), api('/api/recipes')]);
  $('#keyWarn').classList.toggle('hidden', S.cfg.gemini_ready);
  $('#recipeList').innerHTML = S.recipes.map(r => `
    <button class="card" data-id="${r.id}">
      <span class="emoji">${r.emoji || '🍽️'}</span>
      <span><b>${r.name}</b><small>${r.description}</small>
      <small class="evs">${r.steps.map(s => s.event.label).join(' → ')}</small></span>
    </button>`).join('');
  document.querySelectorAll('.card').forEach(el => el.onclick = () => {
    document.querySelectorAll('.card').forEach(c => c.classList.toggle('selected', c === el));
    S.recipe = S.recipes.find(r => r.id === el.dataset.id);
    $('#btnSetup').disabled = false;
  });

  $('#btnSetup').onclick = async () => {
    S.mode = document.querySelector('input[name=mode]:checked').value;
    S.record = $('#optRecord').checked;
    Speech.unlock();
    try {
      await openCamera();
      show('setup');
    } catch (e) {
      toast('카메라 실패: ' + e.message, 6000);
    }
  };
  $('#btnFlip').onclick = async () => {
    S.facing = S.facing === 'environment' ? 'user' : 'environment';
    try { await openCamera(); } catch (e) { toast(e.message); }
  };
  $('#btnBack1').onclick = () => {
    S.stream?.getTracks().forEach(t => t.stop());
    show('home');
  };
  $('#btnStart').onclick = startCooking;
  $('#btnNext').onclick = () => command('next');
  $('#btnPrev').onclick = () => command('prev');
  $('#btnRepeat').onclick = () => command('repeat');
  $('#btnLabel').onclick = () => labelNow('tap');
  $('#btnAsk').onclick = () => { Speech.unlock(); Listener.listen(); };
  $('#optHandsfree').onchange = e => {
    if (e.target.checked && !Listener.available) {
      e.target.checked = false;
      return toast('이 브라우저는 음성 인식을 지원하지 않아요 (Chrome/Safari 권장)');
    }
    Listener.setHandsfree(e.target.checked);
    if (e.target.checked) toast('"코치야, ○○○" 로 질문하세요. "다음", "다시"도 돼요', 5000);
  };
  $('#btnFinish').onclick = finishCooking;
  $('#btnHome').onclick = () => {
    $('#setup .videoWrap').prepend($('#video'));
    $('#instruction').textContent = '';
    $('#uploadBox').classList.add('hidden');
    $('#uploadBox').innerHTML = '<p>영상 업로드 중… <span id="uploadPct">0%</span></p><div class="confBar"><div id="uploadFill"></div></div>';
    show('home');
  };
}

init().catch(e => toast('초기화 실패: ' + e.message, 8000));
