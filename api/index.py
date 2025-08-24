from http.server import BaseHTTPRequestHandler
import json
import os
import re
import time
import requests
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl, urljoin
from bs4 import BeautifulSoup
from readability import Document

# ====== Optional: PRAW for reliable Reddit access ======
PRAW_AVAILABLE = False
try:
    import praw  # pip install praw
    PRAW_AVAILABLE = True
except Exception:
    PRAW_AVAILABLE = False

# ====== Config ======
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "ai-fact-checker/1.0 by anonymous")

FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
if not FACEBOOK_ACCESS_TOKEN:
    app_id = os.getenv("FACEBOOK_APP_ID")
    app_secret = os.getenv("FACEBOOK_APP_SECRET")
    if app_id and app_secret:
        # Graph oEmbed accepts "app_id|app_secret" as an access_token for public oEmbed
        FACEBOOK_ACCESS_TOKEN = f"{app_id}|{app_secret}"

# CORS + timeouts + limits
REQUEST_TIMEOUT = 20
MAX_TEXT_CHARS = 6000

STEALTH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ====== Helpers ======
def cors_headers(handler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

def _build_reddit_json_url(url):
    pu = urlparse(url)
    path = pu.path.rstrip("/")
    if not path.endswith(".json"):
        path += ".json"
    q = dict(parse_qsl(pu.query, keep_blank_values=True))
    q["raw_json"] = "1"
    return urlunparse(pu._replace(path=path, query=urlencode(q)))

def _resolve_url(base, path):
    if not path:
        return None
    return urljoin(base, path)

def _is_image_like(url):
    if not isinstance(url, str):
        return False
    pu = urlparse(url)
    pl = pu.path.lower()
    nl = pu.netloc.lower()
    if re.search(r"\.(jpg|jpeg|png|gif|webp|svg|bmp|tiff|avif)(\?|$)", pl):
        return True
    image_hosts = [
        "pbs.twimg.com","pic.twitter.com","i.redd.it","preview.redd.it","i.imgur.com","imgur.com",
        "i.ytimg.com","media.githubusercontent.com","cdn.discordapp.com","images.unsplash.com",
        "i.pinimg.com","scontent","fbcdn.net","cdninstagram.com","graph.facebook.com"
    ]
    return any(h in nl for h in image_hosts)

def _dedupe(seq):
    seen = set()
    out = []
    for x in seq:
        if x and x not in seen:
            out.append(x)
            seen.add(x)
    return out

def _clean_text(t):
    if not t:
        return ""
    t = re.sub(r"pic\.twitter\.com/\w+", "", t)
    t = re.sub(r"https?://t\.co/\w+", "", t)
    t = " ".join(t.split()).strip()
    if len(t) > MAX_TEXT_CHARS:
        t = t[:MAX_TEXT_CHARS] + "…"
    return t

def _safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return None

def get_platform_name(url):
    u = url.lower()
    if "twitter.com" in u or "x.com" in u:
        return "Twitter/X"
    if "reddit.com" in u or "redd.it" in u:
        return "Reddit"
    if "instagram.com" in u:
        return "Instagram"
    if "facebook.com" in u or "fb.com" in u or "fb.watch" in u:
        return "Facebook"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    if "tiktok.com" in u:
        return "TikTok"
    if "imgur.com" in u:
        return "Imgur"
    return "Web"

# ====== Platform extractors ======
def extract_twitter(url):
    text = ""
    imgs = []
    pu = urlparse(url)
    m = re.search(r"/status/(\d+)", pu.path)
    if not m:
        return {"text": "", "image_urls": []}
    tweet_id = m.group(1)

    # 1) Unauth tweet syndication
    try:
        api = f"https://cdn.syndication.twimg.com/widgets/tweet?id={tweet_id}&lang=en"
        r = requests.get(api, headers=STEALTH_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = _safe_json(r) or {}
            text = data.get("text", "") or ""
            for p in data.get("photos", []) or []:
                u = p.get("url")
                if _is_image_like(u):
                    imgs.append(u)
            poster = (data.get("video") or {}).get("poster")
            if _is_image_like(poster):
                imgs.append(poster)
    except Exception:
        pass

    # 2) oEmbed fallback (HTML parsing)
    if not text or not imgs:
        try:
            oembed = f"https://publish.twitter.com/oembed?url={url}"
            r = requests.get(oembed, headers=STEALTH_HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = _safe_json(r) or {}
                html = data.get("html", "")
                if html:
                    soup = BeautifulSoup(html, "lxml")
                    # text from blockquote
                    block = soup.find("blockquote")
                    if block:
                        text = text or block.get_text(" ", strip=True)
                    for img in soup.find_all("img"):
                        src = img.get("src")
                        if _is_image_like(src):
                            imgs.append(src)
        except Exception:
            pass

    return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}

def extract_reddit(url):
    """
    Prefer PRAW (OAuth). Fallback to public JSON if no creds or PRAW unavailable.
    """
    # PRAW path
    if PRAW_AVAILABLE and REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
        try:
            reddit = praw.Reddit(
                client_id=REDDIT_CLIENT_ID,
                client_secret=REDDIT_CLIENT_SECRET,
                user_agent=REDDIT_USER_AGENT,
                check_for_async=False,
            )
            submission = reddit.submission(url=url)
            title = submission.title or ""
            selftext = submission.selftext or ""
            text = f"{title}\n\n{selftext}".strip()

            imgs = []
            # Single image or link
            if submission.url and _is_image_like(submission.url):
                imgs.append(submission.url)

            # Gallery
            if getattr(submission, "is_gallery", False) and getattr(submission, "media_metadata", None):
                for meta in submission.media_metadata.values():
                    u = (meta.get("s") or {}).get("u")
                    if u:
                        u = u.replace("&amp;", "&")
                        if _is_image_like(u):
                            imgs.append(u)

            # Preview
            if getattr(submission, "preview", None):
                for im in submission.preview.get("images", []):
                    src = (im.get("source") or {}).get("url", "")
                    src = src.replace("&amp;", "&")
                    if _is_image_like(src):
                        imgs.append(src)

            return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}
        except Exception:
            # fall through to JSON
            pass

    # Public JSON fallback
    try:
        json_url = _build_reddit_json_url(url)
        r = requests.get(json_url, headers=STEALTH_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = _safe_json(r)
            if isinstance(data, list) and data and "data" in data[0]:
                children = data[0]["data"].get("children", [])
                if children:
                    post = children[0].get("data", {}) or {}
                    title = post.get("title", "") or ""
                    selftext = post.get("selftext", "") or ""
                    text = f"{title}\n\n{selftext}".strip()

                    imgs = []
                    direct = post.get("url_overridden_by_dest") or post.get("url")
                    if _is_image_like(direct):
                        imgs.append(direct)

                    if "preview" in post:
                        for im in post["preview"].get("images", []):
                            src = (im.get("source") or {}).get("url", "")
                            src = src.replace("&amp;", "&")
                            if _is_image_like(src):
                                imgs.append(src)

                    if "media_metadata" in post:
                        for meta in post["media_metadata"].values():
                            if meta.get("e") == "Image":
                                u = (meta.get("s") or {}).get("u", "")
                                u = u.replace("&amp;", "&")
                                if _is_image_like(u):
                                    imgs.append(u)

                    return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}
    except Exception:
        pass

    return {
        "text": "",
        "image_urls": [],
    }

def extract_instagram(url):
    """
    Instagram oEmbed via Graph API requires FACEBOOK_ACCESS_TOKEN.
    Returns title/author and thumbnail if available.
    """
    text = ""
    imgs = []
    if not FACEBOOK_ACCESS_TOKEN:
        return {"text": "", "image_urls": []}

    try:
        api = "https://graph.facebook.com/v17.0/instagram_oembed"
        r = requests.get(api, params={"url": url, "access_token": FACEBOOK_ACCESS_TOKEN}, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = _safe_json(r) or {}
            title = data.get("title") or ""
            author = data.get("author_name") or ""
            text = (title or "") + (f" (by {author})" if author else "")
            thumb = data.get("thumbnail_url")
            if _is_image_like(thumb):
                imgs.append(thumb)
    except Exception:
        pass
    return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}

def extract_facebook(url):
    """
    Facebook oEmbed requires FACEBOOK_ACCESS_TOKEN.
    """
    text = ""
    imgs = []
    if not FACEBOOK_ACCESS_TOKEN:
        return {"text": "", "image_urls": []}

    try:
        # Try post oEmbed first
        api = "https://graph.facebook.com/v17.0/oembed_post"
        r = requests.get(api, params={"url": url, "access_token": FACEBOOK_ACCESS_TOKEN}, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            # Fallback page oEmbed for non-post URLs
            api = "https://graph.facebook.com/v17.0/oembed_page"
            r = requests.get(api, params={"url": url, "access_token": FACEBOOK_ACCESS_TOKEN}, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = _safe_json(r) or {}
            html = data.get("html", "")
            if html:
                soup = BeautifulSoup(html, "lxml")
                text = soup.get_text(" ", strip=True)
                for img in soup.find_all("img"):
                    src = img.get("src")
                    if _is_image_like(src):
                        imgs.append(src)
            thumb = data.get("thumbnail_url")
            if _is_image_like(thumb):
                imgs.append(thumb)
    except Exception:
        pass
    return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}

def extract_youtube(url):
    text = ""
    imgs = []
    try:
        r = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, headers=STEALTH_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = _safe_json(r) or {}
            title = data.get("title") or ""
            author = data.get("author_name") or ""
            text = f"{title} (by {author})" if title and author else (title or author)
            # derive thumbnail if missing
            thumb = data.get("thumbnail_url")
            if _is_image_like(thumb):
                imgs.append(thumb)
            else:
                # Try to derive from video id
                m = re.search(r"(?:v=|/embed/|youtu\.be/)([A-Za-z0-9_-]{6,})", url)
                if m:
                    vid = m.group(1)
                    imgs.append(f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg")
    except Exception:
        pass
    return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}

def extract_tiktok(url):
    text = ""
    imgs = []
    try:
        r = requests.get("https://www.tiktok.com/oembed", params={"url": url}, headers=STEALTH_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = _safe_json(r) or {}
            title = data.get("title") or ""
            author = data.get("author_name") or ""
            text = f"{title} (by {author})" if title and author else (title or author)
            thumb = data.get("thumbnail_url")
            if _is_image_like(thumb):
                imgs.append(thumb)
    except Exception:
        pass
    return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}

def extract_generic(url):
    text = ""
    imgs = []
    try:
        r = requests.get(url, headers=STEALTH_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            doc = Document(r.text)
            text = BeautifulSoup(doc.summary(), "lxml").get_text(" ", strip=True)

            soup = BeautifulSoup(r.text, "lxml")
            # OG/Twitter cards
            for prop in ["og:description", "description"]:
                m = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
                if m and m.get("content"):
                    # Prefer description only if our readability text is too thin
                    if not text or len(text) < 120:
                        text = m["content"]

            for prop in ["og:image", "twitter:image", "image"]:
                m = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
                if m and m.get("content"):
                    imgs.append(m["content"])

            # Inline images as fallback (first 3)
            if not imgs:
                for img in soup.find_all("img", limit=3):
                    src = img.get("src")
                    if src:
                        absu = _resolve_url(url, src)
                        if _is_image_like(absu):
                            imgs.append(absu)
    except Exception:
        pass
    return {"text": _clean_text(text), "image_urls": _dedupe(imgs)}

def extract_content_from_url(url):
    """
    Multi-platform extractor that returns {"text": str, "image_urls": [..]}.
    """
    if not url or not isinstance(url, str):
        return {"text": "", "image_urls": []}

    netloc = urlparse(url).netloc.lower()

    try:
        if "twitter.com" in netloc or "x.com" in netloc:
            return extract_twitter(url)
        if "reddit.com" in netloc or "redd.it" in netloc:
            return extract_reddit(url)
        if "instagram.com" in netloc:
            return extract_instagram(url)
        if "facebook.com" in netloc or "fb.com" in netloc or "fb.watch" in netloc:
            return extract_facebook(url)
        if "youtube.com" in netloc or "youtu.be" in netloc:
            return extract_youtube(url)
        if "tiktok.com" in netloc:
            return extract_tiktok(url)
        # fallback
        return extract_generic(url)
    except Exception as e:
        return {"text": f"Extraction failed: {str(e)}", "image_urls": []}

# ====== Fact-checking ======
def clean_json_response(content):
    # Strip code fences & "json " prefixes
    content = re.sub(r"```(json)?\n?", "", content).strip()
    content = re.sub(r"```", "", content).strip()
    content = re.sub(r"^json\s+", "", content, flags=re.IGNORECASE).strip()
    # Extract first {...} block
    m = re.search(r"\{.*\}", content, re.DOTALL)
    return m.group(0) if m else content

def fact_check_text(text):
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500

    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}

    prompt = f"""
Analyze this text for factual claims:

TEXT: {text}

Return ONLY a JSON object with NO markdown formatting:
{{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 85, "explanation": "Your analysis here", "sources": ["https://example.com"]}}
"""

    try:
        response = requests.post(
            PERPLEXITY_URL,
            headers=headers,
            json={
                "model": "sonar-pro",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
            },
            timeout=REQUEST_TIMEOUT + 10,
        )

        if response.status_code == 200:
            result = _safe_json(response) or {}
            content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            try:
                parsed = json.loads(clean_json_response(content))
            except Exception:
                parsed = {
                    "verdict": "INSUFFICIENT EVIDENCE",
                    "confidence": 70,
                    "explanation": f"Got non-JSON response: {content}",
                    "sources": [],
                }

            return {
                "fact_check_results": [{
                    "claim": (text[:200] + "...") if len(text) > 200 else text,
                    "result": parsed,
                }],
                "original_text": text,
                "claims_found": 1,
                "timestamp": time.time(),
            }, 200

        return {"error": f"API request failed: {response.status_code}"}, 500
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}, 500

def fact_check_image(image_data_url, image_url):
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500

    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}

    # OpenAI-compatible vision content structure (Perplexity accepts this)
    msg_content = [{
        "type": "text",
        "text": (
            "Analyze this image for factual claims. Look for:\n"
            "1) Any text, quotes, or statements\n"
            "2) Charts, graphs, numbers\n"
            "3) Names, dates, locations or attributions\n\n"
            "Return ONLY a JSON object (no code fences): "
            '{"verdict":"TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS","confidence":85,"explanation":"...","sources":["url1"]}'
        )
    }]

    if image_data_url:
        msg_content.append({"type": "image_url", "image_url": {"url": image_data_url}})
    elif image_url:
        msg_content.append({"type": "image_url", "image_url": {"url": image_url}})

    payload = {"model": "sonar-pro", "messages": [{"role": "user", "content": msg_content}], "max_tokens": 800}

    try:
        response = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT + 20)
        if response.status_code != 200:
            return {"error": f"Analysis failed: HTTP {response.status_code}"}, 500

        content = (_safe_json(response) or {}).get("choices", [{}])[0].get("message", {}).get("content", "")

        try:
            parsed = json.loads(clean_json_response(content))
        except Exception:
            parsed = {
                "verdict": "INSUFFICIENT EVIDENCE",
                "confidence": 70,
                "explanation": f"Analysis returned unexpected format: {content}",
                "sources": [],
            }

        result = {
            "fact_check_results": [{
                "claim": "Image Analysis",
                "result": {
                    "verdict": parsed.get("verdict", "INSUFFICIENT EVIDENCE"),
                    "confidence": parsed.get("confidence", 70),
                    "explanation": parsed.get("explanation", "Analysis completed"),
                    "sources": parsed.get("sources", []),
                },
            }],
            "claims_found": 0 if parsed.get("verdict") == "NO FACTUAL CLAIMS" else 1,
            "timestamp": time.time(),
            "source_url": image_url or None,
        }
        return result, 200
    except Exception as e:
        return {"error": f"Analysis failed: {str(e)}"}, 500

def fact_check_url_with_images(url):
    try:
        content = extract_content_from_url(url)
        text = (content.get("text") or "").strip()
        image_urls = content.get("image_urls") or []

        all_results = []
        image_analysis = []

        if text and len(text) > 10:
            text_result, sc = fact_check_text(text)
            if sc == 200 and isinstance(text_result, dict):
                for r in text_result.get("fact_check_results", []):
                    r["source_type"] = "text"
                    all_results.append(r)

        for u in image_urls:
            img_result, sc = fact_check_image("", u)
            if sc == 200 and isinstance(img_result, dict):
                checks = img_result.get("fact_check_results", [])
                image_analysis.append({
                    "image_url": u,
                    "claims_found": len(checks),
                    "fact_check_results": checks,
                })
                for c in checks:
                    cc = c.copy()
                    cc["source_type"] = "image"
                    cc["image_url"] = u
                    all_results.append(cc)
            else:
                image_analysis.append({"image_url": u, "claims_found": 0, "fact_check_results": []})

        platform = get_platform_name(url)

        return {
            "original_text": text,
            "fact_check_results": all_results,
            "image_analysis_results": image_analysis,
            "claims_found": len(all_results),
            "images_processed": len(image_analysis),
            "timestamp": time.time(),
            "source_url": url,
            "platform": platform,
        }, 200
    except Exception as e:
        return {"error": f"URL analysis failed: {str(e)}"}, 500

# ====== HTTP handler ======
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            payload = {
                "status": "healthy",
                "timestamp": time.time(),
                "api_key_set": bool(PERPLEXITY_API_KEY),
                "reddit_oauth": bool(REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET and PRAW_AVAILABLE),
                "fb_token": bool(FACEBOOK_ACCESS_TOKEN),
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            cors_headers(self)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            cors_headers(self)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length or 0)
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            cors_headers(self)
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            return

        status, resp = 500, {"error": "Unknown error"}
        if self.path == "/api/fact-check":
            text = (data.get("text") or "").strip()
            url = (data.get("url") or "").strip()
            if not text and not url:
                status, resp = 400, {"error": "No text or URL provided"}
            else:
                if url:
                    resp, status = fact_check_url_with_images(url)
                else:
                    resp, status = fact_check_text(text)

        elif self.path == "/api/fact-check-image":
            image_data_url = data.get("image_data_url", "")
            image_url = data.get("image_url", "")
            if not image_data_url and not image_url:
                status, resp = 400, {"error": "No image provided"}
            else:
                resp, status = fact_check_image(image_data_url, image_url)
        else:
            status, resp = 404, {"error": "Endpoint not found"}

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        cors_headers(self)
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        cors_headers(self)
        self.end_headers()