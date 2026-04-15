"""
ReupMaster Pro - Affiliate Automation Service
Automatically find and attach affiliate product links to video captions.
Supports: Shopee, TikTok Shop, Lazada.
"""
import re
import logging
import asyncio
from app.config import settings

logger = logging.getLogger("reupmaster.affiliate")


# ─── Affiliate Link Templates ───
AFFILIATE_PLATFORMS = {
    "shopee": {
        "name": "Shopee",
        "icon": "🛒",
        "search_url": "https://shopee.vn/search?keyword={keyword}",
        "affiliate_prefix": "https://shope.ee/",
        "example": "https://shope.ee/abc123",
    },
    "tiktok_shop": {
        "name": "TikTok Shop",
        "icon": "🎵",
        "search_url": "https://www.tiktok.com/shop/search?q={keyword}",
        "affiliate_prefix": "https://vt.tiktok.com/",
        "example": "https://vt.tiktok.com/ZSxyz789/",
    },
    "lazada": {
        "name": "Lazada",
        "icon": "🏪",
        "search_url": "https://www.lazada.vn/catalog/?q={keyword}",
        "affiliate_prefix": "https://s.lazada.vn/",
        "example": "https://s.lazada.vn/abc",
    },
}


async def generate_affiliate_caption(
    video_title: str,
    video_description: str = "",
    product_keywords: str = "",
    affiliate_link: str = "",
    style: str = "hard_sell",
    language: str = "vi",
) -> dict:
    """
    Use AI to generate a caption with embedded affiliate link & call-to-action.
    
    Args:
        video_title: Title of the video
        video_description: Original description
        product_keywords: Product-related keywords
        affiliate_link: The actual affiliate URL to embed
        style: 'hard_sell', 'soft_sell', 'review', 'unboxing'
        language: 'vi' or 'en'
    """
    style_guides = {
        "hard_sell": "Viết caption bán hàng trực tiếp, gấp gáp, tạo FOMO (sợ hết hàng/hết sale). Dùng emoji 🔥💥 nhiều. Kêu gọi mua ngay.",
        "soft_sell": "Viết caption giới thiệu sản phẩm một cách tự nhiên, như đang chia sẻ trải nghiệm cá nhân. Nhẹ nhàng, đáng tin cậy.",
        "review": "Viết caption review sản phẩm, chia sẻ ưu/nhược điểm. Chân thực, khách quan nhưng vẫn khéo léo giới thiệu link mua.",
        "unboxing": "Viết caption theo kiểu unboxing, hào hứng khui hộp. Tạo tò mò, kích thích mua.",
    }

    prompt = f"""Bạn là chuyên gia content affiliate marketing trên Facebook/TikTok.

Tiêu đề video: {video_title}
Mô tả gốc: {video_description}
Từ khóa sản phẩm: {product_keywords}
Link affiliate: {affiliate_link or '[LINK SẼ ĐƯỢC CHÈN SAU]'}
Phong cách: {style_guides.get(style, style_guides['soft_sell'])}
Ngôn ngữ: {'Tiếng Việt' if language == 'vi' else 'English'}

Yêu cầu:
1. Caption thu hút, viral, CÓ SẴN LINK sản phẩm trong nội dung
2. Có emoji phù hợp 🔥💰🛒
3. PHẢI có Call-to-Action rõ ràng (vd: "Mua ngay tại link", "Click bio", "Comment SĐT")
4. Tạo hashtag liên quan đến sản phẩm + trending
5. Nếu có link affiliate, đặt ở vị trí nổi bật
6. Thêm 1 dòng "Comment [emoji] để nhận link" (tăng engagement)

Trả về JSON:
{{
    "caption": "Nội dung caption đầy đủ, bao gồm link...",
    "first_comment": "Comment đầu tiên (chèn link ở đây nếu muốn tránh giảm reach)...",
    "hashtags": ["#hashtag1", "#hashtag2", ...],
    "cta_text": "Câu Call-to-Action chính"
}}"""

    try:
        provider = settings.AI_PROVIDER.lower()

        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a top affiliate marketing copywriter. Always respond in valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,
                max_tokens=1200,
            )
            result_text = resp.choices[0].message.content

        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            resp = await asyncio.to_thread(model.generate_content, prompt)
            result_text = resp.text
        else:
            return {"error": f"Unknown AI provider: {provider}"}

        # Parse JSON
        import json
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
            # Auto-insert affiliate link if provided
            if affiliate_link and affiliate_link not in parsed.get("caption", ""):
                parsed["caption"] += f"\n\n🛒 Mua ngay: {affiliate_link}"
            if affiliate_link and affiliate_link not in parsed.get("first_comment", ""):
                parsed["first_comment"] = f"🔗 Link sản phẩm: {affiliate_link}\n" + parsed.get("first_comment", "")
            return parsed

        return {"caption": result_text, "hashtags": [], "first_comment": ""}

    except Exception as e:
        logger.error(f"Affiliate caption error: {e}")
        return {"error": str(e)}


def build_shopee_affiliate_link(product_url: str, affiliate_id: str = "") -> str:
    """Convert a Shopee product URL to an affiliate link."""
    if not affiliate_id:
        return product_url
    # Shopee affiliate deep link format
    return f"https://shope.ee/{affiliate_id}?url={product_url}"


def extract_product_keywords(title: str, description: str = "") -> list[str]:
    """Extract likely product keywords from video title/description."""
    combined = f"{title} {description}".lower()
    
    # Common product-related terms (Vietnamese)
    product_patterns = [
        r'(kem\s+\w+)', r'(máy\s+\w+)', r'(áo\s+\w+)', r'(quần\s+\w+)',
        r'(giày\s+\w+)', r'(túi\s+\w+)', r'(đồng hồ\s*\w*)', r'(tai nghe\s*\w*)',
        r'(điện thoại\s*\w*)', r'(laptop\s*\w*)', r'(sạc\s+\w+)', r'(cáp\s+\w+)',
        r'(son\s+\w+)', r'(phấn\s+\w+)', r'(serum\s+\w+)', r'(nước hoa\s*\w*)',
        r'(ốp lưng\s*\w*)', r'(balo\s*\w*)', r'(kính\s+\w+)',
    ]
    
    keywords = []
    for pattern in product_patterns:
        matches = re.findall(pattern, combined, re.IGNORECASE)
        keywords.extend(matches)
    
    # Also split title into significant words
    words = [w for w in title.split() if len(w) > 2 and w.lower() not in 
             {'và', 'của', 'cho', 'với', 'này', 'khi', 'đến', 'hay', 'rất', 'các', 'được', 'không'}]
    
    return list(set(keywords + words[:5]))


def get_affiliate_platforms() -> list[dict]:
    """Return list of supported affiliate platforms."""
    return [
        {
            "id": k,
            "name": v["name"],
            "icon": v["icon"],
            "example": v["example"],
        }
        for k, v in AFFILIATE_PLATFORMS.items()
    ]
