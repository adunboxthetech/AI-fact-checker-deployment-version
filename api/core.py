import base64
import datetime
import ipaddress
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import (
    parse_qs,
    parse_qsl,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import requests
from bs4 import BeautifulSoup
from readability import Document


def _get_env_var_insensitive(key: str) -> Optional[str]:
    for k, v in os.environ.items():
        if k.lower() == key.lower():
            return v
    return None


GEMINI_API_KEY = _get_env_var_insensitive("GEMINI_API_KEY") or _get_env_var_insensitive(
    "GOOGLE_API_KEY"
)
GEMINI_URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_PRIMARY_MODEL = "gemini-2.0-flash"
GEMINI_FALLBACK_MODELS = ["gemini-2.0-flash-lite"]

# Groq API configuration — primary provider (OpenAI-compatible, higher free-tier RPM)
GROQ_API_KEY = _get_env_var_insensitive("GROQ_API_KEY")
GROQ_URL_BASE = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TEXT_MODEL = "llama-3.3-70b-versatile"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_FALLBACK_TEXT_MODEL = "llama-3.1-8b-instant"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
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
    "target url returned error",
    "markdown content:",
    "you've been blocked by network security",
    "you have been blocked by network security",
    "http error 403",
    "403: forbidden",
    "403 forbidden",
]

MAX_TEXT_CHARS = 12000
MAX_CLAIMS = 6
MAX_IMAGE_CLAIMS = 4
MAX_IMAGES_TO_ANALYZE = 2
MAX_CONCURRENT_IMAGE_REQUESTS = 1
MAX_IMAGE_DOWNLOAD_BYTES = 8 * 1024 * 1024
MAX_WEB_EVIDENCE_SOURCES = 5
MAX_WEB_EVIDENCE_CLAIMS = 6
MAX_WEB_EVIDENCE_FETCHES = 4
WEB_SEARCH_TIMEOUT_SECONDS = 8
WEB_EVIDENCE_FETCH_TIMEOUT_SECONDS = 6
GEMINI_RETRY_ATTEMPTS = 1
GEMINI_INITIAL_RETRY_DELAY_SECONDS = 1.0
GEMINI_BACKOFF_MULTIPLIER = 2.0
MAX_GEMINI_RETRY_DELAY_SECONDS = 4.0
GEMINI_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
GEMINI_INTER_REQUEST_DELAY = 0.5  # seconds between API calls
GROQ_INTER_REQUEST_DELAY = 0.3  # Groq has higher RPM limits than Gemini
GROQ_MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024  # Groq limits base64 images to 4MB
UPSTREAM_TIMEOUT_SECONDS = 25


@dataclass
class GeminiResponse:
    status_code: int
    body: str
    headers: Dict[str, str] = field(default_factory=dict)

    def json(self) -> Dict[str, Any]:
        return json.loads(self.body or "{}")


def _try_parse_json_block(s: Optional[str]) -> Optional[Any]:
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
            return json.loads(s[start : end + 1])
        except Exception:
            pass
    start = s.find("[")
    end = s.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except Exception:
            pass
    return None


def _extract_error_message(response: Optional[GeminiResponse]) -> str:
    if response is None:
        return "no response from upstream model"
    parsed = _try_parse_json_block(response.body)
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        parsed = parsed[0]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
    if response.body:
        return response.body[:200]
    return f"upstream status {response.status_code}"


def _coerce_confidence(value: Any, default: int = 75) -> int:
    if isinstance(value, str):
        value = re.sub(r"[^\d]", "", value)
        value = int(value) if value else default
    else:
        try:
            value = int(value)
        except Exception:
            value = default
    return max(0, min(100, value))


def _is_google_grounding_redirect(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower()
    return host.endswith("vertexaisearch.cloud.google.com") or host.endswith(
        "googleusercontent.com"
    )


def _source_url_from_title(title: Any) -> Optional[str]:
    if not isinstance(title, str):
        return None
    title = title.strip()
    if not title:
        return None
    match = re.search(r"([a-z0-9-]+(?:\.[a-z0-9-]+)+)", title, flags=re.I)
    if not match:
        return None
    host = match.group(1).lower()
    if host.endswith(".") or "." not in host:
        return None
    return f"https://{host}"


def _normalize_source_url(url: str) -> str:
    url = (url or "").strip().strip(".,;)]}\"'")
    if not re.match(r"^https?://", url, flags=re.I):
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid"}
    ]
    return urlunparse(
        parsed._replace(query=urlencode(query_pairs, doseq=True), fragment="")
    )


def _source_key(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return f"{parsed.netloc.lower()}{path.lower()}"


def _dedupe_sources(urls: List[str], limit: int = 5) -> List[str]:
    seen = set()
    cleaned: List[str] = []
    for url in urls:
        normalized = _normalize_source_url(url)
        if not normalized or _is_google_grounding_redirect(normalized):
            continue
        key = _source_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
        if len(cleaned) >= limit:
            break
    return cleaned


def _source_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _is_social_source_url(url: str) -> bool:
    host = _source_host(url)
    return host in {
        "x.com",
        "twitter.com",
        "mobile.twitter.com",
        "facebook.com",
        "instagram.com",
        "threads.net",
        "tiktok.com",
        "reddit.com",
        "youtube.com",
        "youtu.be",
    } or host.endswith(".reddit.com")


def _extract_grounding_sources(response_data: Dict[str, Any]) -> List[str]:
    candidates = response_data.get("candidates", [])
    if not candidates or not isinstance(candidates[0], dict):
        return []
    metadata = (
        candidates[0].get("groundingMetadata")
        or candidates[0].get("grounding_metadata")
        or {}
    )
    chunks = metadata.get("groundingChunks") or metadata.get("grounding_chunks") or []
    urls: List[str] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        web = chunk.get("web") if isinstance(chunk.get("web"), dict) else {}
        uri = web.get("uri") or web.get("url") or ""
        title_url = _source_url_from_title(web.get("title"))
        if isinstance(uri, str) and uri:
            normalized = _normalize_source_url(uri)
            if normalized and not _is_google_grounding_redirect(normalized):
                urls.append(normalized)
                continue
        if title_url:
            urls.append(title_url)
    return _dedupe_sources(urls)


def _clean_sources(value: Any, fallback: Optional[List[str]] = None) -> List[str]:
    urls: List[str] = []
    if isinstance(value, str):
        value = re.findall(r"https?://[^\s)\]}]+", value, flags=re.I)
    if isinstance(value, list):
        urls.extend(source for source in value if isinstance(source, str))
    cleaned = _dedupe_sources(urls)
    if cleaned:
        return cleaned
    return _dedupe_sources(fallback or [])


def _retry_delay_seconds(attempt: int) -> float:
    return GEMINI_INITIAL_RETRY_DELAY_SECONDS * (GEMINI_BACKOFF_MULTIPLIER**attempt)


def _retry_after_seconds(response: Optional[GeminiResponse]) -> Optional[float]:
    if response is None:
        return None
    header_value = response.headers.get("Retry-After") or response.headers.get(
        "retry-after"
    )
    if header_value:
        try:
            return max(0.0, float(header_value))
        except ValueError:
            pass

    parsed = _try_parse_json_block(response.body)
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        parsed = parsed[0]
    if isinstance(parsed, dict):
        details = parsed.get("error", {}).get("details", [])
        if isinstance(details, list):
            for detail in details:
                retry_delay = (
                    detail.get("retryDelay") if isinstance(detail, dict) else None
                )
                if isinstance(retry_delay, str):
                    match = re.search(r"([\d.]+)s", retry_delay)
                    if match:
                        return max(0.0, float(match.group(1)))

    match = re.search(r"retry in\s+([\d.]+)\s*(ms|s)", response.body or "", flags=re.I)
    if match:
        delay = float(match.group(1))
        if match.group(2).lower() == "ms":
            delay = delay / 1000
        return max(0.0, delay)
    return None


def _models_for_payload(payload: Dict[str, Any]) -> List[str]:
    requested_model = payload.get("model") or GEMINI_PRIMARY_MODEL
    models = [requested_model]
    if requested_model == GEMINI_PRIMARY_MODEL:
        models.extend(GEMINI_FALLBACK_MODELS)
    return _dedupe(models)


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
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        hostname = parsed.hostname or ""
        if not hostname or any(ch.isspace() for ch in hostname):
            return False
        try:
            ip = ipaddress.ip_address(hostname)
            return not (
                ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            )
        except ValueError:
            pass
        if hostname.lower() == "localhost" or "." not in hostname:
            return False
        return True
    except Exception:
        return False


def _clean_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").split())


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
    return any(
        host in parsed.netloc
        for host in [
            "pbs.twimg.com",
            "i.redd.it",
            "preview.redd.it",
            "external-preview.redd.it",
            "i.imgur.com",
            "imgur.com",
            "cdninstagram.com",
            "instagram.com",
            "fbcdn.net",
            "fbsbx.com",
            "twimg.com",
            "media.tumblr.com",
            "media.discordapp.net",
            "cdn.discordapp.com",
        ]
    )


def _is_image_content_type(content_type: str) -> bool:
    return (content_type or "").lower().split(";", 1)[0].strip().startswith("image/")


def _is_html_content_type(content_type: str) -> bool:
    media_type = (content_type or "").lower().split(";", 1)[0].strip()
    return not media_type or media_type in {
        "text/html",
        "application/xhtml+xml",
        "application/xml",
        "text/xml",
    }


def _remote_url_is_image(url: str) -> bool:
    try:
        headers = {
            **DEFAULT_HEADERS,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        resp = requests.head(url, headers=headers, allow_redirects=True, timeout=6)
        if resp.status_code in {405, 403} or resp.status_code >= 500:
            resp = requests.get(
                url, headers=headers, allow_redirects=True, timeout=6, stream=True
            )
        return resp.status_code < 400 and _is_image_content_type(
            resp.headers.get("Content-Type", "")
        )
    except Exception:
        return False


def _image_content_key(url: str) -> str:
    parsed = urlparse(url)
    basename = parsed.path.rstrip("/").rsplit("/", 1)[-1].lower()
    if re.search(r"\.(jpg|jpeg|png|gif|webp|svg)$", basename, flags=re.I):
        return basename
    return f"{parsed.netloc.lower()}{parsed.path.lower()}"


def _filter_image_urls(
    image_urls: List[str], known_image_urls: Optional[List[str]] = None
) -> List[str]:
    known = set(known_image_urls or [])
    filtered: List[str] = []
    content_keys = set()
    for img in _dedupe([u for u in image_urls if u]):
        if img in known or _is_image_like(img) or _remote_url_is_image(img):
            content_key = _image_content_key(img)
            if content_key in content_keys:
                continue
            content_keys.add(content_key)
            filtered.append(img)
        if len(filtered) >= 10:
            break
    return filtered


def _download_image_as_data_url(
    url: str, max_bytes: int = MAX_IMAGE_DOWNLOAD_BYTES
) -> Optional[str]:
    if not url:
        return None
    try:
        headers = {
            **DEFAULT_HEADERS,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=15, stream=True)
        resp.raise_for_status()
        content_type = (
            resp.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if not _is_image_content_type(content_type):
            return None

        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                return None
            chunks.append(chunk)
        if not chunks:
            return None
        encoded = base64.b64encode(b"".join(chunks)).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    except Exception:
        return None


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


def _has_post_adapter(platform: str) -> bool:
    return platform in {"twitter", "reddit", "tiktok", "youtube"}


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

    og_desc = soup.find("meta", property="og:description") or soup.find(
        "meta", attrs={"name": "description"}
    )
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()
    else:
        tw_desc = soup.find("meta", attrs={"name": "twitter:description"})
        if tw_desc and tw_desc.get("content"):
            description = tw_desc["content"].strip()

    return title, description


def _extract_meta_images(soup: BeautifulSoup, base_url: str) -> List[str]:
    images = []
    for prop in [
        "og:image",
        "og:image:secure_url",
        "twitter:image",
        "twitter:image:src",
    ]:
        meta = soup.find("meta", property=prop) or soup.find(
            "meta", attrs={"name": prop}
        )
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
    replacement_chars = text.count("\ufffd")
    control_chars = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
    binary_noise = replacement_chars > 5 or control_chars > max(10, len(text) * 0.03)
    return (
        len(text) < 200
        or binary_noise
        or any(marker in lowered for marker in BOILERPLATE_MARKERS)
    )


def _fetch_html(url: str) -> Tuple[str, str, str]:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=12)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if not _is_html_content_type(content_type):
        return "", resp.url, content_type
    return resp.text, resp.url, content_type


def _fetch_jina_text(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        query = f"?{parsed.query}" if parsed.query else ""
        wrapped = (
            f"https://r.jina.ai/{parsed.scheme}://{parsed.netloc}{parsed.path}{query}"
        )
        resp = requests.get(wrapped, headers=DEFAULT_HEADERS, timeout=14)
        text = _clean_text(resp.text)
        if resp.status_code == 200 and len(text) > 200 and not _looks_blocked(text):
            return text
    except Exception:
        return None
    return None


def _unwrap_duckduckgo_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    try:
        parsed = urlparse(url)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return target or url
    except Exception:
        return url
    return url


def _unwrap_bing_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if "bing.com" not in parsed.netloc or not parsed.path.startswith("/ck/"):
            return url
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if not encoded:
            return url
        if encoded.startswith("http"):
            return encoded
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        padding = "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode(
            "utf-8", errors="replace"
        )
        return decoded or url
    except Exception:
        return url


def _unwrap_yahoo_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if "search.yahoo.com" not in parsed.netloc:
            return url
        match = re.search(r"/RU=([^/]+)", parsed.path)
        if match:
            return unquote(match.group(1))
    except Exception:
        return url
    return url


def _unwrap_search_result_url(url: str) -> str:
    return _unwrap_yahoo_url(_unwrap_bing_url(_unwrap_duckduckgo_url(url)))


def _clean_search_query(text: str, max_chars: int = 160) -> str:
    text = re.sub(r"^\[Image\]\s*", "", text or "", flags=re.I)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -:|")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].strip()


def _claim_key(text: str) -> str:
    return _clean_text(re.sub(r"^\[Image\]\s*", "", text or "", flags=re.I)).lower()


def _rank_search_sources(
    items: List[Dict[str, str]], max_results: int
) -> List[Dict[str, str]]:
    social = [item for item in items if _is_social_source_url(item.get("url", ""))]
    nonsocial = [
        item for item in items if not _is_social_source_url(item.get("url", ""))
    ]
    ordered = nonsocial or social
    deduped_urls = _dedupe_sources([item["url"] for item in ordered], max_results)
    by_url = {item["url"]: item for item in ordered}
    return [by_url[url] for url in deduped_urls if url in by_url]


def _search_duckduckgo_sources(query: str, max_results: int) -> List[Dict[str, str]]:
    query = _clean_search_query(query)
    if not query:
        return []
    try:
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers=DEFAULT_HEADERS,
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        items: List[Dict[str, str]] = []
        for node in soup.select(".result"):
            link = node.select_one(".result__a")
            if not link:
                continue
            url = _normalize_source_url(_unwrap_search_result_url(link.get("href", "")))
            if not url or _is_google_grounding_redirect(url):
                continue
            title = _clean_text(link.get_text(" ", strip=True))
            snippet_node = node.select_one(".result__snippet")
            snippet = _clean_text(
                snippet_node.get_text(" ", strip=True) if snippet_node else ""
            )
            items.append({"url": url, "title": title, "snippet": snippet})
            if len(items) >= max_results * 2:
                break
        return _rank_search_sources(items, max_results)
    except Exception:
        return []


def _search_bing_sources(query: str, max_results: int) -> List[Dict[str, str]]:
    query = _clean_search_query(query)
    if not query:
        return []
    try:
        resp = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers=DEFAULT_HEADERS,
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        items: List[Dict[str, str]] = []
        for node in soup.select("li.b_algo"):
            link = node.find("a")
            if not link:
                continue
            url = _normalize_source_url(_unwrap_search_result_url(link.get("href", "")))
            if not url or _is_google_grounding_redirect(url):
                continue
            title = _clean_text(link.get_text(" ", strip=True))
            snippet_node = node.find("p")
            snippet = _clean_text(
                snippet_node.get_text(" ", strip=True) if snippet_node else ""
            )
            items.append({"url": url, "title": title, "snippet": snippet})
            if len(items) >= max_results * 2:
                break
        return _rank_search_sources(items, max_results)
    except Exception:
        return []


def _search_yahoo_sources(query: str, max_results: int) -> List[Dict[str, str]]:
    query = _clean_search_query(query)
    if not query:
        return []
    try:
        resp = requests.get(
            "https://search.yahoo.com/search",
            params={"p": query},
            headers=DEFAULT_HEADERS,
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        items: List[Dict[str, str]] = []
        for node in soup.select("div.dd.algo"):
            link = node.find("a")
            if not link:
                continue
            url = _normalize_source_url(_unwrap_search_result_url(link.get("href", "")))
            if not url or _is_google_grounding_redirect(url):
                continue
            title = _clean_text(link.get_text(" ", strip=True))
            snippet_node = node.find(class_="compText")
            snippet = _clean_text(
                snippet_node.get_text(" ", strip=True) if snippet_node else ""
            )
            items.append({"url": url, "title": title, "snippet": snippet})
            if len(items) >= max_results * 2:
                break
        return _rank_search_sources(items, max_results)
    except Exception:
        return []


def _search_web_sources(
    query: str, max_results: int = MAX_WEB_EVIDENCE_SOURCES
) -> List[Dict[str, str]]:
    combined: List[Dict[str, str]] = []
    for search_fn in (
        _search_duckduckgo_sources,
        _search_bing_sources,
        _search_yahoo_sources,
    ):
        if (
            len(_dedupe_sources([item["url"] for item in combined], max_results))
            >= max_results
        ):
            break
        combined.extend(search_fn(query, max_results))
    return _rank_search_sources(combined, max_results)


def _fetch_evidence_page_summary(source: Dict[str, str]) -> Dict[str, str]:
    url = source.get("url", "")
    if not url or _is_social_source_url(url):
        return source
    try:
        resp = requests.get(
            url, headers=DEFAULT_HEADERS, timeout=WEB_EVIDENCE_FETCH_TIMEOUT_SECONDS
        )
        if resp.status_code >= 400 or not _is_html_content_type(
            resp.headers.get("Content-Type", "")
        ):
            return source
        soup = BeautifulSoup(resp.text, "lxml")
        title, description = _extract_meta_text(soup)
        body = _extract_body_text(resp.text)
        summary = _clean_text(
            " ".join(part for part in [description, body[:900]] if part)
        )
        if title:
            source["title"] = title
        if summary:
            source["snippet"] = _truncate(summary, 900)
    except Exception:
        pass
    return source


def _gather_web_evidence_for_claims(
    claims: List[str],
) -> Dict[str, List[Dict[str, str]]]:
    clean_claims = [
        _clean_search_query(claim) for claim in claims if _clean_search_query(claim)
    ]
    clean_claims = _dedupe(clean_claims)[:MAX_WEB_EVIDENCE_CLAIMS]
    if not clean_claims:
        return {}

    evidence: Dict[str, List[Dict[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=min(4, len(clean_claims))) as executor:
        futures = {
            executor.submit(_search_web_sources, claim): claim for claim in clean_claims
        }
        for future in as_completed(futures):
            claim = futures[future]
            try:
                sources = future.result() or []
            except Exception:
                sources = []
            evidence[claim] = sources

    fetch_candidates: List[Tuple[str, Dict[str, str]]] = []
    for claim, sources in evidence.items():
        for source in sources[:MAX_WEB_EVIDENCE_FETCHES]:
            fetch_candidates.append((claim, source))

    if fetch_candidates:
        with ThreadPoolExecutor(max_workers=min(6, len(fetch_candidates))) as executor:
            futures = {
                executor.submit(_fetch_evidence_page_summary, dict(source)): (
                    claim,
                    index,
                )
                for claim, sources in evidence.items()
                for index, source in enumerate(sources[:MAX_WEB_EVIDENCE_FETCHES])
            }
            for future in as_completed(futures):
                claim, index = futures[future]
                try:
                    evidence[claim][index] = future.result()
                except Exception:
                    pass
    return evidence


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
    t = re.sub(r"https?://\S+|pic\.twitter\.com/\S+|@\w+|#\w+", " ", t)
    t = _clean_text(t)
    words = t.split()
    if len(words) < 6:
        return False
    if re.search(
        r"\b(is|are|was|were|has|have|had|will|won|lost|died|born|founded|"
        r"announced|said|says|claims|reports|files|accused|convicted|acquitted|"
        r"killed|arrested|sentenced|caused|proved|debunked|manufacture|manufactures|"
        r"manufactured|build|builds|built|produce|produces|produced|launch|launches|"
        r"launched|open|opens|opened|invest|invests|invested|export|exports|import|imports)\b",
        t,
    ):
        return True
    if re.search(
        r"\bto\s+(manufacture|build|produce|launch|open|invest|export|import|make|set up|establish)\b",
        t,
    ):
        return True
    if re.search(r"\b\d{1,4}([.,]\d+)?%?\b", t):
        return True
    return False


def _has_substantial_article_text(text: str) -> bool:
    return len(_clean_text(text)) >= 400


def _extract_images_from_html(soup: BeautifulSoup, base_url: str) -> List[str]:
    images: List[str] = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            srcset = img.get("srcset")
            if srcset:
                parts = [
                    p.strip().split(" ")[0] for p in srcset.split(",") if p.strip()
                ]
                if parts:
                    src = parts[-1]
        if src:
            images.append(_resolve_url(base_url, src))
    return images


def _image_detection_info(url: str, text: str, image_urls: List[str]) -> Dict[str, Any]:
    image_patterns = [
        r"reddit\.com/r/.+/comments/",
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
    text_has_images = any(
        re.search(p, text or "", re.IGNORECASE) for p in image_patterns
    )
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
    return urlunparse(parsed._replace(path=path, query=urlencode({"raw_json": "1"})))


def _reddit_post_id(url: str) -> Optional[str]:
    match = re.search(r"/comments/([a-z0-9]+)/", urlparse(url).path, flags=re.I)
    return match.group(1) if match else None


def _reddit_request_candidates(url: str) -> List[str]:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    candidates = [_build_reddit_json_url(url)]
    if path:
        candidates.append(
            urlunparse(
                parsed._replace(
                    netloc="api.reddit.com",
                    path=path,
                    query=urlencode({"raw_json": "1"}),
                )
            )
        )
    post_id = _reddit_post_id(url)
    if post_id:
        candidates.append(f"https://www.reddit.com/by_id/t3_{post_id}.json?raw_json=1")
        candidates.append(f"https://api.reddit.com/by_id/t3_{post_id}?raw_json=1")
    return _dedupe(candidates)


def _reddit_old_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(netloc="old.reddit.com", query="", fragment=""))


def _reddit_post_from_json(data: Any) -> Optional[Dict[str, Any]]:
    try:
        if isinstance(data, list):
            return data[0]["data"]["children"][0]["data"]
        if isinstance(data, dict):
            children = data.get("data", {}).get("children", [])
            if children:
                return children[0].get("data")
    except Exception:
        return None
    return None


def _extract_reddit_json(url: str) -> Optional[Dict[str, Any]]:
    headers = {
        **BROWSER_HEADERS,
        "User-Agent": "AI-Fact-Checker/1.0 by u/ad_unboxthetech",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }
    for json_url in _reddit_request_candidates(url):
        try:
            resp = requests.get(json_url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue
            post = _reddit_post_from_json(resp.json())
            if not post:
                continue
            title = post.get("title", "")
            body = post.get("selftext", "")
            text = _clean_text(f"{title} {body}")
            images: List[str] = []
            if post.get("url_overridden_by_dest") and _is_image_like(
                post["url_overridden_by_dest"]
            ):
                images.append(post["url_overridden_by_dest"])
            preview = post.get("preview", {}).get("images", [])
            for img in preview:
                source = img.get("source", {}).get("url")
                if source:
                    images.append(source.replace("&amp;", "&"))
                for resolution in img.get("resolutions", []) or []:
                    url_value = resolution.get("url")
                    if url_value:
                        images.append(url_value.replace("&amp;", "&"))
            media_meta = post.get("media_metadata") or {}
            for media in media_meta.values():
                if media.get("e") == "Image" and media.get("s"):
                    src = media["s"].get("u") or media["s"].get("gif")
                    if src:
                        images.append(src.replace("&amp;", "&"))
            return {"text": text, "title": title, "images": _dedupe(images)}
        except Exception:
            continue
    return None


def _extract_reddit_old_html(url: str) -> Optional[Dict[str, Any]]:
    try:
        post_id = _reddit_post_id(url)
        resp = requests.get(_reddit_old_url(url), headers=BROWSER_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        thing = soup.find(attrs={"data-fullname": f"t3_{post_id}"}) if post_id else None
        if thing is None:
            thing = soup.find(
                "div", class_=lambda value: value and "thing" in value.split()
            )
        if thing is None:
            return None

        title_node = thing.find(
            "a", class_=lambda value: value and "title" in value.split()
        )
        title = title_node.get_text(" ", strip=True) if title_node else ""
        body_node = soup.find(
            "div", class_=lambda value: value and "usertext-body" in value.split()
        )
        body = body_node.get_text(" ", strip=True) if body_node else ""
        text = _clean_text(f"{title} {body}")
        images: List[str] = []

        for attr in ["data-url", "data-media-url"]:
            value = thing.get(attr)
            if value and _is_image_like(value):
                images.append(value)
        for link in thing.find_all("a"):
            href = link.get("href")
            if href and _is_image_like(href):
                images.append(_resolve_url(resp.url, href))
        for img in thing.find_all("img"):
            src = img.get("src")
            if src:
                images.append(_resolve_url(resp.url, src))

        if not text and not images:
            return None
        return {
            "text": text,
            "title": title,
            "images": _dedupe([img for img in images if img]),
        }
    except Exception:
        return None


def _extract_reddit_unfurled(url: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(
            "https://api.microlink.io/",
            params={"url": url},
            headers=DEFAULT_HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data") or {}
        title = data.get("title") or ""
        description = data.get("description") or ""
        images = []
        image = data.get("image") or {}
        if isinstance(image, dict) and image.get("url"):
            images.append(image["url"])
        if not title and not description and not images:
            return None
        return {
            "text": _clean_text(f"{title} {description}"),
            "title": title,
            "images": images,
        }
    except Exception:
        return None


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
                    preview = (
                        media.get("media_url_https")
                        or media.get("media_url")
                        or media.get("preview_image_url")
                    )
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
        resp = requests.get(
            api_url,
            params={"id": tweet_id, "lang": "en"},
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = data.get("text") or data.get("full_text") or ""
            user = data.get("user") or {}
            title = (
                f"Post by @{user.get('screen_name', 'user')}"
                if user
                else "Twitter/X post"
            )
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
            text = (
                BeautifulSoup(html, "lxml").get_text(" ", strip=True)
                if html
                else data.get("title", "")
            )
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
        media_urls = re.findall(r"https?://pbs\.twimg\.com/[^\s)\]}\"']+", jina_text)
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
        title = (
            f"Post by @{author.get('screen_name')}"
            if author.get("screen_name")
            else "Twitter/X post"
        )
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
    return (
        _extract_reddit_json(url)
        or _extract_reddit_old_html(url)
        or _extract_reddit_unfurled(url)
    )


def _extract_oembed(url: str, endpoint: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(
            endpoint,
            params={"url": url, "format": "json"},
            headers=DEFAULT_HEADERS,
            timeout=10,
        )
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
    known_image_urls: List[str] = []
    prefer_extracted = False

    if extracted:
        text_content = extracted.get("text", "") or ""
        title = extracted.get("title", "") or ""
        image_urls.extend(extracted.get("images", []) or [])
        if _has_post_adapter(platform) and (text_content or image_urls):
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
        if not prefer_extracted and (
            not text_content or len(text_content.strip()) < 80
        ):
            if not _looks_blocked(body_text):
                text_content = body_text
            elif jsonld_text:
                text_content = jsonld_text
            elif meta_desc:
                text_content = meta_desc

        image_urls.extend(_extract_meta_images(soup, final_url))
        image_urls.extend(_extract_jsonld_images(jsonld_items))
        image_urls.extend(_extract_images_from_html(soup, final_url))
    elif _is_image_content_type(content_type):
        image_urls.append(final_url)
        known_image_urls.append(final_url)

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

    image_urls = _filter_image_urls(image_urls, known_image_urls)

    image_detection_info = _image_detection_info(url, text_content, image_urls)

    return {
        "text": text_content or "",
        "title": title or "",
        "image_urls": image_urls[:10],
        "image_detection_info": image_detection_info,
    }


class FactChecker:
    def __init__(
        self, api_key: Optional[str] = None, groq_api_key: Optional[str] = None
    ):
        # Gemini key (fallback provider)
        resolved_gemini = (
            api_key
            or _get_env_var_insensitive("GEMINI_API_KEY")
            or GEMINI_API_KEY
            or _get_env_var_insensitive("GOOGLE_API_KEY")
            or ""
        )
        self.gemini_api_key = resolved_gemini.strip()

        # Groq key (primary provider — higher RPM, dedicated LPU hardware)
        resolved_groq = (
            groq_api_key
            or _get_env_var_insensitive("GROQ_API_KEY")
            or GROQ_API_KEY
            or ""
        )
        self.groq_api_key = resolved_groq.strip()

        # At least one provider must be configured
        if not self.gemini_api_key and not self.groq_api_key:
            raise ValueError(
                "No API key configured. Set GROQ_API_KEY and/or GEMINI_API_KEY."
            )

        # Keep legacy attribute for compatibility with _analyze_single_image_url
        self.api_key = self.gemini_api_key or self.groq_api_key

        self.headers = {
            "Content-Type": "application/json",
        }
        self.last_image_error = ""
        self.last_text_error = ""

    @staticmethod
    def _translate_messages_to_contents(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI-style messages to native Gemini 'contents' format."""
        contents = []
        for msg in messages:
            role = "user" if msg.get("role") in ("user", "system") else "model"
            content = msg.get("content", "")
            if isinstance(content, str):
                contents.append({"role": role, "parts": [{"text": content}]})
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append({"text": item.get("text", "")})
                        elif item.get("type") == "image_url":
                            image_url = item.get("image_url", {}).get("url", "")
                            if image_url.startswith("data:"):
                                # Parse data URL: data:mime;base64,DATA
                                match = re.match(
                                    r"data:([^;]+);base64,(.+)", image_url, re.DOTALL
                                )
                                if match:
                                    mime_type = match.group(1)
                                    b64_data = match.group(2)
                                    parts.append(
                                        {
                                            "inline_data": {
                                                "mime_type": mime_type,
                                                "data": b64_data,
                                            }
                                        }
                                    )
                            else:
                                # Remote URL — use file_data for Gemini
                                mime_type = "image/jpeg"
                                if image_url.lower().endswith(".png"):
                                    mime_type = "image/png"
                                elif image_url.lower().endswith(".gif"):
                                    mime_type = "image/gif"
                                elif image_url.lower().endswith(".webp"):
                                    mime_type = "image/webp"
                                parts.append(
                                    {
                                        "file_data": {
                                            "mime_type": mime_type,
                                            "file_uri": image_url,
                                        }
                                    }
                                )
                if parts:
                    contents.append({"role": role, "parts": parts})
        return contents

    @staticmethod
    def _translate_native_response(body: str) -> str:
        """Convert native Gemini response to OpenAI-compatible format for downstream parsing."""
        try:
            data = json.loads(body)
            candidates = data.get("candidates", [])
            if not candidates:
                return body
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            grounding_sources = _extract_grounding_sources(data)
            # Return in OpenAI-compatible format so all downstream parsing works unchanged
            return json.dumps(
                {
                    "choices": [{"message": {"role": "assistant", "content": text}}],
                    "grounding_sources": grounding_sources,
                }
            )
        except Exception:
            return body

    def _post_gemini(
        self, payload: Dict[str, Any], retries: int = GEMINI_RETRY_ATTEMPTS
    ) -> Optional[GeminiResponse]:
        """Call native Gemini API with retry and model fallback on ANY non-200."""
        last_response: Optional[GeminiResponse] = None
        last_error: Optional[str] = None
        models = _models_for_payload(payload)

        # Translate OpenAI-style messages to native Gemini contents
        messages = payload.get("messages", [])
        contents = self._translate_messages_to_contents(messages)

        use_search = bool(payload.get("use_web_search"))

        # Build generation config
        # CRITICAL: Gemini does NOT support response_mime_type together with tools
        # (googleSearch). When search is enabled, we ask for JSON in the prompt instead.
        generation_config: Dict[str, Any] = {}
        if (
            payload.get("response_format", {}).get("type") == "json_object"
            and not use_search
        ):
            generation_config["response_mime_type"] = "application/json"
        # Disable thinking on 2.5+ models for speed — we don't need reasoning traces
        # (thinkingConfig is silently ignored by models that don't support it)

        for model_index, model in enumerate(models):
            api_url = (
                f"{GEMINI_URL_BASE}/{model}:generateContent?key={self.gemini_api_key}"
            )
            native_payload = {"contents": contents}
            if generation_config:
                native_payload["generationConfig"] = generation_config
            if use_search:
                native_payload["tools"] = [{"googleSearch": {}}]
            encoded_payload = json.dumps(native_payload).encode("utf-8")
            model_failed = False
            for attempt in range(retries):
                try:
                    req = urllib_request.Request(
                        api_url,
                        data=encoded_payload,
                        headers=self.headers,
                        method="POST",
                    )
                    with urllib_request.urlopen(
                        req, timeout=UPSTREAM_TIMEOUT_SECONDS
                    ) as upstream:
                        body = upstream.read().decode("utf-8", errors="replace")
                        status_code = int(getattr(upstream, "status", 200))
                        # Translate native response to OpenAI-compatible format
                        translated_body = self._translate_native_response(body)
                        response = GeminiResponse(
                            status_code=status_code,
                            body=translated_body,
                            headers=dict(upstream.headers),
                        )
                except urllib_error.HTTPError as err:
                    body = ""
                    try:
                        body = err.read().decode("utf-8", errors="replace")
                    except Exception:
                        body = ""
                    response = GeminiResponse(
                        status_code=int(err.code),
                        body=body,
                        headers=dict(err.headers or {}),
                    )
                except Exception as err:
                    last_error = f"{type(err).__name__}: {err}"
                    response = None

                if response is not None:
                    last_response = response
                    if response.status_code == 200:
                        return response
                    # Non-transient errors (400, 403, 404, etc.) → try next model immediately
                    if response.status_code not in GEMINI_TRANSIENT_STATUS_CODES:
                        model_failed = True
                        break
                    # Transient error (429, 5xx) with more models available → try next model
                    if model_index < len(models) - 1:
                        model_failed = True
                        break
                if attempt < retries - 1:
                    retry_after = _retry_after_seconds(last_response)
                    delay = (
                        retry_after
                        if retry_after is not None
                        else _retry_delay_seconds(attempt)
                    )
                    delay = min(delay, MAX_GEMINI_RETRY_DELAY_SECONDS)
                    time.sleep(delay)
            if model_failed and model_index < len(models) - 1:
                # Brief pause before trying next model
                time.sleep(1.0)
                continue
        if last_response is None and last_error:
            return GeminiResponse(status_code=0, body=json.dumps({"error": last_error}))
        return last_response

    def _post_groq(
        self,
        payload: Dict[str, Any],
        retries: int = GEMINI_RETRY_ATTEMPTS,
        use_vision: bool = False,
    ) -> Optional[GeminiResponse]:
        """Call Groq API (OpenAI-compatible) with retry and model fallback."""
        if not self.groq_api_key:
            return None

        last_response: Optional[GeminiResponse] = None
        last_error: Optional[str] = None

        # Select models based on whether vision is needed
        if use_vision:
            models = [GROQ_VISION_MODEL]
        else:
            models = [GROQ_TEXT_MODEL, GROQ_FALLBACK_TEXT_MODEL]

        for model_index, model in enumerate(models):
            groq_payload: Dict[str, Any] = {
                "model": model,
                "messages": payload.get("messages", []),
            }
            # Groq supports response_format for JSON mode
            if payload.get("response_format", {}).get("type") == "json_object":
                groq_payload["response_format"] = {"type": "json_object"}

            encoded = json.dumps(groq_payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AI-Fact-Checker/1.0 (+https://anindya-das-ai-fact-checker.vercel.app)",
                "Authorization": f"Bearer {self.groq_api_key}",
            }
            model_failed = False
            for attempt in range(retries):
                try:
                    req = urllib_request.Request(
                        GROQ_URL_BASE,
                        data=encoded,
                        headers=headers,
                        method="POST",
                    )
                    with urllib_request.urlopen(
                        req, timeout=UPSTREAM_TIMEOUT_SECONDS
                    ) as upstream:
                        body = upstream.read().decode("utf-8", errors="replace")
                        status_code = int(getattr(upstream, "status", 200))
                        # Groq responses are already in OpenAI format — no translation needed
                        response = GeminiResponse(
                            status_code=status_code,
                            body=body,
                            headers=dict(upstream.headers),
                        )
                except urllib_error.HTTPError as err:
                    body = ""
                    try:
                        body = err.read().decode("utf-8", errors="replace")
                    except Exception:
                        body = ""
                    response = GeminiResponse(
                        status_code=int(err.code),
                        body=body,
                        headers=dict(err.headers or {}),
                    )
                except Exception as err:
                    last_error = f"{type(err).__name__}: {err}"
                    response = None

                if response is not None:
                    last_response = response
                    if response.status_code == 200:
                        return response
                    if response.status_code not in GEMINI_TRANSIENT_STATUS_CODES:
                        model_failed = True
                        break
                    if model_index < len(models) - 1:
                        model_failed = True
                        break
                if attempt < retries - 1:
                    retry_after = _retry_after_seconds(last_response)
                    delay = (
                        retry_after
                        if retry_after is not None
                        else _retry_delay_seconds(attempt)
                    )
                    delay = min(delay, MAX_GEMINI_RETRY_DELAY_SECONDS)
                    time.sleep(delay)
            if model_failed and model_index < len(models) - 1:
                time.sleep(0.5)
                continue

        if last_response is None and last_error:
            return GeminiResponse(status_code=0, body=json.dumps({"error": last_error}))
        return last_response

    def _has_vision_content(self, payload: Dict[str, Any]) -> bool:
        """Check if payload contains image content (vision request)."""
        for msg in payload.get("messages", []):
            content = msg.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return True
        return False

    def _post_api(self, payload: Dict[str, Any]) -> Optional[GeminiResponse]:
        """Unified API call: tries Groq first (primary), falls back to Gemini.

        Groq is preferred because:
        - Higher free-tier RPM (30-60 vs 15)
        - Dedicated LPU hardware (fewer 503 "high demand" errors)
        - OpenAI-compatible format (simpler, no translation needed)

        When use_web_search is set, we prefer Gemini (Google Search Grounding).
        If Gemini fails, we fall back to Groq without search.
        """
        use_vision = self._has_vision_content(payload)
        use_web_search = payload.get("use_web_search", False)

        # If web search is needed, try Gemini first (Google Search Grounding)
        if use_web_search and self.gemini_api_key:
            response = self._post_gemini(payload)
            if response is not None and response.status_code == 200:
                return response
            # Gemini failed — fall back to Groq without search
            if self.groq_api_key:
                fallback_payload = {
                    k: v for k, v in payload.items() if k != "use_web_search"
                }
                response = self._post_groq(fallback_payload, use_vision=use_vision)
                if response is not None and response.status_code == 200:
                    return response
            return response

        # Try Groq first (if key is configured)
        if self.groq_api_key:
            # Strip use_web_search from Groq payloads (not supported)
            groq_payload = {k: v for k, v in payload.items() if k != "use_web_search"}
            response = self._post_groq(groq_payload, use_vision=use_vision)
            if response is not None and response.status_code == 200:
                return response

        # Fall back to Gemini
        if self.gemini_api_key:
            return self._post_gemini(payload)

        # If we got a non-200 from Groq and no Gemini key, return whatever Groq gave us
        return response if self.groq_api_key else None

    def _rate_limit_pause(self):
        """Brief pause between API calls to respect free-tier RPM limits."""
        delay = (
            GROQ_INTER_REQUEST_DELAY
            if self.groq_api_key
            else GEMINI_INTER_REQUEST_DELAY
        )
        time.sleep(delay)

    def extract_claims(self, text: str, max_claims: int = MAX_CLAIMS) -> List[str]:
        if not text:
            return []
        clipped = _truncate(text, 6000)
        current_date = datetime.date.today().isoformat()
        prompt = (
            f"Today's date is {current_date}. "
            "Extract up to {max_claims} factual claims EXPLICITLY stated in this text. "
            "The text might be an article, a short statement, a question, or a rumor. "
            "If it's a short statement or a direct claim, extract it directly. "
            "Do not infer, assume, or use outside knowledge. "
            "Do not generate claims about people/entities unless directly asserted in the text. "
            "Return ONLY a numbered list. If there are absolutely no factual claims or premises, reply with EXACTLY 'NONE'.\n\n"
            "Text: {text}"
        ).format(max_claims=max_claims, text=clipped)

        payload = {
            "model": GEMINI_PRIMARY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = self._post_api(payload)
        if response is None or response.status_code != 200:
            return []
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except Exception:
            return []
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
        current_date = datetime.date.today().isoformat()
        prompt = (
            f"Today's date is {current_date}. "
            "Fact-check this claim with high accuracy. Provide:\n"
            "1. Verdict (TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/UNVERIFIABLE)\n"
            "2. Confidence level (0-100%)\n"
            "3. Brief explanation (2-3 sentences). Do NOT refuse to fact-check by saying you cannot browse the internet or access real-time data; use your best existing knowledge.\n"
            "4. Key sources used as a list of canonical URLs. Each source MUST be a full http(s) URL. "
            "Do not include reference numbers or titles, only URLs.\n\n"
            "Claim: {claim}\n\n"
            "Format your response as JSON with keys: verdict, confidence, explanation, sources"
        ).format(claim=claim)

        payload = {
            "model": GEMINI_PRIMARY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "use_web_search": True,
        }
        response = self._post_api(payload)

        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "no-response"
            error_detail = ""
            if response and response.body:
                parsed = _try_parse_json_block(response.body)
                if isinstance(parsed, dict) and "error" in parsed:
                    if isinstance(parsed["error"], str):
                        error_detail = f"; {parsed['error']}"
                    else:
                        error_detail = f"; {json.dumps(parsed['error'])}"
                elif response.body:
                    error_detail = f"; {response.body[:200]}"
            return {
                "verdict": "ERROR",
                "confidence": 0,
                "explanation": f"Failed to verify claim (upstream status: {status}{error_detail})",
                "sources": [],
            }

        try:
            response_json = response.json()
            content = response_json["choices"][0]["message"]["content"]
            grounding_sources = _clean_sources(
                response_json.get("grounding_sources", [])
            )
        except Exception:
            return {
                "verdict": "ERROR",
                "confidence": 0,
                "explanation": "Upstream returned an unreadable response",
                "sources": [],
            }
        parsed = _try_parse_json_block(content)
        if parsed is not None:
            urls: List[str] = []
            if isinstance(parsed.get("sources"), list):
                for item in parsed["sources"]:
                    if isinstance(item, str) and re.match(
                        r"^https?://", item.strip(), flags=re.I
                    ):
                        urls.append(item.strip())
            if not urls and isinstance(parsed.get("explanation"), str):
                urls = re.findall(
                    r"https?://[^\s)\]}]+", parsed["explanation"], flags=re.I
                )
            parsed["sources"] = _clean_sources(urls, grounding_sources)
            conf_val = parsed.get("confidence", 75)
            if isinstance(conf_val, str):
                conf_val = re.sub(r"[^\d]", "", conf_val)
                conf_val = int(conf_val) if conf_val else 75
            else:
                try:
                    conf_val = int(conf_val)
                except Exception:
                    conf_val = 75
            return {
                "verdict": parsed.get("verdict", "INSUFFICIENT EVIDENCE"),
                "confidence": conf_val,
                "explanation": parsed.get("explanation", "Analysis completed"),
                "sources": parsed.get("sources", []),
            }

        urls = re.findall(r"https?://[^\s)\]}]+", content, flags=re.I)
        return {
            "verdict": "ANALYSIS COMPLETE",
            "confidence": 75,
            "explanation": content,
            "sources": _clean_sources(urls, grounding_sources),
        }

    def fact_check_text_claims(
        self, text: str, max_claims: int = MAX_CLAIMS
    ) -> List[Dict[str, Any]]:
        self.last_text_error = ""
        if not text:
            return []
        clipped = _truncate(text, 7000)
        current_date = datetime.date.today().isoformat()
        prompt = (
            f"Today's date is {current_date}. "
            f"Extract and fact-check up to {max_claims} concrete factual claims from the provided text. "
            "The text might be an article, a short statement, a question, or a rumor. "
            "If it's a short statement or a direct claim, fact-check it directly. "
            "Use your internal knowledge to verify the claims to the best of your ability. "
            "Do NOT refuse to answer by saying you cannot browse the internet or access current data; provide the best fact-check based on your existing knowledge. "
            "Return ONLY JSON with this exact shape: "
            '{"claims":[{"claim":"...","verdict":"TRUE|FALSE|PARTIALLY TRUE|INSUFFICIENT EVIDENCE|UNVERIFIABLE",'
            '"confidence":85,"explanation":"2-3 sentences","sources":["https://..."]}]}. '
            "Confidence must be an integer from 1 to 100. "
            "Even if the text is short or conversational, identify the core premise and fact-check it. "
            'Only return {"claims":[]} if absolutely no claim can be derived.\n\n'
            f"Text to analyze: {clipped}"
        )

        payload = {
            "model": GEMINI_PRIMARY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "use_web_search": True,
        }
        response = self._post_api(payload)
        if response is None or response.status_code != 200:
            error_msg = _extract_error_message(response)
            print(
                f"DEBUG: Gemini API Error ({response.status_code if response else 'None'}): {error_msg}"
            )
            self.last_text_error = error_msg
            return []
        try:
            response_json = response.json()
            content = response_json["choices"][0]["message"]["content"]
            grounding_sources = _clean_sources(
                response_json.get("grounding_sources", [])
            )
        except Exception:
            self.last_text_error = (
                "Upstream returned an unreadable text analysis response"
            )
            return []

        parsed = _try_parse_json_block(content)
        if isinstance(parsed, list):
            claim_items = parsed
        elif isinstance(parsed, dict):
            if isinstance(parsed.get("claims"), list):
                claim_items = parsed["claims"]
            elif isinstance(parsed.get("claims"), dict):
                claim_items = [parsed["claims"]]
            elif (
                parsed.get("claim")
                or parsed.get("verdict")
                or parsed.get("explanation")
            ):
                claim_items = [parsed]
            else:
                claim_items = []
        else:
            fallback_text = _clean_text(content)
            if not fallback_text or fallback_text.lower() in {
                "none",
                "no claims",
                "no factual claims",
            }:
                return []
            urls = re.findall(r"https?://[^\s)\]}]+", content, flags=re.I)
            return [
                {
                    "claim": "Text claim analysis",
                    "result": {
                        "verdict": "ANALYSIS COMPLETE",
                        "confidence": 60,
                        "explanation": fallback_text,
                        "sources": _clean_sources(urls, grounding_sources),
                    },
                }
            ]
        if not isinstance(claim_items, list):
            return []

        results: List[Dict[str, Any]] = []
        for item in claim_items[:max_claims]:
            if not isinstance(item, dict):
                continue
            claim = _clean_text(str(item.get("claim", "")))
            if not claim:
                claim = _clean_text(
                    str(item.get("statement", "") or item.get("text", ""))
                )
            if not claim and item.get("explanation"):
                claim = "Text claim analysis"
            if not claim:
                continue
            results.append(
                {
                    "claim": claim,
                    "result": {
                        "verdict": item.get("verdict", "INSUFFICIENT EVIDENCE"),
                        "confidence": _coerce_confidence(item.get("confidence", 75)),
                        "explanation": item.get("explanation", "Analysis completed"),
                        "sources": _clean_sources(
                            item.get("sources", []), grounding_sources
                        ),
                    },
                }
            )
        return results

    def refine_results_with_web_evidence(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Search the public web for each claim and rerank/rewrite verdicts against evidence snippets."""
        self.last_text_error = ""
        claims = [
            _clean_search_query(item.get("claim", ""))
            for item in results[:MAX_WEB_EVIDENCE_CLAIMS]
            if isinstance(item, dict) and item.get("claim")
        ]
        evidence_by_claim = _gather_web_evidence_for_claims(claims)
        if not any(evidence_by_claim.values()):
            return results

        def evidence_sources_for(claim: str) -> List[str]:
            evidence = evidence_by_claim.get(_clean_search_query(claim), [])
            return _clean_sources([item.get("url", "") for item in evidence])

        evidence_payload = []
        for item in results[:MAX_WEB_EVIDENCE_CLAIMS]:
            if not isinstance(item, dict) or not item.get("claim"):
                continue
            clean_claim = _clean_search_query(item["claim"])
            evidence = evidence_by_claim.get(clean_claim, [])
            if not evidence:
                continue
            evidence_payload.append(
                {
                    "claim": item["claim"],
                    "current_verdict": item.get("result", {}).get("verdict"),
                    "current_explanation": item.get("result", {}).get("explanation"),
                    "evidence": evidence[:MAX_WEB_EVIDENCE_SOURCES],
                }
            )

        if not evidence_payload:
            return results

        current_date = datetime.date.today().isoformat()
        prompt = (
            f"Today's date is {current_date}. You are a careful fact-checking editor. "
            "Re-check each claim using the provided public web evidence snippets. "
            "Prefer independent reporting, official sources, and primary documents over the original social post. "
            "If the evidence supports the claim, mark TRUE. If it contradicts the claim, mark FALSE or PARTIALLY TRUE. "
            "If the evidence is weak, missing, circular, or only repeats the same social post, mark INSUFFICIENT EVIDENCE. "
            "Use only URLs that appear in the evidence list as sources. "
            "Return ONLY JSON with this exact shape: "
            '{"claims":[{"claim":"...","verdict":"TRUE|FALSE|PARTIALLY TRUE|INSUFFICIENT EVIDENCE|UNVERIFIABLE",'
            '"confidence":85,"explanation":"2-3 sentences describing the evidence used","sources":["https://..."]}]}. '
            f"Evidence package: {json.dumps(evidence_payload, ensure_ascii=False)}"
        )
        payload = {
            "model": GEMINI_PRIMARY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        response = self._post_api(payload)

        updates: Dict[str, Dict[str, Any]] = {}
        if response is not None and response.status_code == 200:
            try:
                content = response.json()["choices"][0]["message"]["content"]
                parsed = _try_parse_json_block(content)
                claim_items = (
                    parsed.get("claims", []) if isinstance(parsed, dict) else parsed
                )
                if isinstance(claim_items, dict):
                    claim_items = [claim_items]
                if isinstance(claim_items, list):
                    for item in claim_items:
                        if isinstance(item, dict) and item.get("claim"):
                            updates[_claim_key(item["claim"])] = item
            except Exception:
                updates = {}
        elif response is not None:
            self.last_text_error = _extract_error_message(response)

        refined: List[Dict[str, Any]] = []
        for item in results:
            if (
                not isinstance(item, dict)
                or not item.get("claim")
                or not isinstance(item.get("result"), dict)
            ):
                refined.append(item)
                continue
            update = updates.get(_claim_key(item["claim"]))
            evidence_sources = evidence_sources_for(item["claim"])
            if update:
                model_sources = _clean_sources(update.get("sources", []))
                item = {
                    "claim": item["claim"],
                    "result": {
                        "verdict": update.get(
                            "verdict",
                            item["result"].get("verdict", "INSUFFICIENT EVIDENCE"),
                        ),
                        "confidence": _coerce_confidence(
                            update.get(
                                "confidence", item["result"].get("confidence", 75)
                            )
                        ),
                        "explanation": update.get(
                            "explanation",
                            item["result"].get("explanation", "Analysis completed"),
                        ),
                        "sources": _dedupe_sources(
                            model_sources + evidence_sources, MAX_WEB_EVIDENCE_SOURCES
                        ),
                    },
                }
            elif evidence_sources and not _clean_sources(
                item["result"].get("sources", [])
            ):
                item["result"]["sources"] = evidence_sources
            refined.append(item)
        return refined

    def extract_image_claims(
        self,
        image_url: Optional[str],
        image_data_url: Optional[str],
        max_claims: int = MAX_IMAGE_CLAIMS,
    ) -> List[str]:
        self.last_image_error = ""
        if not image_url and not image_data_url:
            return []
        current_date = datetime.date.today().isoformat()
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Today's date is {current_date}. "
                            "Analyze this image. It may be a social-media post image, meme, screenshot, chart, news card, headline, or article. "
                            "Focus ONLY on substantive text, numbers, charts, quotes, and statistics visible inside the image. "
                            "CRITICAL: DO NOT just describe what objects or things are in the image (e.g., 'The image displays a flag'). "
                            "Extract the main factual assertions and text-based claims from that content that a third-party could verify. "
                            "Ignore all UI elements, metadata, timestamps, usernames, profile pictures, and engagement metrics (likes/retweets). "
                            "Do NOT extract claims about who posted what or when. "
                            "If the text is short or a single statement, treat it as a claim. "
                            "Return ONLY the claims as a numbered list. If none, respond with 'NONE'."
                        ),
                    }
                ],
            }
        ]
        if image_data_url:
            messages[0]["content"].append(
                {"type": "image_url", "image_url": {"url": image_data_url}}
            )
        else:
            messages[0]["content"].append(
                {"type": "image_url", "image_url": {"url": image_url}}
            )

        payload = {
            "model": GEMINI_PRIMARY_MODEL,
            "messages": messages,
        }
        response = self._post_api(payload)
        if response is None or response.status_code != 200:
            self.last_image_error = _extract_error_message(response)
            return []
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except Exception:
            self.last_image_error = "Upstream returned an unreadable vision response"
            return []
        normalized = content.strip().lower()
        if normalized in {"none", "no claims", "no factual claims"}:
            return []
        claims = []
        for line in content.split("\n"):
            line = line.strip().lstrip("-*")
            if re.match(r"^\d+[\).]", line):
                line = re.sub(r"^\d+[\).]\s*", "", line).strip()
            if re.match(
                r"^(here are|factual claims|claims from the image)\b", line, flags=re.I
            ):
                continue
            if line:
                claims.append(line)
        return claims[:max_claims]

    def fact_check_image_content(
        self,
        image_url: Optional[str],
        image_data_url: Optional[str],
        max_claims: int = MAX_IMAGE_CLAIMS,
    ) -> List[Dict[str, Any]]:
        """Analyze visible image claims and fact-check them in one Gemini call."""
        self.last_image_error = ""
        if not image_url and not image_data_url:
            return []
        current_date = datetime.date.today().isoformat()
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Today's date is {current_date}. "
                            f"Analyze this image and fact-check up to {max_claims} substantive factual claims visible in it. "
                            "The image may be a Reddit/social-media image, meme, screenshot, chart, stock card, headline, or news card. "
                            "Use OCR to extract visible text, labels, quotes, numbers, and charts. "
                            "CRITICAL: DO NOT just describe objects in the image (e.g., 'The image displays a flag'). "
                            "Focus exclusively on extracting and fact-checking assertions, statements, text-based claims, or statistics. "
                            "If the image contains any text, premise, or implied claim, fact-check it. "
                            "Use your extensive internal knowledge base to thoroughly verify these claims. "
                            "Do NOT refuse to answer by saying you cannot browse the internet or access current data; provide the best assessment possible based on your existing knowledge. "
                            "Return ONLY JSON with this exact shape: "
                            '{"claims":[{"claim":"...","verdict":"TRUE|FALSE|PARTIALLY TRUE|INSUFFICIENT EVIDENCE|UNVERIFIABLE",'
                            '"confidence":85,"explanation":"2-3 sentences","sources":["https://..."]}]}. '
                            "Sources must be full http(s) URLs when available. "
                            'Only return {"claims":[]} if absolutely no text or factual assertion is present.'
                        ),
                    }
                ],
            }
        ]
        if image_data_url:
            messages[0]["content"].append(
                {"type": "image_url", "image_url": {"url": image_data_url}}
            )
        else:
            messages[0]["content"].append(
                {"type": "image_url", "image_url": {"url": image_url}}
            )

        payload = {
            "model": GEMINI_PRIMARY_MODEL,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "use_web_search": True,
        }
        response = self._post_api(payload)
        if response is None or response.status_code != 200:
            self.last_image_error = _extract_error_message(response)
            return []
        try:
            response_json = response.json()
            content = response_json["choices"][0]["message"]["content"]
            grounding_sources = _clean_sources(
                response_json.get("grounding_sources", [])
            )
        except Exception:
            self.last_image_error = "Upstream returned an unreadable vision response"
            return []

        parsed = _try_parse_json_block(content)
        if isinstance(parsed, list):
            claim_items = parsed
        elif isinstance(parsed, dict):
            if isinstance(parsed.get("claims"), list):
                claim_items = parsed["claims"]
            elif isinstance(parsed.get("claims"), dict):
                claim_items = [parsed["claims"]]
            elif (
                parsed.get("claim")
                or parsed.get("verdict")
                or parsed.get("explanation")
            ):
                claim_items = [parsed]
            else:
                claim_items = []
        else:
            fallback_text = _clean_text(content)
            if not fallback_text or fallback_text.lower() in {
                "none",
                "no claims",
                "no factual claims",
            }:
                return []
            urls = re.findall(r"https?://[^\s)\]}]+", content, flags=re.I)
            return [
                {
                    "claim": "[Image] Visual claim analysis",
                    "result": {
                        "verdict": "ANALYSIS COMPLETE",
                        "confidence": 60,
                        "explanation": fallback_text,
                        "sources": _clean_sources(urls, grounding_sources),
                    },
                }
            ]
        if not isinstance(claim_items, list):
            return []

        results: List[Dict[str, Any]] = []
        for item in claim_items[:max_claims]:
            if not isinstance(item, dict):
                continue
            claim = _clean_text(str(item.get("claim", "")))
            if not claim:
                claim = _clean_text(
                    str(item.get("statement", "") or item.get("text", ""))
                )
            if not claim and item.get("explanation"):
                claim = "Visual claim analysis"
            if not claim:
                continue
            results.append(
                {
                    "claim": f"[Image] {claim}",
                    "result": {
                        "verdict": item.get("verdict", "INSUFFICIENT EVIDENCE"),
                        "confidence": _coerce_confidence(item.get("confidence", 75)),
                        "explanation": item.get(
                            "explanation", "Visual analysis completed"
                        ),
                        "sources": _clean_sources(
                            item.get("sources", []), grounding_sources
                        ),
                    },
                }
            )
        return results


def _get_checker() -> Tuple[Optional[FactChecker], Optional[str]]:
    try:
        return FactChecker(), None
    except Exception as exc:
        return None, str(exc)


def fact_check_text_input(text: str) -> Tuple[Dict[str, Any], int]:
    checker, checker_error = _get_checker()
    if checker is None:
        return {
            "error": checker_error
            or "No API key configured (set GROQ_API_KEY and/or GEMINI_API_KEY)"
        }, 500
    text = _clean_text(text)
    if not text:
        return {"error": "No text provided"}, 400

    results = checker.fact_check_text_claims(text)
    if results and hasattr(checker, "refine_results_with_web_evidence"):
        results = checker.refine_results_with_web_evidence(results)

    response = {
        "original_text": text,
        "claims_found": len(results),
        "fact_check_results": results,
        "timestamp": time.time(),
    }
    if checker.last_text_error and not results:
        response["analysis_error"] = checker.last_text_error
    return response, 200


def fact_check_image_input(
    image_data_url: Optional[str], image_url: Optional[str]
) -> Tuple[Dict[str, Any], int]:
    checker, checker_error = _get_checker()
    if checker is None:
        return {"error": checker_error or "GEMINI_API_KEY not configured"}, 500

    original_image = image_url or ("data_url" if image_data_url else None)
    if not image_data_url and image_url:
        image_data_url = _download_image_as_data_url(image_url)

    results = checker.fact_check_image_content(
        image_url=image_url, image_data_url=image_data_url
    )
    if results and hasattr(checker, "refine_results_with_web_evidence"):
        results = checker.refine_results_with_web_evidence(results)
    image_analysis_error = checker.last_image_error

    response = {
        "original_image": original_image,
        "claims_found": len(results),
        "fact_check_results": results,
        "timestamp": time.time(),
        "source_url": image_url or None,
    }
    if image_analysis_error and not results:
        response["image_analysis_error"] = image_analysis_error
    return response, 200


def _analyze_single_image_url(api_key: str, image_url: str) -> Dict[str, Any]:
    try:
        checker = FactChecker(api_key=api_key)
        image_data_url = _download_image_as_data_url(image_url)
        checks = checker.fact_check_image_content(
            image_url=None if image_data_url else image_url,
            image_data_url=image_data_url,
        )
        if checker.last_image_error:
            return {
                "image_url": image_url,
                "status": "failed",
                "reason": checker.last_image_error,
                "claims": [],
                "checks": [],
            }
        return {
            "image_url": image_url,
            "status": "ok",
            "claims": [item.get("claim", "") for item in checks if item.get("claim")],
            "checks": checks,
        }
    except Exception as exc:
        return {
            "image_url": image_url,
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "claims": [],
        }


def _analyze_image_urls_with_queue(
    checker: FactChecker, image_urls: List[str]
) -> List[Dict[str, Any]]:
    """Analyze images sequentially to avoid rate-limit exhaustion on free tier."""
    candidates = [url for url in image_urls[:MAX_IMAGES_TO_ANALYZE] if url]
    if not candidates:
        return []

    results: List[Dict[str, Any]] = []
    for image_url in candidates:
        # Rate-limit pause between image analysis calls
        if results:
            time.sleep(GEMINI_INTER_REQUEST_DELAY)
        try:
            result = _analyze_single_image_url(checker.api_key, image_url)
            results.append(result)
        except Exception as exc:
            results.append(
                {
                    "image_url": image_url,
                    "status": "failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "claims": [],
                    "checks": [],
                }
            )

    return results


def fact_check_url_input(url: str) -> Tuple[Dict[str, Any], int]:
    checker, checker_error = _get_checker()
    if checker is None:
        return {"error": checker_error or "GEMINI_API_KEY not configured"}, 500

    url = normalize_url(url)
    if not is_valid_url(url):
        return {"error": "Invalid URL. Only http(s) URLs are supported."}, 400

    content = extract_content_from_url(url)
    text = content.get("text", "")
    title = content.get("title", "")
    image_urls = content.get("image_urls", [])
    image_detection_info = content.get("image_detection_info", {})

    results: List[Dict[str, Any]] = []
    text_analysis_error = ""

    should_analyze_text = bool(text) and (
        not image_urls or _has_substantial_article_text(text) or _has_claim_signal(text)
    )
    if should_analyze_text:
        results.extend(checker.fact_check_text_claims(text))
        text_analysis_error = checker.last_text_error
        # Pause before any subsequent image analysis to avoid rate limits
        if results and image_urls and hasattr(checker, "_rate_limit_pause"):
            checker._rate_limit_pause()

    image_analysis_results: List[Dict[str, Any]] = []
    image_analysis_skipped_reason = ""
    should_analyze_images = bool(image_urls) and not _has_substantial_article_text(text)
    if image_urls and not should_analyze_images:
        image_analysis_skipped_reason = "Visual analysis skipped because article text was available; image analysis is reserved for image-first posts."
    if should_analyze_images:
        image_analysis_results = _analyze_image_urls_with_queue(checker, image_urls)
        for image_result in image_analysis_results:
            checks = image_result.get("checks", [])
            if isinstance(checks, list):
                for item in checks:
                    if (
                        isinstance(item, dict)
                        and item.get("claim")
                        and item.get("result")
                    ):
                        results.append(item)

    if results and hasattr(checker, "refine_results_with_web_evidence"):
        results = checker.refine_results_with_web_evidence(results)

    source_fallback = _clean_sources([url])
    for item in results:
        result = item.get("result") if isinstance(item, dict) else None
        if isinstance(result, dict):
            result["sources"] = _dedupe_sources(
                _clean_sources(result.get("sources", [])) + source_fallback
            )

    response = {
        "original_text": text,
        "claims_found": len(results),
        "fact_check_results": results,
        "timestamp": time.time(),
        "source_url": url,
        "source_title": title,
        "images_detected": len(image_urls),
        "debug_image_urls": image_urls[:10],
        "image_analysis_results": image_analysis_results,
        "image_detection_info": image_detection_info,
    }
    if text_analysis_error and not results:
        response["analysis_error"] = text_analysis_error
    if image_analysis_skipped_reason:
        response["image_analysis_skipped_reason"] = image_analysis_skipped_reason

    if image_detection_info.get("image_detected") and not image_urls:
        response["image_detection_message"] = image_detection_info.get("message", "")

    if image_urls:
        response["selected_image_url"] = image_urls[0]
        image_analysis_errors = [
            item.get("reason", "")
            for item in image_analysis_results
            if item.get("status") == "failed" and item.get("reason")
        ]
        if (
            not any(item.get("claim", "").startswith("[Image]") for item in results)
            and image_analysis_errors
        ):
            response["image_analysis_error"] = image_analysis_errors[0]

    return response, 200
