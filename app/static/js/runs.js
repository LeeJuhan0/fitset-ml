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
        // 배포 열: 환경별로 현재 배포 버전이면 배지, 완료된 run이면 배포 버튼(롤백 포함)
        const action = ENVS.map(env => r.version === deployed[env]?.classifier?.latestVersion
          ? `<span class="pill deployed ${env}">${env} 배포됨</span>`
          : r.status === 'FINISHED' ? `<button class="btn-deploy-row ${env}" onclick="deployVersion('${r.version}', '${env}')">${env} 배포</button>`
          : '').join(' ');
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
