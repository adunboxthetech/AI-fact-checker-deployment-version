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

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
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

def _resolve_url(base, path):
    """Resolve relative URLs"""
    if not path:
        return None
    return urljoin(base, path)

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
        "imgur.com", "i.ytimg.com", "media.githubusercontent.com", 
        "cdn.discordapp.com", "images.unsplash.com", "i.pinimg.com", 
        "scontent", "fbcdn.net", "cdninstagram.com", "graph.facebook.com"
    ]
    
    # Check for image hosts
    for host in image_hosts:
        if host in netloc_lower:
            return True
    
    # Twitter-specific patterns
    if any(domain in netloc_lower for domain in ['twitter.com', 'x.com', 't.co']):
        if '/media/' in path_lower or 'format=' in pu.query or 'name=' in pu.query:
            return True
    
    # Check for image-like query parameters
    query_lower = pu.query.lower()
    if any(param in query_lower for param in ['format=jpg', 'format=png', 'format=webp', '.jpg', '.png']):
        return True
    
    # Generic media indicators
    if any(indicator in path_lower for indicator in ['/media/', '/image/', '/img/', '/photo/', '/pic/']):
        return True
    
    return False

def extract_content_from_url(url):
    """Extract both text and images from social media URLs"""
    parsed_url = urlparse(url)
    netloc = parsed_url.netloc
    text_content = ""
    image_urls = []
    
    print(f"Extracting content from: {url}")
    
    try:
        # Twitter/X handler
        if 'twitter.com' in netloc or 'x.com' in netloc:
            match = re.search(r'/status/(\d+)', parsed_url.path)
            if match:
                tweet_id = match.group(1)
                print(f"Processing Twitter/X tweet ID: {tweet_id}")
                
                # Twitter syndication API
                api_url = f"https://cdn.syndication.twimg.com/widgets/tweet?id={tweet_id}&lang=en"
                try:
                    r = requests.get(api_url, headers=DEFAULT_HEADERS, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        text_content = data.get('text', '')
                        
                        # Extract photos
                        for photo in data.get('photos', []):
                            img_url = photo.get('url')
                            if img_url:
                                image_urls.append(img_url)
                                print(f"Found Twitter photo: {img_url}")
                        
                        # Extract video poster
                        if data.get('video') and data['video'].get('poster'):
                            image_urls.append(data['video']['poster'])
                            print(f"Found Twitter video poster: {data['video']['poster']}")
                        
                        print(f"Twitter API extracted {len(image_urls)} images")
                except Exception as e:
                    print(f"Twitter API failed: {e}")
                
                # Fallback to oEmbed
                if not image_urls:
                    try:
                        oembed_url = f"https://publish.twitter.com/oembed?url={url}"
                        r = requests.get(oembed_url, headers=DEFAULT_HEADERS, timeout=10)
                        if r.status_code == 200:
                            oembed_data = r.json()
                            html_content = oembed_data.get('html', '')
                            if html_content:
                                soup = BeautifulSoup(html_content, 'lxml')
                                for img in soup.find_all('img'):
                                    src = img.get('src')
                                    if src and _is_image_like(src):
                                        image_urls.append(src)
                                        print(f"Found oEmbed image: {src}")
                                print(f"Twitter oEmbed extracted {len(image_urls)} images")
                    except Exception as e:
                        print(f"Twitter oEmbed failed: {e}")
        
        # Reddit handler
        elif 'reddit.com' in netloc or 'redd.it' in netloc:
            json_url = _build_reddit_json_url(url)
            try:
                r = requests.get(json_url, headers=DEFAULT_HEADERS, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    post_data = data[0]['data']['children'][0]['data']
                    text_content = f"{post_data.get('title', '')} {post_data.get('selftext', '')}".strip()
                    
                    # Extract images from Reddit
                    if post_data.get('url_overridden_by_dest') and _is_image_like(post_data['url_overridden_by_dest']):
                        image_urls.append(post_data['url_overridden_by_dest'])
                    
                    # Reddit preview images
                    if 'preview' in post_:
                        for img in post_data['preview'].get('images', []):
                            img_src = img['source']['url'].replace('&amp;', '&')
                            if _is_image_like(img_src):
                                image_urls.append(img_src)
                    
                    # Reddit media metadata
                    if 'media_metadata' in post_:
                        for media_id in post_data['media_metadata']:
                            media = post_data['media_metadata'][media_id]
                            if media.get('e') == 'Image' and 's' in media:
                                img_url = media['s']['u'].replace('&amp;', '&')
                                if _is_image_like(img_url):
                                    image_urls.append(img_url)
                    
                    print(f"Reddit extracted {len(image_urls)} images")
            except Exception as e:
                print(f"Reddit extraction failed: {e}")
        
        # Generic URL handler
        if not text_content or len(image_urls) == 0:
            try:
                enhanced_headers = {
                    **DEFAULT_HEADERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Cache-Control": "no-cache"
                }
                
                r = requests.get(url, headers=enhanced_headers, timeout=15, allow_redirects=True)
                r.raise_for_status()
                html = r.text
                print(f"Generic scraper got {len(html)} chars of HTML")
                
                # Extract text content
                if not text_content:
                    doc = Document(html)
                    text_content = BeautifulSoup(doc.summary(), 'lxml').get_text(' ', strip=True)
                    if len(text_content) < 150:
                        text_content = BeautifulSoup(html, 'lxml').get_text(' ', strip=True)
                
                # Extract images
                soup = BeautifulSoup(html, 'lxml')
                
                # Meta tags for social media images
                for prop in ['og:image', 'og:image:secure_url', 'twitter:image', 'twitter:image:src']:
                    meta = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
                    if meta and meta.get('content'):
                        img_url = _resolve_url(url, meta['content'])
                        if img_url and _is_image_like(img_url):
                            image_urls.append(img_url)
                            print(f"Found meta image: {img_url}")
                
                # All img tags
                for img in soup.find_all('img'):
                    for attr in ['src', 'data-src', 'data-lazy-src', 'data-original']:
                        src = img.get(attr)
                        if src:
                            resolved_url = _resolve_url(url, src)
                            if resolved_url and _is_image_like(resolved_url):
                                if not any(skip in resolved_url.lower() for skip in ['avatar', 'profile', 'icon', 'logo', 'badge']):
                                    image_urls.append(resolved_url)
                                    print(f"Found img tag: {resolved_url}")
                
                print(f"Generic extraction found {len(image_urls)} images")
            except Exception as e:
                print(f"Generic extraction failed: {e}")
                raise ValueError(f"Failed to fetch URL: {e}")
    
    except Exception as e:
        print(f"Overall extraction failed: {e}")
        return {"text": f"Extraction failed: {e}", "image_urls": []}
    
    # Clean up text
    text_content = ' '.join(text_content.split())
    if len(text_content) > 12000:
        text_content = text_content[:12000] + '…'
    
    # Deduplicate and prioritize images
    unique_images = []
    seen = set()
    for img_url in image_urls:
        if img_url and img_url not in seen and _is_image_like(img_url):
            unique_images.append(img_url)
            seen.add(img_url)
    
    # Sort by priority
    def image_priority(img_url):
        if 'pbs.twimg.com' in img_url:
            return 0
        elif 'pic.twitter.com' in img_url:
            return 1
        elif any(host in img_url for host in ['i.redd.it', 'i.imgur.com']):
            return 2
        else:
            return 3
    
    final_images = sorted(unique_images, key=image_priority)[:5]  # Limit to 5 images
    
    print(f"Final result: {len(final_images)} images extracted")
    for i, img in enumerate(final_images):
        print(f"  {i+1}: {img}")
    
    return {
        "text": text_content or "No text content found.",
        "image_urls": final_images
    }

def fact_check_text(text):
    """Fact-check text content using Perplexity"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""
You are a fact-checking assistant. Analyze the following text and fact-check any factual claims.

TEXT TO ANALYZE: {text}

RESPONSE FORMAT: Return ONLY a valid JSON object with this exact structure:

{{
  "verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS",
  "confidence": 75,
  "explanation": "Your explanation here",
  "sources": ["https://example.com/source1"]
}}

CRITICAL: Return ONLY the JSON object, no other text.
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
                # Clean the content
                clean_content = content.strip()
                if clean_content.startswith('json'):
                    clean_content = clean_content[4:].strip()
                
                parsed = json.loads(clean_content)
                
                fact_check_result = {
                    "claim": text[:200] + "..." if len(text) > 200 else text,
                    "result": parsed
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
                
                verdict = verdict_match.group(1) if verdict_match else "INSUFFICIENT EVIDENCE"
                confidence = int(confidence_match.group(1)) if confidence_match else 75
                explanation = explanation_match.group(1) if explanation_match else content
                
                fact_check_result = {
                    "claim": text[:200] + "..." if len(text) > 200 else text,
                    "result": {
                        "verdict": verdict,
                        "confidence": confidence,
                        "explanation": explanation,
                        "sources": ["Perplexity Analysis"]
                    }
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
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text", 
                        "text": (
                            "Analyze this image for factual claims. Look for text, charts, graphs, statistics, or any verifiable information. "
                            "Return ONLY a JSON object: "
                            '{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 75, "explanation": "Your analysis", "sources": ["url1"]}'
                        )
                    }
                ]
            }
        ]
        
        # Add image
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        elif image_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_url})
        
        payload = {
            "model": "sonar-pro",
            "messages": messages,
            "max_tokens": 600
        }
        
        sonar_resp = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=30)
        
        if sonar_resp.status_code != 200:
            return {"error": f"Image analysis failed: HTTP {sonar_resp.status_code}"}, 500
        
        content = sonar_resp.json()['choices'][0]['message']['content']
        
        try:
            # Clean and parse JSON
            clean_content = content.strip()
            if clean_content.startswith('json'):
                clean_content = clean_content[4:].strip()
            
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
            # Fallback for non-JSON responses
            if "no factual claims" in content.lower():
                return {
                    "fact_check_results": [{
                        "claim": "Image Analysis",
                        "result": {
                            "verdict": "NO FACTUAL CLAIMS",
                            "confidence": 100,
                            "explanation": "This image does not contain verifiable factual claims.",
                            "sources": []
                        }
                    }],
                    "claims_found": 0,
                    "timestamp": time.time(),
                    "source_url": image_url if image_url else None
                }, 200
            else:
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
                    "timestamp": time.time(),
                    "source_url": image_url if image_url else None
                }, 200
    
    except Exception as e:
        return {"error": f"Image analysis failed: {str(e)}"}, 500

def fact_check_url_with_images(url):
    """Extract and fact-check both text and images from URLs"""
    try:
        print(f"Starting fact-check for URL: {url}")
        
        # Extract content
        content = extract_content_from_url(url)
        text = content.get("text", "")
        image_urls = content.get("image_urls", [])
        
        print(f"Extracted text length: {len(text)}")
        print(f"Extracted {len(image_urls)} images")
        
        all_results = []
        
        # Fact-check text if meaningful content exists
        if text and len(text.strip()) > 20:
            try:
                print("Starting text fact-check...")
                text_result, status_code = fact_check_text(text)
                if status_code == 200 and isinstance(text_result, dict):
                    text_fact_checks = text_result.get('fact_check_results', [])
                    for result in text_fact_checks:
                        result['source_type'] = 'text'
                        all_results.append(result)
                    print(f"Text analysis completed: {len(text_fact_checks)} claims")
            except Exception as e:
                print(f"Text fact-checking failed: {e}")
        
        # Fact-check each image individually
        image_analysis_results = []
        for i, img_url in enumerate(image_urls[:3]):  # Limit to first 3 images
            try:
                print(f"Starting fact-check for image {i+1}: {img_url}")
                img_result, status_code = fact_check_image("", img_url)
                
                if status_code == 200 and isinstance(img_result, dict):
                    img_fact_checks = img_result.get('fact_check_results', [])
                    
                    image_result_summary = {
                        "image_url": img_url,
                        "claims_found": len(img_fact_checks),
                        "fact_check_results": img_fact_checks
                    }
                    
                    if img_fact_checks:
                        image_analysis_results.append(image_result_summary)
                        
                        # Add to combined results for frontend
                        for fact_check in img_fact_checks:
                            fact_check_copy = fact_check.copy()
                            fact_check_copy['source_type'] = 'image'
                            fact_check_copy['image_url'] = img_url
                            all_results.append(fact_check_copy)
                        
                        print(f"Image {i+1} analysis completed: {len(img_fact_checks)} claims")
                    else:
                        print(f"Image {i+1}: No factual claims found")
                        
            except Exception as e:
                print(f"Image {i+1} fact-checking failed: {e}")
                error_result = {
                    "image_url": img_url,
                    "error": str(e),
                    "claims_found": 0,
                    "fact_check_results": []
                }
                image_analysis_results.append(error_result)
        
        # Get platform name
        platform = get_platform_name(url)
        
        print(f"Final results: {len(all_results)} total claims found")
        
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
        print(f"URL analysis failed: {e}")
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
    elif 'imgur.com' in url:
        return "Imgur"
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
                response_data = {"error": "No image data URL or image URL provided"}
                status_code = 400
            else:
                if image_data_url and len(image_data_url) > 10 * 1024 * 1024:
                    response_data = {"error": "Image data URL is too large. Please use a smaller image."}
                    status_code = 400
                else:
                    try:
                        response_data, status_code = fact_check_image(image_data_url, image_url)
                    except Exception as e:
                        response_data = {"error": f"Image analysis failed: {str(e)}"}
                        status_code = 400
        else:
            response_data = {"error": "Endpoint not found"}
            status_code = 404
        
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
