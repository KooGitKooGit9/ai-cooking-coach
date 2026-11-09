// 결과표 렌더링 (index.html, sessions.html 공용)
const STATUS_TEXT = {
  pass: '성공', early: '너무 빠름', late: '너무 늦음', miss: '못 잡음', unlabeled: '기준 없음',
};

function fmtT(t) {
  if (t == null) return '–';
  const m = Math.floor(t / 60), s = (t % 60).toFixed(1).padStart(4, '0');
  return `${m}:${s}`;
}

function renderReport(report, title = '') {
  if (!report) return `<p class="muted">${title ? title + ': ' : ''}아직 결과 없음</p>`;
  const rows = report.rows.map(r => `
    <tr class="st-${r.status}">
      <td>${r.label}</td>
      <td>${fmtT(r.human_t)}</td>
      <td>${fmtT(r.ai_t)}</td>
      <td>${r.diff == null ? '–' : (r.diff > 0 ? '+' : '') + r.diff + '초'}</td>
      <td><span class="pill">${STATUS_TEXT[r.status]}</span></td>
    </tr>`).join('');
  const rate = report.pass_rate == null ? '–' : Math.round(report.pass_rate * 100) + '%';
  return `
    <div class="report">
      ${title ? `<h3>${title}</h3>` : ''}
      <div class="kpis">
        <div><b>${rate}</b><span>±${report.tolerance}초 적중</span></div>
        <div><b>${report.passed}/${report.labeled}</b><span>성공/기준</span></div>
        <div><b>${report.mae == null ? '–' : report.mae + '초'}</b><span>평균 오차</span></div>
      </div>
      <table>
        <thead><tr><th>이벤트</th><th>사람</th><th>AI</th><th>차이</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
