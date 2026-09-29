// ── 배포 (dev: 우리 실험용, prod: 실사용자용) ─────────────────────────────
const ENVS = ['dev', 'prod'];

function confirmDeploy(target, env) {
  if (env !== 'prod') return confirm(`${target} 을 dev 에 배포하시겠습니까?`);
  return confirm(`[PROD] ${target} 을 실사용자에게 배포합니다. 계속하시겠습니까?`);
}

async function deployModel() {
  deployVersion(document.getElementById('deployBtn').dataset.version, 'dev');
}

// 이력 테이블·완료 배너 공용 배포 액션 — 과거 버전 재배포(롤백)도 이 경로를 쓴다
async function deployVersion(version, env) {
  if (!confirmDeploy(version, env)) return;
  try {
    await api('POST', '/deploy', { version, env });
    alert(`${env} 배포 완료!`);
    loadModelInfo();
  } catch(e) { alert(e.message); }
}

async function loadModelInfo() {
  const el = document.getElementById('modelInfo');
  try {
    const results = await Promise.all(ENVS.map(env => api('GET', `/models/deployed?env=${env}`)));
    ENVS.forEach((env, i) => { deployed[env] = results[i].data; });
    el.innerHTML = ENVS.map(env => {
      const c = deployed[env].classifier;
      return `<div class="env-row">
        <span class="pill env ${env}">${env}</span>
        ${c ? `<div class="deployed-version">${c.latestVersion}</div><div class="deployed-url">${c.modelUrl}</div>`
            : '<p class="empty">배포된 모델 없음</p>'}
      </div>`;
    }).join('');
  } catch(e) {
    deployed = { dev: null, prod: null };
    el.innerHTML = `<p class="empty">${e.message}</p>`;
  }
  renderRuns();          // 배포 배지가 환경별 최신 배포 버전을 따라가도록 재렌더
  if (phaseModels.length) { renderPhaseModels(); renderPhaseDeploy(); }
}
