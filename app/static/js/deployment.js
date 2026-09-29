// ── 배포 ───────────────────────────────────────────────────────────────
async function deployModel() {
  deployVersion(document.getElementById('deployBtn').dataset.version);
}

// 이력 테이블·완료 배너 공용 배포 액션 — 과거 버전 재배포(롤백)도 이 경로를 쓴다
async function deployVersion(version) {
  if (!confirm(`${version} 배포하시겠습니까?`)) return;
  try {
    await api('POST', '/deploy', { version });
    alert('배포 완료!');
    loadModelInfo();
    loadRuns();
    loadVersionStats();
  } catch(e) { alert(e.message); }
}

async function loadModelInfo() {
  const el = document.getElementById('modelInfo');
  try {
    const { data } = await api('GET', '/model/latest');
    deployedVersion = data.latestVersion;
    el.innerHTML = `
      <div class="deployed-version">${data.latestVersion}</div>
      <div class="deployed-url">${data.modelUrl}</div>`;
  } catch(e) {
    deployedVersion = null;
    el.innerHTML = `<p class="empty">${e.status === 404 ? '배포된 모델 없음' : e.message}</p>`;
  }
  renderRuns();   // 배포 배지가 최신 배포 버전을 따라가도록 재렌더
}
