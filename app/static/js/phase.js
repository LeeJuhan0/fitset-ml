const PHASE_CLASSES = ['SQUAT', 'PUSHUP', 'DUMBBELL_CURL'];
const MODEL_STATUS = { training: '학습 중', completed: '완료', failed: '실패' };
let phaseModels = [];
let openPhaseDetail = null;   // 파일별 렙 오차를 펼친 모델 id

function phaseDeployed(env, cls) {
  return deployed[env]?.phaseModels.find(p => p.class === cls);
}

async function loadPhaseModels() {
  const el = document.getElementById('phaseModelList');
  const sel = document.getElementById('phaseTrainClass');
  if (!sel.options.length) {
    try {
      const ex = await fetch('/api/v1/exercises').then(r => r.json());
      const supported = ex.data.exercises.filter(e => e.phaseSupported).map(e => e.class);
      sel.innerHTML = (supported.length ? supported : PHASE_CLASSES).map(c => `<option value="${c}">${c}</option>`).join('');
    } catch (e) { sel.innerHTML = PHASE_CLASSES.map(c => `<option value="${c}">${c}</option>`).join(''); }
  }
  try {
    const { data } = await api('GET', '/phase/models');
    phaseModels = data.models;
    renderPhaseModels();
    renderPhaseDeploy();
    if (phaseModels.some(m => m.status === 'training')) setTimeout(loadPhaseModels, 8000);
  } catch (e) { el.innerHTML = `<p class="empty" style="color:#DC2626">${e.message}</p>`; }
}

function renderPhaseModels() {
  const el = document.getElementById('phaseModelList');
  document.getElementById('phaseModelCount').textContent = `${phaseModels.length}개 버전`;
  if (!phaseModels.length) { el.innerHTML = '<p class="empty">학습된 렙카운팅 모델이 없습니다</p>'; return; }
  el.innerHTML = `
    <table class="data-table">
      <thead><tr><th>종목</th><th>버전</th><th>상태</th><th>파일</th><th title="val (괄호는 학습 데이터 평가)">macro F1</th><th title="val (괄호는 학습 데이터 평가)">렙 오차</th><th>윈도우</th><th class="cell-right" style="text-align:right">생성</th><th>다운로드</th></tr></thead>
      <tbody>${phaseModels.map(m => {
        const v = m.metrics?.val ?? {}, f = m.metrics?.final ?? {};
        const badge = m.status === 'failed' ? `<span class="pill failed" title="${(m.error ?? '').replace(/"/g, '&quot;')}">실패</span>`
          : m.status === 'training' ? '<span class="pill labeling">학습 중</span>' : '<span class="pill labeled">완료</span>';
        const dl = m.canDownload
          ? ['pt', 'onnx', 'mlpackage'].map(x => `<button class="dl-btn" onclick="event.stopPropagation();downloadPhaseModel(${m.id},'${x}')">${x}</button>`).join('')
          : '';
        const open = openPhaseDetail === m.id;
        return `<tr class="${open ? 'selected' : ''}" onclick="togglePhaseDetail(${m.id})" title="클릭하면 파일별 렙 오차">
          <td><span class="pill class">${m.class}</span></td>
          <td><b>${m.version}</b>${ENVS.filter(env => phaseDeployed(env, m.class)?.latestVersion === m.version).map(env => ` <span class="pill env ${env}">${env}</span>`).join('')}</td>
          <td>${badge}</td>
          <td>${m.numFiles}</td>
          <td>${valAndFinal(v.macro_f1, f.macro_f1)}</td>
          <td>${valAndFinal(v.count_mae, f.count_mae)}</td>
          <td style="color:#9CA3AF">${m.window}/${m.stride}</td>
          <td class="cell-right"><div class="v">${fmtDate(m.createdAt)}</div></td>
          <td style="white-space:nowrap">${dl}</td>
        </tr>${open ? `<tr class="detail-row"><td colspan="9">${phaseDetail(m)}</td></tr>` : ''}`;
      }).join('')}</tbody>
    </table>`;
}

function valAndFinal(v, f) {
  return `${v ?? '-'} <span style="color:#9CA3AF">(${f ?? '-'})</span>`;
}

function togglePhaseDetail(id) {
  openPhaseDetail = openPhaseDetail === id ? null : id;
  renderPhaseModels();
}

// 파일별 렙 수, val 은 각 파일 끝 VAL_FRAC 구간, final 은 전체 재학습 모델을 학습 데이터 그대로 평가
function phaseDetail(m) {
  const val = m.metrics?.val, fin = m.metrics?.final;
  if (!val && !fin) return '<p class="empty">지표 없음</p>';
  const vf = val?.per_file ?? {}, ff = fin?.per_file ?? {};
  const diff = r => r ? r.model_count - r.label_count : null;
  const names = [...new Set([...Object.keys(vf), ...Object.keys(ff)])]
    .sort((a, b) => Math.abs(diff(vf[b]) ?? 0) - Math.abs(diff(vf[a]) ?? 0) || Math.abs(diff(ff[b]) ?? 0) - Math.abs(diff(ff[a]) ?? 0));
  const diffCell = d => d == null ? '<td>-</td>' : `<td class="${d ? 'count-off' : 'count-ok'}">${d > 0 ? '+' : ''}${d}</td>`;
  const summary = (name, x) => x ? `${name} acc ${x.acc} · F1 ${x.macro_f1} · 렙 오차 ${x.count_mae ?? '-'}` : `${name} 없음`;
  return `<div class="phase-detail">
    <div class="modal-sub">${summary('val', val)} &nbsp;|&nbsp; ${summary('학습 데이터', fin)}<br>
      val 은 파일마다 끝 20% 구간만 센 렙 수, 학습 데이터 평가는 학습에 쓴 데이터라 실제보다 좋게 나온다. 파일을 누르면 영상에서 예측을 본다</div>
    <table class="stats-table per-file-table">
      <thead><tr><th>파일</th><th>val 라벨</th><th>val 모델</th><th>val 차이</th><th>전체 라벨</th><th>전체 모델</th><th>전체 차이</th></tr></thead>
      <tbody>${names.map(n => `<tr onclick="event.stopPropagation();openVideoFromDataset('${n}', ${m.id})">
        <td>${n}</td>
        <td>${vf[n]?.label_count ?? '-'}</td><td>${vf[n]?.model_count ?? '-'}</td>${diffCell(diff(vf[n]))}
        <td>${ff[n]?.label_count ?? '-'}</td><td>${ff[n]?.model_count ?? '-'}</td>${diffCell(diff(ff[n]))}
      </tr>`).join('')}</tbody>
    </table>
  </div>`;
}

// 학습 파일명은 승격된 {stem}.parquet, 수집 파일은 {stem}.csv
function openVideoFromDataset(datasetName, modelId) {
  const filename = datasetName.replace(/\.parquet$/, '.csv');
  if (!videoFiles.some(f => f.filename === filename)) { alert(`영상 목록에 없는 파일입니다: ${filename}`); return; }
  openVideo(filename, modelId);
}

function renderPhaseDeploy() {
  const el = document.getElementById('phaseDeployList');
  const byClass = {};
  phaseModels.filter(m => m.canDownload).forEach(m => (byClass[m.class] ??= []).push(m));
  const classes = Object.keys(byClass).sort();
  document.getElementById('phaseDeployCount').textContent = `${classes.length}개 종목`;
  if (!classes.length) { el.innerHTML = '<p class="empty">배포할 수 있는 완료 모델이 없습니다. 렙카운트 학습 페이지에서 먼저 학습하세요</p>'; return; }
  el.innerHTML = `
    <table class="data-table">
      <thead><tr><th>종목</th>${ENVS.map(env => `<th>${env} 버전</th><th>${env} 배포 시각</th>`).join('')}<th>버전 선택</th><th></th></tr></thead>
      <tbody>${classes.map(c => {
        const current = phaseDeployed('dev', c);
        const options = byClass[c].map(m => {
          const f = m.metrics?.final ?? {};
          const selected = current ? m.version === current.latestVersion : m === byClass[c][0];
          return `<option value="${m.id}" ${selected ? 'selected' : ''}>${m.version} · F1 ${f.macroF1 ?? f.macro_f1 ?? '-'} · 렙 오차 ${f.countMae ?? f.count_mae ?? '-'}</option>`;
        }).join('');
        const envCells = ENVS.map(env => {
          const d = phaseDeployed(env, c);
          return d ? `<td><b>${d.latestVersion}</b></td><td>${fmtDate(d.updatedAt)}</td>`
            : '<td><span style="color:#9CA3AF">미배포</span></td><td>-</td>';
        }).join('');
        return `<tr>
          <td><span class="pill class">${c}</span></td>
          ${envCells}
          <td><select class="status-filter" id="deploySel_${c}">${options}</select></td>
          <td><div style="display:flex;gap:6px">${ENVS.map(env => `<button class="btn-label ${env}" onclick="deployPhaseModel('${c}', '${env}')">${env} 배포</button>`).join('')}</div></td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
}

async function deployPhaseModel(cls, env) {
  const id = document.getElementById(`deploySel_${cls}`).value;
  const m = phaseModels.find(x => String(x.id) === id);
  if (!confirmDeploy(`${cls} ${m.version}`, env)) return;
  try {
    await api('POST', `/phase/models/${id}/deploy`, { env });
    loadModelInfo();
  } catch (e) { alert(e.message); }
}

async function startPhaseTraining() {
  const btn = document.getElementById('phaseTrainBtn');
  btn.disabled = true;
  try {
    const { data } = await api('POST', '/phase/train', {
      class: document.getElementById('phaseTrainClass').value,
      epochs: parseInt(document.getElementById('phaseTrainEpochs').value),
      lr: parseFloat(document.getElementById('phaseTrainLr').value),
    });
    alert(`${data.class} ${data.version} 학습 시작 (파일 ${data.numFiles}개)`);
    loadPhaseModels();
  } catch (e) { alert(e.message); }
  btn.disabled = false;
}

async function downloadPhaseModel(id, fmt) {
  try {
    const { data } = await api('GET', `/phase/models/${id}/download-url?format=${fmt}`);
    window.open(data.url, '_blank');
  } catch (e) { alert(e.message); }
}
