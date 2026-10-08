// ── IMU 파형 공용 ──────────────────────────────────────────────────────
const IMU_COLORS = ['#EF4444', '#F59E0B', '#8B5CF6'];

// 위 acc, 아래 gyro, 채널별 평균 빼고 묶음 안에서 같은 축척, 색은 x y z 순
function drawImuWaves(ctx, w, h, imu, total) {
  [['ax', 'ay', 'az'], ['gx', 'gy', 'gz']].forEach((group, gi) => {
    const top = gi * h / 2, half = h / 4;
    const series = group.map(k => {
      const v = imu.channels[k];
      const mean = v.reduce((a, b) => a + b, 0) / v.length;
      return v.map(y => y - mean);
    });
    const amp = Math.max(1e-6, ...series.map(s => s.reduce((a, b) => Math.max(a, Math.abs(b)), 0)));
    series.forEach((s, ci) => {
      ctx.strokeStyle = IMU_COLORS[ci]; ctx.lineWidth = 1;
      ctx.beginPath();
      s.forEach((y, i) => {
        const x = imu.t[i] / total * w, py = top + half - y / amp * (half - 4);
        i ? ctx.lineTo(x, py) : ctx.moveTo(x, py);
      });
      ctx.stroke();
    });
    ctx.fillStyle = '#6B7280'; ctx.font = '10px sans-serif';
    ctx.fillText(gi ? 'gyro' : 'acc', 4, top + 11);
  });
}

// ── 파일 6축 그래프 모달 ────────────────────────────────────────────────
let fileImu = null;

async function openImu(filename) {
  fileImu = null;
  document.getElementById('imuTitle').textContent = filename;
  document.getElementById('imuSub').textContent = '로딩 중...';
  document.getElementById('imuModal').classList.add('visible');
  drawFileImu();
  try {
    const { data } = await api('GET', `/graph/imu?filename=${encodeURIComponent(filename)}`);
    if (document.getElementById('imuTitle').textContent !== filename) return;
    fileImu = data;
    document.getElementById('imuSub').textContent = `${data.t[data.t.length - 1].toFixed(1)}초 · ${data.t.length.toLocaleString()}점`;
    drawFileImu();
  } catch (e) {
    document.getElementById('imuSub').innerHTML = `<span style="color:#DC2626">${e.message}</span>`;
  }
}

// 가로축은 파일 시작부터의 초, 10초마다 회색 세로선
function drawFileImu() {
  const canvas = document.getElementById('imuFileCanvas');
  const dpr = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  if (!fileImu || !fileImu.t.length) return;
  const total = Math.max(1e-6, fileImu.t[fileImu.t.length - 1]);
  ctx.strokeStyle = 'rgba(107,114,128,.25)'; ctx.fillStyle = '#9CA3AF'; ctx.font = '10px sans-serif';
  for (let s = 10; s < total; s += 10) {
    const x = s / total * w;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    ctx.fillText(`${s}s`, x + 2, h - 3);
  }
  drawImuWaves(ctx, w, h, fileImu, total);
}
window.addEventListener('resize', drawFileImu);

function closeImu() { document.getElementById('imuModal').classList.remove('visible'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeImu(); });
