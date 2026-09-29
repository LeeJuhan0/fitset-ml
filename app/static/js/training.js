// ── KPI ────────────────────────────────────────────────────────────────
function renderKpis() {
  document.getElementById('kpiFileCount').textContent = allFiles.length;
  const untrained = allFiles.filter(f => !f.isTrained).length;
  document.getElementById('kpiFileSub').textContent = `등록된 CSV 파일 · 미학습 ${untrained}개`;
}

function renderBestAcc() {
  const done = runsData.filter(r => r.status === 'FINISHED' && r.metrics.valAccuracy != null);
  if (!done.length) {
    document.getElementById('kpiBestAcc').textContent = '-';
    document.getElementById('kpiAccArrow').style.display = 'none';
    document.getElementById('kpiAccSub').textContent = '완료된 학습 없음';
    return;
  }
  const best = Math.max(...done.map(r => r.metrics.valAccuracy));
  document.getElementById('kpiBestAcc').textContent = (best * 100).toFixed(1) + '%';
  document.getElementById('kpiAccArrow').style.display = 'inline-flex';
  document.getElementById('kpiAccSub').textContent = `완료된 학습 ${done.length}회 중 최고 검증 정확도`;
}

// ── 학습 ───────────────────────────────────────────────────────────────
async function startTrain() {
  if (!selectedFiles.size) { alert('파일을 1개 이상 선택하세요'); return; }
  const btn = document.getElementById('trainBtn');
  btn.disabled = true;
  try {
    const { data } = await api('POST', '/train', {
      files: [...selectedFiles],
      epochs: parseInt(document.getElementById('epochs').value),
      lr: parseFloat(document.getElementById('lr').value),
    });
    currentJobId = data.jobId;
    lastVersion = data.version;
    showProgress(data.version, data.totalEpochs);
    pollStatus();
  } catch(e) { alert(e.message); btn.disabled = false; }
}

const GAUGE_LEN = 264;   // 반원 호 길이 (stroke-dasharray 기준)
function setGauge(pct) {
  document.getElementById('gaugeFill').setAttribute('stroke-dashoffset', GAUGE_LEN * (1 - pct / 100));
  document.getElementById('gaugeNum').textContent = pct + '%';
}

function showProgress(version, total) {
  setGauge(0);
  document.getElementById('progressLabel').innerHTML = `<b>${version}</b> 학습 중...`;
  document.getElementById('metricsGrid').innerHTML = [
    ['Train Loss', '-'], ['Val Loss', '-'], ['Val Acc', '-'],
  ].map(([l,v]) => `<div class="metric-box"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join('');
  document.getElementById('mlflowRunLink').style.display = 'none';
}

function pollStatus() {
  clearPoll();
  pollTimer = setInterval(async () => {
    try {
      const { data } = await api('GET', `/train/status?jobId=${currentJobId}`);
      const { status, experimentId, epoch, totalEpochs, trainLoss, valLoss, valAccuracy, error } = data;
      const errorBox = document.getElementById('trainError');
      errorBox.textContent = error ?? '';
      errorBox.style.display = status === 'failed' && error ? 'block' : 'none';
      const pct = totalEpochs ? Math.round((epoch / totalEpochs) * 100) : 0;
      setGauge(pct);
      document.getElementById('progressLabel').innerHTML =
        `<b>${lastVersion}</b> ${status === 'running' ? `epoch ${epoch}/${totalEpochs}` : status}`;
      document.getElementById('metricsGrid').innerHTML = [
        ['Train Loss', trainLoss?.toFixed(4) ?? '-'],
        ['Val Loss',   valLoss?.toFixed(4)   ?? '-'],
        ['Val Acc',    valAccuracy ? (valAccuracy * 100).toFixed(1) + '%' : '-'],
      ].map(([l,v]) => `<div class="metric-box"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join('');

      const link = document.getElementById('mlflowRunLink');
      // MLflow 3.x run URL: /#/experiments/{experimentId}/runs/{runId}
      link.href = experimentId
        ? `${MLFLOW}/#/experiments/${experimentId}/runs/${currentJobId}`
        : `${MLFLOW}/#/experiments/0/runs/${currentJobId}`;
      link.style.display = 'inline-flex';

      if (status === 'completed' || status === 'failed') {
        clearPoll();
        document.getElementById('trainBtn').disabled = false;
        loadRuns();
        if (status === 'completed') {
          document.getElementById('deployBtn').dataset.version = lastVersion;
          document.getElementById('deployBtn').style.removeProperty('display');
          loadFiles();
        }
      }
    } catch(e) { console.error(e); }
  }, 3000);
}
function clearPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
