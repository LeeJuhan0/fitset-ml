// ── 파일 통계 모달 ─────────────────────────────────────────────────────
const CHANNEL_UNITS = { ax: 'm/s²', ay: 'm/s²', az: 'm/s²', gx: 'rad/s', gy: 'rad/s', gz: 'rad/s' };

async function openStats(filename) {
  const modal = document.getElementById('statsModal');
  document.getElementById('statsTitle').textContent = filename;
  document.getElementById('statsSub').textContent = '';
  document.getElementById('statsBody').innerHTML = '<p class="empty">로딩 중...</p>';
  modal.classList.add('visible');
  try {
    const { data } = await api('GET', `/data/stats?filename=${encodeURIComponent(filename)}`);
    document.getElementById('statsSub').innerHTML =
      `${data.class} · ${data.durationSeconds}초 · ${data.usedRows.toLocaleString()}/${data.totalRows.toLocaleString()} 샘플 사용 · `
      + (data.trimApplied
          ? `앞뒤 ${data.trimSeconds}초 제외`
          : `<span class="warn">파일이 짧아 전체 구간으로 계산됨</span>`);
    document.getElementById('statsBody').innerHTML = `
      <table class="stats-table">
        <thead><tr><th>채널</th><th>평균</th><th>최소</th><th>최대</th><th>표준편차</th></tr></thead>
        <tbody>
          ${data.channels.map(c => `<tr>
            <td>${c.channel} <span style="color:#9CA3AF;font-weight:400">${CHANNEL_UNITS[c.channel] ?? ''}</span></td>
            <td>${c.mean.toFixed(3)}</td>
            <td>${c.min.toFixed(3)}</td>
            <td>${c.max.toFixed(3)}</td>
            <td>${c.std.toFixed(3)}</td>
          </tr>`).join('')}
        </tbody>
      </table>`;
  } catch(e) {
    document.getElementById('statsBody').innerHTML = `<p class="empty" style="color:#DC2626">${e.message}</p>`;
  }
}

function closeStats() { document.getElementById('statsModal').classList.remove('visible'); }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeStats(); });
