// ===== Douyin Video Downloader - Frontend App =====

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const HISTORY_KEY = 'douyin_dl_history';

// DOM elements - Video tab
const urlInput = $('#url-input');
const pasteBtn = $('#paste-btn');
const downloadBtn = $('#download-btn');
const errorSection = $('#error-section');
const errorMessage = $('#error-message');
const resultSection = $('#result-section');
const historySection = $('#history-section');
const historyList = $('#history-list');
const clearHistoryBtn = $('#clear-history-btn');

// DOM elements - Profile tab
const profileUrlInput = $('#profile-url-input');
const profilePasteBtn = $('#profile-paste-btn');
const profileScanBtn = $('#profile-scan-btn');
const profileErrorSection = $('#profile-error-section');
const profileErrorMessage = $('#profile-error-message');
const profileResultSection = $('#profile-result-section');
const profileVideosGrid = $('#profile-videos-grid');
const videoCountInput = $('#video-count');

// DOM elements - Shared
const toast = $('#toast');
const toastMessage = $('#toast-message');

// ===== State =====
let currentVideoData = null;
let currentProfileVideos = [];

// ===== Utilities =====

function formatNumber(num) {
  if (!num) return '0';
  num = parseInt(num);
  if (num >= 100000000) return (num / 100000000).toFixed(1) + '亿';
  if (num >= 10000) return (num / 10000).toFixed(1) + '万';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
  return num.toString();
}

function formatDuration(ms) {
  if (!ms) return '0:00';
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function showToast(message, duration = 3000) {
  toastMessage.textContent = message;
  toast.classList.remove('hidden');
  toast.offsetHeight;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.classList.add('hidden'), 300);
  }, duration);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ===== Tab Navigation =====

const tabBtns = $$('.tab-btn');
const tabContents = $$('.tab-content');
const tabIndicator = $('#tab-indicator');

tabBtns.forEach((btn) => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    tabBtns.forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    tabContents.forEach((c) => c.classList.remove('active'));
    $(`#${tab}-tab`).classList.add('active');
    tabIndicator.classList.toggle('right', tab === 'profile');
  });
});

// ===== Video Tab Logic =====

function showError(msg) {
  errorMessage.textContent = msg;
  errorSection.classList.remove('hidden');
  resultSection.classList.add('hidden');
}

function hideError() {
  errorSection.classList.add('hidden');
}

function setLoading(loading) {
  downloadBtn.classList.toggle('loading', loading);
  downloadBtn.disabled = loading;
}

// ===== History =====

function getHistory() {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); }
  catch { return []; }
}

function saveToHistory(data) {
  const history = getHistory();
  const filtered = history.filter((item) => item.id !== data.id);
  filtered.unshift({
    id: data.id, desc: data.desc, author: data.author,
    cover: data.cover, videoUrl: data.videoUrl, timestamp: Date.now(),
  });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(filtered.slice(0, 20)));
  renderHistory();
}

function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
}

function renderHistory() {
  const history = getHistory();
  if (history.length === 0) { historySection.classList.add('hidden'); return; }
  historySection.classList.remove('hidden');
  historyList.innerHTML = '';
  history.forEach((item) => {
    const el = document.createElement('div');
    el.className = 'history-item';
    el.innerHTML = `
      <div class="history-thumb">
        <img src="${item.cover || ''}" alt="" onerror="this.style.display='none'" loading="lazy">
      </div>
      <div class="history-details">
        <div class="history-author">${escapeHtml(item.author || 'Unknown')}</div>
        <div class="history-desc">${escapeHtml(item.desc || 'Không có mô tả')}</div>
      </div>
      <div class="history-time">${formatTimeAgo(item.timestamp)}</div>
    `;
    el.addEventListener('click', () => {
      if (item.videoUrl) {
        window.open(`/api/download?url=${encodeURIComponent(item.videoUrl)}&filename=douyin_${item.id}.mp4`, '_blank');
      } else { showToast('Không có link tải cho video này'); }
    });
    historyList.appendChild(el);
  });
}

function formatTimeAgo(timestamp) {
  const diff = Date.now() - timestamp;
  const m = Math.floor(diff / 60000), h = Math.floor(diff / 3600000), d = Math.floor(diff / 86400000);
  if (m < 1) return 'Vừa xong';
  if (m < 60) return `${m} phút`;
  if (h < 24) return `${h} giờ`;
  return `${d} ngày`;
}

// ===== Display Single Video Result =====

function displayResult(data) {
  currentVideoData = data;
  const coverImg = $('#video-cover');
  coverImg.src = data.cover || '';
  coverImg.style.display = data.cover ? 'block' : 'none';
  $('#duration-badge').textContent = formatDuration(data.duration);
  const avatarImg = $('#avatar-img');
  avatarImg.src = data.authorAvatar || '';
  avatarImg.style.display = data.authorAvatar ? 'block' : 'none';
  $('#author-name').textContent = data.author || 'Unknown';
  $('#video-id').textContent = `ID: ${data.id || '—'}`;
  $('#video-desc').textContent = data.desc || 'Không có mô tả';
  const stats = data.statistics || {};
  $('#stat-likes').textContent = formatNumber(stats.likes);
  $('#stat-comments').textContent = formatNumber(stats.comments);
  $('#stat-shares').textContent = formatNumber(stats.shares);
  $('#stat-plays').textContent = formatNumber(stats.plays);
  const musicInfo = $('#music-info');
  if (data.musicTitle) {
    musicInfo.classList.remove('hidden');
    $('#music-title').textContent = `${data.musicTitle}${data.musicAuthor ? ' — ' + data.musicAuthor : ''}`;
  } else { musicInfo.classList.add('hidden'); }
  const dlBtn = $('#dl-video-btn');
  if (data.videoUrl) {
    dlBtn.href = `/api/download?url=${encodeURIComponent(data.videoUrl)}&filename=douyin_${data.id || 'video'}.mp4`;
    dlBtn.classList.remove('disabled');
  } else { dlBtn.href = '#'; dlBtn.classList.add('disabled'); }
  resultSection.classList.remove('hidden');
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
  if (data.id) saveToHistory(data);
}

async function parseVideo(url) {
  hideError();
  setLoading(true);
  resultSection.classList.add('hidden');
  try {
    const response = await fetch('/api/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || 'Đã có lỗi xảy ra');
    displayResult(result.data);
  } catch (error) {
    showError(error.message || 'Không thể phân tích video. Vui lòng thử lại.');
  } finally { setLoading(false); }
}

// ===== Profile Tab Logic =====

function showProfileError(msg) {
  profileErrorMessage.textContent = msg;
  profileErrorSection.classList.remove('hidden');
  profileResultSection.classList.add('hidden');
}

function hideProfileError() {
  profileErrorSection.classList.add('hidden');
}

function setProfileLoading(loading) {
  profileScanBtn.classList.toggle('loading', loading);
  profileScanBtn.disabled = loading;
}

function displayProfileResult(data) {
  const { userInfo, videos } = data;
  currentProfileVideos = videos;

  // User info
  const avatarImg = $('#profile-avatar-img');
  avatarImg.src = userInfo.avatar || '';
  avatarImg.style.display = userInfo.avatar ? 'block' : 'none';
  $('#profile-nickname').textContent = userInfo.nickname || 'Unknown';
  $('#profile-signature').textContent = userInfo.signature || '';
  if (userInfo.verified) {
    $('#profile-verified').classList.remove('hidden');
  } else {
    $('#profile-verified').classList.add('hidden');
  }

  $('#profile-following').textContent = formatNumber(userInfo.followingCount);
  $('#profile-followers').textContent = formatNumber(userInfo.followerCount);
  $('#profile-likes').textContent = formatNumber(userInfo.totalFavorited);
  $('#profile-videos-count').textContent = formatNumber(userInfo.awemeCount);

  // Videos count badge
  $('#videos-found-badge').textContent = videos.length;

  // Render video grid
  profileVideosGrid.innerHTML = '';
  videos.forEach((v, i) => {
    const card = document.createElement('div');
    card.className = 'pv-card';
    card.style.animationDelay = `${i * 0.05}s`;
    const dlUrl = v.videoUrl
      ? `/api/download?url=${encodeURIComponent(v.videoUrl)}&filename=douyin_${v.id || i}.mp4`
      : '#';
    card.innerHTML = `
      <div class="pv-thumb">
        <img src="${v.cover || ''}" alt="" loading="lazy" onerror="this.style.display='none'">
        <span class="pv-duration">${formatDuration(v.duration)}</span>
        <span class="pv-plays">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          ${formatNumber(v.statistics?.plays)}
        </span>
      </div>
      <div class="pv-info">
        <div class="pv-desc">${escapeHtml(v.desc || 'Không có mô tả')}</div>
        <div class="pv-actions">
          <a class="pv-dl-btn primary" href="${dlUrl}" ${v.videoUrl ? 'download' : ''} title="Tải video">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Tải
          </a>
          <button class="pv-dl-btn secondary copy-video-link" data-url="${v.videoUrl || ''}" title="Copy link">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
            Copy
          </button>
        </div>
      </div>
    `;
    profileVideosGrid.appendChild(card);
  });

  // Copy link buttons
  profileVideosGrid.querySelectorAll('.copy-video-link').forEach((btn) => {
    btn.addEventListener('click', () => {
      const url = btn.dataset.url;
      if (url) {
        navigator.clipboard.writeText(url).then(() => showToast('Đã copy link!')).catch(() => showToast('Lỗi copy'));
      } else { showToast('Không có link video'); }
    });
  });

  profileResultSection.classList.remove('hidden');
  profileResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function scanProfile() {
  const url = profileUrlInput.value.trim();
  if (!url) { showProfileError('Vui lòng nhập link profile Douyin'); return; }
  hideProfileError();
  setProfileLoading(true);
  profileResultSection.classList.add('hidden');
  const count = parseInt(videoCountInput.value) || 10;
  try {
    const response = await fetch('/api/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, count }),
    });
    const result = await response.json();
    if (!response.ok || !result.success) throw new Error(result.error || 'Đã có lỗi xảy ra');
    displayProfileResult(result.data);
  } catch (error) {
    showProfileError(error.message || 'Không thể quét profile. Vui lòng thử lại.');
  } finally { setProfileLoading(false); }
}

// ===== Event Listeners =====

// Video tab
pasteBtn.addEventListener('click', async () => {
  try { urlInput.value = await navigator.clipboard.readText(); urlInput.focus(); showToast('Đã dán link'); }
  catch { showToast('Không thể đọc clipboard. Hãy dán bằng Ctrl+V'); }
});

downloadBtn.addEventListener('click', () => {
  const url = urlInput.value.trim();
  if (!url) { showError('Vui lòng nhập link video Douyin'); urlInput.focus(); return; }
  parseVideo(url);
});

urlInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') downloadBtn.click(); });

$('#copy-link-btn').addEventListener('click', () => {
  if (currentVideoData?.videoUrl) {
    navigator.clipboard.writeText(currentVideoData.videoUrl)
      .then(() => showToast('Đã copy link video!')).catch(() => showToast('Không thể copy link'));
  }
});

clearHistoryBtn.addEventListener('click', () => { clearHistory(); showToast('Đã xoá lịch sử'); });

urlInput.addEventListener('paste', () => {
  setTimeout(() => {
    const val = urlInput.value.trim();
    if (val && (val.includes('douyin.com') || val.includes('iesdouyin.com'))) {
      setTimeout(() => downloadBtn.click(), 300);
    }
  }, 100);
});

// Profile tab
profilePasteBtn.addEventListener('click', async () => {
  try { profileUrlInput.value = await navigator.clipboard.readText(); profileUrlInput.focus(); showToast('Đã dán link'); }
  catch { showToast('Không thể đọc clipboard'); }
});

profileScanBtn.addEventListener('click', scanProfile);
profileUrlInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') scanProfile(); });

// Count presets
$$('.count-preset').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.count-preset').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    videoCountInput.value = btn.dataset.count;
  });
});

videoCountInput.addEventListener('input', () => {
  $$('.count-preset').forEach((b) => {
    b.classList.toggle('active', b.dataset.count === videoCountInput.value);
  });
});

// Download all
$('#download-all-btn').addEventListener('click', () => {
  if (!currentProfileVideos.length) { showToast('Chưa có video nào'); return; }
  const withUrl = currentProfileVideos.filter((v) => v.videoUrl);
  if (!withUrl.length) { showToast('Không có link tải'); return; }
  showToast(`Đang mở ${withUrl.length} link tải...`);
  withUrl.forEach((v, i) => {
    setTimeout(() => {
      const a = document.createElement('a');
      a.href = `/api/download?url=${encodeURIComponent(v.videoUrl)}&filename=douyin_${v.id || i}.mp4`;
      a.download = `douyin_${v.id || i}.mp4`;
      a.click();
    }, i * 800);
  });
});

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
  renderHistory();
  urlInput.focus();
});
