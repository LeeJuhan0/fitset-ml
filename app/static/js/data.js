// ── 학습 데이터 테이블 ─────────────────────────────────────────────────
let allFiles = [];
let page = 1;
let rowsPerPage = 10;
let sortKey = null;      // 'filename' | 'class' | 'createdAt'
let sortDir = 1;         // 1 asc, -1 desc

async function loadFiles() {
  const el = document.getElementById('fileList');
  el.innerHTML = '<p class="empty">로딩 중...</p>';
  try {
    const { data } = await api('GET', '/data');
    allFiles = data.files;
    rebuildClassFilter();
    renderFiles();
    renderKpis();
  } catch(e) { el.innerHTML = `<p class="empty" style="color:#DC2626">${e.message}</p>`; }
}

// 데이터에 실제로 존재하는 종목으로 필터 옵션을 구성(현재 선택은 유지, 사라진 종목이면 전체로 복귀)
function rebuildClassFilter() {
  const sel = document.getElementById('classFilter');
  const prev = sel.value;
  const classes = [...new Set(allFiles.map(f => f.class))].sort();
  sel.innerHTML = '<option value="">전체 종목</option>' +
    classes.map(c => `<option value="${c}">${c}</option>`).join('');
  sel.value = classes.includes(prev) ? prev : '';
}

function toggleClassFilter() { document.getElementById('classFilter').classList.toggle('open'); }
function filterChanged() { page = 1; renderFiles(); }

// 현재 필터·검색·정렬이 적용된 목록 (페이지네이션 이전)
function visibleFiles() {
  const filter = document.getElementById('classFilter').value;
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  let files = allFiles
    .filter(f => !filter || f.class === filter)
    .filter(f => !q || f.filename.toLowerCase().includes(q) || (f.deviceId ?? '').toLowerCase().includes(q));
  if (sortKey) {
    files = [...files].sort((a, b) => sortDir * String(a[sortKey] ?? '').localeCompare(String(b[sortKey] ?? '')));
  } else {
    files = [...files].sort((a, b) => a.class.localeCompare(b.class) || a.filename.localeCompare(b.filename));
  }
  return files;
}

function setSort(key) {
  if (sortKey === key) { sortDir = -sortDir; } else { sortKey = key; sortDir = 1; }
  renderFiles();
}

function fmtDate(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString('ko-KR', { year: '2-digit', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function statusPill(f) {
  if (f.uploaded === false) return '<span class="pill pending">업로드 대기</span>';
  if (f.isTrained)          return `<span class="pill trained">${f.trainedInVersion} 학습됨</span>`;
  return '<span class="pill idle">미학습</span>';
}

function sortIc(key) {
  if (sortKey !== key) return '<span class="sort-ic">↕</span>';
  return `<span class="sort-ic">${sortDir === 1 ? '▲' : '▼'}</span>`;
}

function renderFiles() {
  const el = document.getElementById('fileList');
  const files = visibleFiles();
  const pages = Math.max(1, Math.ceil(files.length / rowsPerPage));
  if (page > pages) page = pages;
  const start = (page - 1) * rowsPerPage;
  const slice = files.slice(start, start + rowsPerPage);

  if (!files.length) {
    el.innerHTML = '<p class="empty">CSV 파일이 없습니다</p>';
    document.getElementById('tableFade').classList.remove('visible');
    document.getElementById('pagiBar').innerHTML = '';
    updateSelectCount();
    return;
  }

  el.innerHTML = `
    <table class="data-table">
      <thead><tr>
        <th style="width:36px"><input type="checkbox" id="selectAll" onclick="toggleSelectAll(this.checked)" /></th>
        <th style="width:44px">#</th>
        <th class="sortable ${sortKey==='filename'?'sorted':''}" onclick="setSort('filename')">파일명 ${sortIc('filename')}</th>
        <th class="sortable ${sortKey==='class'?'sorted':''}" onclick="setSort('class')">종목 ${sortIc('class')}</th>
        <th>상태</th>
        <th class="sortable cell-right ${sortKey==='createdAt'?'sorted':''}" onclick="setSort('createdAt')" style="text-align:right">수집일시 ${sortIc('createdAt')}</th>
        <th style="width:52px;text-align:center">통계</th>
        <th style="width:52px;text-align:center">그래프</th>
      </tr></thead>
      <tbody>
        ${slice.map((f, i) => `
        <tr class="${selectedFiles.has(f.filename) ? 'selected' : ''}" onclick="toggleFile(this,'${f.filename}')">
          <td><input type="checkbox" ${selectedFiles.has(f.filename) ? 'checked' : ''}
                onclick="event.stopPropagation();toggleFile(this.closest('tr'),'${f.filename}')"/></td>
          <td class="row-num">${start + i + 1}</td>
          <td class="cell-name"><div class="nm">${f.filename}</div><div class="id">${f.deviceId ?? '-'} · ${f.format}${f.phaseLabeled ? ' · phase' : ''}</div></td>
          <td><span class="pill class">${f.class}</span></td>
          <td>${statusPill(f)}</td>
          <td class="cell-right"><div class="v">${fmtDate(f.createdAt)}</div></td>
          <td style="text-align:center">
            <button class="stats-btn" title="센서 통계 보기" onclick="event.stopPropagation();openStats('${f.filename}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            </button>
          </td>
          <td style="text-align:center">
            <button class="stats-btn" title="6축 그래프 보기" onclick="event.stopPropagation();openImu('${f.filename}')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="2,12 6,6 10,16 14,8 18,14 22,10"/></svg>
            </button>
          </td>
        </tr>`).join('')}
      </tbody>
    </table>`;

  // 마지막 페이지가 아니면 아래로 페이드아웃(다음 페이지가 이어지는 느낌)
  document.getElementById('tableFade').classList.toggle('visible', page < pages);

  document.getElementById('pagiBar').innerHTML = `
    <span class="range">${start + 1}-${start + slice.length} of ${files.length}</span>
    <span>Rows per page:</span>
    <select onchange="rowsPerPage=parseInt(this.value);page=1;renderFiles()">
      ${[10, 25, 50].map(n => `<option value="${n}" ${n === rowsPerPage ? 'selected' : ''}>${n}</option>`).join('')}
    </select>
    <button class="pg-btn" onclick="page--;renderFiles()" ${page <= 1 ? 'disabled' : ''}>‹</button>
    <button class="pg-btn" onclick="page++;renderFiles()" ${page >= pages ? 'disabled' : ''}>›</button>
    <span>${page}/${pages}</span>`;

  updateSelectCount();
}

function toggleFile(el, name) {
  if (selectedFiles.has(name)) { selectedFiles.delete(name); el.classList.remove('selected'); el.querySelector('input').checked = false; }
  else { selectedFiles.add(name); el.classList.add('selected'); el.querySelector('input').checked = true; }
  updateSelectCount();
}

// 전체선택: 현재 필터·검색으로 보이는 파일들(모든 페이지)을 선택/해제
// 업로드 대기(uploaded=false)는 S3에 실물이 없어 학습이 400으로 막히므로 제외한다.
function toggleSelectAll(checked) {
  selectableFiles().forEach(f =>
    checked ? selectedFiles.add(f.filename) : selectedFiles.delete(f.filename));
  renderFiles();
}

// 보이는 파일 중 학습에 넣을 수 있는 것만
function selectableFiles() {
  return visibleFiles().filter(f => f.uploaded !== false);
}

function updateSelectCount() {
  document.getElementById('selectCount').textContent = `${selectedFiles.size}개 선택됨`;
  const files = selectableFiles();
  const all = document.getElementById('selectAll');
  if (all) all.checked = files.length > 0 && files.every(f => selectedFiles.has(f.filename));
}
