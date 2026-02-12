import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl, urljoin

import requests
from bs4 import BeautifulSoup
from readability import Document

PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

BROWSER_HEADERS = {
    **DEFAULT_HEADERS,
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

BOILERPLATE_MARKERS = [
    "enable javascript",
    "javascript is not available",
    "please enable cookies",
    "sign in",
    "you’re being redirected",
    "you are being redirected",
    "access denied",
    "verify you are a human",
]

MAX_TEXT_CHARS = 12000
MAX_CLAIMS = 6
MAX_IMAGE_CLAIMS = 4
MAX_IMAGES_TO_ANALYZE = 1


def _try_parse_json_block(s: Optional[str]) -> Optional[dict]:
    if s is None:
        return None
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.I)
        s = re.sub(r"\s*```$", "", s)
    if s.lower().startswith("json "):
        s = s[5:].strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except Exception:
            return None
    return None


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, flags=re.I):
        url = f"https://{url}"
    return url


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _clean_text(text: str) -> str:
    return " ".join((text or "").split())


def _truncate(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _resolve_url(base: str, path: str) -> Optional[str]:
    if not path:
        return None
    return urljoin(base, path)


def _is_image_like(url: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    if re.search(r"\.(jpg|jpeg|png|gif|webp|svg)$", parsed.path, re.I):
        return True
    return any(host in parsed.netloc for host in [
        "pbs.twimg.com",
        "i.redd.it",
        "preview.redd.it",
        "external-preview.redd.it",
        "i.imgur.com",
        "imgur.com",
        "cdninstagram.com",
        "fbcdn.net",
        "media.tumblr.com",
        "media.discordapp.net",
    ])


def _detect_platform(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if "twitter.com" in netloc or "x.com" in netloc:
        return "twitter"
    if "reddit.com" in netloc or "redd.it" in netloc:
        return "reddit"
    if "tiktok.com" in netloc:
        return "tiktok"
    if "youtube.com" in netloc or "youtu.be" in netloc:
        return "youtube"
    if "instagram.com" in netloc:
        return "instagram"
    if "facebook.com" in netloc or "fb.com" in netloc:
        return "facebook"
    return "generic"


def _extract_meta_text(soup: BeautifulSoup) -> Tuple[str, str]:
    title = ""
    description = ""

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

    og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()
    else:
        tw_desc = soup.find("meta", attrs={"name": "twitter:description"})
        if tw_desc and tw_desc.get("content"):
            description = tw_desc["content"].strip()

    return title, description


def _extract_meta_images(soup: BeautifulSoup, base_url: str) -> List[str]:
    images = []
    for prop in ["og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"]:
        meta = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if meta and meta.get("content"):
            images.append(_resolve_url(base_url, meta["content"]))
    return images


def _extract_jsonld(soup: BeautifulSoup) -> List[dict]:
    items = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, list):
            items.extend([d for d in data if isinstance(d, dict)])
        elif isinstance(data, dict):
            items.append(data)
    return items


def _extract_jsonld_text(items: List[dict]) -> str:
    texts = []
    for item in items:
        for key in ["articleBody", "text", "description", "headline", "name"]:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
        if isinstance(item.get("mainEntityOfPage"), dict):
            name = item["mainEntityOfPage"].get("name")
            if isinstance(name, str) and name.strip():
                texts.append(name.strip())
    return _clean_text(" ".join(texts))


def _extract_jsonld_images(items: List[dict]) -> List[str]:
    images: List[str] = []
    for item in items:
        for key in ["image", "thumbnailUrl"]:
            value = item.get(key)
            if isinstance(value, str):
                images.append(value)
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, str):
                        images.append(v)
            elif isinstance(value, dict):
                url = value.get("url") or value.get("contentUrl")
                if isinstance(url, str):
                    images.append(url)
    return images


def _extract_body_text(html: str) -> str:
    doc = Document(html)
    summary_html = doc.summary()
    soup = BeautifulSoup(summary_html, "lxml")
    text = soup.get_text(separator=" ", strip=True)
    if len(text) < 200:
        full = BeautifulSoup(html, "lxml")
        text = full.get_text(separator=" ", strip=True)
    return _clean_text(text)


def _looks_blocked(text: str) -> bool:
    if not text:
        return True
    lowered = text.lower()
    return len(text) < 200 or any(marker in lowered for marker in BOILERPLATE_MARKERS)


def _fetch_html(url: str) -> Tuple[str, str, str]:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    return resp.text, resp.url, content_type


def _fetch_jina_text(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        query = f"?{parsed.query}" if parsed.query else ""
        wrapped = f"https://r.jina.ai/{parsed.scheme}://{parsed.netloc}{parsed.path}{query}"
        resp = requests.get(wrapped, headers=DEFAULT_HEADERS, timeout=14)
        if resp.status_code == 200 and len(resp.text.strip()) > 200:
            return _clean_text(resp.text)
    except Exception:
        return None
    return None


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    deduped = []
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _has_claim_signal(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    # Remove noisy tokens that are common in social posts but not claims.
    t = re.sub(r"https?://\\S+|pic\\.twitter\\.com/\\S+|@\\w+|#\\w+", " ", t)
    t = _clean_text(t)
    words = t.split()
    if len(words) < 6:
        return False
    if re.search(
        r"\b(is|are|was|were|has|have|had|will|won|lost|died|born|founded|"
        r"announced|said|says|claims|reports|files|accused|convicted|acquitted|"
        r"killed|arrested|sentenced|caused|proved|debunked)\b",
        t,
    ):
        return True
    if re.search(r"\b\d{1,4}([.,]\d+)?%?\b", t):
        return True
    return False


def _extract_images_from_html(soup: BeautifulSoup, base_url: str) -> List[str]:
    images: List[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            srcset = img.get("srcset")
            if srcset:
                parts = [p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()]
                if parts:
                    src = parts[-1]
        if src:
            images.append(_resolve_url(base_url, src))
    return images


def _image_detection_info(url: str, text: str, image_urls: List[str]) -> Dict[str, Any]:
    image_patterns = [
        r"pic\.twitter\.com",
        r"pbs\.twimg\.com",
        r"i\.redd\.it",
        r"preview\.redd\.it",
        r"imgur\.com",
        r"\.(jpg|jpeg|png|gif|webp|svg)",
        r"redditmedia\.com",
        r"redditstatic\.com",
        r"external-preview\.redd\.it",
        r"images\.redd\.it",
        r"media\.redd\.it",
    ]
    url_has_images = any(re.search(p, url, re.IGNORECASE) for p in image_patterns)
    text_has_images = any(re.search(p, text or "", re.IGNORECASE) for p in image_patterns)
    image_detected = bool(image_urls) or url_has_images or text_has_images
    message = ""
    if image_detected and not image_urls:
        message = (
            "Images detected in this post, but they cannot be accessed directly from the URL. "
            "Please provide a screenshot of the image for visual fact-checking."
        )
    return {
        "has_images": bool(image_urls),
        "image_detected": image_detected,
        "message": message,
    }


def _build_reddit_json_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path.endswith(".json"):
        path += ".json"
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    q["raw_json"] = "1"
    return urlunparse(parsed._replace(path=path, query=urlencode(q)))


def _extract_twitter(url: str) -> Optional[Dict[str, Any]]:
    match = re.search(r"/status/(\d+)", url)
    if not match:
        return None
    tweet_id = match.group(1)

    def _clean_media_url(media_url: Optional[str]) -> Optional[str]:
        if not media_url:
            return None
        # Prefer full-size images from pbs.twimg.com
        if "pbs.twimg.com" in media_url and "?" not in media_url:
            return f"{media_url}?format=jpg&name=orig"
        return media_url

    def _pick_screen_name(data: Dict[str, Any]) -> Optional[str]:
        if isinstance(data.get("user"), dict) and data["user"].get("screen_name"):
            return data["user"]["screen_name"]
        try:
            core = data.get("core", {})
            user = core.get("user_results", {}).get("result", {})
            legacy = user.get("legacy", {})
            return legacy.get("screen_name")
        except Exception:
            return None

    def _pick_text(data: Dict[str, Any]) -> str:
        text = data.get("text") or data.get("full_text") or ""
        if text:
            return text
        note = None
        if isinstance(data.get("note_tweet"), dict):
            note = data["note_tweet"].get("text")
        if not note:
            note = data.get("note_tweet_results", {}).get("result", {}).get("text")
        return note or ""

    def _sanitize_twitter_text(text: str) -> str:
        text = _clean_text(text or "")
        # oEmbed often appends author/date after an em dash.
        if " — " in text:
            text = text.split(" — ", 1)[0].strip()
        text = re.sub(r"\s*https?://t\.co/\w+\s*$", "", text, flags=re.I)
        text = re.sub(r"\s*pic\.twitter\.com/\w+\s*$", "", text, flags=re.I)
        return _clean_text(text)

    best_text = ""
    best_title = "Twitter/X post"
    images: List[str] = []

    def _merge_candidate(text: str, title: str, candidate_images: List[str]) -> None:
        nonlocal best_text, best_title, images
        text = _sanitize_twitter_text(text)
        if text and not best_text:
            best_text = text
        if title and best_title == "Twitter/X post":
            best_title = title
        for media_url in candidate_images:
            cleaned = _clean_media_url(media_url)
            if cleaned:
                images.append(cleaned)
        images = _dedupe(images)

    try:
        # Newer syndication endpoint with richer media details
        result_url = "https://cdn.syndication.twimg.com/tweet-result"
        resp = requests.get(
            result_url,
            params={"id": tweet_id, "lang": "en"},
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = _pick_text(data)
            screen_name = _pick_screen_name(data)
            title = f"Post by @{screen_name}" if screen_name else "Twitter/X post"
            candidate_images: List[str] = []
            for media in data.get("mediaDetails", []) or []:
                media_type = (media.get("type") or "").lower()
                if media_type in {"photo", "image"}:
                    media_url = media.get("media_url_https") or media.get("media_url")
                    if media_url:
                        candidate_images.append(media_url)
                elif media_type in {"video", "animated_gif"}:
                    preview = media.get("media_url_https") or media.get("media_url") or media.get("preview_image_url")
                    if preview:
                        candidate_images.append(preview)
            if not candidate_images:
                for photo in data.get("photos", []) or []:
                    if photo.get("url"):
                        candidate_images.append(photo.get("url"))
            if not candidate_images and isinstance(data.get("extended_entities"), dict):
                for media in data["extended_entities"].get("media", []) or []:
                    media_url = media.get("media_url_https") or media.get("media_url")
                    if media_url:
                        candidate_images.append(media_url)
            _merge_candidate(text, title, candidate_images)
    except Exception:
        pass

    try:
        api_url = "https://cdn.syndication.twimg.com/widgets/tweet"
        resp = requests.get(api_url, params={"id": tweet_id, "lang": "en"}, headers=DEFAULT_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            text = data.get("text") or data.get("full_text") or ""
            user = data.get("user") or {}
            title = f"Post by @{user.get('screen_name', 'user')}" if user else "Twitter/X post"
            candidate_images: List[str] = []
            for photo in data.get("photos", []) or []:
                if photo.get("url"):
                    candidate_images.append(photo.get("url"))
            if data.get("video") and data["video"].get("poster"):
                candidate_images.append(data["video"]["poster"])
            _merge_candidate(text, title, candidate_images)
    except Exception:
        pass

    # Critical fallback for X media extraction when syndication lacks images.
    proxy = _extract_twitter_via_proxy(url)
    if proxy:
        _merge_candidate(
            proxy.get("text", ""),
            proxy.get("title", "Twitter/X post"),
            proxy.get("images", []),
        )

    try:
        oembed = requests.get(
            "https://publish.twitter.com/oembed",
            params={"url": url},
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
        if oembed.status_code == 200:
            data = oembed.json()
            html = data.get("html", "")
            text = BeautifulSoup(html, "lxml").get_text(" ", strip=True) if html else data.get("title", "")
            _merge_candidate(text, data.get("author_name") or "Twitter/X post", [])
    except Exception:
        pass

    if best_text or images:
        return {"text": best_text, "title": best_title, "images": images}

    return None


def _extract_twitter_media_from_jina(url: str) -> List[str]:
    """Best-effort media URL extraction from Jina text for X posts."""
    try:
        jina_text = _fetch_jina_text(url)
        if not jina_text:
            return []
        media_urls = re.findall(r"https?://pbs\\.twimg\\.com/[^\\s)\\]}\"']+", jina_text)
        cleaned = []
        for u in media_urls:
            if "pbs.twimg.com" in u and "?" not in u:
                u = f"{u}?format=jpg&name=orig"
            cleaned.append(u)
        return _dedupe(cleaned)
    except Exception:
        return []


def _extract_twitter_via_proxy(url: str) -> Optional[Dict[str, Any]]:
    """Fallback to a public X proxy that exposes media URLs."""
    match = re.search(r"/status/(\d+)", url)
    if not match:
        return None
    tweet_id = match.group(1)
    try:
        proxy_url = f"https://api.fxtwitter.com/i/status/{tweet_id}"
        resp = requests.get(proxy_url, headers=DEFAULT_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        tweet = data.get("tweet") or {}
        text = tweet.get("text") or tweet.get("raw_text", {}).get("text") or ""
        author = tweet.get("author") or {}
        title = f"Post by @{author.get('screen_name')}" if author.get("screen_name") else "Twitter/X post"
        images = []
        media = tweet.get("media") or {}
        for photo in media.get("photos", []) or []:
            if photo.get("url"):
                images.append(photo["url"])
        for item in media.get("all", []) or []:
            if item.get("type") == "photo" and item.get("url"):
                images.append(item["url"])
        return {"text": text, "title": title, "images": _dedupe(images)}
    except Exception:
        return None


def _extract_reddit(url: str) -> Optional[Dict[str, Any]]:
    try:
        json_url = _build_reddit_json_url(url)
        resp = requests.get(json_url, headers=BROWSER_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        post = data[0]["data"]["children"][0]["data"]
        title = post.get("title", "")
        body = post.get("selftext", "")
        text = _clean_text(f"{title} {body}")
        images: List[str] = []
        if post.get("url_overridden_by_dest") and _is_image_like(post["url_overridden_by_dest"]):
            images.append(post["url_overridden_by_dest"])
        preview = post.get("preview", {}).get("images", [])
        for img in preview:
            source = img.get("source", {}).get("url")
            if source:
                images.append(source.replace("&amp;", "&"))
        media_meta = post.get("media_metadata") or {}
        for media in media_meta.values():
            if media.get("e") == "Image" and media.get("s"):
                src = media["s"].get("u") or media["s"].get("gif")
                if src:
                    images.append(src.replace("&amp;", "&"))
        return {"text": text, "title": title, "images": images}
    except Exception:
        return None


def _extract_oembed(url: str, endpoint: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(endpoint, params={"url": url, "format": "json"}, headers=DEFAULT_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        text = data.get("title") or data.get("author_name") or ""
        images = []
        thumb = data.get("thumbnail_url")
        if thumb:
            images.append(thumb)
        return {"text": text, "title": data.get("title") or "", "images": images}
    except Exception:
        return None


def extract_content_from_url(url: str) -> Dict[str, Any]:
    url = normalize_url(url)
    if not is_valid_url(url):
        raise ValueError("Invalid URL. Only http(s) URLs are supported.")

    if _is_image_like(url):
        return {
            "text": "",
            "title": "",
            "image_urls": [url],
            "image_detection_info": _image_detection_info(url, "", [url]),
        }

    platform = _detect_platform(url)
    extracted: Optional[Dict[str, Any]] = None

    if platform == "twitter":
        extracted = _extract_twitter(url)
    elif platform == "reddit":
        extracted = _extract_reddit(url)
    elif platform == "tiktok":
        extracted = _extract_oembed(url, "https://www.tiktok.com/oembed")
    elif platform == "youtube":
        extracted = _extract_oembed(url, "https://www.youtube.com/oembed")

    text_content = ""
    title = ""
    image_urls: List[str] = []
    prefer_extracted = False

    if extracted:
        text_content = extracted.get("text", "") or ""
        title = extracted.get("title", "") or ""
        image_urls.extend(extracted.get("images", []) or [])
        if platform == "twitter" and (text_content or image_urls):
            prefer_extracted = True
    if platform == "twitter":
        # Avoid generic HTML/Jina fallbacks for X posts to prevent unrelated content.
        prefer_extracted = True

    html = ""
    content_type = ""
    final_url = url

    if not prefer_extracted and (not text_content or len(text_content.strip()) < 80):
        try:
            html, final_url, content_type = _fetch_html(url)
        except Exception:
            html = ""

    if html:
        soup = BeautifulSoup(html, "lxml")
        meta_title, meta_desc = _extract_meta_text(soup)
        title = title or meta_title

        jsonld_items = _extract_jsonld(soup)
        jsonld_text = _extract_jsonld_text(jsonld_items)

        body_text = _extract_body_text(html)
        if not prefer_extracted and (not text_content or len(text_content.strip()) < 80):
            if not _looks_blocked(body_text):
                text_content = body_text
            elif jsonld_text:
                text_content = jsonld_text
            elif meta_desc:
                text_content = meta_desc

        image_urls.extend(_extract_meta_images(soup, final_url))
        image_urls.extend(_extract_jsonld_images(jsonld_items))
        image_urls.extend(_extract_images_from_html(soup, final_url))

    text_content = _clean_text(text_content)

    if not text_content and title and platform != "twitter":
        text_content = title

    if not prefer_extracted and (_looks_blocked(text_content) or not text_content):
        jina_text = _fetch_jina_text(url)
        if jina_text:
            text_content = jina_text

    if platform == "twitter" and not image_urls:
        image_urls.extend(_extract_twitter_media_from_jina(url))

    text_content = _truncate(text_content, MAX_TEXT_CHARS)

    image_urls = _dedupe([img for img in image_urls if img])
    image_urls = [img for img in image_urls if _is_image_like(img)]

    image_detection_info = _image_detection_info(url, text_content, image_urls)

    return {
        "text": text_content or "",
        "title": title or "",
        "image_urls": image_urls[:10],
        "image_detection_info": image_detection_info,
    }


class FactChecker:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or PERPLEXITY_API_KEY
        if not self.api_key:
            raise ValueError("PERPLEXITY_API_KEY is not set")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post_perplexity(self, payload: Dict[str, Any], retries: int = 3) -> Optional[requests.Response]:
        """Retry transient upstream errors (especially rate limits)."""
        last_response: Optional[requests.Response] = None
        for attempt in range(retries):
            try:
                response = requests.post(
                    PERPLEXITY_URL,
                    headers=self.headers,
                    json=payload,
                    timeout=30,
                )
                last_response = response
                if response.status_code == 200:
                    return response
                if response.status_code not in {429, 500, 502, 503, 504}:
                    return response
            except requests.RequestException:
                response = None
            if attempt < retries - 1:
                time.sleep(1.2 * (attempt + 1))
        return last_response

    def extract_claims(self, text: str, max_claims: int = MAX_CLAIMS) -> List[str]:
        if not text:
            return []
        clipped = _truncate(text, 6000)
        prompt = (
            "Extract up to {max_claims} factual claims EXPLICITLY stated in this text. "
            "Do not infer, assume, or use outside knowledge. "
            "Do not generate claims about people/entities unless directly asserted in the text. "
            "Return ONLY a numbered list. If there are no factual claims, reply with EXACTLY 'NONE'.\n\n"
            "Text: {text}"
        ).format(max_claims=max_claims, text=clipped)

        payload = {
            "model": "sonar-pro",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 350,
        }
        response = self._post_perplexity(payload)
        if response is None or response.status_code != 200:
            return []
        content = response.json()["choices"][0]["message"]["content"]
        normalized = re.sub(r"[\s\.\!\:]+", " ", content.strip().lower()).strip()
        if normalized in {"none", "no claims", "no factual claims"}:
            return []
        claims = []
        for line in content.split("\n"):
            line = line.strip().lstrip("-*")
            if re.match(r"^\d+[\).]", line):
                line = re.sub(r"^\d+[\).]\s*", "", line).strip()
            # Defensive filter in case model returns prose instead of list.
            if line.lower() in {"none", "no claims", "no factual claims"}:
                continue
            if line:
                claims.append(line)
        return claims[:max_claims]

    def fact_check_claim(self, claim: str) -> Dict[str, Any]:
        prompt = (
            "Fact-check this claim with high accuracy. Provide:\n"
            "1. Verdict (TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE)\n"
            "2. Confidence level (0-100%)\n"
            "3. Brief explanation (2-3 sentences)\n"
            "4. Key sources used as a list of canonical URLs. Each source MUST be a full http(s) URL. "
            "Do not include reference numbers or titles, only URLs.\n\n"
            "Claim: {claim}\n\n"
            "Format your response as JSON with keys: verdict, confidence, explanation, sources"
        ).format(claim=claim)

        payload = {
            "model": "sonar-pro",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
        }
        response = self._post_perplexity(payload)

        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "no-response"
            return {
                "verdict": "ERROR",
                "confidence": 0,
                "explanation": f"Failed to verify claim (upstream status: {status})",
                "sources": [],
            }

        content = response.json()["choices"][0]["message"]["content"]
        parsed = _try_parse_json_block(content)
        if parsed is not None:
            urls: List[str] = []
            if isinstance(parsed.get("sources"), list):
                for item in parsed["sources"]:
                    if isinstance(item, str) and re.match(r"^https?://", item.strip(), flags=re.I):
                        urls.append(item.strip())
            if not urls and isinstance(parsed.get("explanation"), str):
                urls = re.findall(r"https?://[^\s)\]}]+", parsed["explanation"], flags=re.I)
            if urls:
                parsed["sources"] = urls[:5]
            return {
                "verdict": parsed.get("verdict", "INSUFFICIENT EVIDENCE"),
                "confidence": int(parsed.get("confidence", 75)),
                "explanation": parsed.get("explanation", "Analysis completed"),
                "sources": parsed.get("sources", []),
            }

        urls = re.findall(r"https?://[^\s)\]}]+", content, flags=re.I)
        return {
            "verdict": "ANALYSIS COMPLETE",
            "confidence": 75,
            "explanation": content,
            "sources": urls[:5] if urls else ["Perplexity Sonar Analysis"],
        }

    def extract_image_claims(self, image_url: Optional[str], image_data_url: Optional[str], max_claims: int = MAX_IMAGE_CLAIMS) -> List[str]:
        if not image_url and not image_data_url:
            return []
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Analyze this image. Extract all factual claims that a third-party could verify. "
                            "Return ONLY the claims as a numbered list. If none, respond with 'NONE'."
                        ),
                    }
                ],
            }
        ]
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        else:
            messages[0]["content"].append({"type": "image_url", "image_url": image_url})

        payload = {
            "model": "sonar-pro",
            "messages": messages,
            "max_tokens": 500,
        }
        response = self._post_perplexity(payload)
        if response is None or response.status_code != 200:
            return []
        content = response.json()["choices"][0]["message"]["content"]
        normalized = content.strip().lower()
        if normalized in {"none", "no claims", "no factual claims"}:
            return []
        claims = []
        for line in content.split("\n"):
            line = line.strip().lstrip("-*")
            if re.match(r"^\d+[\).]", line):
                line = re.sub(r"^\d+[\).]\s*", "", line).strip()
            if line:
                claims.append(line)
        return claims[:max_claims]


def _get_checker() -> Optional[FactChecker]:
    try:
        return FactChecker()
    except Exception:
        return None


def fact_check_text_input(text: str) -> Tuple[Dict[str, Any], int]:
    checker = _get_checker()
    if checker is None:
        return {"error": "PERPLEXITY_API_KEY not configured"}, 500
    text = _clean_text(text)
    if not text:
        return {"error": "No text provided"}, 400

    claims = checker.extract_claims(text)
    if not claims and len(text.split()) >= 6:
        # Fallback keeps UX predictable when claim extraction is too strict.
        claims = [text]

    results = []
    for claim in claims:
        if claim.strip():
            results.append({"claim": claim, "result": checker.fact_check_claim(claim)})

    return {
        "original_text": text,
        "claims_found": len(results),
        "fact_check_results": results,
        "timestamp": time.time(),
    }, 200


def fact_check_image_input(image_data_url: Optional[str], image_url: Optional[str]) -> Tuple[Dict[str, Any], int]:
    checker = _get_checker()
    if checker is None:
        return {"error": "PERPLEXITY_API_KEY not configured"}, 500

    claims = checker.extract_image_claims(image_url=image_url, image_data_url=image_data_url)
    results = []
    for claim in claims:
        if claim.strip():
            results.append({"claim": claim, "result": checker.fact_check_claim(claim)})

    return {
        "original_image": "data_url" if image_data_url else image_url,
        "claims_found": len(results),
        "fact_check_results": results,
        "timestamp": time.time(),
        "source_url": image_url or None,
    }, 200


def fact_check_url_input(url: str) -> Tuple[Dict[str, Any], int]:
    checker = _get_checker()
    if checker is None:
        return {"error": "PERPLEXITY_API_KEY not configured"}, 500

    url = normalize_url(url)
    if not is_valid_url(url):
        return {"error": "Invalid URL. Only http(s) URLs are supported."}, 400

    content = extract_content_from_url(url)
    text = content.get("text", "")
    title = content.get("title", "")
    image_urls = content.get("image_urls", [])
    image_detection_info = content.get("image_detection_info", {})

    results: List[Dict[str, Any]] = []

    if text:
        text_claims = checker.extract_claims(text)
        if not text_claims and len(text.split()) >= 6:
            text_claims = [text]
        for claim in text_claims:
            if claim.strip():
                results.append({"claim": claim, "result": checker.fact_check_claim(claim)})

    if image_urls:
        for img_url in image_urls[:MAX_IMAGES_TO_ANALYZE]:
            image_claims = checker.extract_image_claims(image_url=img_url, image_data_url=None)
            for claim in image_claims:
                if claim.strip():
                    results.append({"claim": f"[Image] {claim}", "result": checker.fact_check_claim(claim)})

    response = {
        "original_text": text,
        "claims_found": len(results),
        "fact_check_results": results,
        "timestamp": time.time(),
        "source_url": url,
        "source_title": title,
        "images_detected": len(image_urls),
        "debug_image_urls": image_urls[:10],
        "image_detection_info": image_detection_info,
    }

    if image_detection_info.get("image_detected") and not image_urls:
        response["image_detection_message"] = image_detection_info.get("message", "")

    if image_urls:
        response["selected_image_url"] = image_urls[0]

    return response, 200
