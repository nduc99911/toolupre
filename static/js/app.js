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
        library: 'Thư viện Video',
        process: 'Xử lý Video',
        ai: 'AI Viết lại',
        publish: 'Đăng / Lên lịch',
        schedule: 'Lịch đăng bài',
        pages: 'Facebook Pages',
        settings: 'Cài đặt',
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
        case 'dashboard': loadStats(); break;
        case 'logs': loadLogs(); break;
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
                    <div class="time">${dt.toLocaleTimeString('vi-VN', {hour:'2-digit',minute:'2-digit'})}</div>
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
            <div style="display:flex;align-items:center;gap:10px;">
                <span class="badge badge-downloading">⏳ Downloading</span>
                <span style="font-size:12px;color:var(--text-tertiary);">ID: ${result.id}</span>
            </div>
            <div class="progress-bar"><div class="progress-fill" id="progress-${result.id}" style="width:0%"></div></div>
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

            if (progressEl && status.progress !== undefined) {
                progressEl.style.width = `${Math.min(100, Math.max(0, status.progress))}%`;
            }

            if (status.status === 'downloaded') {
                if (progressEl) progressEl.style.width = '100%';
                showToast(`Video ${videoId} đã tải xong! ✅`, 'success');
                clearInterval(state.pollIntervals[videoId]);
                delete state.pollIntervals[videoId];
                loadStats();
            } else if (status.status === 'processed') {
                if (progressEl) progressEl.style.width = '100%';
                showToast(`Video ${videoId} đã xử lý xong! ⚡`, 'success');
                clearInterval(state.pollIntervals[videoId]);
                delete state.pollIntervals[videoId];
                loadStats();
            } else if (status.status === 'failed') {
                showToast(`Video ${videoId} lỗi: ${status.error_message}`, 'error');
                clearInterval(state.pollIntervals[videoId]);
                delete state.pollIntervals[videoId];
            }
        } catch (err) {
            // ignore
        }
    }, 2000);
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
            <div style="display:flex;align-items:center;gap:10px;margin-top:8px;">
                <span class="badge badge-processing">⏳ Processing</span>
                <span style="font-size:12px;color:var(--text-tertiary);">ID: ${videoId}</span>
            </div>
            <div class="progress-bar"><div class="progress-fill" id="progress-${videoId}" style="width:10%"></div></div>
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
            ${hooks.map((h, i) => `<div style="padding:6px 0;font-size:12px;color:var(--text-secondary);">${i+1}. ${escapeHtml(h)}</div>`).join('')}
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
                <div class="date">${dt.toLocaleDateString('vi-VN', {day:'2-digit',month:'2-digit',year:'numeric'})}</div>
                <div class="time">${dt.toLocaleTimeString('vi-VN', {hour:'2-digit',minute:'2-digit'})}</div>
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
            <button class="btn btn-ghost btn-sm" onclick="deleteFBPage('${p.id}')" style="color:var(--accent-danger);">🗑️</button>
        </div>`;
    });
    container.innerHTML = html;
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
window.addEventListener('message', function(event) {
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
