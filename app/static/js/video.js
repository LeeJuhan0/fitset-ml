const POSE_EDGES = [[11,12],[11,13],[13,15],[12,14],[14,16],[11,23],[12,24],[23,24],[23,25],[25,27],[24,26],[26,28],
                    [27,29],[29,31],[28,30],[30,32],[15,17],[15,19],[16,18],[16,20]];
const PHASE_NAME = { 0: '내려감', 1: '올라감', 2: '멈춤' };
let poseData = null;
let poseRaf = null;

async function openVideo(filename) {
  const f = videoFiles.find(x => x.filename === filename);
  const modal = document.getElementById('videoModal');
  const video = document.getElementById('viewerVideo');
  document.getElementById('videoTitle').textContent = filename;
  document.getElementById('videoSub').textContent = `${f.class} · ${STATUS_LABEL[f.status] ?? f.status}` + (f.label ? '' : ' · 라벨링 후 관절·구간이 표시됩니다');
  document.getElementById('phaseStrip').innerHTML = '';
  document.getElementById('phaseBadge').style.display = 'none';
  poseData = null;
  modal.classList.add('visible');
  try {
    const { data } = await api('GET', `/phase/video-url?filename=${encodeURIComponent(filename)}`);
    video.src = data.url;
    if (f.label) {
      const pose = await api('GET', `/phase/pose?filename=${encodeURIComponent(filename)}`);
      poseData = pose.data;
      renderPhaseStrip();
      document.getElementById('phaseBadge').style.display = 'flex';
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
}

function seekFromStrip(event) {
  if (!poseData) return;
  const rect = event.currentTarget.getBoundingClientRect();
  const ratio = (event.clientX - rect.left) / rect.width;
  const video = document.getElementById('viewerVideo');
  video.currentTime = ratio * poseData.frames.length / poseData.fps;
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeVideo(); });
