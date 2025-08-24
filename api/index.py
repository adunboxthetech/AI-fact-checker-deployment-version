from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
import re
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl, urljoin
from bs4 import BeautifulSoup
from readability import Document

# Perplexity API configuration
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

# Anti-blocking headers
STEALTH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
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
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

def _build_reddit_json_url(url):
    """Convert Reddit URL to JSON API URL"""
    pu = urlparse(url)
    path = pu.path.rstrip('/')
    if not path.endswith('.json'):
        path += '.json'
    q = dict(parse_qsl(pu.query, keep_blank_values=True))
    q['raw_json'] = '1'
    return urlunparse(pu._replace(path=path, query=urlencode(q)))

def _is_image_like(url):
    """Enhanced image detection for social media platforms"""
    if not isinstance(url, str):
        return False
    
    pu = urlparse(url)
    path_lower = pu.path.lower()
    netloc_lower = pu.netloc.lower()
    
    # Direct image extensions
    if re.search(r'\.(jpg|jpeg|png|gif|webp|svg|bmp|tiff|avif)(\?|$)', path_lower):
        return True
    
    # Image hosting domains
    image_hosts = [
        "pbs.twimg.com", "pic.twitter.com", "i.redd.it", "i.imgur.com", 
        "imgur.com", "preview.redd.it", "media.githubusercontent.com"
    ]
    
    for host in image_hosts:
        if host in netloc_lower:
            return True
    
    return False

def extract_content_from_url(url):
    """Clean content extraction that doesn't return error messages as content"""
    parsed_url = urlparse(url)
    netloc = parsed_url.netloc
    text_content = ""
    image_urls = []
    
    print(f"🔍 EXTRACTING: {url}")
    
    try:
        # Twitter/X handler
        if 'twitter.com' in netloc or 'x.com' in netloc:
            match = re.search(r'/status/(\d+)', parsed_url.path)
            if match:
                tweet_id = match.group(1)
                
                # Twitter syndication API
                try:
                    api_url = f"https://cdn.syndication.twimg.com/widgets/tweet?id={tweet_id}&lang=en"
                    r = requests.get(api_url, headers=STEALTH_HEADERS, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        text_content = data.get('text', '').strip()
                        
                        # Extract images
                        for photo in data.get('photos', []):
                            if photo.get('url'):
                                image_urls.append(photo['url'])
                                
                        if data.get('video', {}).get('poster'):
                            image_urls.append(data['video']['poster'])
                            
                        print(f"📱 Twitter: {len(image_urls)} images, {len(text_content)} chars text")
                except Exception as e:
                    print(f"❌ Twitter API failed: {e}")
                
                # oEmbed fallback
                if not image_urls:
                    try:
                        oembed_url = f"https://publish.twitter.com/oembed?url={url}"
                        r = requests.get(oembed_url, headers=STEALTH_HEADERS, timeout=15)
                        if r.status_code == 200:
                            oembed_data = r.json()
                            html_content = oembed_data.get('html', '')
                            if html_content:
                                soup = BeautifulSoup(html_content, 'lxml')
                                for img in soup.find_all('img'):
                                    src = img.get('src')
                                    if src and _is_image_like(src):
                                        image_urls.append(src)
                    except Exception as e:
                        print(f"❌ oEmbed failed: {e}")
        
        # Reddit handler - CLEAN VERSION
        elif 'reddit.com' in netloc or 'redd.it' in netloc:
            try:
                json_url = _build_reddit_json_url(url)
                r = requests.get(json_url, headers=STEALTH_HEADERS, timeout=15)
                
                if r.status_code == 200:
                    data = r.json()
                    post_data = data[0]['data']['children'][0]['data']
                    
                    # Extract text
                    title = post_data.get('title', '').strip()
                    selftext = post_data.get('selftext', '').strip()
                    text_content = f"{title} {selftext}".strip()
                    
                    # Extract images
                    if post_data.get('url_overridden_by_dest'):
                        img_url = post_data['url_overridden_by_dest']
                        if _is_image_like(img_url):
                            image_urls.append(img_url)
                    
                    if 'preview' in post_data:
                        for img_data in post_data['preview'].get('images', []):
                            img_src = img_data['source']['url'].replace('&amp;', '&')
                            if _is_image_like(img_src):
                                image_urls.append(img_src)
                    
                    if 'media_metadata' in post_data:
                        for media_id, media in post_data['media_metadata'].items():
                            if media.get('e') == 'Image' and media.get('s', {}).get('u'):
                                img_url = media['s']['u'].replace('&amp;', '&')
                                if _is_image_like(img_url):
                                    image_urls.append(img_url)
                    
                    print(f"📊 Reddit: {len(image_urls)} images, {len(text_content)} chars text")
                
                else:
                    print(f"❌ Reddit access blocked: {r.status_code}")
                    # DON'T return error message as content - just return empty
                    return {"text": "", "image_urls": []}
                    
            except Exception as e:
                print(f"❌ Reddit failed: {e}")
                # DON'T return error message as content - just return empty
                return {"text": "", "image_urls": []}
        
        # Generic handler
        else:
            try:
                r = requests.get(url, headers=STEALTH_HEADERS, timeout=15, allow_redirects=True)
                if r.status_code == 200:
                    doc = Document(r.text)
                    text_content = BeautifulSoup(doc.summary(), 'lxml').get_text(' ', strip=True)
                    
                    soup = BeautifulSoup(r.text, 'lxml')
                    for prop in ['og:image', 'twitter:image']:
                        meta = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
                        if meta and meta.get('content'):
                            image_urls.append(meta['content'])
            except Exception as e:
                print(f"❌ Generic extraction failed: {e}")
    
    except Exception as e:
        print(f"❌ Overall extraction failed: {e}")
        # DON'T return error messages as content
        return {"text": "", "image_urls": []}
    
    # Clean up text
    if text_content:
        text_content = re.sub(r'pic\.twitter\.com/\w+', '', text_content)
        text_content = re.sub(r'https://t\.co/\w+', '', text_content)
        text_content = ' '.join(text_content.split()).strip()
        if len(text_content) > 12000:
            text_content = text_content[:12000] + '…'
    
    # Deduplicate images
    final_images = []
    seen = set()
    for img_url in image_urls:
        if img_url and img_url not in seen:
            final_images.append(img_url)
            seen.add(img_url)
    
    print(f"🎯 FINAL: Text={len(text_content)} chars, Images={len(final_images)}")
    
    return {
        "text": text_content,
        "image_urls": final_images
    }

def clean_json_response(content):
    """Clean JSON response by removing markdown formatting"""
    content = re.sub(r'```', '', content)
    content = re.sub(r'```\s*', '', content)
    content = re.sub(r'^json\s+', '', content.strip())
    
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        return json_match.group(0)
    
    return content

def fact_check_text(text):
    """Fact-check text content - ONLY if it's actual content, not error messages"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    # DON'T fact-check error messages or empty content
    if not text or len(text.strip()) < 10:
        return {"error": "No meaningful content to fact-check"}, 400
    
    # DON'T fact-check if it looks like an error message
    error_indicators = [
        "failed to extract",
        "access restrictions",
        "content blocked",
        "extraction failed",
        "unable to access",
        "error:"
    ]
    
    if any(indicator in text.lower() for indicator in error_indicators):
        return {"error": "Cannot fact-check error messages"}, 400
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""
Analyze this text for factual claims:

TEXT: {text}

Return ONLY a JSON object with NO markdown formatting:

{{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 85, "explanation": "Your analysis here", "sources": ["https://example.com"]}}

CRITICAL: Return ONLY the JSON object with no other text, no code blocks, no formatting.
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
                
                return {
                    "fact_check_results": [{
                        "claim": text[:200] + "..." if len(text) > 200 else text,
                        "result": parsed
                    }],
                    "original_text": text,
                    "claims_found": 1,
                    "timestamp": time.time()
                }, 200
                
            except json.JSONDecodeError:
                return {
                    "fact_check_results": [{
                        "claim": text[:200] + "..." if len(text) > 200 else text,
                        "result": {
                            "verdict": "INSUFFICIENT EVIDENCE",
                            "confidence": 75,
                            "explanation": "Analysis completed but response format was invalid",
                            "sources": ["Perplexity Analysis"]
                        }
                    }],
                    "original_text": text,
                    "claims_found": 1,
                    "timestamp": time.time()
                }, 200
        else:
            return {"error": f"API request failed: {response.status_code}"}, 500
    
    except Exception as e:
        return {"error": f"Request failed: {str(e)}"}, 500

def fact_check_image(image_data_url, image_url):
    """Direct image analysis"""
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
                        "explanation": "Image analysis completed but format was invalid",
                        "sources": []
                    }
                }],
                "claims_found": 1,
                "timestamp": time.time()
            }, 200
    
    except Exception as e:
        return {"error": f"Analysis failed: {str(e)}"}, 500

def fact_check_url_with_images(url):
    """Main function with proper error handling"""
    try:
        print(f"\n=== STARTING FACT-CHECK FOR: {url} ===")
        
        # Extract content
        content = extract_content_from_url(url)
        text = content.get("text", "").strip()
        image_urls = content.get("image_urls", [])
        
        print(f"EXTRACTION RESULT: Text={len(text)} chars, Images={len(image_urls)}")
        
        all_results = []
        
        # Only fact-check text if we have actual content (not error messages)
        if text and len(text) > 10:
            try:
                text_result, status_code = fact_check_text(text)
                if status_code == 200 and isinstance(text_result, dict):
                    text_fact_checks = text_result.get('fact_check_results', [])
                    for result in text_fact_checks:
                        result['source_type'] = 'text'
                        all_results.append(result)
                    print(f"✅ Text analysis: {len(text_fact_checks)} claims")
                elif status_code == 400:
                    print(f"⚠️ Skipping text analysis: {text_result.get('error', 'Invalid content')}")
            except Exception as e:
                print(f"❌ Text analysis failed: {e}")
        else:
            print(f"⚠️ No meaningful text content to analyze")
        
        # Fact-check images
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
        
        # Handle case where nothing could be extracted
        if len(all_results) == 0 and len(text) == 0:
            return {
                "error": f"Unable to extract content from {platform} due to access restrictions",
                "original_text": "",
                "fact_check_results": [],
                "image_analysis_results": [],
                "claims_found": 0,
                "images_processed": 0,
                "timestamp": time.time(),
                "source_url": url,
                "platform": platform
            }, 200
        
        return {
            "original_text": text,
            "fact_check_results": all_results,
            "image_analysis_results": image_analysis_results,
            "claims_found": len(all_results),
            "images_processed": len(image_analysis_results),
            "timestamp": time.time(),
            "source_url": url,
            "platform": platform
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
