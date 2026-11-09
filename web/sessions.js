const $ = s => document.querySelector(s);
let recipes = {}, current = null;

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function toast(msg) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 3000);
}
const pct = r => (r && r.pass_rate != null ? Math.round(r.pass_rate * 100) + '%' : '–');

async function loadList() {
  const list = await api('/api/sessions');
  $('#sessions').innerHTML = list.length ? list.map(s => `
    <a class="sessionItem" href="#${s.id}">
      <b>${s.recipe_name}</b> · ${s.mode === 'blind' ? '🧪 테스트' : '🗣️ 코치'}${s.source === 'upload' ? ' · 업로드' : ''}
      <small>${s.created} · 라벨 ${Object.keys(s.labels).length}개 · 라이브 ${pct(s.report_live)} · 리플레이 ${pct(s.report_replay)}${s.video ? '' : ' · 영상 없음'}</small>
    </a>`).join('') : '<p class="muted">아직 기록이 없어요.</p>';
}

async function loadDetail(sid) {
  const s = await api(`/api/sessions/${sid}`);
  current = s;
  const recipe = recipes[s.recipe_id];
  $('#dTitle').textContent = s.recipe_name;
  $('#dMeta').textContent = `${s.created} · ${s.mode === 'blind' ? '정확도 테스트' : '코치 모드'} · ${s.source}${s.model ? ' · ' + s.model : ''}`;
  const v = $('#review');
  $('#noVideo').classList.toggle('hidden', !!s.video);
  v.classList.toggle('hidden', !s.video);
  if (s.video) v.src = `/api/sessions/${sid}/video`;

  $('#labelRows').innerHTML = recipe.steps.map(st => `
    <div class="labelRow" data-id="${st.event.id}">
      <span>${st.event.label}</span>
      <input type="number" step="0.1" min="0" inputmode="decimal" value="${s.labels[st.event.id] != null ? (+s.labels[st.event.id]).toFixed(1) : ''}" placeholder="–">
      <button class="ghost mark">현재 시점</button>
      <button class="ghost seek">▶</button>
    </div>`).join('');
  document.querySelectorAll('.labelRow').forEach(row => {
    const input = row.querySelector('input');
    row.querySelector('.mark').onclick = () => { input.value = v.currentTime.toFixed(1); };
    row.querySelector('.seek').onclick = () => {
      if (input.value !== '') { v.currentTime = Math.max(0, +input.value - 3); v.play(); }
    };
  });
  renderReports(s);
  $('#replayCmd').textContent = `.venv/bin/python -m eval.replay ${sid}`;
}

function renderReports(s) {
  $('#dReports').innerHTML = renderReport(s.report_live, '라이브 AI 판단') + renderReport(s.report_replay, '리플레이 AI 판단');
}

$('#btnSave').onclick = async () => {
  const labels = {};
  document.querySelectorAll('.labelRow').forEach(row => {
    const val = row.querySelector('input').value;
    if (val !== '') labels[row.dataset.id] = parseFloat(val);
  });
  try {
    const s = await api(`/api/sessions/${current.id}/labels`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ labels }),
    });
    renderReports(s);
    toast('저장했어요');
  } catch (e) { toast('저장 실패: ' + e.message); }
};

$('#uploadForm').onsubmit = async e => {
  e.preventDefault();
  const file = $('#upFile').files[0];
  if (!file) return toast('영상 파일을 고르세요');
  const fd = new FormData();
  fd.append('recipe_id', $('#upRecipe').value);
  fd.append('file', file);
  $('#upStatus').textContent = '올리는 중…';
  try {
    const r = await api('/api/videos', { method: 'POST', body: fd });
    $('#upStatus').textContent = '';
    location.hash = r.session_id;
  } catch (err) { $('#upStatus').textContent = '실패: ' + err.message; }
};

async function route() {
  const sid = location.hash.slice(1);
  document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
  if (sid) {
    $('#detail').classList.add('active');
    try { await loadDetail(sid); } catch (e) { toast(e.message); }
  } else {
    $('#list').classList.add('active');
    $('#review').pause();
    loadList();
  }
  window.scrollTo(0, 0);
}

(async () => {
  const list = await api('/api/recipes');
  list.forEach(r => { recipes[r.id] = r; });
  $('#upRecipe').innerHTML = list.map(r => `<option value="${r.id}">${r.emoji} ${r.name}</option>`).join('');
  window.onhashchange = route;
  route();
})();
