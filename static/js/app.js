/**
 * ReupMaster Pro - Frontend Application
 * Complete client-side logic for the social media automation tool.
 */

// ═══════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════
const state = {
    currentPage: 'dashboard',
    videos: [],
    fbPages: [],
    scheduledPosts: [],
    processOptions: {},
    selectedStyle: 'viral',
    selectedPageId: null,
    pollIntervals: {},
};

// ═══════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadStats();
    loadSettings();
    loadProcessOptions();

    // Auto-refresh stats every 10 seconds
    setInterval(loadStats, 10000);
    // Auto-refresh video statuses every 5 seconds
    setInterval(refreshVideoStatuses, 5000);
});

// ═══════════════════════════════════════════
// NAVIGATION
// ═══════════════════════════════════════════
function initNavigation() {
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.addEventListener('click', () => {
            navigateTo(item.dataset.page);
        });
    });
}

function navigateTo(page) {
    // Update state
    state.currentPage = page;

    // Update nav active
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (navItem) navItem.classList.add('active');

    // Show page
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');

    // Update header title
    const titles = {
        dashboard: 'Dashboard',
        download: 'Tải Video',
        'profile-scan': 'Quét Profile & Tải hàng loạt',
        library: 'Thư viện Video',
        process: 'Xử lý Video',
        ai: 'AI Viết lại',
        publish: 'Đăng / Lên lịch',
        'mass-schedule': 'Đăng hàng loạt (SO9 Style)',
        schedule: 'Lịch đăng bài',
        affiliate: 'Affiliate Marketing',
        seeding: 'Auto Seeding (Like/Comment/Share)',
        analytics: 'Thống kê Pages (SO9 Style)',
        pages: 'Facebook Pages',
        settings: 'Cài đặt',
        logs: 'System Logs',
    };
    document.getElementById('page-title').textContent = titles[page] || page;

    // Load data for the page
    switch (page) {
        case 'library': loadVideos(); break;
        case 'process': loadVideoSelects(); break;
        case 'publish': loadPublishData(); break;
        case 'schedule': loadSchedule(); break;
        case 'pages': loadFBPages(); break;
        case 'settings': loadSettings(); break;
        case 'dashboard': loadStats(); loadDashboardAnalytics(); break;
        case 'logs': loadLogs(); break;
        case 'mass-schedule': loadMassScheduleData(); break;
        case 'profile-scan': break;
        case 'affiliate': loadAffiliateData(); break;
        case 'seeding': loadSeedingPage(); break;
        case 'analytics': loadAnalyticsPage(); break;
    }

    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');
}

// ═══════════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════════
async function api(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
        }
        return data;
    } catch (err) {
        console.error(`API Error [${url}]:`, err);
        throw err;
    }
}

// ═══════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════
async function loadStats() {
    try {
        const stats = await api('/api/stats');
        document.getElementById('stat-total').textContent = stats.total_videos || 0;
        document.getElementById('stat-downloaded').textContent = stats.downloaded || 0;
        document.getElementById('stat-processed').textContent = stats.processed || 0;
        document.getElementById('stat-published').textContent = stats.published || 0;
        document.getElementById('stat-pages').textContent = stats.active_pages || 0;
        document.getElementById('stat-pending').textContent = stats.pending_posts || 0;

        // Update badges
        document.getElementById('badge-library').textContent = stats.total_videos || 0;
        document.getElementById('badge-schedule').textContent = stats.pending_posts || 0;

        // Scheduler status
        const schedulerEl = document.getElementById('scheduler-status');
        if (stats.scheduler?.running) {
            schedulerEl.textContent = 'Scheduler: Active';
        } else {
            schedulerEl.textContent = 'Scheduler: Inactive';
        }

        // Load recent videos for dashboard
        loadRecentVideos();
        loadUpcomingPosts();
    } catch (err) {
        console.error('Failed to load stats:', err);
    }
}

async function loadRecentVideos() {
    try {
        const data = await api('/api/videos?limit=5');
        const container = document.getElementById('recent-videos');
        if (!data.videos || data.videos.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🎬</div>
                    <div class="empty-title">Chưa có video nào</div>
                    <div class="empty-desc">Bắt đầu bằng cách tải video</div>
                    <button class="btn btn-primary" onclick="navigateTo('download')">⬇️ Tải video</button>
                </div>`;
            return;
        }

        let html = '<div class="table-wrapper"><table>';
        html += '<thead><tr><th>Video</th><th>Platform</th><th>Trạng thái</th><th>Thời gian</th></tr></thead><tbody>';
        data.videos.forEach(v => {
            const platform = getPlatformIcon(v.source_platform);
            const badge = getStatusBadge(v.status);
            const time = timeAgo(v.created_at);
            const title = v.title || v.original_filename || v.source_url?.substring(0, 40) + '...';
            html += `<tr>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(title)}">${escapeHtml(title)}</td>
                <td>${platform}</td>
                <td>${badge}</td>
                <td style="color:var(--text-tertiary);font-size:12px;">${time}</td>
            </tr>`;
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    } catch (err) {
        console.error('Failed to load recent videos:', err);
    }
}

async function loadUpcomingPosts() {
    try {
        const data = await api('/api/schedule?status=pending');
        const container = document.getElementById('upcoming-posts');
        if (!data.posts || data.posts.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📅</div>
                    <div class="empty-title">Không có bài chờ đăng</div>
                </div>`;
            return;
        }

        let html = '';
        data.posts.slice(0, 5).forEach(p => {
            const dt = new Date(p.scheduled_time);
            html += `<div class="schedule-item">
                <div class="schedule-time">
                    <div class="date">${dt.toLocaleDateString('vi-VN')}</div>
                    <div class="time">${dt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</div>
                </div>
                <div class="schedule-info">
                    <div class="sched-title">${escapeHtml(p.video_title || 'Video')}</div>
                    <div class="sched-page">📘 ${escapeHtml(p.page_name || 'Page')}</div>
                </div>
                <span class="badge badge-${p.status}">${p.status}</span>
            </div>`;
        });
        container.innerHTML = html;
    } catch (err) {
        console.error('Failed to load upcoming posts:', err);
    }
}

// ═══════════════════════════════════════════
// DOWNLOAD
// ═══════════════════════════════════════════
function detectPlatform(input) {
    const url = input.value.trim();
    const badge = document.getElementById('platform-badge');

    if (!url) {
        badge.style.display = 'none';
        return;
    }

    const platforms = {
        tiktok: /tiktok\.com/i,
        douyin: /douyin\.com/i,
        facebook: /facebook\.com|fb\.watch|fb\.com/i,
        youtube: /youtube\.com|youtu\.be/i,
        instagram: /instagram\.com/i,
    };

    for (const [name, regex] of Object.entries(platforms)) {
        if (regex.test(url)) {
            badge.textContent = name.charAt(0).toUpperCase() + name.slice(1);
            badge.className = `platform-badge ${name}`;
            badge.style.display = 'block';
            return;
        }
    }
    badge.style.display = 'none';
}

async function downloadSingle() {
    const url = document.getElementById('download-url').value.trim();
    if (!url) {
        showToast('Vui lòng nhập URL video', 'warning');
        return;
    }

    const btn = document.getElementById('btn-download');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Đang tải...';

    try {
        const result = await api('/api/download', {
            method: 'POST',
            body: JSON.stringify({ url })
        });

        showToast(`Đang tải video từ ${result.platform}`, 'info');

        // Show progress
        const statusEl = document.getElementById('download-status');
        statusEl.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <span class="badge badge-downloading">⏳ Downloading</span>
                    <span style="font-size:12px;color:var(--text-tertiary);">ID: ${result.id}</span>
                </div>
                <div id="progress-text-${result.id}" style="font-size:13px;font-weight:700;color:var(--accent-primary);">0%</div>
            </div>
            <div class="progress-bar" style="height:8px;"><div class="progress-fill" id="progress-${result.id}" style="width:0%"></div></div>
        `;

        // Poll for status
        startPolling(result.id);

        // Clear input
        document.getElementById('download-url').value = '';
        document.getElementById('platform-badge').style.display = 'none';
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⬇️ Tải Video';
    }
}

async function downloadBatch() {
    const text = document.getElementById('batch-urls').value.trim();
    if (!text) {
        showToast('Vui lòng nhập danh sách URL', 'warning');
        return;
    }

    const urls = text.split('\n').filter(u => u.trim());
    if (urls.length === 0) {
        showToast('Không tìm thấy URL nào', 'warning');
        return;
    }

    try {
        const result = await api('/api/download/batch', {
            method: 'POST',
            body: JSON.stringify({ urls })
        });

        showToast(`Đang tải ${result.count} video`, 'info');

        // Show batch status
        const statusEl = document.getElementById('batch-status');
        let html = '';
        result.videos.forEach(v => {
            html += `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span class="badge badge-downloading">⏳</span>
                <span style="font-size:11px;color:var(--text-tertiary);">${v.platform}</span>
                <span style="font-size:11px;">${v.id}</span>
            </div>`;
            startPolling(v.id);
        });
        statusEl.innerHTML = html;

        document.getElementById('batch-urls').value = '';
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

// Count URLs in batch textarea
document.addEventListener('DOMContentLoaded', () => {
    const batchEl = document.getElementById('batch-urls');
    if (batchEl) {
        batchEl.addEventListener('input', () => {
            const count = batchEl.value.split('\n').filter(u => u.trim()).length;
            document.getElementById('batch-count').textContent = `${count} URLs`;
        });
    }
});

// ═══════════════════════════════════════════
// POLLING & STATUS
// ═══════════════════════════════════════════
function startPolling(videoId) {
    if (state.pollIntervals[videoId]) return;

    state.pollIntervals[videoId] = setInterval(async () => {
        try {
            const status = await api(`/api/videos/${videoId}/status`);
            const progressEl = document.getElementById(`progress-${videoId}`);
            const textEl = document.getElementById(`progress-text-${videoId}`);

            if (progressEl && status.progress !== undefined) {
                const p = Math.min(100, Math.max(0, status.progress));
                progressEl.style.width = `${p}%`;
                if (textEl) textEl.textContent = `${p.toFixed(1)}%`;
            }

            if (status.status === 'downloaded') {
                if (progressEl) progressEl.style.width = '100%';
                if (textEl) textEl.textContent = '100% ✅';

                const badgeEl = document.getElementById(`badge-status-${videoId}`);
                if (badgeEl) {
                    badgeEl.className = 'badge badge-downloaded';
                    badgeEl.innerHTML = '✅ Downloaded';
                }

                showToast(`Video ${videoId} đã tải xong! ✅`, 'success');
                clearInterval(state.pollIntervals[videoId]);
                delete state.pollIntervals[videoId];
                loadStats();
            } else if (status.status === 'processed') {
                if (progressEl) progressEl.style.width = '100%';
                if (textEl) textEl.textContent = '100% ⚡';

                const badgeEl = document.getElementById(`badge-status-${videoId}`);
                if (badgeEl) {
                    badgeEl.className = 'badge badge-processed';
                    badgeEl.innerHTML = '⚡ Processed';
                }

                showToast(`Video ${videoId} đã xử lý xong! ⚡`, 'success');
                clearInterval(state.pollIntervals[videoId]);
                delete state.pollIntervals[videoId];
                loadStats();
            } else if (status.status === 'failed') {
                if (textEl) textEl.textContent = '❌ Lỗi';
                if (progressEl) progressEl.style.background = 'var(--accent-danger)';
                showToast(`Video ${videoId} lỗi: ${status.error_message}`, 'error');
                clearInterval(state.pollIntervals[videoId]);
                delete state.pollIntervals[videoId];
            }
        } catch (err) {
            // ignore
        }
    }, 1500);
}

async function refreshVideoStatuses() {
    // Only refresh on library page
    if (state.currentPage !== 'library') return;
    // Reload if we have any downloading/processing videos
    const hasActive = state.videos.some(v =>
        v.status === 'downloading' || v.status === 'processing'
    );
    if (hasActive) {
        await loadVideos();
    }
}

// ═══════════════════════════════════════════
// VIDEO LIBRARY
// ═══════════════════════════════════════════
async function loadVideos(statusFilter) {
    try {
        const url = statusFilter && statusFilter !== 'all'
            ? `/api/videos?status=${statusFilter}`
            : '/api/videos';
        const data = await api(url);
        state.videos = data.videos || [];
        renderVideoGrid(state.videos);
    } catch (err) {
        console.error('Failed to load videos:', err);
    }
}

function filterVideos(status, btn) {
    // Update tab buttons
    document.querySelectorAll('#library-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadVideos(status);
}

function renderVideoGrid(videos) {
    const grid = document.getElementById('video-grid');
    if (!videos || videos.length === 0) {
        grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1;">
                <div class="empty-icon">🎬</div>
                <div class="empty-title">Không có video nào</div>
                <div class="empty-desc">Tải video để bắt đầu sử dụng</div>
                <button class="btn btn-primary" onclick="navigateTo('download')">⬇️ Tải video</button>
            </div>`;
        return;
    }

    let html = '';
    videos.forEach(v => {
        const title = v.title || v.original_filename || 'Untitled';
        const platformIcon = getPlatformEmoji(v.source_platform);
        const duration = formatDuration(v.duration);
        const fileSize = formatSize(v.file_size);
        const badge = getStatusBadge(v.status);
        const thumbUrl = v.thumbnail_path ? `/api/file/${v.id}/thumbnail` : '';

        html += `
        <div class="video-card" data-id="${v.id}">
            <div class="video-thumb" onclick="openVideoModal('${v.id}')">
                ${thumbUrl
                ? `<img src="${thumbUrl}" alt="thumb" loading="lazy">`
                : `<span style="font-size:48px;opacity:0.3;">🎬</span>`}
                <div class="play-overlay">
                    <span style="font-size:32px;">▶️</span>
                </div>
                ${duration ? `<span class="duration">${duration}</span>` : ''}
                <span class="platform-icon">${platformIcon}</span>
            </div>
            <div class="video-info">
                <div class="video-title" title="${escapeHtml(title)}">${escapeHtml(title.substring(0, 60))}</div>
                <div class="video-meta">
                    <div>
                        ${badge}
                        <span class="video-size">${fileSize}</span>
                    </div>
                    <div class="video-actions">
                        ${v.status === 'downloaded' ? `<button class="btn-icon" onclick="event.stopPropagation();quickProcess('${v.id}')" title="Xử lý">⚡</button>` : ''}
                        ${(v.status === 'processed' || v.status === 'downloaded') ? `<button class="btn-icon" onclick="event.stopPropagation();quickPublish('${v.id}')" title="Đăng">📤</button>` : ''}
                        <button class="btn-icon" onclick="event.stopPropagation();deleteVideo('${v.id}')" title="Xóa" style="color:var(--accent-danger);">🗑️</button>
                    </div>
                </div>
            </div>
        </div>`;
    });
    grid.innerHTML = html;
}

async function deleteVideo(videoId) {
    if (!confirm('Xóa video này và tất cả file liên quan?')) return;
    try {
        await api(`/api/videos/${videoId}`, { method: 'DELETE' });
        showToast('Đã xóa video', 'success');
        loadVideos();
        loadStats();
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

function quickProcess(videoId) {
    navigateTo('process');
    setTimeout(() => {
        document.getElementById('process-video-select').value = videoId;
        showProcessPreview(videoId);
    }, 200);
}

function quickPublish(videoId) {
    navigateTo('publish');
    setTimeout(() => {
        document.getElementById('publish-video-select').value = videoId;
        showPublishPreview(videoId);
    }, 200);
}

// ═══════════════════════════════════════════
// VIDEO PROCESSING
// ═══════════════════════════════════════════
async function loadProcessOptions() {
    try {
        const data = await api('/api/process/options');
        state.processOptions = data.defaults || {};
        renderProcessOptions(data.options, data.defaults);
    } catch (err) {
        console.error('Failed to load process options:', err);
    }
}

function renderProcessOptions(options, defaults) {
    const grid = document.getElementById('process-options-grid');
    if (!grid) return;

    let html = '';
    for (const [key, opt] of Object.entries(options)) {
        const isActive = defaults[key] || false;
        const hasValue = 'value' in opt;

        html += `
        <div class="option-card ${isActive ? 'active' : ''}" id="opt-card-${key}">
            <div class="option-header">
                <span class="option-name">${opt.name}</span>
                <input type="checkbox" class="toggle" id="opt-${key}" 
                       ${isActive ? 'checked' : ''} 
                       onchange="toggleOption('${key}', this)">
            </div>
            <div class="option-desc">${opt.description}</div>
            ${hasValue && key !== 'change_metadata' && key !== 'remove_audio' ? `
                <div class="option-value">
                    <input type="${typeof opt.value === 'number' ? 'number' : 'text'}" 
                           id="opt-val-${key}" 
                           value="${defaults[key + '_value'] !== undefined ? defaults[key + '_value'] : opt.value}"
                           step="any"
                           onchange="updateOptionValue('${key}', this.value)">
                </div>
            ` : ''}
        </div>`;
    }
    grid.innerHTML = html;
}

function toggleOption(key, checkbox) {
    state.processOptions[key] = checkbox.checked;
    const card = document.getElementById(`opt-card-${key}`);
    if (card) {
        card.classList.toggle('active', checkbox.checked);
    }
}

function updateOptionValue(key, value) {
    state.processOptions[key + '_value'] = value;
}

function resetProcessOptions() {
    loadProcessOptions();
    showToast('Đã reset về mặc định', 'info');
}

async function loadVideoSelects() {
    try {
        const data = await api('/api/videos');
        const select = document.getElementById('process-video-select');
        select.innerHTML = '<option value="">-- Chọn video --</option>';

        (data.videos || []).forEach(v => {
            if (v.status === 'downloaded' || v.status === 'processed' || v.status === 'failed') {
                const title = v.title || v.original_filename || v.id;
                const badge = v.status === 'processed' ? '✅' : v.status === 'failed' ? '❌' : '📥';
                select.innerHTML += `<option value="${v.id}">${badge} ${title.substring(0, 50)} (${v.id})</option>`;
            }
        });
    } catch (err) {
        console.error('Failed to load video selects:', err);
    }
}

function showProcessPreview(videoId) {
    const preview = document.getElementById('process-preview');
    const player = document.getElementById('process-video-player');
    if (videoId) {
        player.src = `/api/file/${videoId}/original`;
        preview.style.display = 'block';
    } else {
        preview.style.display = 'none';
    }
}

async function processVideo() {
    const videoId = document.getElementById('process-video-select').value;
    if (!videoId) {
        showToast('Vui lòng chọn video', 'warning');
        return;
    }

    try {
        const result = await api(`/api/process/${videoId}`, {
            method: 'POST',
            body: JSON.stringify({ options: state.processOptions })
        });

        showToast('Đang xử lý video... ⚡', 'info');
        startPolling(videoId);

        // Show status
        const statusEl = document.getElementById('process-status');
        statusEl.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <span id="badge-status-${videoId}" class="badge badge-processing">⏳ Processing</span>
                    <span style="font-size:12px;color:var(--text-tertiary);">ID: ${videoId}</span>
                </div>
                <div id="progress-text-${videoId}" style="font-size:13px;font-weight:700;color:var(--accent-primary);">0%</div>
            </div>
            <div class="progress-bar" style="height:8px;"><div class="progress-fill" id="progress-${videoId}" style="width:0%"></div></div>
        `;
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

async function processAllVideos() {
    try {
        const data = await api('/api/videos?status=downloaded');
        const videoIds = (data.videos || []).map(v => v.id);

        if (videoIds.length === 0) {
            showToast('Không có video nào cần xử lý', 'warning');
            return;
        }

        const result = await api('/api/process/batch', {
            method: 'POST',
            body: JSON.stringify({
                video_ids: videoIds,
                options: state.processOptions
            })
        });

        showToast(`Đang xử lý ${result.count} video`, 'info');
        videoIds.forEach(id => startPolling(id));
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

// ═══════════════════════════════════════════
// AI SERVICES
// ═══════════════════════════════════════════
function selectStyle(el) {
    document.querySelectorAll('#ai-style-grid .style-card').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    state.selectedStyle = el.dataset.style;
}

async function aiRewrite() {
    const text = document.getElementById('ai-input').value.trim();
    if (!text) {
        showToast('Vui lòng nhập nội dung', 'warning');
        return;
    }

    const btn = document.getElementById('btn-ai-rewrite');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Đang viết lại...';

    try {
        const niche = document.getElementById('ai-niche').value.trim();
        const result = await api('/api/ai/caption', {
            method: 'POST',
            body: JSON.stringify({
                title: text.substring(0, 100),
                description: text,
                style: state.selectedStyle,
                language: 'vi',
                niche: niche
            })
        });

        renderAIResult(result);
    } catch (err) {
        showToast(`Lỗi AI: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🤖 Viết lại bằng AI';
    }
}

function renderAIResult(result) {
    const container = document.getElementById('ai-result');
    if (result.error) {
        container.innerHTML = `<div style="color:var(--accent-danger);">❌ ${escapeHtml(result.error)}</div>`;
        return;
    }

    const caption = result.caption || result.original || '';
    const hashtags = result.hashtags || [];
    const hooks = result.hooks || [];

    let html = `
        <div style="margin-bottom:16px;">
            <div class="form-label">Caption</div>
            <div style="background:var(--bg-tertiary);border-radius:8px;padding:14px;font-size:13px;line-height:1.7;white-space:pre-wrap;" id="ai-caption-text">${escapeHtml(caption)}</div>
        </div>`;

    if (hashtags.length > 0) {
        html += `
        <div style="margin-bottom:16px;">
            <div class="form-label">Hashtags</div>
            <div class="checkbox-grid">
                ${hashtags.map(h => `<span class="checkbox-pill checked">${escapeHtml(h)}</span>`).join('')}
            </div>
        </div>`;
    }

    if (hooks.length > 0) {
        html += `
        <div>
            <div class="form-label">Hook gợi ý</div>
            ${hooks.map((h, i) => `<div style="padding:6px 0;font-size:12px;color:var(--text-secondary);">${i + 1}. ${escapeHtml(h)}</div>`).join('')}
        </div>`;
    }

    container.innerHTML = html;
}

function copyAIResult() {
    const textEl = document.getElementById('ai-caption-text');
    if (textEl) {
        navigator.clipboard.writeText(textEl.textContent);
        showToast('Đã copy caption!', 'success');
    }
}

async function generateHashtags() {
    const topic = document.getElementById('hashtag-topic').value.trim();
    if (!topic) {
        showToast('Nhập chủ đề', 'warning');
        return;
    }

    try {
        const result = await api('/api/ai/hashtags', {
            method: 'POST',
            body: JSON.stringify({ topic, count: 10, language: 'vi' })
        });

        const container = document.getElementById('hashtag-result');
        if (result.hashtags && result.hashtags.length > 0) {
            container.innerHTML = `<div class="checkbox-grid">
                ${result.hashtags.map(h => `<span class="checkbox-pill checked">${escapeHtml(h)}</span>`).join('')}
            </div>`;
        } else {
            container.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;">Không tạo được hashtag</div>';
        }
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

// ═══════════════════════════════════════════
// PUBLISH & SCHEDULE
// ═══════════════════════════════════════════
async function loadPublishData() {
    // Load videos for publish select
    try {
        const data = await api('/api/videos');
        const select = document.getElementById('publish-video-select');
        select.innerHTML = '<option value="">-- Chọn video --</option>';

        (data.videos || []).forEach(v => {
            if (v.status === 'processed' || v.status === 'downloaded') {
                const title = v.title || v.original_filename || v.id;
                const icon = v.status === 'processed' ? '✅' : '📥';
                select.innerHTML += `<option value="${v.id}">${icon} ${title.substring(0, 50)}</option>`;
            }
        });
    } catch (err) {
        console.error('Failed to load publish videos:', err);
    }

    // Load FB pages
    await loadFBPagesForSelect();
}

async function loadFBPagesForSelect() {
    try {
        const data = await api('/api/fb/pages');
        state.fbPages = data.pages || [];
        const container = document.getElementById('page-select-list');

        if (state.fbPages.length === 0) {
            container.innerHTML = `<div style="font-size:12px;color:var(--text-tertiary);">
                Chưa có Page nào. <a href="#" onclick="navigateTo('pages')">Thêm Page →</a></div>`;
            return;
        }

        let html = '';
        state.fbPages.forEach(p => {
            const initial = (p.page_name || 'P')[0].toUpperCase();
            html += `
            <div class="page-select-card ${state.selectedPageId === p.id ? 'selected' : ''}" 
                 onclick="selectPage('${p.id}', this)" style="margin-bottom:8px;">
                <div class="page-avatar">${initial}</div>
                <div class="page-details">
                    <div class="page-card-name">${escapeHtml(p.page_name)}</div>
                    <div class="page-card-cat">${escapeHtml(p.category || 'Page')}</div>
                </div>
            </div>`;
        });
        container.innerHTML = html;
    } catch (err) {
        console.error('Failed to load pages:', err);
    }
}

function selectPage(pageId, el) {
    state.selectedPageId = pageId;
    document.querySelectorAll('.page-select-card').forEach(c => c.classList.remove('selected'));
    if (el) el.classList.add('selected');
}

function showPublishPreview(videoId) {
    const area = document.getElementById('publish-preview-area');
    const player = document.getElementById('publish-video-player');
    if (videoId) {
        // Try processed first, fallback to original
        const video = state.videos.find(v => v.id === videoId);
        if (video?.processed_path) {
            player.src = `/api/file/${videoId}/processed`;
        } else {
            player.src = `/api/file/${videoId}/original`;
        }
        area.style.display = 'block';
    } else {
        area.style.display = 'none';
    }
}

function toggleSchedule() {
    const checked = document.getElementById('schedule-toggle').checked;
    document.getElementById('schedule-time-group').style.display = checked ? 'block' : 'none';
}

async function aiGenerateCaption() {
    const videoId = document.getElementById('publish-video-select').value;
    if (!videoId) {
        showToast('Chọn video trước', 'warning');
        return;
    }

    try {
        const result = await api(`/api/ai/video-caption/${videoId}`, {
            method: 'POST',
            body: JSON.stringify({ style: 'viral', language: 'vi' })
        });

        if (result.caption) {
            document.getElementById('publish-caption').value = result.caption;
        }
        if (result.hashtags) {
            document.getElementById('publish-hashtags').value = result.hashtags.join(' ');
        }
        showToast('AI đã tạo caption! ✨', 'success');
    } catch (err) {
        showToast(`Lỗi AI: ${err.message}`, 'error');
    }
}

async function publishOrSchedule() {
    const videoId = document.getElementById('publish-video-select').value;
    const pageId = state.selectedPageId;
    const caption = document.getElementById('publish-caption').value;
    const hashtags = document.getElementById('publish-hashtags').value;
    const isScheduled = document.getElementById('schedule-toggle').checked;

    if (!videoId) { showToast('Chọn video', 'warning'); return; }
    if (!pageId) { showToast('Chọn Facebook Page', 'warning'); return; }

    const statusEl = document.getElementById('publish-status');

    if (isScheduled) {
        const scheduledTime = document.getElementById('schedule-datetime').value;
        if (!scheduledTime) { showToast('Chọn thời gian đăng', 'warning'); return; }

        try {
            statusEl.innerHTML = '<span class="badge badge-processing">⏳ Đang lên lịch...</span>';
            const result = await api('/api/schedule', {
                method: 'POST',
                body: JSON.stringify({
                    video_id: videoId,
                    page_id: pageId,
                    scheduled_time: new Date(scheduledTime).toISOString(),
                    caption,
                    hashtags,
                })
            });
            showToast(result.message || 'Đã lên lịch!', 'success');
            statusEl.innerHTML = `<span class="badge badge-scheduled">📅 ${result.message}</span>`;
            loadStats();
        } catch (err) {
            showToast(`Lỗi: ${err.message}`, 'error');
            statusEl.innerHTML = `<span class="badge badge-failed">❌ ${err.message}</span>`;
        }
    } else {
        try {
            statusEl.innerHTML = '<span class="badge badge-processing">⏳ Đang đăng...</span>';
            const result = await api('/api/publish', {
                method: 'POST',
                body: JSON.stringify({
                    video_id: videoId,
                    page_id: pageId,
                    caption,
                    hashtags,
                })
            });

            if (result.success) {
                showToast('Đăng thành công! 🎉', 'success');
                statusEl.innerHTML = `<span class="badge badge-published">✅ ${result.message}</span>`;
                loadStats();
            } else {
                showToast(`Lỗi: ${result.error}`, 'error');
                statusEl.innerHTML = `<span class="badge badge-failed">❌ ${result.error}</span>`;
            }
        } catch (err) {
            showToast(`Lỗi: ${err.message}`, 'error');
            statusEl.innerHTML = `<span class="badge badge-failed">❌ ${err.message}</span>`;
        }
    }
}

// ═══════════════════════════════════════════
// SCHEDULE
// ═══════════════════════════════════════════
async function loadSchedule() {
    try {
        const data = await api('/api/schedule');
        state.scheduledPosts = data.posts || [];
        renderScheduleList(state.scheduledPosts);
    } catch (err) {
        console.error('Failed to load schedule:', err);
    }
}

function renderScheduleList(posts) {
    const container = document.getElementById('schedule-list');
    if (!posts || posts.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📅</div>
                <div class="empty-title">Chưa có bài nào được lên lịch</div>
                <div class="empty-desc">Đi tới "Đăng / Lên lịch" để tạo bài đăng mới</div>
                <button class="btn btn-primary" onclick="navigateTo('publish')">📤 Tạo bài đăng</button>
            </div>`;
        return;
    }

    let html = '';
    posts.forEach(p => {
        const dt = new Date(p.scheduled_time);
        const badge = getStatusBadge(p.status);

        html += `
        <div class="schedule-item">
            <div class="schedule-time">
                <div class="date">${dt.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })}</div>
                <div class="time">${dt.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</div>
            </div>
            <div class="schedule-info">
                <div class="sched-title">${escapeHtml(p.video_title || 'Video')}</div>
                <div class="sched-page">📘 ${escapeHtml(p.page_name || 'Page')} • ${escapeHtml(p.caption?.substring(0, 50) || '')}</div>
            </div>
            ${badge}
            ${p.status === 'pending' ? `<button class="btn btn-ghost btn-sm" onclick="cancelScheduled('${p.id}')" style="color:var(--accent-danger);">✕</button>` : ''}
        </div>`;
    });
    container.innerHTML = html;
}

async function cancelScheduled(postId) {
    if (!confirm('Hủy bài đăng này?')) return;
    try {
        await api(`/api/schedule/${postId}`, { method: 'DELETE' });
        showToast('Đã hủy bài đăng', 'success');
        loadSchedule();
        loadStats();
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

// ═══════════════════════════════════════════
// FACEBOOK PAGES
// ═══════════════════════════════════════════
async function loadFBPages() {
    try {
        const data = await api('/api/fb/pages');
        state.fbPages = data.pages || [];
        renderFBPages(state.fbPages);
    } catch (err) {
        console.error('Failed to load FB pages:', err);
    }
}

function renderFBPages(pages) {
    const container = document.getElementById('fb-pages-list');
    if (!pages || pages.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📘</div>
                <div class="empty-title">Chưa có Page nào</div>
                <div class="empty-desc">Thêm Page Access Token ở bên phải</div>
            </div>`;
        return;
    }

    let html = '';
    pages.forEach(p => {
        const initial = (p.page_name || 'P')[0].toUpperCase();
        html += `
        <div class="page-select-card" style="margin-bottom:10px;">
            <div class="page-avatar">${initial}</div>
            <div class="page-details" style="flex:1;">
                <div class="page-card-name">${escapeHtml(p.page_name)}</div>
                <div class="page-card-cat">${escapeHtml(p.category || 'Page')} • ID: ${p.page_id}</div>
            </div>
            <div style="display:flex; gap:4px;">
                <button class="btn btn-ghost btn-sm" onclick="editFBPageToken('${p.id}', '${escapeHtml(p.page_name).replace(/'/g, "\\'")}')" title="Sửa Token">✏️ Sửa Token</button>
                <button class="btn btn-ghost btn-sm" onclick="deleteFBPage('${p.id}')" style="color:var(--accent-danger);" title="Xóa">🗑️</button>
            </div>
        </div>`;
    });
    container.innerHTML = html;
}

function editFBPageToken(pageDbId, pageName) {
    const newToken = prompt(`Nhập Page Access Token mới cho "${pageName}":`);
    if (!newToken) return;

    api(`/api/fb/pages/${pageDbId}`, {
        method: 'PUT',
        body: JSON.stringify({ access_token: newToken.trim() })
    }).then(result => {
        showToast(result.message || 'Đã cập nhật token', 'success');
        loadFBPages();
        loadStats();
    }).catch(err => {
        showToast(`Lỗi: ${err.message}`, 'error');
    });
}

async function addFBPage() {
    const token = document.getElementById('page-token-input').value.trim();
    if (!token) {
        showToast('Nhập Page Access Token', 'warning');
        return;
    }

    try {
        const result = await api('/api/fb/pages', {
            method: 'POST',
            body: JSON.stringify({ access_token: token })
        });
        showToast(result.message || 'Đã thêm Page!', 'success');
        document.getElementById('page-token-input').value = '';
        loadFBPages();
        loadStats();
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

async function importPages() {
    const token = document.getElementById('user-token-input').value.trim();
    if (!token) {
        showToast('Nhập User Access Token', 'warning');
        return;
    }

    try {
        const result = await api('/api/fb/pages/from-user-token', {
            method: 'POST',
            body: JSON.stringify({ user_token: token })
        });
        showToast(`Đã import ${result.count} Pages!`, 'success');
        document.getElementById('user-token-input').value = '';
        loadFBPages();
        loadStats();
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

async function deleteFBPage(pageDbId) {
    if (!confirm('Xóa Page này?')) return;
    try {
        await api(`/api/fb/pages/${pageDbId}`, { method: 'DELETE' });
        showToast('Đã xóa Page', 'success');
        loadFBPages();
        loadStats();
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

// ═══════════════════════════════════════════
// FACEBOOK OAUTH LOGIN
// ═══════════════════════════════════════════
async function loginFacebook() {
    const btn = document.getElementById('btn-fb-login');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Đang kết nối...';

    try {
        const data = await api('/api/fb/login-url');

        // Open Facebook OAuth in a popup window
        const width = 650;
        const height = 700;
        const left = (screen.width - width) / 2;
        const top = (screen.height - height) / 2;

        const popup = window.open(
            data.url,
            'fb_login',
            `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=yes`
        );

        if (!popup) {
            showToast('Trình duyệt chặn popup! Hãy cho phép popup cho trang này.', 'error');
        }
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🔐 Đăng nhập Facebook';
    }
}

// Listen for OAuth callback messages from the popup window
window.addEventListener('message', function (event) {
    if (!event.data || !event.data.type) return;

    if (event.data.type === 'fb_auth_success') {
        const { user, count, pages } = event.data;

        showToast(`🎉 Đăng nhập thành công! Đã import ${count} Pages từ ${user}`, 'success');

        // Update login status UI
        document.getElementById('fb-login-user').textContent = `✅ Đã đăng nhập: ${user}`;
        document.getElementById('fb-login-detail').textContent = `${count} Pages đã được import`;
        document.getElementById('btn-fb-login').innerHTML = '✅ Đã đăng nhập';
        document.getElementById('btn-fb-login').style.background = 'var(--accent-success)';

        // Reload pages list
        loadFBPages();
        loadStats();
    }

    if (event.data.type === 'fb_auth_error') {
        showToast(`❌ Lỗi Facebook: ${event.data.error}`, 'error');
    }
});

// ═══════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════
async function loadSettings() {
    try {
        const data = await api('/api/settings');
        document.getElementById('setting-ai-provider').textContent = (data.ai_provider || '').toUpperCase();

        const openaiEl = document.getElementById('setting-openai');
        openaiEl.textContent = data.has_openai_key ? '✅ Đã cấu hình' : '⚠️ Chưa cấu hình';
        openaiEl.className = `badge ${data.has_openai_key ? 'badge-processed' : 'badge-pending'}`;

        const geminiEl = document.getElementById('setting-gemini');
        geminiEl.textContent = data.has_gemini_key ? '✅ Đã cấu hình' : '⚠️ Chưa cấu hình';
        geminiEl.className = `badge ${data.has_gemini_key ? 'badge-processed' : 'badge-pending'}`;

        const fbEl = document.getElementById('setting-fb');
        fbEl.textContent = data.has_fb_app ? '✅ Đã cấu hình' : '⚠️ Chưa cấu hình';
        fbEl.className = `badge ${data.has_fb_app ? 'badge-processed' : 'badge-pending'}`;

        document.getElementById('setting-ffmpeg').textContent = data.ffmpeg_path || 'system PATH';
        document.getElementById('setting-download-dir').textContent = data.download_dir || '--';
        document.getElementById('setting-processed-dir').textContent = data.processed_dir || '--';

        const cleanupEl = document.getElementById('setting-cleanup');
        if (cleanupEl) {
            cleanupEl.textContent = data.auto_cleanup ? '✅ Bật' : '❌ Tắt';
            cleanupEl.className = `badge ${data.auto_cleanup ? 'badge-processed' : 'badge-failed'}`;
        }
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

// ═══════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════
function getStatusBadge(status) {
    const icons = {
        pending: '⏳', downloading: '⬇️', downloaded: '📥',
        processing: '⚡', processed: '✅', published: '🎉',
        scheduled: '📅', failed: '❌',
    };
    return `<span class="badge badge-${status}">${icons[status] || '❓'} ${status}</span>`;
}

function getPlatformIcon(platform) {
    const icons = {
        tiktok: '<span style="color:#69C9D0;">TikTok</span>',
        douyin: '<span style="color:#fe2c55;">Douyin</span>',
        facebook: '<span style="color:#1877F2;">Facebook</span>',
        youtube: '<span style="color:#FF0000;">YouTube</span>',
        instagram: '<span style="color:#E1306C;">Instagram</span>',
    };
    return icons[platform] || platform || 'Unknown';
}

function getPlatformEmoji(platform) {
    const emojis = {
        tiktok: '🎵', douyin: '🇨🇳', facebook: '📘',
        youtube: '▶️', instagram: '📸', twitter: '🐦',
    };
    return emojis[platform] || '🌐';
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function timeAgo(dateStr) {
    if (!dateStr) return '';
    const now = new Date();
    const date = new Date(dateStr);
    const diff = Math.floor((now - date) / 1000);

    if (diff < 60) return 'Vừa xong';
    if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
    return `${Math.floor(diff / 86400)} ngày trước`;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ─── Toast Notifications ───
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    const icons = {
        success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type]}</span>
        <div class="toast-content">
            <div class="toast-message">${escapeHtml(message)}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        if (toast.parentElement) {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(50px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }
    }, duration);
}

// ─── Modal ───
function openModal(title, bodyHtml, footerHtml = '') {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-footer').innerHTML = footerHtml;
    document.getElementById('modal-overlay').classList.add('active');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('active');
}

// Close modal on overlay click
document.addEventListener('click', (e) => {
    if (e.target.id === 'modal-overlay') closeModal();
});

// Close modal on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal();
        closeVideoModal();
    }
});

// ─── Video Modal ───
function openVideoModal(videoId) {
    const video = state.videos.find(v => v.id === videoId);
    if (!video) return;

    const title = video.title || video.original_filename || 'Video Player';
    document.getElementById('video-modal-title').textContent = title.substring(0, 60);

    const player = document.getElementById('video-modal-player');
    const pathType = video.processed_path ? 'processed' : 'original';
    player.src = `/api/file/${videoId}/${pathType}`;

    document.getElementById('video-modal-overlay').classList.add('active');
    setTimeout(() => { player.play().catch(e => console.log('Auto-play blocked:', e)); }, 100);
}

function closeVideoModal() {
    document.getElementById('video-modal-overlay').classList.remove('active');
    document.getElementById('video-modal-player').pause();
    document.getElementById('video-modal-player').src = '';
}

// ═══════════════════════════════════════════
// LOGS
// ═══════════════════════════════════════════
let logsInterval = null;
let currentLogLevel = 'all';

async function loadLogs() {
    if (state.currentPage !== 'logs') return;

    try {
        const data = await api('/api/logs?count=300');
        renderLogs(data.logs || []);
    } catch (err) {
        console.error('Failed to load logs:', err);
    }

    if (!logsInterval) {
        logsInterval = setInterval(loadLogs, 3000);
    }
}

// Stop polling logs when leaving page
document.querySelectorAll('.nav-item[data-page]').forEach(item => {
    item.addEventListener('click', () => {
        if (item.dataset.page !== 'logs' && logsInterval) {
            clearInterval(logsInterval);
            logsInterval = null;
        }
    });
});

function renderLogs(logsLines) {
    const content = document.getElementById('log-content');
    if (!content) return;

    if (logsLines.length === 0) {
        content.innerHTML = '<div style="color:var(--text-tertiary);font-style:italic;">No logs available.</div>';
        document.getElementById('log-count').textContent = '0 entries';
        return;
    }

    let html = '';
    let visibleCount = 0;

    logsLines.forEach(line => {
        let level = 'INFO';
        if (line.includes(' ERROR: ')) level = 'ERROR';
        else if (line.includes(' WARNING: ')) level = 'WARNING';
        else if (line.includes(' DEBUG: ')) level = 'DEBUG';

        if (currentLogLevel !== 'all' && level !== currentLogLevel) return;

        visibleCount++;

        // Parse format: YYYY-MM-DD HH:MM:SS [logger_name] LEVEL: message
        const match = line.match(/^([0-9-]+\s[0-9:,]+)\s\[(.*?)\]\s([A-Z]+):\s(.*)/);
        if (match) {
            html += `<div class="log-line">
                <span class="log-time">[${match[1]}]</span>
                <span class="log-name">${match[2]}</span>
                <span class="log-${match[3]}">${match[3]}:</span> 
                ${escapeHtml(match[4])}
            </div>`;
        } else {
            // fallback
            html += `<div class="log-line">${escapeHtml(line)}</div>`;
        }
    });

    const isScrolledToBottom = content.parentElement.scrollHeight - content.parentElement.clientHeight <= content.parentElement.scrollTop + 50;

    content.innerHTML = html;
    document.getElementById('log-count').textContent = `${visibleCount} entries`;

    if (document.getElementById('log-auto-scroll').checked && isScrolledToBottom) {
        content.parentElement.scrollTop = content.parentElement.scrollHeight;
    }
}

function filterLogLevel(level) {
    currentLogLevel = level;
    loadLogs();
}

async function clearLogs() {
    try {
        await api('/api/logs', { method: 'DELETE' });
        showToast('Đã xóa logs', 'success');
        document.getElementById('log-content').innerHTML = '';
        currentLogLevel = 'all';
    } catch (err) {
        showToast(`Lỗi xóa log: ${err.message}`, 'error');
    }
}


// ═══════════════════════════════════════════
// DASHBOARD ANALYTICS (Chart.js)
// ═══════════════════════════════════════════
let chartDaily = null;
let chartPlatform = null;

async function loadDashboardAnalytics() {
    try {
        const data = await api('/api/dashboard/analytics');
        renderDailyChart(data.daily_stats || []);
        renderPlatformChart(data.by_platform || []);
        renderPagePerformance(data.page_stats || []);
        renderRecentActivity(data.recent_activity || []);
    } catch (err) {
        console.error('Analytics error:', err);
    }
}

function renderDailyChart(dailyStats) {
    const ctx = document.getElementById('chart-daily');
    if (!ctx) return;

    if (chartDaily) chartDaily.destroy();

    const labels = dailyStats.map(d => d.date);
    chartDaily = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                { label: 'Đã tải', data: dailyStats.map(d => d.downloaded || 0), backgroundColor: 'rgba(0,184,148,0.7)', borderRadius: 4 },
                { label: 'Đã xử lý', data: dailyStats.map(d => d.processed || 0), backgroundColor: 'rgba(108,92,231,0.7)', borderRadius: 4 },
                { label: 'Đã đăng', data: dailyStats.map(d => d.published || 0), backgroundColor: 'rgba(253,203,110,0.7)', borderRadius: 4 },
                { label: 'Lỗi', data: dailyStats.map(d => d.failed || 0), backgroundColor: 'rgba(214,48,49,0.5)', borderRadius: 4 },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#8888a8', font: { size: 11 } } } },
            scales: {
                x: { ticks: { color: '#8888a8' }, grid: { color: 'rgba(255,255,255,0.04)' } },
                y: { ticks: { color: '#8888a8' }, grid: { color: 'rgba(255,255,255,0.04)' }, beginAtZero: true },
            }
        }
    });
}

function renderPlatformChart(platformData) {
    const ctx = document.getElementById('chart-platform');
    if (!ctx) return;

    if (chartPlatform) chartPlatform.destroy();

    const colors = {
        tiktok: '#00f2ea', douyin: '#fe2c55', facebook: '#1877f2',
        youtube: '#ff0000', instagram: '#e4405f', unknown: '#8888a8'
    };

    chartPlatform = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: platformData.map(d => d.source_platform || 'unknown'),
            datasets: [{
                data: platformData.map(d => d.count),
                backgroundColor: platformData.map(d => colors[d.source_platform] || '#8888a8'),
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { color: '#8888a8', font: { size: 12 }, padding: 12 } }
            }
        }
    });
}

function renderPagePerformance(pageStats) {
    const container = document.getElementById('page-performance-list');
    if (!container) return;
    if (!pageStats.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📘</div><div class="empty-title">Chưa có dữ liệu Pages</div></div>';
        return;
    }
    container.innerHTML = pageStats.map(p => `
        <div style="display:flex;align-items:center;gap:12px;padding:10px;border-bottom:1px solid var(--border-color);">
            <div style="width:36px;height:36px;background:linear-gradient(135deg,#1877F2,#42b72a);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;">📘</div>
            <div style="flex:1;min-width:0;">
                <div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(p.page_name || 'Unknown')}</div>
                <div style="font-size:11px;color:var(--text-tertiary);">${p.post_count || 0} bài • ${p.published_count || 0} đã đăng • ${p.pending_count || 0} chờ</div>
            </div>
            <div style="text-align:right;">
                <div style="font-size:18px;font-weight:700;color:var(--accent-primary);">${p.post_count || 0}</div>
            </div>
        </div>
    `).join('');
}

function renderRecentActivity(activities) {
    const container = document.getElementById('recent-activity-list');
    if (!container) return;
    if (!activities.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">🕐</div><div class="empty-title">Chưa có hoạt động</div></div>';
        return;
    }
    const statusIcons = { downloaded: '⬇️', processed: '⚡', published: '✅', failed: '❌', pending: '⏳', processing: '🔄', downloading: '📥' };
    container.innerHTML = activities.map(a => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px;border-bottom:1px solid var(--border-color);font-size:12px;">
            <span style="font-size:16px;">${statusIcons[a.status] || '📄'}</span>
            <div style="flex:1;min-width:0;">
                <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;">${escapeHtml(a.title || a.id)}</div>
                <div style="color:var(--text-tertiary);font-size:11px;">${a.source_platform || ''} • ${a.status}</div>
            </div>
            <div style="color:var(--text-tertiary);font-size:10px;white-space:nowrap;">${a.updated_at ? new Date(a.updated_at).toLocaleString('vi-VN') : ''}</div>
        </div>
    `).join('');
}


// ═══════════════════════════════════════════
// PROFILE SCAN (SO9 9Downloader Style)
// ═══════════════════════════════════════════
let profileVideos = [];

async function scanProfile() {
    const url = document.getElementById('profile-url').value.trim();
    const limit = document.getElementById('profile-limit').value || 30;
    if (!url) { showToast('Vui lòng nhập URL profile', 'error'); return; }

    const btn = document.getElementById('btn-scan-profile');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Đang quét...';
    document.getElementById('profile-scan-status').innerHTML = '<div class="badge badge-processing">🔍 Đang quét profile, có thể mất 30-60s...</div>';

    try {
        const data = await api('/api/profile/list-videos', {
            method: 'POST',
            body: JSON.stringify({ url, limit: parseInt(limit) }),
        });

        profileVideos = data.videos || [];
        document.getElementById('profile-video-count').textContent = profileVideos.length;
        document.getElementById('profile-scan-status').innerHTML = `<div class="badge badge-success">✅ Tìm thấy ${profileVideos.length} video</div>`;

        renderProfileVideos();
    } catch (err) {
        showToast(`Lỗi quét: ${err.message}`, 'error');
        document.getElementById('profile-scan-status').innerHTML = `<div class="badge badge-failed">❌ ${err.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🔍 Quét danh sách Video';
    }
}

function renderProfileVideos() {
    const container = document.getElementById('profile-video-list');
    if (!profileVideos.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-title">Không tìm thấy video</div></div>';
        return;
    }
    container.innerHTML = profileVideos.map((v, i) => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px 4px;border-bottom:1px solid var(--border-color);">
            <input type="checkbox" class="profile-video-cb" data-url="${escapeHtml(v.url)}" checked style="flex-shrink:0;">
            ${v.thumbnail ? `<img src="${v.thumbnail}" style="width:60px;height:40px;object-fit:cover;border-radius:4px;flex-shrink:0;" onerror="this.style.display='none'">` : ''}
            <div style="flex:1;min-width:0;">
                <div style="font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(v.title || 'Untitled')}</div>
                <div style="font-size:10px;color:var(--text-tertiary);">
                    ${v.duration && v.duration !== '0' ? `⏱ ${Math.round(v.duration)}s` : ''}
                    ${v.views && v.views !== '0' ? ` • 👁 ${parseInt(v.views).toLocaleString()}` : ''}
                </div>
            </div>
        </div>
    `).join('');
}

function selectAllProfileVideos() {
    const cbs = document.querySelectorAll('.profile-video-cb');
    const allChecked = [...cbs].every(cb => cb.checked);
    cbs.forEach(cb => cb.checked = !allChecked);
}

async function downloadSelectedProfileVideos() {
    const cbs = document.querySelectorAll('.profile-video-cb:checked');
    const urls = [...cbs].map(cb => cb.dataset.url).filter(Boolean);

    if (!urls.length) { showToast('Chưa chọn video nào', 'error'); return; }

    const btn = document.getElementById('btn-download-selected');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Đang tải...';

    try {
        const data = await api('/api/profile/download-selected', {
            method: 'POST',
            body: JSON.stringify({ urls }),
        });
        showToast(`🎉 Đã bắt đầu tải ${data.count} video!`, 'success');
        navigateTo('library');
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⬇️ Tải video đã chọn';
    }
}


// ═══════════════════════════════════════════
// MASS SCHEDULE (SO9 Style)
// ═══════════════════════════════════════════

async function loadMassScheduleData() {
    try {
        // Load videos (downloaded or processed)
        const videoData = await api('/api/videos?limit=100');
        const videos = (videoData.videos || []).filter(v => ['downloaded', 'processed'].includes(v.status));

        const videoList = document.getElementById('mass-video-list');
        if (videos.length === 0) {
            videoList.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;">Không có video nào sẵn sàng. Hãy tải và xử lý video trước.</div>';
        } else {
            videoList.innerHTML = videos.map(v => `
                <label style="display:flex;align-items:center;gap:8px;padding:6px 4px;cursor:pointer;border-bottom:1px solid var(--border-color);">
                    <input type="checkbox" class="mass-video-cb" value="${v.id}">
                    <span style="font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        ${v.status === 'processed' ? '⚡' : '⬇️'} ${escapeHtml(v.title || v.id)} 
                        <span style="color:var(--text-tertiary);">(${v.source_platform})</span>
                    </span>
                </label>
            `).join('');
        }

        // Load pages
        const pageData = await api('/api/fb/pages');
        const pages = pageData.pages || [];

        const pageList = document.getElementById('mass-page-list');
        if (pages.length === 0) {
            pageList.innerHTML = '<div style="color:var(--text-tertiary);font-size:12px;">Chưa có Page nào. Hãy thêm Page trước.</div>';
        } else {
            pageList.innerHTML = pages.map(p => `
                <label style="display:flex;align-items:center;gap:8px;padding:6px 4px;cursor:pointer;border-bottom:1px solid var(--border-color);">
                    <input type="checkbox" class="mass-page-cb" value="${p.id}">
                    <span style="font-size:12px;flex:1;">📘 ${escapeHtml(p.page_name || p.page_id)}</span>
                    <span style="font-size:10px;color:var(--text-tertiary);">${p.category || ''}</span>
                </label>
            `).join('');
        }

        // Set default start time to 1 hour from now
        const now = new Date(Date.now() + 60 * 60 * 1000);
        const isoLocal = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
        document.getElementById('mass-start-time').value = isoLocal;

    } catch (err) {
        showToast(`Lỗi tải dữ liệu: ${err.message}`, 'error');
    }
}

async function executeMassSchedule() {
    const videoIds = [...document.querySelectorAll('.mass-video-cb:checked')].map(cb => cb.value);
    const pageIds = [...document.querySelectorAll('.mass-page-cb:checked')].map(cb => cb.value);
    const startTime = document.getElementById('mass-start-time').value;
    const interval = document.getElementById('mass-interval').value || 30;
    const caption = document.getElementById('mass-caption').value;
    const hashtags = document.getElementById('mass-hashtags').value;
    const useAiSpin = document.getElementById('mass-ai-spin').checked;

    if (!videoIds.length) { showToast('Vui lòng chọn ít nhất 1 video', 'error'); return; }
    if (!pageIds.length) { showToast('Vui lòng chọn ít nhất 1 Page', 'error'); return; }
    if (!startTime) { showToast('Vui lòng chọn thời gian bắt đầu', 'error'); return; }

    const totalPosts = videoIds.length * pageIds.length;
    if (!confirm(`Sẽ tạo ${totalPosts} bài đăng (${videoIds.length} videos × ${pageIds.length} pages). Tiếp tục?`)) return;

    const statusEl = document.getElementById('mass-schedule-status');
    statusEl.innerHTML = `<div class="badge badge-processing"><span class="spinner"></span> Đang tạo ${totalPosts} bài đăng${useAiSpin ? ' (AI đang spin caption...)' : ''}...</div>`;

    try {
        const data = await api('/api/mass-schedule', {
            method: 'POST',
            body: JSON.stringify({
                video_ids: videoIds,
                page_ids: pageIds,
                start_time: startTime,
                interval: parseInt(interval),
                caption,
                hashtags,
                use_ai_spin: useAiSpin,
            }),
        });

        statusEl.innerHTML = `<div class="badge badge-success">✅ ${data.message}</div>`;

        // Show results
        const resultEl = document.getElementById('mass-schedule-result');
        resultEl.style.display = 'block';
        document.getElementById('mass-result-list').innerHTML = (data.posts || []).map(p => `
            <div style="display:flex;align-items:center;gap:8px;padding:6px;border-bottom:1px solid var(--border-color);font-size:12px;">
                <span>📤</span>
                <span style="flex:1;">Video ${p.video_id} → 📘 ${escapeHtml(p.page_name)}</span>
                <span style="color:var(--text-tertiary);">${new Date(p.scheduled_time).toLocaleString('vi-VN')}</span>
            </div>
        `).join('');

        showToast(`🎉 ${data.message}`, 'success');
        loadStats();
    } catch (err) {
        statusEl.innerHTML = `<div class="badge badge-failed">❌ ${err.message}</div>`;
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}


// ═══════════════════════════════════════════
// AFFILIATE MARKETING
// ═══════════════════════════════════════════
let affVideoData = {};

async function loadAffiliateData() {
    try {
        const data = await api('/api/videos?limit=100');
        const videos = (data.videos || []).filter(v => ['downloaded', 'processed'].includes(v.status));
        const select = document.getElementById('aff-video-select');

        select.innerHTML = '<option value="">-- Chọn video --</option>';
        videos.forEach(v => {
            affVideoData[v.id] = v;
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.textContent = `${v.status === 'processed' ? '⚡' : '⬇️'} ${v.title || v.id} (${v.source_platform || ''})`;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error('Load affiliate data error:', err);
    }
}

function loadAffVideoInfo(videoId) {
    if (!videoId) return;
    const v = affVideoData[videoId];
    if (v && v.title) {
        // Auto-suggest keywords from title
        const keywords = document.getElementById('aff-keywords');
        if (!keywords.value) {
            keywords.value = v.title;
        }
    }
}

async function generateAffiliateCaption() {
    const videoId = document.getElementById('aff-video-select').value;
    const link = document.getElementById('aff-product-link').value.trim();
    const keywords = document.getElementById('aff-keywords').value.trim();
    const style = document.getElementById('aff-style').value;

    if (!keywords && !videoId) {
        showToast('Vui lòng chọn video hoặc nhập từ khóa sản phẩm', 'error');
        return;
    }

    const btn = document.getElementById('btn-gen-aff');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> AI đang viết...';
    document.getElementById('aff-status').innerHTML = '<div class="badge badge-processing">🤖 Đang tạo caption affiliate...</div>';

    const video = affVideoData[videoId] || {};

    try {
        const result = await api('/api/affiliate/generate-caption', {
            method: 'POST',
            body: JSON.stringify({
                video_title: video.title || keywords,
                video_description: video.description || '',
                product_keywords: keywords,
                affiliate_link: link,
                style: style,
                language: 'vi',
            }),
        });

        // Show results
        document.getElementById('aff-result').style.display = 'block';
        document.getElementById('aff-empty').style.display = 'none';
        document.getElementById('aff-result-caption').value = result.caption || '';
        document.getElementById('aff-result-comment').value = result.first_comment || '';
        document.getElementById('aff-result-hashtags').textContent = (result.hashtags || []).join(' ');
        document.getElementById('aff-result-cta').textContent = result.cta_text || '';

        document.getElementById('aff-status').innerHTML = '<div class="badge badge-success">✅ Đã tạo caption thành công!</div>';
        showToast('🎉 Caption affiliate đã sẵn sàng!', 'success');
    } catch (err) {
        document.getElementById('aff-status').innerHTML = `<div class="badge badge-failed">❌ ${err.message}</div>`;
        showToast(`Lỗi: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🤖 AI tạo Caption Affiliate';
    }
}

function copyToClipboard(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const text = el.value || el.textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast('📋 Đã copy!', 'success');
    }).catch(() => {
        // Fallback
        el.select && el.select();
        document.execCommand('copy');
        showToast('📋 Đã copy!', 'success');
    });
}

function useAffCaptionForPublish() {
    const caption = document.getElementById('aff-result-caption').value;
    const hashtags = document.getElementById('aff-result-hashtags').textContent;
    const videoId = document.getElementById('aff-video-select').value;

    // Navigate to publish page
    navigateTo('publish');

    // Pre-fill caption and hashtags
    setTimeout(() => {
        const captionEl = document.getElementById('publish-caption');
        const hashtagsEl = document.getElementById('publish-hashtags');
        if (captionEl) captionEl.value = caption;
        if (hashtagsEl) hashtagsEl.value = hashtags;

        // Pre-select video
        if (videoId) {
            const videoSelect = document.getElementById('publish-video-select');
            if (videoSelect) {
                videoSelect.value = videoId;
                showPublishPreview(videoId);
            }
        }
        showToast('📤 Đã chuyển caption sang trang Đăng bài!', 'success');
    }, 500);
}


// ═══════════════════════════════════════════
// AUTO SEEDING (Like/Comment/Share)
// ═══════════════════════════════════════════

async function loadSeedingPage() {
    await Promise.all([
        loadSeedingStats(),
        loadSeedingAccounts(),
        loadSeedingTasks(),
    ]);
}

async function loadSeedingStats() {
    try {
        const data = await api('/api/seeding/stats');
        document.getElementById('seed-stat-accounts').textContent = data.active_accounts || 0;
        document.getElementById('seed-stat-pending').textContent = data.total_pending || 0;
        document.getElementById('seed-stat-completed').textContent = data.total_completed || 0;
        document.getElementById('seed-stat-today').textContent = data.actions_today || 0;
    } catch (err) {
        console.error('Seeding stats error:', err);
    }
}

async function loadSeedingAccounts() {
    try {
        const data = await api('/api/seeding/accounts');
        const accounts = data.accounts || [];
        const container = document.getElementById('seeding-account-list');

        if (!accounts.length) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">👥</div>
                    <div class="empty-title">Chưa có tài khoản seeding</div>
                    <div class="empty-desc">Thêm Via/Clone để bắt đầu auto seeding</div>
                </div>`;
            return;
        }

        container.innerHTML = accounts.map(a => {
            const typeColors = { clone: '#e17055', via: '#6c5ce7', personal: '#00b894' };
            const statusIcon = a.status === 'active' ? '🟢' : '🔴';
            return `
            <div style="display:flex;align-items:center;gap:10px;padding:10px;border-bottom:1px solid var(--border-color);">
                <div style="width:36px;height:36px;background:linear-gradient(135deg,${typeColors[a.account_type] || '#8888a8'},#2d3436);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0;">
                    ${statusIcon}
                </div>
                <div style="flex:1;min-width:0;">
                    <div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        ${escapeHtml(a.name)} 
                        <span class="badge" style="font-size:10px;background:${typeColors[a.account_type] || '#555'};color:#fff;padding:2px 6px;border-radius:4px;">${a.account_type}</span>
                    </div>
                    <div style="font-size:11px;color:var(--text-tertiary);">
                        ID: ${a.fb_user_id || '?'} • ${a.actions_today || 0}/${a.daily_limit || 50} hôm nay
                    </div>
                </div>
                <button class="btn btn-ghost btn-sm" onclick="deleteSeedingAccount('${a.id}')" title="Xóa">🗑️</button>
            </div>`;
        }).join('');
    } catch (err) {
        console.error('Load seeding accounts error:', err);
    }
}

async function addSeedingAccount() {
    const name = document.getElementById('seed-acc-name').value.trim();
    const token = document.getElementById('seed-acc-token').value.trim();
    const accountType = document.getElementById('seed-acc-type').value;
    const dailyLimit = document.getElementById('seed-acc-limit').value || 50;

    if (!token) {
        showToast('Vui lòng nhập Access Token', 'error');
        return;
    }

    try {
        const data = await api('/api/seeding/accounts', {
            method: 'POST',
            body: JSON.stringify({
                name,
                access_token: token,
                account_type: accountType,
                daily_limit: parseInt(dailyLimit),
            }),
        });

        showToast(`✅ ${data.message}`, 'success');
        document.getElementById('seed-acc-name').value = '';
        document.getElementById('seed-acc-token').value = '';
        loadSeedingAccounts();
        loadSeedingStats();
    } catch (err) {
        showToast(`❌ ${err.message}`, 'error');
    }
}

async function deleteSeedingAccount(accountId) {
    if (!confirm('Xóa tài khoản này? Tất cả task liên quan cũng sẽ bị xóa.')) return;

    try {
        await api(`/api/seeding/accounts/${accountId}`, { method: 'DELETE' });
        showToast('Đã xóa tài khoản', 'success');
        loadSeedingAccounts();
        loadSeedingStats();
    } catch (err) {
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

async function createSeedingPlan() {
    const fbPostId = document.getElementById('seed-post-id').value.trim();
    const pageName = document.getElementById('seed-page-name').value.trim();
    const doLike = document.getElementById('seed-action-like').checked;
    const doComment = document.getElementById('seed-action-comment').checked;
    const doShare = document.getElementById('seed-action-share').checked;
    const delayMin = parseInt(document.getElementById('seed-delay-min').value) || 30;
    const delayMax = parseInt(document.getElementById('seed-delay-max').value) || 180;

    if (!fbPostId) {
        showToast('Vui lòng nhập Facebook Post ID', 'error');
        return;
    }
    if (!doLike && !doComment && !doShare) {
        showToast('Vui lòng chọn ít nhất 1 tác vụ', 'error');
        return;
    }

    const statusEl = document.getElementById('seeding-plan-status');
    statusEl.innerHTML = '<div class="badge badge-processing"><span class="spinner"></span> Đang tạo kế hoạch seeding...</div>';

    try {
        const data = await api('/api/seeding/create-plan', {
            method: 'POST',
            body: JSON.stringify({
                fb_post_id: fbPostId,
                page_name: pageName,
                actions: { like: doLike, comment: doComment, share: doShare },
                delay_min: delayMin,
                delay_max: delayMax,
            }),
        });

        statusEl.innerHTML = `<div class="badge badge-success">✅ ${data.message}</div>`;
        showToast(`🎯 ${data.message}`, 'success');

        // Clear form
        document.getElementById('seed-post-id').value = '';
        document.getElementById('seed-page-name').value = '';

        // Reload data
        loadSeedingTasks();
        loadSeedingStats();
    } catch (err) {
        statusEl.innerHTML = `<div class="badge badge-failed">❌ ${err.message}</div>`;
        showToast(`Lỗi: ${err.message}`, 'error');
    }
}

async function loadSeedingTasks() {
    try {
        const data = await api('/api/seeding/tasks?limit=50');
        const tasks = data.tasks || [];
        const container = document.getElementById('seeding-task-list');

        if (!tasks.length) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📋</div>
                    <div class="empty-title">Chưa có tác vụ seeding nào</div>
                </div>`;
            return;
        }

        const actionIcons = { like: '👍', comment: '💬', share: '📤' };
        const statusColors = { pending: '#fdcb6e', completed: '#00b894', failed: '#d63031', skipped: '#636e72' };

        container.innerHTML = tasks.map(t => `
            <div style="display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border-color);font-size:12px;">
                <span style="font-size:16px;">${actionIcons[t.action_type] || '🎯'}</span>
                <div style="flex:1;min-width:0;">
                    <div style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                        ${t.action_type.toUpperCase()} → ${escapeHtml(t.page_name || t.fb_post_id)}
                        ${t.comment_text ? `<span style="color:var(--text-tertiary);"> "${escapeHtml(t.comment_text.substring(0, 25))}..."</span>` : ''}
                    </div>
                    <div style="color:var(--text-tertiary);font-size:10px;">
                        👤 ${escapeHtml(t.account_name || t.account_id)} • Lịch: ${t.scheduled_at ? new Date(t.scheduled_at).toLocaleString('vi-VN') : '?'}
                    </div>
                </div>
                <span class="badge" style="font-size:10px;background:${statusColors[t.status] || '#555'};color:#fff;padding:2px 8px;border-radius:4px;">
                    ${t.status}
                </span>
            </div>
        `).join('');
    } catch (err) {
        console.error('Load seeding tasks error:', err);
    }
}

// ═══════════════════════════════════════════
// PAGE ANALYTICS (SO9 Style)
// ═══════════════════════════════════════════
let anaChartEngagement = null;
let anaChartFans = null;

async function loadAnalyticsPage() {
    try {
        const tableBody = document.getElementById('analytics-table-body');
        tableBody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 40px; color: var(--text-tertiary);"><div class="spinner" style="margin-bottom: 10px;"></div><br>Đang lấy dữ liệu trực tiếp từ Facebook Graph API cho tất cả các Page...<br>Việc này có thể mất vài giây.</td></tr>';

        const data = await api('/api/fb/analytics');
        const pages = data.pages || [];

        if (pages.length === 0) {
            document.getElementById('analytics-table-body').innerHTML = '<tr><td colspan="6" style="text-align:center;">Chưa có dữ liệu. Hãy thêm Page và thử lại.</td></tr>';
            return;
        }

        // Sort by engagement
        pages.sort((a, b) => b.total_engagement - a.total_engagement);

        // Update Hero Stats
        document.getElementById('ana-total-fans').textContent = pages.reduce((sum, p) => sum + (p.fan_count || 0), 0).toLocaleString();
        document.getElementById('ana-total-engagement').textContent = pages.reduce((sum, p) => sum + (p.total_engagement || 0), 0).toLocaleString();
        document.getElementById('ana-avg-engagement').textContent = (pages.reduce((sum, p) => sum + (p.avg_engagement || 0), 0) / pages.length).toFixed(1);
        document.getElementById('ana-total-posts').textContent = pages.reduce((sum, p) => sum + (p.post_count || 0), 0);

        // Render Table
        tableBody.innerHTML = pages.map((p, i) => `
            <tr>
                <td><span class="rank-badge rank-${i + 1}">${i + 1}</span></td>
                <td>
                    <div style="display:flex;align-items:center;gap:10px;">
                        <div style="width:30px;height:30px;background:linear-gradient(135deg,#1877F2,#42b72a);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;">📘</div>
                        <strong>${escapeHtml(p.name)}</strong>
                    </div>
                </td>
                <td style="font-weight:600;color:var(--accent-primary);">${(p.fan_count || 0).toLocaleString()}</td>
                <td style="color:var(--accent-success);">${(p.total_engagement || 0).toLocaleString()}</td>
                <td><span class="badge badge-processed">${p.avg_engagement || 0}</span></td>
                <td>
                    <button class="btn btn-ghost btn-sm" onclick="navigateTo('publish'); setTimeout(()=> {document.getElementById('publish-video-select').focus();}, 500)">📤 Đăng bài</button>
                </td>
            </tr>
        `).join('');

        // Render Charts
        renderAnalyticsCharts(pages);

    } catch (err) {
        showToast(`Lỗi tải thống kê: ${err.message}`, 'error');
    }
}

function renderAnalyticsCharts(pages) {
    // Engagement Chart
    const ctxEng = document.getElementById('chart-ana-engagement');
    if (anaChartEngagement) anaChartEngagement.destroy();

    anaChartEngagement = new Chart(ctxEng, {
        type: 'bar',
        data: {
            labels: pages.map(p => p.name.substring(0, 15)),
            datasets: [{
                label: 'Tổng tương tác',
                data: pages.map(p => p.total_engagement),
                backgroundColor: 'rgba(108, 92, 231, 0.7)',
                borderRadius: 4
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8888a8' } },
                y: { grid: { display: false }, ticks: { color: '#8888a8' } }
            }
        }
    });

    // Followers Chart
    const ctxFans = document.getElementById('chart-ana-fans');
    if (anaChartFans) anaChartFans.destroy();

    anaChartFans = new Chart(ctxFans, {
        type: 'pie',
        data: {
            labels: pages.slice(0, 5).map(p => p.name),
            datasets: [{
                data: pages.slice(0, 5).map(p => p.fan_count),
                backgroundColor: ['#0984e3', '#00b894', '#6c5ce7', '#fdcb6e', '#d63031'],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#8888a8', padding: 20, font: { size: 11 } }
                }
            }
        }
    });
}

