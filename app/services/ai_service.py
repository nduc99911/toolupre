"""
ReupMaster Pro - AI Service
AI-powered text rewriting for descriptions, captions, and hashtags.
Supports: OpenAI (GPT) and Google Gemini.
"""
import json
import asyncio
from app.config import settings
from app import database as db


async def rewrite_text_openai(text: str, style: str = "viral",
                               language: str = "vi") -> dict:
    """Rewrite text using OpenAI API."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        system_prompt = _get_system_prompt(style, language)

        response = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Viết lại nội dung sau:\n\n{text}"}
            ],
            temperature=0.8,
            max_tokens=1000,
        )

        result_text = response.choices[0].message.content
        return _parse_ai_response(result_text)

    except Exception as e:
        return {"error": str(e)}


async def rewrite_text_gemini(text: str, style: str = "viral",
                               language: str = "vi") -> dict:
    """Rewrite text using Google Gemini API."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL)

        system_prompt = _get_system_prompt(style, language)
        full_prompt = f"{system_prompt}\n\nViết lại nội dung sau:\n\n{text}"

        response = await asyncio.to_thread(
            model.generate_content, full_prompt
        )

        result_text = response.text
        return _parse_ai_response(result_text)

    except Exception as e:
        return {"error": str(e)}


async def rewrite_text(text: str, style: str = "viral",
                       language: str = "vi") -> dict:
    """Rewrite text using configured AI provider."""
    provider = settings.AI_PROVIDER.lower()

    if provider == "openai":
        return await rewrite_text_openai(text, style, language)
    elif provider == "gemini":
        return await rewrite_text_gemini(text, style, language)
    else:
        return {"error": f"Unknown AI provider: {provider}"}


async def generate_caption(video_title: str, video_description: str = "",
                          style: str = "viral", language: str = "vi",
                          niche: str = "") -> dict:
    """Generate an engaging caption for social media post."""
    prompt = f"""Tạo caption hấp dẫn cho bài đăng video trên Facebook:
- Tiêu đề video: {video_title}
- Mô tả gốc: {video_description}
- Phong cách: {style}
- Ngôn ngữ: {'Tiếng Việt' if language == 'vi' else 'English'}
- Niche/Chủ đề: {niche or 'general'}

Yêu cầu:
1. Caption phải thu hút, gây tò mò
2. Sử dụng emoji phù hợp
3. Có call-to-action (like, share, comment)
4. Tạo 5-10 hashtag liên quan
5. Độ dài caption: 100-300 ký tự

Trả về JSON format:
{{
    "caption": "Nội dung caption...",
    "hashtags": ["#hashtag1", "#hashtag2", ...],
    "hooks": ["Hook 1", "Hook 2", "Hook 3"]
}}"""

    try:
        provider = settings.AI_PROVIDER.lower()

        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a viral social media expert. Always respond in valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,
                max_tokens=1000,
            )
            result_text = response.choices[0].message.content

        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            response = await asyncio.to_thread(
                model.generate_content, prompt
            )
            result_text = response.text
        else:
            return {"error": f"Unknown AI provider: {provider}"}

        # Try to parse JSON from response
        return _extract_json(result_text)

    except Exception as e:
        return {"error": str(e)}


async def generate_hashtags(topic: str, count: int = 10,
                           language: str = "vi") -> list[str]:
    """Generate relevant hashtags for a topic."""
    prompt = f"""Tạo {count} hashtag phổ biến và liên quan cho chủ đề: "{topic}"
Ngôn ngữ: {'Tiếng Việt' if language == 'vi' else 'English'}
Trả về dưới dạng danh sách, mỗi hashtag một dòng.
Bao gồm cả hashtag trending và hashtag niche cụ thể."""

    try:
        provider = settings.AI_PROVIDER.lower()

        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.8,
                max_tokens=500,
            )
            result_text = response.choices[0].message.content

        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            response = await asyncio.to_thread(
                model.generate_content, prompt
            )
            result_text = response.text
        else:
            return []

        # Parse hashtags
        hashtags = []
        for line in result_text.strip().split("\n"):
            line = line.strip().strip("-").strip("*").strip()
            if line.startswith("#"):
                hashtags.append(line.split()[0])  # Take only the hashtag part
            elif line:
                hashtags.append(f"#{line.replace(' ', '').replace('#', '')}")

        return hashtags[:count]

    except Exception as e:
        return []


def _get_system_prompt(style: str, language: str) -> str:
    """Get system prompt based on style."""
    lang_name = "Tiếng Việt" if language == "vi" else "English"

    style_guides = {
        "viral": f"""Bạn là chuyên gia content viral trên mạng xã hội.
Viết lại nội dung sao cho:
- Gây tò mò, thu hút ngay từ câu đầu tiên
- Sử dụng ngôn ngữ {lang_name} tự nhiên, dễ hiểu
- Thêm emoji phù hợp
- Tạo cảm xúc mạnh (ngạc nhiên, cảm động, hài hước)
- Kích thích tương tác (like, share, comment)
- Giữ nghĩa gốc nhưng dùng từ ngữ hoàn toàn khác
- Thêm hashtag liên quan""",

        "professional": f"""Bạn là chuyên gia viết content chuyên nghiệp.
Viết lại nội dung bằng {lang_name}:
- Giọng văn chuyên nghiệp, uy tín
- Rõ ràng, súc tích
- Có giá trị thông tin cao
- Giữ nghĩa gốc nhưng paraphrase hoàn toàn
- Phù hợp đăng trên các nền tảng chuyên nghiệp""",

        "funny": f"""Bạn là người viết content hài hước, dí dỏm.
Viết lại nội dung bằng {lang_name}:
- Hài hước, vui nhộn
- Sử dụng meme language phù hợp
- Thêm emoji vui
- Gây cười nhưng vẫn giữ nội dung chính
- Paraphrase hoàn toàn từ gốc""",

        "storytelling": f"""Bạn là storyteller xuất sắc.
Viết lại nội dung bằng {lang_name} dưới dạng câu chuyện:
- Hook mạnh ngay câu đầu
- Tạo suspense, tò mò
- Kết thúc bất ngờ hoặc ý nghĩa
- Dùng ngôn ngữ giàu hình ảnh
- Hoàn toàn khác biệt với bản gốc về mặt từ ngữ"""
    }

    return style_guides.get(style, style_guides["viral"])


def _parse_ai_response(text: str) -> dict:
    """Parse AI response into structured format."""
    # Try JSON first
    json_result = _extract_json(text)
    if json_result and "error" not in json_result:
        return json_result

    # Otherwise return as plain text
    lines = text.strip().split("\n")
    hashtags = [l.strip() for l in lines if l.strip().startswith("#")]

    caption = "\n".join([l for l in lines if not l.strip().startswith("#")])

    return {
        "caption": caption.strip(),
        "hashtags": hashtags,
        "original": text
    }


def _extract_json(text: str) -> dict:
    """Extract JSON from AI response text."""
    import re

    # Try to find JSON block
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find JSON object directly
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # Try the whole text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    return {"caption": text, "hashtags": []}
