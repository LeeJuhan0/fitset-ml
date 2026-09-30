const POSE_EDGES = [[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28],
                    [27,29],[29,31],[28,30],[30,32],[15,17],[15,19],[16,18],[16,20]];
const PHASE_NAME = { 0: '내려감', 1: '올라감' };
let poseData = null;
let poseRaf = null;
let editing = false;
let originalPhases = null;
let editFilename = null;

async function openVideo(filename) {
  const f = videoFiles.find(x => x.filename === filename);
  const modal = document.getElementById('videoModal');
  const video = document.getElementById('viewerVideo');
  document.getElementById('videoTitle').textContent = filename;
  document.getElementById('videoSub').textContent = `${f.class} · ${STATUS_LABEL[f.status] ?? f.status}` + (f.label ? '' : ' · 라벨링 후 관절·구간이 표시됩니다');
  document.getElementById('phaseStrip').innerHTML = '';
  document.getElementById('phaseBadge').style.display = 'none';
  document.getElementById('phaseEditBar').style.display = 'none';
  poseData = null;
  editFilename = filename;
  setEditing(false);
  modal.classList.add('visible');
  try {
    const { data } = await api('GET', `/phase/video-url?filename=${encodeURIComponent(filename)}`);
    video.src = data.url;
    if (f.label) {
      const pose = await api('GET', `/phase/pose?filename=${encodeURIComponent(filename)}`);
      poseData = pose.data;
      originalPhases = poseData.frames.map(fr => fr[0]);
      renderPhaseStrip();
      document.getElementById('phaseBadge').style.display = 'flex';
      document.getElementById('phaseEditBar').style.display = 'flex';
      drawLoop();
    }
  } catch (e) { document.getElementById('videoSub').textContent = `불러오기 실패: ${e.message}`; }
}

function closeVideo() {
  const video = document.getElementById('viewerVideo');
  video.pause(); video.removeAttribute('src'); video.load();
  if (poseRaf) cancelAnimationFrame(poseRaf);
  poseRaf = null; poseData = null;
  document.getElementById('videoModal').classList.remove('visible');
}

function currentFrame() {
  const video = document.getElementById('viewerVideo');
  return poseData ? Math.min(poseData.frames.length - 1, Math.max(0, Math.floor(video.currentTime * poseData.fps))) : -1;
}

function drawLoop() {
  const video = document.getElementById('viewerVideo');
  const canvas = document.getElementById('viewerCanvas');
  const ctx = canvas.getContext('2d');
  const step = () => {
    if (!poseData) return;
    if (canvas.width !== video.clientWidth || canvas.height !== video.clientHeight) {
      canvas.width = video.clientWidth; canvas.height = video.clientHeight;
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const [phase, lm] = poseData.frames[currentFrame()] ?? [-1, null];
    if (lm) {
      const vw = video.videoWidth || 1, vh = video.videoHeight || 1;
      const scale = Math.min(canvas.width / vw, canvas.height / vh);
      const ox = (canvas.width - vw * scale) / 2, oy = (canvas.height - vh * scale) / 2;
      const pt = i => [ox + lm[i][0] * vw * scale, oy + lm[i][1] * vh * scale, lm[i][2]];
      ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(240,169,62,.9)';
      POSE_EDGES.forEach(([a, b]) => {
        const [x1, y1, v1] = pt(a), [x2, y2, v2] = pt(b);
        if (v1 < 0.5 || v2 < 0.5) return;
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      });
      ctx.fillStyle = '#fff';
      for (let i = 11; i < 33; i++) {
        const [x, y, v] = pt(i);
        if (v < 0.5) continue;
        ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
      }
    }
    const badge = document.getElementById('phaseBadge');
    badge.className = 'phase-badge ' + (phase >= 0 ? `p${phase}` : 'pn');
    badge.innerHTML = phase >= 0 ? `${phase} <small>${PHASE_NAME[phase]}</small>` : `– <small>미검출</small>`;
    poseRaf = requestAnimationFrame(step);
  };
  poseRaf = requestAnimationFrame(step);
}

function renderPhaseStrip() {
  const strip = document.getElementById('phaseStrip');
  const frames = poseData.frames;
  const segs = [];
  let start = 0;
  for (let i = 1; i <= frames.length; i++) {
    if (i < frames.length && frames[i][0] === frames[start][0]) continue;
    segs.push([frames[start][0], i - start]); start = i;
  }
  strip.innerHTML = segs.map(([p, n]) => `<div class="${p >= 0 ? 'p' + p : 'pn'}" style="width:${(n / frames.length) * 100}%"></div>`).join('');
  if (!editing) return;
  let pos = 0;
  segs.slice(0, -1).forEach(([, n]) => {
    pos += n;
    const h = document.createElement('div');
    h.className = 'phase-handle';
    h.style.left = `${(pos / frames.length) * 100}%`;
    h.dataset.frame = pos;
    h.onclick = e => e.stopPropagation();
    h.onpointerdown = startDrag;
    strip.appendChild(h);
  });
  strip.querySelectorAll(':scope > div:not(.phase-handle)').forEach(el => el.ondblclick = togglePhaseAt);
}

function segmentAt(frame) {
  const frames = poseData.frames;
  let lo = frame, hi = frame + 1;
  while (lo > 0 && frames[lo - 1][0] === frames[frame][0]) lo--;
  while (hi < frames.length && frames[hi][0] === frames[frame][0]) hi++;
  return [lo, hi];
}

function setPhases(lo, hi, phase) {
  for (let i = lo; i < hi; i++) poseData.frames[i][0] = phase;
}

function frameFromEvent(event) {
  const rect = document.getElementById('phaseStrip').getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
  return Math.round(ratio * poseData.frames.length);
}

function startDrag(event) {
  event.stopPropagation();
  const b = Number(event.currentTarget.dataset.frame);
  const left = poseData.frames[b - 1][0], right = poseData.frames[b][0];
  const lo = segmentAt(b - 1)[0], hi = segmentAt(b)[1];
  const video = document.getElementById('viewerVideo');
  video.pause();
  const move = e => {
    const f = Math.min(hi - 1, Math.max(lo + 1, frameFromEvent(e)));
    setPhases(lo, f, left);
    setPhases(f, hi, right);
    video.currentTime = f / poseData.fps;
    renderPhaseStrip();
  };
  const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

function togglePhaseAt(event) {
  const frame = Math.min(poseData.frames.length - 1, frameFromEvent(event));
  const [lo, hi] = segmentAt(frame);
  setPhases(lo, hi, poseData.frames[frame][0] === 0 ? 1 : 0);
  renderPhaseStrip();
}

function splitAtCurrent() {
  const frame = currentFrame();
  const [lo, hi] = segmentAt(frame);
  if (frame === lo) return;
  setPhases(frame, hi, poseData.frames[frame][0] === 0 ? 1 : 0);
  renderPhaseStrip();
}

function setEditing(on) {
  editing = on;
  document.getElementById('phaseStrip').classList.toggle('editing', on);
  document.getElementById('phaseEditTools').style.display = on ? 'inline' : 'none';
  document.getElementById('phaseEditToggle').textContent = on ? '편집 종료' : '구간 편집';
}

function toggleEdit() {
  setEditing(!editing);
  renderPhaseStrip();
}

function resetEdit() {
  poseData.frames.forEach((fr, i) => fr[0] = originalPhases[i]);
  renderPhaseStrip();
}

async function savePhases() {
  const phases = poseData.frames.map(fr => fr[0]);
  try {
    await api('PATCH', '/phase/files/phases', { filename: editFilename, phases });
    originalPhases = phases;
    setEditing(false);
    renderPhaseStrip();
    loadVideos();
    alert('구간을 저장했습니다');
  } catch (e) { alert(e.message); }
}

function seekFromStrip(event) {
  if (!poseData) return;
  const rect = event.currentTarget.getBoundingClientRect();
  const ratio = (event.clientX - rect.left) / rect.width;
  const video = document.getElementById('viewerVideo');
  video.currentTime = ratio * poseData.frames.length / poseData.fps;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeVideo(); });
