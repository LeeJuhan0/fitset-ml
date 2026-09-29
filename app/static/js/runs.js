// ── 학습 이력 · 선택 배포 ──────────────────────────────────────────────
async function loadRuns() {
  const el = document.getElementById('runsBox');
  try {
    const { data } = await api('GET', '/runs');
    runsData = data.runs || [];
    bestRunId = data.bestRunId ?? null;
    renderRuns();
    renderBestAcc();
  } catch(e) { el.innerHTML = `<p class="empty" style="color:#DC2626">${e.message}</p>`; }
}

function renderRuns() {
  const el = document.getElementById('runsBox');
  if (!el) return;
  if (!runsData.length) { el.innerHTML = '<p class="empty">학습 이력 없음</p>'; return; }
  el.innerHTML = `
    <table class="runs-table">
      <thead><tr>
        <th>버전</th><th>상태</th><th>Val Acc</th><th>F1</th><th>파일</th><th>시작</th><th>소요</th><th></th>
      </tr></thead>
      <tbody>${runsData.map(r => {
        const acc = r.metrics.valAccuracy != null ? (r.metrics.valAccuracy * 100).toFixed(1) + '%' : '-';
        const f1  = r.metrics.f1Macro != null ? r.metrics.f1Macro.toFixed(3) : '-';
        const started = new Date(r.startTime).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        const dur = r.duration != null ? `${Math.floor(r.duration / 60)}분 ${r.duration % 60}초` : '-';
        const statusBadge = r.status === 'FAILED' ? `<span class="pill failed" title="${(r.error ?? '').replace(/"/g, '&quot;')}">실패</span>`
          : r.status === 'RUNNING' ? '<span class="pill idle">학습 중</span>'
          : '<span class="pill trained">완료</span>';
        // 배포 열: 현재 배포 버전이면 배지, 완료된 run이면 배포 버튼(롤백 포함)
        const action = r.version === deployedVersion ? '<span class="pill deployed">배포됨</span>'
          : r.status === 'FINISHED' ? `<button class="btn-deploy-row" onclick="deployVersion('${r.version}')">배포</button>`
          : '';
        return `<tr>
          <td><b>${r.version}</b>${r.runId === bestRunId ? ' <span class="pill best">BEST</span>' : ''}</td>
          <td>${statusBadge}</td>
          <td>${acc}</td>
          <td>${f1}</td>
          <td>${r.params.numFiles ?? '-'}</td>
          <td style="color:#9CA3AF">${started}</td>
          <td style="color:#9CA3AF">${dur}</td>
          <td>${action}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
}

// ── 버전 분포 (오렌지 가로 막대 랭킹) ──────────────────────────────────
async function loadVersionStats() {
  const el = document.getElementById('versionStats');
  try {
    const { data } = await api('GET', '/model/version-stats');
    if (!data.stats.length) { el.innerHTML = '<p class="empty">최근 24시간 리포트 없음</p>'; return; }
    const maxRatio = Math.max(...data.stats.map(s => s.ratio), 0.0001);
    el.innerHTML = data.stats.map(s => `
      <div class="dist-row">
        <div class="dist-bar ${s.version === data.latestVersion ? 'latest' : ''}"
             style="width:${Math.max(10, Math.round(s.ratio / maxRatio * 78))}%">${s.version}</div>
        <span class="dist-num">${s.count}건 · ${Math.round(s.ratio * 100)}%</span>
      </div>`).join('')
      + `<div class="dist-caption">최근 24시간 폴링 리포트 ${data.totalReports}건 기준 · 진한 막대 = 최신 배포 버전</div>`;
  } catch(e) { el.innerHTML = `<p class="empty">${e.message}</p>`; }
}
