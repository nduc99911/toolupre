const express = require('express');
const fetch = require('node-fetch');
const { chromium } = require('playwright');
const path = require('path');
const { URL } = require('url');

const app = express();
const PORT = 3000;
let browser = null;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Common headers to mimic a real browser
const BROWSER_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
  'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
  'Accept-Encoding': 'gzip, deflate, br',
  'Sec-Ch-Ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
  'Sec-Ch-Ua-Mobile': '?0',
  'Sec-Ch-Ua-Platform': '"Windows"',
  'Sec-Fetch-Dest': 'document',
  'Sec-Fetch-Mode': 'navigate',
  'Sec-Fetch-Site': 'none',
  'Sec-Fetch-User': '?1',
  'Upgrade-Insecure-Requests': '1',
};

/**
 * Extract the video ID from various Douyin URL formats
 */
function extractVideoId(url) {
  // Format: https://www.douyin.com/video/7123456789
  const videoMatch = url.match(/douyin\.com\/video\/(\d+)/);
  if (videoMatch) return videoMatch[1];

  // Format: https://www.douyin.com/note/7123456789
  const noteMatch = url.match(/douyin\.com\/note\/(\d+)/);
  if (noteMatch) return noteMatch[1];

  return null;
}

/**
 * Extract sec_uid from Douyin profile URL
 */
function extractSecUid(url) {
  // Format: https://www.douyin.com/user/MS4wLjABAAAA...
  const userMatch = url.match(/douyin\.com\/user\/([^?/&]+)/);
  if (userMatch) return userMatch[1];
  return null;
}

/**
 * Extract video data from an aweme item
 */
function extractVideoFromAweme(item) {
  let videoUrl = null;
  const video = item.video;
  if (video) {
    if (video.bit_rate && video.bit_rate.length > 0) {
      const sorted = [...video.bit_rate].sort((a, b) => (b.bit_rate || 0) - (a.bit_rate || 0));
      const best = sorted[0];
      if (best.play_addr?.url_list) {
        videoUrl = best.play_addr.url_list[0];
      }
    }
    if (!videoUrl && video.play_addr?.url_list) {
      videoUrl = video.play_addr.url_list[0];
    }
  }
  return {
    id: item.aweme_id || item.awemeId || '',
    desc: item.desc || '',
    author: item.author?.nickname || item.authorInfo?.nickname || '',
    authorAvatar: item.author?.avatar_thumb?.url_list?.[0] || item.authorInfo?.avatarThumb?.url_list?.[0] || '',
    statistics: {
      likes: item.statistics?.digg_count || item.stats?.diggCount || 0,
      comments: item.statistics?.comment_count || item.stats?.commentCount || 0,
      shares: item.statistics?.share_count || item.stats?.shareCount || 0,
      plays: item.statistics?.play_count || item.stats?.playCount || 0,
    },
    cover: video?.cover?.url_list?.[0] || video?.origin_cover?.url_list?.[0] || '',
    duration: video?.duration || 0,
    videoUrl,
    musicTitle: item.music?.title || '',
    musicAuthor: item.music?.author || '',
    createTime: item.create_time || item.createTime || 0,
  };
}

/**
 * Resolve short URL (v.douyin.com) to full URL
 */
async function resolveShortUrl(shortUrl) {
  try {
    const response = await fetch(shortUrl, {
      headers: BROWSER_HEADERS,
      redirect: 'manual',
    });

    const location = response.headers.get('location');
    if (location) {
      return location;
    }

    // Try following redirects manually
    const response2 = await fetch(shortUrl, {
      headers: BROWSER_HEADERS,
      redirect: 'follow',
    });
    return response2.url;
  } catch (error) {
    throw new Error('Không thể resolve link ngắn: ' + error.message);
  }
}

/**
 * Fetch video info from Douyin page
 */
async function fetchVideoInfo(videoUrl) {
  let context;
  try {
    let fullUrl = videoUrl;
    if (videoUrl.includes('v.douyin.com') || videoUrl.includes('vt.tiktok.com')) {
      fullUrl = await resolveShortUrl(videoUrl);
    }
    const videoId = extractVideoId(fullUrl);

    if (!browser) browser = await chromium.launch({ headless: true });
    context = await browser.newContext({
      userAgent: BROWSER_HEADERS['User-Agent'],
      viewport: { width: 1280, height: 720 }
    });
    const page = await context.newPage();
    await page.goto(fullUrl, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(3000); // Give time for anti-bot
    const html = await page.content();

    let videoData = null;

    const renderDataMatch = html.match(/<script id="RENDER_DATA"[^>]*>([\s\S]*?)<\/script>/);
    if (renderDataMatch) {
      try {
        const decoded = decodeURIComponent(renderDataMatch[1]);
        const renderData = JSON.parse(decoded);
        for (const key of Object.keys(renderData)) {
          const section = renderData[key];
          if (section && section.aweme) {
            const aweme = section.aweme;
            const detail = aweme.detail || aweme;
            videoData = {
              id: detail.awemeId || detail.aweme_id || videoId,
              desc: detail.desc || '',
              author: detail.authorInfo?.nickname || detail.author?.nickname || 'Unknown',
              authorAvatar: detail.authorInfo?.avatarThumb?.url_list?.[0] || detail.author?.avatar_thumb?.url_list?.[0] || '',
              statistics: {
                likes: detail.stats?.diggCount || detail.statistics?.digg_count || 0,
                comments: detail.stats?.commentCount || detail.statistics?.comment_count || 0,
                shares: detail.stats?.shareCount || detail.statistics?.share_count || 0,
                plays: detail.stats?.playCount || detail.statistics?.play_count || 0,
              },
              cover: detail.video?.cover?.url_list?.[0] || detail.video?.origin_cover?.url_list?.[0] || '',
              duration: detail.video?.duration || 0,
              videoUrl: null,
              musicTitle: detail.music?.title || '',
              musicAuthor: detail.music?.author || '',
            };
            const video = detail.video;
            if (video) {
              if (video.bit_rate && video.bit_rate.length > 0) {
                const sorted = [...video.bit_rate].sort((a, b) => (b.bit_rate || 0) - (a.bit_rate || 0));
                const best = sorted[0];
                if (best.play_addr?.url_list) {
                  videoData.videoUrl = best.play_addr.url_list[0];
                }
              }
              if (!videoData.videoUrl && video.play_addr?.url_list) {
                videoData.videoUrl = video.play_addr.url_list[0];
              }
            }
            break;
          }
        }
      } catch (e) { console.error('Error parsing RENDER_DATA:', e.message); }
    }

    if (!videoData) {
      throw new Error('Không thể trích xuất thông tin video. Douyin có thể đã thay đổi cấu trúc trang.');
    }

    return videoData;
  } catch (error) {
    throw error;
  } finally {
    if (context) await context.close();
  }
}

// API endpoint to parse video
app.post('/api/parse', async (req, res) => {
  try {
    const { url } = req.body;

    if (!url) {
      return res.status(400).json({ error: 'Vui lòng nhập link video Douyin' });
    }

    // Validate URL
    if (!url.includes('douyin.com') && !url.includes('iesdouyin.com')) {
      return res.status(400).json({ error: 'Link không hợp lệ. Vui lòng nhập link Douyin.' });
    }

    const videoInfo = await fetchVideoInfo(url);
    res.json({ success: true, data: videoInfo });
  } catch (error) {
    console.error('Parse error:', error);
    res.status(500).json({ error: error.message || 'Đã có lỗi xảy ra khi phân tích video' });
  }
});

// Proxy endpoint to download video (avoids CORS)
app.get('/api/download', async (req, res) => {
  try {
    const { url, filename } = req.query;

    if (!url) {
      return res.status(400).json({ error: 'Missing video URL' });
    }

    const response = await fetch(url, {
      headers: {
        'User-Agent': BROWSER_HEADERS['User-Agent'],
        'Referer': 'https://www.douyin.com/',
      },
    });

    if (!response.ok) {
      throw new Error(`Failed to fetch video: ${response.status}`);
    }

    const contentType = response.headers.get('content-type') || 'video/mp4';
    const contentLength = response.headers.get('content-length');

    res.setHeader('Content-Type', contentType);
    res.setHeader('Content-Disposition', `attachment; filename="${filename || 'douyin_video.mp4'}"`);
    if (contentLength) {
      res.setHeader('Content-Length', contentLength);
    }

    response.body.pipe(res);
  } catch (error) {
    console.error('Download error:', error);
    res.status(500).json({ error: 'Lỗi khi tải video' });
  }
});

// ===== Profile Scanning =====

/**
 * Fetch profile info and videos from a Douyin user page
 */
async function fetchProfileVideos(profileUrl, maxCount = 10) {
  let context;
  try {
    let fullUrl = profileUrl;
    if (profileUrl.includes('v.douyin.com') || profileUrl.includes('vt.tiktok.com')) {
      fullUrl = await resolveShortUrl(profileUrl);
    }
    const secUid = extractSecUid(fullUrl);
    if (!secUid) {
      throw new Error('Không thể trích xuất sec_uid từ link profile. Vui lòng dùng link dạng: https://www.douyin.com/user/...');
    }

    console.log(`[Profile] sec_uid: ${secUid}, requesting ${maxCount} videos`);

    if (!browser) browser = await chromium.launch({ headless: true });
    context = await browser.newContext({
      userAgent: BROWSER_HEADERS['User-Agent'],
      viewport: { width: 1280, height: 720 }
    });
    const page = await context.newPage();
    
    let userInfo = null;
    let videos = [];
    
    // Intercept API responses for pagination
    page.on('response', async (response) => {
      const reqUrl = response.url();
      if (reqUrl.includes('/aweme/v1/web/aweme/post/')) {
        try {
          const data = await response.json();
          if (data && data.aweme_list && Array.isArray(data.aweme_list)) {
            for (const item of data.aweme_list) {
              videos.push(extractVideoFromAweme(item));
            }
          }
        } catch (e) {
          // ignore
        }
      }
    });

    await page.goto(fullUrl, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(4000); // Give time for initial load and API interception

    const html = await page.content();

    // Extract user info from RENDER_DATA
    const renderDataMatch = html.match(/<script id="RENDER_DATA"[^>]*>([\s\S]*?)<\/script>/);
    if (renderDataMatch) {
      try {
        const decoded = decodeURIComponent(renderDataMatch[1]);
        const renderData = JSON.parse(decoded);
        for (const key of Object.keys(renderData)) {
          const section = renderData[key];
          if (section?.user) {
            const u = section.user;
            userInfo = {
              secUid: u.secUid || u.sec_uid || secUid,
              uid: u.uid || u.uniqueId || '',
              nickname: u.nickname || u.uniqueId || 'Unknown',
              avatar: u.avatarThumb?.url_list?.[0] || u.avatar_thumb?.url_list?.[0] || u.avatarMedium?.url_list?.[0] || '',
              signature: u.signature || u.desc || '',
              followerCount: u.followerCount || u.mplatform_followers_count || 0,
              followingCount: u.followingCount || u.following_count || 0,
              totalFavorited: u.totalFavorited || u.total_favorited || 0,
              awemeCount: u.awemeCount || u.aweme_count || 0,
              verified: u.customVerify || u.verification_type !== undefined || false,
            };
          }
          // Also check if initial videos were embedded in SSR
          if (section?.post && section.post.data && Array.isArray(section.post.data)) {
            for (const item of section.post.data) {
              videos.push(extractVideoFromAweme(item));
            }
          }
        }
      } catch (e) {
        console.error('[Profile] Error parsing RENDER_DATA:', e.message);
      }
    }

    // Scroll to load more videos until we reach maxCount
    let scrollCount = 0;
    const maxScrolls = 20; // safety limit
    
    // Deduplicate function
    const deduplicate = (arr) => {
      const seen = new Set();
      return arr.filter(item => {
        if (!item || !item.id || seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      });
    };

    while (deduplicate(videos).length < maxCount && scrollCount < maxScrolls) {
      const prevLength = videos.length;
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await page.waitForTimeout(2500); // Wait for API response
      if (videos.length === prevLength) {
        // No new videos loaded, might be end of list
        scrollCount++;
      } else {
        scrollCount = 0; // reset if progress made
      }
    }

    videos = deduplicate(videos).slice(0, maxCount);

    if (!userInfo || userInfo.nickname === 'Unknown') {
      let nickname = userInfo ? userInfo.nickname : 'Unknown';
      try {
        const title = await page.title();
        const titleMatch = title.match(/(.*?)(?:的个人主页|的抖音)/);
        if (titleMatch) nickname = titleMatch[1].trim();
      } catch (e) {}
      
      if (!userInfo) {
        userInfo = {
          secUid, uid: '', nickname, avatar: '', signature: '',
          followerCount: 0, followingCount: 0, totalFavorited: 0, awemeCount: 0, verified: false,
        };
      } else {
        userInfo.nickname = nickname;
      }
    }

    return {
      userInfo,
      videos,
      totalFound: videos.length,
    };
  } catch (error) {
    throw error;
  } finally {
    if (context) await context.close();
  }
}

// API endpoint to scan profile
app.post('/api/profile', async (req, res) => {
  try {
    const { url, count } = req.body;

    if (!url) {
      return res.status(400).json({ error: 'Vui lòng nhập link profile Douyin' });
    }

    if (!url.includes('douyin.com')) {
      return res.status(400).json({ error: 'Link không hợp lệ. Vui lòng nhập link Douyin profile.' });
    }

    const maxCount = Math.min(Math.max(parseInt(count) || 10, 1), 100);
    const profileData = await fetchProfileVideos(url, maxCount);
    res.json({ success: true, data: profileData });
  } catch (error) {
    console.error('Profile error:', error);
    res.status(500).json({ error: error.message || 'Đã có lỗi xảy ra khi quét profile' });
  }
});

// Serve the frontend
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, async () => {
  browser = await chromium.launch({ headless: true });
  console.log(`\n🎬 Douyin Video Downloader đang chạy tại: http://localhost:${PORT}\n`);
});
