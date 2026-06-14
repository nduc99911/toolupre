const fs = require('fs');

const file = 'server.js';
let content = fs.readFileSync(file, 'utf8');

// 1. Add Playwright
if (!content.includes('const { chromium } = require(\'playwright\');')) {
  content = content.replace("const fetch = require('node-fetch');", "const fetch = require('node-fetch');\nconst { chromium } = require('playwright');");
}

if (!content.includes('let browser = null;')) {
  content = content.replace("const PORT = 3000;", "const PORT = 3000;\nlet browser = null;");
}

if (!content.includes('browser = await chromium.launch')) {
  content = content.replace("app.listen(PORT, () => {", "app.listen(PORT, async () => {\n  browser = await chromium.launch({ headless: true });");
}

// 2. Replace fetchVideoInfo
const newFetchVideoInfo = `async function fetchVideoInfo(videoUrl) {
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

    const renderDataMatch = html.match(/<script id="RENDER_DATA"[^>]*>([\\s\\S]*?)<\\/script>/);
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
}`;

// 3. Replace fetchProfileVideos
const newFetchProfileVideos = `async function fetchProfileVideos(profileUrl, maxCount = 10) {
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

    console.log(\`[Profile] sec_uid: \${secUid}, requesting \${maxCount} videos\`);

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
    const renderDataMatch = html.match(/<script id="RENDER_DATA"[^>]*>([\\s\\S]*?)<\\/script>/);
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

    if (!userInfo) {
      userInfo = {
        secUid, uid: '', nickname: 'Unknown', avatar: '', signature: '',
        followerCount: 0, followingCount: 0, totalFavorited: 0, awemeCount: 0, verified: false,
      };
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
}`;

const fetchVideoInfoRegex = /async function fetchVideoInfo\(videoUrl\) \{[\s\S]*?\}\s*(?=\/\/ API endpoint to parse video)/;
const fetchProfileVideosRegex = /async function fetchProfileVideos\(profileUrl, maxCount = 10\) \{[\s\S]*?\}\s*(?=\/\/ API endpoint to scan profile)/;

content = content.replace(fetchVideoInfoRegex, newFetchVideoInfo + "\n\n");
content = content.replace(fetchProfileVideosRegex, newFetchProfileVideos + "\n\n");

fs.writeFileSync(file, content);
console.log('Successfully updated server.js with Playwright integration.');
