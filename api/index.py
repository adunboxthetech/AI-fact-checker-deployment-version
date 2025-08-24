from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
import re
from urllib.parse import urlparse, urlunparse, ParseResult, urlencode, parse_qsl, urljoin
from bs4 import BeautifulSoup
from readability import Document

# Perplexity API configuration
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# Enhanced headers for Reddit specifically
REDDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0"
}

# Additional headers that mimic real browser behavior
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"'
}

def process_image_url(image_url):
    """Process image URL to handle redirects and protected URLs"""
    if not image_url:
        return None
    
    try:
        # Handle data URLs
        if image_url.startswith('data:'):
            return image_url
        
        # Handle redirect URLs
        response = requests.head(image_url, headers=DEFAULT_HEADERS, timeout=10, allow_redirects=True)
        if response.status_code == 200:
            return response.url
        
        # If HEAD fails, try GET
        response = requests.get(image_url, headers=DEFAULT_HEADERS, timeout=10, stream=True)
        if response.status_code == 200:
            return response.url
        
        return image_url
    except Exception:
        return image_url

def _extract_reddit_post_id(url: str) -> str:
    """Extract Reddit post ID from URL"""
    patterns = [
        r'/comments/([a-zA-Z0-9]+)/',
        r'/r/\w+/comments/([a-zA-Z0-9]+)/',
        r'redd\.it/([a-zA-Z0-9]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def _build_reddit_json_url(url: str) -> str:
    pu = urlparse(url)
    path = pu.path.rstrip('/')
    if not path.endswith('.json'):
        path += '.json'
    q = dict(parse_qsl(pu.query, keep_blank_values=True))
    q['raw_json'] = '1'
    return urlunparse(pu._replace(path=path, query=urlencode(q)))

def _resolve_url(base, path):
    if not path:
        return None
    return urljoin(base, path)

def _is_image_like(url: str) -> bool:
    if not isinstance(url, str):
        return False
    pu = urlparse(url)
    if re.search(r'\.(jpg|jpeg|png|gif|webp|svg)$', pu.path, re.I):
        return True
    # Allow known image hosts even without extension
    return any(h in pu.netloc for h in [
        "pbs.twimg.com", 
        "i.redd.it", 
        "i.imgur.com",
        "preview.redd.it",
        "external-preview.redd.it",
        "images.redd.it",
        "media.redd.it",
        "redditmedia.com",
        "redditstatic.com"
    ])

def _detect_images_in_text(text_content: str) -> dict:
    """Detect if text content contains image patterns and provide appropriate messaging."""
    try:
        image_patterns = [
            r'pic\.twitter\.com/[a-zA-Z0-9]+',
            r'i\.redd\.it/[a-zA-Z0-9]+',
            r'preview\.redd\.it/[a-zA-Z0-9]+',
            r'imgur\.com/[a-zA-Z0-9]+',
            r'https?://[^\s]+\.(jpg|jpeg|png|gif|webp|svg)',
            r'redditmedia\.com/[^\s]+',
            r'redditstatic\.com/[^\s]+',
            r'pbs\.twimg\.com/[^\s]+',
            r'cdninstagram\.com/[^\s]+',
            r'external-preview\.redd\.it/[^\s]+',
            r'images\.redd\.it/[^\s]+',
            r'media\.redd\.it/[^\s]+'
        ]
        
        has_images = any(re.search(pattern, text_content, re.IGNORECASE) for pattern in image_patterns)
        
        if has_images:
            return {
                "has_images": True,
                "message": "Images detected in this post, but they cannot be accessed directly from the URL. Please provide a screenshot of the image for visual fact-checking.",
                "image_detected": True
            }
        else:
            return {
                "has_images": False,
                "message": "",
                "image_detected": False
            }
    except Exception:
        return {
            "has_images": False,
            "message": "",
            "image_detected": False
        }

def _detect_reddit_images_special(url: str, text_content: str) -> dict:
    """Special detection for Reddit images that might not be in URL or text patterns."""
    try:
        if 'reddit.com' in url or 'redd.it' in url:
            reddit_image_indicators = [
                r'\[.*?\]\(https?://[^\s]+\)',
                r'!\[.*?\]\(https?://[^\s]+\)',
                r'image', r'photo', r'picture', r'img', r'gallery', r'album',
                r'\[img\]', r'\[/img\]', r'<img', r'image post', r'image submission',
                r'posted.*image', r'shared.*image', r'uploaded.*image',
            ]
            
            has_indicators = any(re.search(pattern, text_content, re.IGNORECASE) for pattern in reddit_image_indicators)
            is_likely_image_post = len(text_content.strip()) < 100 and any(word in text_content.lower() for word in ['image', 'photo', 'picture', 'img'])
            
            if has_indicators or is_likely_image_post:
                return {
                    "has_images": True,
                    "message": "Images detected in this Reddit post, but they cannot be accessed directly from the URL. Please provide a screenshot of the image for visual fact-checking.",
                    "image_detected": True
                }
        
        return {
            "has_images": False,
            "message": "",
            "image_detected": False
        }
    except Exception:
        return {
            "has_images": False,
            "message": "",
            "image_detected": False
        }

def _detect_images_in_url(url: str) -> dict:
    """Detect if a URL contains images and provide appropriate messaging."""
    try:
        image_patterns = [
            r'pic\.twitter\.com',
            r'i\.redd\.it',
            r'preview\.redd\.it',
            r'imgur\.com',
            r'\.(jpg|jpeg|png|gif|webp|svg)',
            r'redditmedia\.com',
            r'redditstatic\.com',
            r'external-preview\.redd\.it',
            r'images\.redd\.it',
            r'media\.redd\.it'
        ]
        
        has_images = any(re.search(pattern, url, re.IGNORECASE) for pattern in image_patterns)
        
        if has_images:
            return {
                "has_images": True,
                "message": "Images detected in this post, but they cannot be accessed directly from the URL. Please provide a screenshot of the image for visual fact-checking.",
                "image_detected": True
            }
        else:
            return {
                "has_images": False,
                "message": "",
                "image_detected": False
            }
    except Exception:
        return {
            "has_images": False,
            "message": "",
            "image_detected": False
        }

# Twitter extraction functions
def _try_twitter_syndication_api(url: str) -> dict:
    """Try Twitter's syndication API"""
    match = re.search(r'/status/(\d+)', url)
    if not match:
        return None
    
    tweet_id = match.group(1)
    api_url = f"https://cdn.syndication.twimg.com/widgets/tweet?id={tweet_id}&lang=en"
    
    try:
        r = requests.get(api_url, headers=DEFAULT_HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            text_content = data.get('text', '').strip()
            
            image_urls = []
            for photo in data.get('photos', []):
                if photo.get('url'):
                    image_urls.append(photo['url'])
            
            if data.get('video', {}).get('poster'):
                image_urls.append(data['video']['poster'])
            
            return {"text": text_content, "images": image_urls}
    except Exception:
        pass
    
    return None

def _try_twitter_oembed_api(url: str) -> dict:
    """Try Twitter's oEmbed API"""
    try:
        oembed_url = f"https://publish.twitter.com/oembed?url={url}"
        r = requests.get(oembed_url, headers=DEFAULT_HEADERS, timeout=15)
        if r.status_code == 200:
            oembed_data = r.json()
            html_content = oembed_data.get('html', '')
            if html_content:
                soup = BeautifulSoup(html_content, 'lxml')
                
                # Extract text from blockquote
                blockquote = soup.find('blockquote')
                text_content = ""
                if blockquote:
                    for link in blockquote.find_all('a'):
                        link.decompose()
                    text_content = blockquote.get_text(strip=True)
                    text_content = re.sub(r'pic\.twitter\.com/\w+', '', text_content)
                    text_content = text_content.strip()
                
                # Extract images
                image_urls = []
                for img in soup.find_all('img'):
                    src = img.get('src')
                    if src and _is_image_like(src):
                        image_urls.append(src)
                
                return {"text": text_content, "images": image_urls}
    except Exception:
        pass
    
    return None

def _try_twitter_with_enhanced_headers(url: str) -> dict:
    """Try Twitter with enhanced headers"""
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            
            # Try to extract tweet content
            selectors = ['div[data-testid="tweetText"]', 'div[lang]', '[data-testid="tweet"] div[lang]']
            text_content = ""
            
            for selector in selectors:
                elements = soup.select(selector)
                for element in elements:
                    candidate_text = element.get_text(strip=True)
                    if candidate_text and len(candidate_text) > 10:
                        text_content = candidate_text
                        break
                if text_content:
                    break
            
            # Extract images
            image_urls = []
            for img in soup.find_all('img'):
                src = img.get('src')
                if src and _is_image_like(src):
                    image_urls.append(src)
            
            return {"text": text_content, "images": image_urls}
    except Exception:
        pass
    
    return None

def _try_twitter_mobile(url: str) -> dict:
    """Try Twitter mobile version"""
    try:
        mobile_url = url.replace('twitter.com', 'mobile.twitter.com').replace('x.com', 'mobile.twitter.com')
        r = requests.get(mobile_url, headers=BROWSER_HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            
            text_content = ""
            title_elem = soup.find('title')
            if title_elem:
                text_content = title_elem.get_text().strip()
            
            image_urls = []
            for img in soup.find_all('img'):
                src = img.get('src')
                if src and _is_image_like(src):
                    image_urls.append(src)
            
            return {"text": text_content, "images": image_urls}
    except Exception:
        pass
    
    return None

def _try_twitter_with_session(url: str) -> dict:
    """Try Twitter with session"""
    try:
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            
            text_content = ""
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc:
                text_content = meta_desc.get('content', '').strip()
            
            image_urls = []
            for img in soup.find_all('img'):
                src = img.get('src')
                if src and _is_image_like(src):
                    image_urls.append(src)
            
            return {"text": text_content, "images": image_urls}
    except Exception:
        pass
    
    return None

def _try_generic_twitter_scraper(url: str) -> dict:
    """Generic Twitter scraper as last resort"""
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            
            # Try meta tags
            text_content = ""
            for meta_name in ['description', 'twitter:description', 'og:description']:
                meta = soup.find('meta', attrs={'name': meta_name}) or soup.find('meta', attrs={'property': meta_name})
                if meta:
                    text_content = meta.get('content', '').strip()
                    break
            
            # Extract images from meta tags
            image_urls = []
            for meta_name in ['twitter:image', 'og:image']:
                meta = soup.find('meta', attrs={'name': meta_name}) or soup.find('meta', attrs={'property': meta_name})
                if meta:
                    src = meta.get('content')
                    if src and _is_image_like(src):
                        image_urls.append(src)
            
            return {"text": text_content, "images": image_urls}
    except Exception:
        pass
    
    return None

# Include all your Reddit extraction functions here...
def _try_reddit_api_with_id(url: str) -> dict:
    """Try to extract content using Reddit post ID and API"""
    post_id = _extract_reddit_post_id(url)
    if not post_id:
        return None
    
    try:
        oembed_url = f"https://www.reddit.com/oembed?url={url}"
        r = requests.get(oembed_url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            text_content = data.get('title', '')
            if data.get('description'):
                text_content += f" {data['description']}"
            
            image_urls = []
            if data.get('thumbnail_url'):
                image_urls.append(data['thumbnail_url'])
            
            return {"text": text_content, "images": image_urls}
    except Exception:
        pass
    
    return None

def _try_reddit_json_api_robust(url: str) -> dict:
    """Try Reddit's JSON API with multiple header variations"""
    json_url = _build_reddit_json_url(url)
    
    header_sets = [REDDIT_HEADERS, BROWSER_HEADERS]
    
    for headers in header_sets:
        try:
            r = requests.get(json_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                post_data = data[0]['data']['children'][0]['data']
                text_content = f"{post_data.get('title', '')} {post_data.get('selftext', '')}".strip()
                
                image_urls = []
                
                # Extract images from various sources
                if post_data.get('url_overridden_by_dest') and _is_image_like(post_data['url_overridden_by_dest']):
                    image_urls.append(post_data['url_overridden_by_dest'])
                
                if 'preview' in post_data and post_data['preview'].get('images'):
                    for img in post_data['preview']['images']:
                        if img.get('source') and img['source'].get('url'):
                            img_url = img['source']['url'].replace('&amp;', '&')
                            image_urls.append(img_url)
                
                if 'media_metadata' in post_data:
                    for media_id in post_data['media_metadata']:
                        media = post_data['media_metadata'][media_id]
                        if media.get('e') == 'Image' and media.get('s'):
                            if media['s'].get('u'):
                                img_url = media['s']['u'].replace('&amp;', '&')
                                image_urls.append(img_url)
                
                unique_images = []
                seen_urls = set()
                for img_url in image_urls:
                    if img_url and img_url not in seen_urls and _is_image_like(img_url):
                        unique_images.append(img_url)
                        seen_urls.add(img_url)
                
                return {"text": text_content, "images": unique_images}
        except Exception:
            continue
    
    return None

# Continue with other Reddit functions...
def _try_reddit_with_rotating_ua(url: str) -> dict:
    """Try Reddit with rotating User-Agents"""
    user_agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
    
    for ua in user_agents:
        try:
            headers = {**BROWSER_HEADERS, "User-Agent": ua}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                
                title_elem = soup.find('h1') or soup.find('h2') or soup.find('h3')
                title = title_elem.get_text().strip() if title_elem else ""
                
                image_urls = []
                for img in soup.find_all('img'):
                    src = img.get('src')
                    if src and _is_image_like(src):
                        image_urls.append(_resolve_url(url, src))
                
                if title:
                    return {"text": title, "images": image_urls}
        except Exception:
            continue
    
    return None

def _try_reddit_mobile_enhanced(url: str) -> dict:
    """Try Reddit's mobile version"""
    try:
        mobile_url = url.replace('www.reddit.com', 'm.reddit.com')
        r = requests.get(mobile_url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            
            title_elem = soup.find('h1') or soup.find('h2') or soup.find('h3')
            title = title_elem.get_text().strip() if title_elem else ""
            
            image_urls = []
            for img in soup.find_all('img'):
                src = img.get('src')
                if src and _is_image_like(src):
                    image_urls.append(src)
            
            return {"text": title, "images": image_urls}
    except Exception:
        pass
    return None

def _try_old_reddit_robust(url: str) -> dict:
    """Try old.reddit.com"""
    try:
        old_url = url.replace('www.reddit.com', 'old.reddit.com')
        r = requests.get(old_url, headers=BROWSER_HEADERS, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            
            title_elem = soup.find('a', class_='title') or soup.find('h1')
            title = title_elem.get_text().strip() if title_elem else ""
            
            image_urls = []
            for img in soup.find_all('img'):
                src = img.get('src')
                if src and _is_image_like(src):
                    image_urls.append(src)
            
            return {"text": title, "images": image_urls}
    except Exception:
        pass
    return None

def _try_reddit_with_session(url: str) -> dict:
    """Try Reddit with session"""
    try:
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        
        r = session.get(url, timeout=10)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'lxml')
            
            title_elem = soup.find('h1') or soup.find('h2')
            title = title_elem.get_text().strip() if title_elem else ""
            
            image_urls = []
            for img in soup.find_all('img'):
                src = img.get('src')
                if src and _is_image_like(src):
                    image_urls.append(src)
            
            return {"text": title, "images": image_urls}
    except Exception:
        pass
    return None

def _try_generic_reddit_scraper_robust(url: str) -> dict:
    """Generic scraper for Reddit as last resort"""
    header_sets = [BROWSER_HEADERS, REDDIT_HEADERS]
    
    for headers in header_sets:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                html = r.text
                doc = Document(html)
                text_content = BeautifulSoup(doc.summary(), 'lxml').get_text(' ', strip=True)
                
                soup = BeautifulSoup(html, 'lxml')
                image_urls = []
                for img in soup.find_all('img'):
                    src = img.get('src')
                    if src and _is_image_like(src):
                        image_urls.append(_resolve_url(url, src))
                
                if text_content and len(text_content.strip()) > 10:
                    return {"text": text_content, "images": image_urls}
        except Exception:
            continue
    
    return None

def extract_content_from_url(url: str) -> dict:
    """Main content extraction function with your comprehensive approach"""
    parsed_url = urlparse(url)
    netloc = parsed_url.netloc
    text_content = ""
    image_urls = []
    image_detection_info = _detect_images_in_url(url)

    try:
        # Twitter/X handler with multiple approaches
        if 'twitter.com' in netloc or 'x.com' in netloc:
            approaches = [
                lambda: _try_twitter_syndication_api(url),
                lambda: _try_twitter_oembed_api(url),
                lambda: _try_twitter_with_enhanced_headers(url),
                lambda: _try_twitter_mobile(url),
                lambda: _try_twitter_with_session(url),
                lambda: _try_generic_twitter_scraper(url)
            ]
            
            for i, approach in enumerate(approaches):
                try:
                    result = approach()
                    if result and result.get('text') and len(result['text'].strip()) > 5:
                        text_content = result['text']
                        image_urls = result.get('images', [])
                        print(f"Twitter extraction succeeded with approach {i+1}")
                        break
                except Exception as e:
                    print(f"Twitter approach {i+1} failed: {str(e)}")
                    continue

        # Reddit handler with multiple approaches
        elif 'reddit.com' in netloc or 'redd.it' in netloc:
            approaches = [
                lambda: _try_reddit_api_with_id(url),
                lambda: _try_reddit_json_api_robust(url),
                lambda: _try_reddit_with_rotating_ua(url),
                lambda: _try_reddit_mobile_enhanced(url),
                lambda: _try_old_reddit_robust(url),
                lambda: _try_reddit_with_session(url),
                lambda: _try_generic_reddit_scraper_robust(url)
            ]
            
            for i, approach in enumerate(approaches):
                try:
                    result = approach()
                    if result and result.get('text') and len(result['text'].strip()) > 10:
                        text_content = result['text']
                        image_urls = result.get('images', [])
                        print(f"Reddit extraction succeeded with approach {i+1}")
                        break
                except Exception as e:
                    print(f"Reddit approach {i+1} failed: {str(e)}")
                    continue

        # Generic URL handler
        if not text_content:
            try:
                r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
                r.raise_for_status()
                html = r.text
                doc = Document(html)
                text_content = BeautifulSoup(doc.summary(), 'lxml').get_text(' ', strip=True)
                if len(text_content) < 150:
                    text_content = BeautifulSoup(html, 'lxml').get_text(' ', strip=True)
                
                soup = BeautifulSoup(html, 'lxml')
                for prop in ['og:image', 'og:image:secure_url', 'twitter:image']:
                    meta = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
                    if meta and meta.get('content'):
                        image_urls.append(_resolve_url(url, meta['content']))
                
                for img in soup.find_all('img'):
                    src = img.get('src') or img.get('data-src')
                    if src:
                        image_urls.append(_resolve_url(url, src))

            except requests.RequestException as e:
                raise ValueError(f"Failed to fetch URL: {e}")

    except Exception as e:
        return {"text": f"Extraction failed: {e}", "image_urls": []}

    # Clean up text content
    text_content = ' '.join(text_content.split())
    if len(text_content) > 12000:
        text_content = text_content[:12000] + '…'

    # Filter and deduplicate image URLs
    unique_images = sorted(list(set(filter(None, image_urls))))
    final_images = [img for img in unique_images if _is_image_like(img)]

    # Enhanced image detection
    url_image_detection = _detect_images_in_url(url)
    text_image_detection = _detect_images_in_text(text_content)
    reddit_special_detection = _detect_reddit_images_special(url, text_content)
    
    combined_image_detection = {
        "has_images": url_image_detection["has_images"] or text_image_detection["has_images"] or reddit_special_detection["has_images"],
        "image_detected": url_image_detection["image_detected"] or text_image_detection["image_detected"] or reddit_special_detection["image_detected"],
        "message": ""
    }
    
    if combined_image_detection["image_detected"] and len(final_images) == 0:
        if reddit_special_detection["message"]:
            combined_image_detection["message"] = reddit_special_detection["message"]
        elif text_image_detection["message"]:
            combined_image_detection["message"] = text_image_detection["message"]
        elif url_image_detection["message"]:
            combined_image_detection["message"] = url_image_detection["message"]
        else:
            combined_image_detection["message"] = "Images detected in this post, but they cannot be accessed directly from the URL. Please provide a screenshot of the image for visual fact-checking."

    return {
        "text": text_content or "No text content found.",
        "image_urls": final_images[:10],
        "image_detection_info": combined_image_detection
    }

def clean_json_response(content):
    """Clean JSON response by removing markdown formatting"""
    if not content:
        return content
        
    # Remove markdown code blocks
    content = re.sub(r'```(?:json)?\s*', '', content, flags=re.DOTALL)
    # Remove any remaining markdown syntax
    content = re.sub(r'^json\s+', '', content.strip())
    
    # Find JSON content
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        return json_match.group(0)
    
    return content

def fact_check_text(text):
    """Complete fact-check function with proper JSON handling"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""
You are a fact-checking assistant. Analyze the following text and fact-check any factual claims.

TEXT TO ANALYZE: {text}

TASK: If you find factual claims, provide a fact-check analysis. If no factual claims are found, indicate this.

RESPONSE FORMAT: Return ONLY a valid JSON object with this exact structure:

{{
    "verdict": "TRUE",
    "confidence": 95,
    "explanation": "Your explanation here in plain text, not JSON format",
    "sources": ["https://example.com/source1", "https://example.com/source2"]
}}

VERDICT OPTIONS: TRUE, FALSE, PARTIALLY TRUE, INSUFFICIENT EVIDENCE, NO FACTUAL CLAIMS
CONFIDENCE: 0-100 (integer)
EXPLANATION: Plain text explanation, not JSON
SOURCES: Array of URLs as strings

CRITICAL REQUIREMENTS: 
- Return ONLY the JSON object
- Do not include any text before or after
- Do not format the explanation as JSON
- Use plain text for the explanation field
- Do not prefix with "json" or any other text
- The response must be parseable by JSON.parse()
"""
    
    try:
        response = requests.post(
            PERPLEXITY_URL,
            headers=headers,
            json={
                "model": "sonar-pro",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            try:
                clean_content = clean_json_response(content)
                parsed = json.loads(clean_content)
                
                fact_check_result = {
                    "claim": text[:200] + "..." if len(text) > 200 else text,
                    "result": parsed,
                    "status": "ANALYSIS COMPLETE"
                }
                
                return {
                    "fact_check_results": [fact_check_result],
                    "original_text": text,
                    "claims_found": 1,
                    "timestamp": time.time()
                }, 200
                
            except json.JSONDecodeError:
                # Fallback parsing
                verdict_match = re.search(r'"verdict":\s*"([^"]+)"', content, re.IGNORECASE)
                confidence_match = re.search(r'"confidence":\s*(\d+)', content, re.IGNORECASE)
                explanation_match = re.search(r'"explanation":\s*"([^"]+)"', content, re.IGNORECASE)
                sources_match = re.search(r'"sources":\s*\[(.*?)\]', content, re.IGNORECASE | re.DOTALL)
                
                verdict = verdict_match.group(1) if verdict_match else "INSUFFICIENT EVIDENCE"
                confidence = int(confidence_match.group(1)) if confidence_match else 75
                explanation = explanation_match.group(1) if explanation_match else content
                sources = ["Perplexity Analysis"]
                
                if sources_match:
                    sources_text = sources_match.group(1)
                    url_matches = re.findall(r'https?://[^"\s,]+', sources_text)
                    if url_matches:
                        sources = url_matches
                    else:
                        all_urls = re.findall(r'https?://[^"\s,]+', content)
                        if all_urls:
                            sources = all_urls[:5]
                
                fact_check_result = {
                    "claim": text[:200] + "..." if len(text) > 200 else text,
                    "result": {
                        "verdict": verdict,
                        "confidence": confidence,
                        "explanation": explanation,
                        "sources": sources
                    },
                    "status": "ANALYSIS COMPLETE"
                }
                
                return {
                    "fact_check_results": [fact_check_result],
                    "original_text": text,
                    "claims_found": 1,
                    "timestamp": time.time()
                }, 200
        else:
            return {"error": f"API request failed: {response.status_code}"}, 500
    
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}, 500

def fact_check_image(image_data_url, image_url):
    """Fact-check image content using Perplexity vision"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        messages = [{
            "role": "user",
            "content": [{
                "type": "text", 
                "text": (
                    "Analyze this image for factual claims. Look for:\n"
                    "1. Any text, quotes, or statements in the image\n"
                    "2. Charts, graphs, or data visualizations\n"
                    "3. Statistics, numbers, or factual information\n"
                    "4. Names, dates, locations, or attributions\n\n"
                    "Return ONLY a JSON object with NO code blocks:\n"
                    '{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 85, "explanation": "Your analysis", "sources": ["url1"]}'
                )
            }]
        }]
        
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        elif image_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_url})
        
        payload = {
            "model": "sonar-pro",
            "messages": messages,
            "max_tokens": 800
        }
        
        response = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=45)
        
        if response.status_code != 200:
            return {"error": f"Analysis failed: HTTP {response.status_code}"}, 500
        
        content = response.json()['choices'][0]['message']['content']
        
        try:
            clean_content = clean_json_response(content)
            parsed = json.loads(clean_content)
            
            result = {
                "fact_check_results": [{
                    "claim": "Image Analysis",
                    "result": {
                        "verdict": parsed.get("verdict", "INSUFFICIENT EVIDENCE"),
                        "confidence": parsed.get("confidence", 75),
                        "explanation": parsed.get("explanation", "Analysis completed"),
                        "sources": parsed.get("sources", [])
                    }
                }],
                "claims_found": 1 if parsed.get("verdict") != "NO FACTUAL CLAIMS" else 0,
                "timestamp": time.time(),
                "source_url": image_url if image_url else None
            }
            
            return result, 200
        
        except json.JSONDecodeError:
            return {
                "fact_check_results": [{
                    "claim": "Image Analysis",
                    "result": {
                        "verdict": "INSUFFICIENT EVIDENCE",
                        "confidence": 75,
                        "explanation": content,
                        "sources": []
                    }
                }],
                "claims_found": 1,
                "timestamp": time.time()
            }, 200
    
    except Exception as e:
        return {"error": f"Analysis failed: {str(e)}"}, 500

def fact_check_url_with_images(url):
    """Main function that extracts and fact-checks both text and images"""
    try:
        print(f"\n=== STARTING FACT-CHECK FOR: {url} ===")
        
        # Extract content using your comprehensive approach
        content = extract_content_from_url(url)
        text = content.get("text", "").strip()
        image_urls = content.get("image_urls", [])
        image_detection_info = content.get("image_detection_info", {})
        
        print(f"EXTRACTION RESULT: Text={len(text)} chars, Images={len(image_urls)}")
        
        all_results = []
        
        # Fact-check text if meaningful content exists
        if text and len(text) > 10 and "extraction failed" not in text.lower():
            try:
                text_result, status_code = fact_check_text(text)
                if status_code == 200 and isinstance(text_result, dict):
                    text_fact_checks = text_result.get('fact_check_results', [])
                    for result in text_fact_checks:
                        result['source_type'] = 'text'
                        all_results.append(result)
                    print(f"✅ Text analysis: {len(text_fact_checks)} claims")
            except Exception as e:
                print(f"❌ Text analysis failed: {e}")
        
        # Fact-check each accessible image
        image_analysis_results = []
        for i, img_url in enumerate(image_urls):
            try:
                print(f"🖼️ Analyzing image {i+1}: {img_url}")
                img_result, status_code = fact_check_image("", img_url)
                
                if status_code == 200 and isinstance(img_result, dict):
                    img_fact_checks = img_result.get('fact_check_results', [])
                    
                    image_result_summary = {
                        "image_url": img_url,
                        "claims_found": len(img_fact_checks),
                        "fact_check_results": img_fact_checks
                    }
                    
                    image_analysis_results.append(image_result_summary)
                    
                    for fact_check in img_fact_checks:
                        fact_check_copy = fact_check.copy()
                        fact_check_copy['source_type'] = 'image'
                        fact_check_copy['image_url'] = img_url
                        all_results.append(fact_check_copy)
                    
                    print(f"✅ Image {i+1} analysis: {len(img_fact_checks)} claims")
                        
            except Exception as e:
                print(f"❌ Image {i+1} analysis failed: {e}")
        
        platform = get_platform_name(url)
        
        return {
            "original_text": text,
            "fact_check_results": all_results,
            "image_analysis_results": image_analysis_results,
            "claims_found": len(all_results),
            "images_processed": len(image_analysis_results),
            "timestamp": time.time(),
            "source_url": url,
            "platform": platform,
            "image_detection_info": image_detection_info
        }, 200
        
    except Exception as e:
        print(f"❌ URL analysis failed: {e}")
        return {"error": f"URL analysis failed: {str(e)}"}, 500

def get_platform_name(url):
    """Get platform name from URL"""
    if 'twitter.com' in url or 'x.com' in url:
        return "Twitter/X"
    elif 'reddit.com' in url:
        return "Reddit"
    elif 'instagram.com' in url:
        return "Instagram"
    elif 'facebook.com' in url:
        return "Facebook"
    else:
        return "Web"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/health':
            response_data = {
                "status": "healthy",
                "timestamp": time.time(),
                "api_key_set": bool(PERPLEXITY_API_KEY)
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode())
        else:
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            return
        
        response_data = {"error": "Unknown error"}
        status_code = 500
        
        if self.path == '/api/fact-check':
            text = data.get('text', '')
            url = data.get('url', '')
            
            if not text and not url:
                response_data = {"error": "No text or URL provided"}
                status_code = 400
            else:
                try:
                    if url:
                        response_data, status_code = fact_check_url_with_images(url)
                    else:
                        response_data, status_code = fact_check_text(text)
                except Exception as e:
                    response_data = {"error": f"Analysis failed: {str(e)}"}
                    status_code = 500
        
        elif self.path == '/api/fact-check-image':
            image_data_url = data.get('image_data_url', '')
            image_url = data.get('image_url', '')
            
            if not image_data_url and not image_url:
                response_data = {"error": "No image provided"}
                status_code = 400
            else:
                try:
                    response_data, status_code = fact_check_image(image_data_url, image_url)
                except Exception as e:
                    response_data = {"error": f"Image analysis failed: {str(e)}"}
                    status_code = 500
        else:
            response_data = {"error": "Endpoint not found"}
            status_code = 404
        
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
