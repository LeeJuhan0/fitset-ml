// 대시보드와 같은 오리진의 /mlflow 경로를 가리킨다. ALB가 이 경로를 MLflow 컨테이너로 넘긴다.
const MLFLOW = location.origin + '/mlflow';
document.getElementById('mlflowHomeBtn').href = MLFLOW + '/';
document.getElementById('navMlflow').href = MLFLOW + '/';
document.getElementById('kpiMlflowLink').href = MLFLOW + '/';
// ── 사이드바 ───────────────────────────────────────────────────────────
function toggleSidebar() {
  const c = document.getElementById('shell').classList.toggle('collapsed');
  document.getElementById('collapseBtn').textContent = c ? '>' : '<';
}
const PAGES = { 'labeling': '영상 라벨링 · 승격', 'phase-train': '렙카운트 학습', 'phase-deploy': '렙카운트 배포', 'classifier': '분류기 학습 · 배포' };
function route() {
  const name = PAGES[location.hash.slice(1)] ? location.hash.slice(1) : 'labeling';
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.dataset.page === name));
  document.querySelectorAll('nav .nav-item[data-page]').forEach(n => n.classList.toggle('active', n.dataset.page === name));
  document.getElementById('pageTitle').textContent = PAGES[name];
}
window.addEventListener('hashchange', route);
route();
function sideSearch(q) {
  // 사이드바 검색 = 테이블 검색과 동일한 상태를 공유
  document.getElementById('searchInput').value = q;
  filterChanged();
  if (q) location.hash = 'classifier';
}

let platform = 'ios';
let selectedFiles = new Set();
let pollTimer = null;
let currentJobId = null;
let lastVersion = null;
let deployed = { dev: null, prod: null };   // 환경별 현재 배포 (loadModelInfo가 채움 — 분류기·렙카운트 배지용)
let runsData = [];            // GET /runs 결과 캐시 (배포 버전 갱신 시 재렌더용)
let bestRunId = null;

function setPlatform(p) {
  platform = p;
  document.querySelectorAll('.platform-tabs button').forEach(b =>
    b.classList.toggle('active', b.textContent.toLowerCase() === p));
  selectedFiles.clear();
  page = 1;
  clearPoll();
  loadFiles();
  loadModelInfo();
  loadRuns();
  selectedVideos.clear();
  loadVideos();
  loadPhaseModels();
}

async function api(method, path, body) {
  const res = await fetch(`/api/v1/${platform}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) {
    // 실패 봉투 {traceId, error: {code, message}} — 상태코드는 err.status로 별도 전달
    const err = new Error(data.error?.message || data.detail || JSON.stringify(data));
    err.status = res.status;
    throw err;
  }
  return data;
}
