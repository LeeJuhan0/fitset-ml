const STATUS_LABEL = { pending: '대기', labeling: '라벨링 중', labeled: '완료', failed: '실패' };
let videoFiles = [];
let selectedVideos = new Set();
let exerciseClasses = [];

async function loadVideos() {
  const el = document.getElementById('videoList');
  try {
    if (!exerciseClasses.length) {
      const ex = await fetch('/api/v1/exercises').then(r => r.json()).catch(() => null);
      exerciseClasses = (ex?.data?.exercises ?? []).filter(e => e.phaseSupported).map(e => e.class).sort();
    }
    const { data } = await api('GET', '/phase/files');
    videoFiles = data.files;
    rebuildVideoFilters(data.counts);
    renderVideos();
    if (videoFiles.some(f => f.status === 'labeling')) setTimeout(loadVideos, 5000);
  } catch (e) { el.innerHTML = `<p class="empty" style="color:#DC2626">${e.message}</p>`; }
}
function rebuildVideoFilters(counts) {
  const st = document.getElementById('videoStatusFilter'), prevSt = st.value;
  st.innerHTML = `<option value="">전체 (${counts.total})</option>` +
    Object.keys(STATUS_LABEL).map(k => `<option value="${k}">${STATUS_LABEL[k]} (${counts[k] ?? 0})</option>`).join('');
  st.value = prevSt;
  const cl = document.getElementById('videoClassFilter'), prevCl = cl.value;
  const classes = [...new Set(videoFiles.map(f => f.class))].sort();
  cl.innerHTML = '<option value="">전체 종목</option>' + classes.map(c => `<option value="${c}">${c}</option>`).join('');
  cl.value = classes.includes(prevCl) ? prevCl : '';
}

function visibleVideos() {
  const st = document.getElementById('videoStatusFilter').value;
  const cl = document.getElementById('videoClassFilter').value;
  const q = document.getElementById('videoSearch').value.trim().toLowerCase();
  return videoFiles
    .filter(f => !st || f.status === st)
    .filter(f => !cl || f.class === cl)
    .filter(f => !q || f.filename.toLowerCase().includes(q))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

function videoStatusPill(f) {
  if (f.uploaded === false) return '<span class="pill pending">업로드 대기</span>';
  const cls = { pending: 'idle', labeling: 'labeling', labeled: 'labeled', failed: 'failed' }[f.status] ?? 'idle';
  const title = f.status === 'failed' && f.error ? ` title="${f.error.replace(/"/g, '&quot;')}"` : '';
  const promoted = f.datasetFile?.uploaded ?` <span class="pill promoted" title="${f.datasetFile.s3Key}">승격됨</span>` : '';
  return `<span class="pill ${cls}"${title}>${STATUS_LABEL[f.status] ?? f.status}</span>${promoted}`;
}

function phaseMini(f) {
  if (f.label && !f.label.hasPhase) return '<span class="pill idle" title="각도 규칙 없음, 관절만 추출">관절만</span>';
  const c = f.label?.phaseSummary?.rowPhaseCounts;
  if (!c) return '<span style="color:#9CA3AF">-</span>';
  return `<span class="phase-mini"><span class="p0">0 ${c['0'] ?? 0}</span><span class="p1">1 ${c['1'] ?? 0}</span><span class="p2">2 ${c['2'] ?? 0}</span></span>`;
}

function classChangeBlock(f) {
  if (f.uploaded === false) return '업로드 미완료';
  if (f.status === 'labeling') return '라벨링 중';
  if (f.datasetFile) return '승격 후에는 바꿀 수 없음';
  return null;
}

function classCell(f) {
  const block = classChangeBlock(f);
  if (block || !exerciseClasses.length) return `<span class="pill class" title="${block ?? ''}">${f.class}</span>`;
  const classes = exerciseClasses.includes(f.class) ? exerciseClasses : [f.class, ...exerciseClasses];
  return `<select class="class-select" title="종목 변경" onclick="event.stopPropagation()" onchange="changeClass('${f.filename}', this)">
    ${classes.map(c => `<option value="${c}" ${c === f.class ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
}

async function changeClass(name, sel) {
  const f = videoFiles.find(x => x.filename === name);
  const note = f?.label ? '\n기존 라벨 결과는 지워지고 다시 라벨링해야 합니다.' : '';
  if (!confirm(`${name} 의 종목을 ${sel.value} 로 바꿀까요?\n파일명이 새로 매겨집니다.${note}`)) { sel.value = f.class; return; }
  sel.disabled = true;
  try {
    const { data } = await api('PATCH', '/phase/files/class', { filename: name, class: sel.value });
    if (selectedVideos.delete(name)) selectedVideos.add(data.filename);
    loadVideos();
  } catch (e) { alert(e.message); sel.value = f.class; sel.disabled = false; }
}

function renderVideos() {
  const el = document.getElementById('videoList');
  const files = visibleVideos();
  if (!files.length) { el.innerHTML = '<p class="empty">영상이 없습니다</p>'; updateVideoSelect(); return; }
  el.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th style="width:36px"><input type="checkbox" id="videoSelectAll" onclick="toggleVideoAll(this.checked)" /></th>
        <th>파일명</th><th>종목</th><th>상태</th><th>행 수</th><th>phase 행 수</th>
        <th class="cell-right" style="text-align:right">수집일시</th><th style="width:52px;text-align:center">영상</th><th style="width:52px;text-align:center">삭제</th>
      </tr></thead>
      <tbody>${files.map(f => `
        <tr class="${selectedVideos.has(f.filename) ? 'selected' : ''}" onclick="toggleVideo(this,'${f.filename}')">
          <td><input type="checkbox" ${selectedVideos.has(f.filename) ? 'checked' : ''} ${selectable(f) ? '' : 'disabled'}
                onclick="event.stopPropagation();toggleVideo(this.closest('tr'),'${f.filename}')"/></td>
          <td class="cell-name"><div class="nm">${f.filename}</div><div class="id">${f.deviceId} · ${f.label ? f.label.videoBucket : f.videoBucket}</div></td>
          <td>${classCell(f)}</td>
          <td>${videoStatusPill(f)}</td>
          <td>${f.rows ?? '-'}</td>
          <td>${phaseMini(f)}</td>
          <td class="cell-right"><div class="v">${fmtDate(f.createdAt)}</div></td>
          <td style="text-align:center">
            <button class="stats-btn" title="영상 보기" onclick="event.stopPropagation();openVideo('${f.filename}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="6 4 20 12 6 20 6 4"/></svg>
            </button>
          </td>
          <td style="text-align:center">
            <button class="stats-btn danger" title="${f.status === 'labeling' ? '라벨링 중에는 삭제 불가' : '삭제'}" ${f.status === 'labeling' ? 'disabled' : ''}
                    onclick="event.stopPropagation();deleteVideo('${f.filename}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>
            </button>
          </td>
        </tr>`).join('')}
      </tbody>
    </table>`;
  updateVideoSelect();
}
function labelable(f) { return f.canLabel; }
function promotable(f) { return f.canPromote; }
function selectable(f) { return labelable(f) || promotable(f); }

function toggleVideo(el, name) {
  const f = videoFiles.find(x => x.filename === name);
  if (!selectable(f)) return;
  if (selectedVideos.has(name)) selectedVideos.delete(name); else selectedVideos.add(name);
  renderVideos();
}
function toggleVideoAll(checked) {
  visibleVideos().filter(selectable).forEach(f => checked ? selectedVideos.add(f.filename) : selectedVideos.delete(f.filename));
  renderVideos();
}
function updateVideoSelect() {
  document.getElementById('videoSelectCount').textContent = `${selectedVideos.size}개 선택됨`;
  const chosen = videoFiles.filter(f => selectedVideos.has(f.filename));
  document.getElementById('labelBtn').disabled = !chosen.some(labelable);
  document.getElementById('promoteBtn').disabled = !chosen.some(promotable);
  const all = document.getElementById('videoSelectAll');
  const files = visibleVideos().filter(selectable);
  if (all) all.checked = files.length > 0 && files.every(f => selectedVideos.has(f.filename));
}

async function startLabeling() {
  if (!selectedVideos.size) return;
  const relabel = videoFiles.filter(f => selectedVideos.has(f.filename) && f.label).length;
  if (relabel && !confirm(`${relabel}개는 이미 라벨링됨, 다시 라벨링하면 수동 수정이 덮어써지고 승격본도 갱신됩니다.`)) return;
  const btn = document.getElementById('labelBtn');
  btn.disabled = true;
  try {
    const { data } = await api('POST', '/phase/label', { filenames: [...selectedVideos] });
    selectedVideos.clear();
    if (data.skipped.length) alert('건너뜀:\n' + data.skipped.map(s => `${s.filename}: ${s.reason}`).join('\n'));
    loadVideos();
  } catch (e) { alert(e.message); btn.disabled = false; }
}
async function deleteVideo(name) {
  const f = videoFiles.find(x => x.filename === name);
  const note = f?.datasetFile?.uploaded ? '\n승격된 데이터셋 사본은 남습니다.' : '';
  if (!confirm(`${name} 을 삭제할까요?\nCSV, 영상, 라벨 결과가 S3에서 지워지고 되돌릴 수 없습니다.${note}`)) return;
  try {
    await api('DELETE', `/phase/files?filename=${encodeURIComponent(name)}`);
    selectedVideos.delete(name);
    loadVideos();
  } catch (e) { alert(e.message); }
}
async function promoteSelected() {
  const names = videoFiles.filter(f => selectedVideos.has(f.filename) && promotable(f)).map(f => f.filename);
  if (!names.length) return;
  if (!confirm(`${names.length}개를 학습 데이터셋으로 승격할까요?`)) return;
  const btn = document.getElementById('promoteBtn');
  btn.disabled = true;
  try {
    const { data } = await api('POST', '/phase/promote', { filenames: names });
    selectedVideos.clear();
    if (data.skipped.length) alert('건너뜀:\n' + data.skipped.map(s => `${s.filename}: ${s.reason}`).join('\n'));
    loadVideos();
    loadFiles();
  } catch (e) { alert(e.message); btn.disabled = false; }
}
