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
        "scontent", "fbcdn.net", "cdninstagram.com", "graph.facebook.com",
        "preview.redd.it"
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
    """ANTI-BLOCKING VERSION: Handle 403 errors and use multiple strategies"""
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
                print(f"📱 Twitter ID: {tweet_id}")
                
                # Method 1: Twitter syndication API
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
                                print(f"✅ Found Twitter image: {photo['url']}")
                                
                        if data.get('video', {}).get('poster'):
                            image_urls.append(data['video']['poster'])
                            
                        print(f"📱 Twitter API: {len(image_urls)} images, text: {len(text_content)} chars")
                except Exception as e:
                    print(f"❌ Twitter API failed: {e}")
                
                # Method 2: oEmbed fallback
                if not image_urls:
                    try:
                        oembed_url = f"https://publish.twitter.com/oembed?url={url}"
                        r = requests.get(oembed_url, headers=STEALTH_HEADERS, timeout=15)
                        if r.status_code == 200:
                            oembed_data = r.json()
                            html_content = oembed_data.get('html', '')
                            if html_content:
                                soup = BeautifulSoup(html_content, 'lxml')
                                
                                # Extract text if not already found
                                if not text_content:
                                    blockquote = soup.find('blockquote')
                                    if blockquote:
                                        for link in blockquote.find_all('a'):
                                            link.decompose()
                                        text_content = blockquote.get_text(strip=True)
                                        text_content = re.sub(r'pic\.twitter\.com/\w+', '', text_content)
                                        text_content = text_content.strip()
                                
                                # Extract images
                                for img in soup.find_all('img'):
                                    src = img.get('src')
                                    if src and _is_image_like(src):
                                        image_urls.append(src)
                                        print(f"✅ Found oEmbed image: {src}")
                                        
                                print(f"📱 oEmbed: {len(image_urls)} images found")
                    except Exception as e:
                        print(f"❌ oEmbed failed: {e}")
                
                # If no images found, create a placeholder for AI analysis
                if not image_urls:
                    print(f"⚠️ No images from Twitter API - will use AI fallback")
                    image_urls = [f"AI_ANALYZE:{url}"]
        
        # Reddit handler with multiple strategies
        elif 'reddit.com' in netloc or 'redd.it' in netloc:
            try:
                # Multiple strategies for Reddit
                strategies = [
                    lambda u: u + '.json?raw_json=1',  # Direct JSON
                    lambda u: u.replace('www.reddit.com', 'old.reddit.com') + '.json',  # Old Reddit
                    lambda u: u  # Direct HTML scraping
                ]
                
                for i, strategy in enumerate(strategies):
                    try:
                        target_url = strategy(url)
                        print(f"🔄 Reddit strategy {i+1}: {target_url}")
                        
                        r = requests.get(target_url, headers=STEALTH_HEADERS, timeout=15)
                        print(f"📊 Reddit response: {r.status_code}")
                        
                        if r.status_code == 200:
                            if target_url.endswith('.json'):
                                # JSON response
                                data = r.json()
                                post_data = data[0]['data']['children'][0]['data']
                                text_content = f"{post_data.get('title', '')} {post_data.get('selftext', '')}".strip()
                                
                                # Extract images
                                if post_data.get('url_overridden_by_dest'):
                                    img_url = post_data['url_overridden_by_dest']
                                    if _is_image_like(img_url):
                                        image_urls.append(img_url)
                                
                                # Reddit preview images
                                for img_data in post_data.get('preview', {}).get('images', []):
                                    img_src = img_data['source']['url'].replace('&amp;', '&')
                                    if _is_image_like(img_src):
                                        image_urls.append(img_src)
                                
                                # Media metadata
                                for media_id, media in post_data.get('media_metadata', {}).items():
                                    if media.get('e') == 'Image' and media.get('s', {}).get('u'):
                                        img_url = media['s']['u'].replace('&amp;', '&')
                                        if _is_image_like(img_url):
                                            image_urls.append(img_url)
                                
                                print(f"✅ Reddit JSON: {len(image_urls)} images found")
                                break
                            else:
                                # HTML scraping fallback
                                soup = BeautifulSoup(r.text, 'lxml')
                                # Extract title and text
                                title_elem = soup.find('h1') or soup.find('title')
                                if title_elem:
                                    text_content = title_elem.get_text(strip=True)
                                
                                # Look for images in HTML
                                for img in soup.find_all('img'):
                                    src = img.get('src')
                                    if src and _is_image_like(src):
                                        image_urls.append(src)
                                
                                print(f"✅ Reddit HTML: {len(image_urls)} images found")
                                break
                                
                    except Exception as e:
                        print(f"❌ Reddit strategy {i+1} failed: {e}")
                        continue
                
                # If all strategies failed but we know it's a Reddit post with images
                if not image_urls and 'i.redd.it' not in url:
                    image_urls = [f"AI_ANALYZE:{url}"]
                    print(f"⚠️ Reddit extraction failed - using AI fallback")
                    
            except Exception as e:
                print(f"❌ Reddit extraction failed: {e}")
                return {"text": f"Content blocked by Reddit: {str(e)}", "image_urls": [f"AI_ANALYZE:{url}"]}
        
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
        return {"text": f"Extraction failed: {str(e)}", "image_urls": [f"AI_ANALYZE:{url}"]}
    
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
        "text": text_content or "",
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
Analyze this text for factual claims that can be verified:

TEXT: {text}

Return ONLY a JSON object:

{{
  "verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS",
  "confidence": 85,
  "explanation": "Your analysis here",
  "sources": ["https://example.com"]
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
                clean_content = content.strip()
                if clean_content.startswith('json'):
                    clean_content = clean_content[4:].strip()
                
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
                            "explanation": content,
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
    """ENHANCED: Handle both direct images and AI-based URL analysis"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    print(f"🔍 ANALYZING: {image_url or 'uploaded image'}")
    
    try:
        # Check if this is an AI_ANALYZE request
        if image_url and image_url.startswith("AI_ANALYZE:"):
            actual_url = image_url.replace("AI_ANALYZE:", "")
            print(f"🤖 AI-based analysis for: {actual_url}")
            
            # Use Perplexity to visit and analyze the URL content
            ai_prompt = f"""
Visit this social media URL and analyze ALL visual content (images, graphics, charts, infographics):
{actual_url}

Tasks:
1. Look for ANY images, graphics, charts, or visual content in the post
2. Read ALL visible text within images/graphics
3. Identify factual claims, statistics, quotes, or data points
4. Note any attributions, sources, or citations shown in visuals
5. Fact-check any verifiable claims found in the visual content

For the specific URL provided:
- If Twitter: Look for embedded images, quote cards, screenshots
- If Reddit: Look for uploaded images, infographics, charts, memes with text
- Extract and verify any factual information displayed visually

Return ONLY a JSON object:
{{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 85, "explanation": "Detailed analysis of visual content including specific claims found and their verification", "sources": ["source1.com", "source2.com"]}}

CRITICAL: If you find visual content with factual claims, fact-check them thoroughly. If no visual content or only decorative images, return "NO FACTUAL CLAIMS".
"""
            
            payload = {
                "model": "sonar-pro",
                "messages": [{"role": "user", "content": ai_prompt}],
                "max_tokens": 1000
            }
            
        else:
            # Standard image analysis
            messages = [{
                "role": "user",
                "content": [{
                    "type": "text", 
                    "text": (
                        "Analyze this image for factual claims. Look for:\n"
                        "1. Any text, quotes, or statements\n"
                        "2. Charts, graphs, or data visualizations\n"
                        "3. Statistics, numbers, or factual information\n"
                        "4. Names, dates, locations, or attributions\n\n"
                        "Return ONLY a JSON object:\n"
                        '{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 85, "explanation": "Your detailed analysis", "sources": ["url1"]}'
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
        
        # Make the request
        response = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=45)
        
        if response.status_code != 200:
            print(f"❌ API failed: {response.status_code}")
            return {"error": f"Analysis failed: HTTP {response.status_code}"}, 500
        
        content = response.json()['choices'][0]['message']['content']
        print(f"📋 Analysis response: {content[:200]}...")
        
        try:
            # Parse JSON response
            clean_content = content.strip()
            if clean_content.startswith('json'):
                clean_content = clean_content[4:].strip()
            
            parsed = json.loads(clean_content)
            
            result = {
                "fact_check_results": [{
                    "claim": "Visual Content Analysis" if image_url and image_url.startswith("AI_ANALYZE:") else "Image Analysis",
                    "result": {
                        "verdict": parsed.get("verdict", "INSUFFICIENT EVIDENCE"),
                        "confidence": parsed.get("confidence", 75),
                        "explanation": parsed.get("explanation", "Analysis completed"),
                        "sources": parsed.get("sources", [])
                    }
                }],
                "claims_found": 1 if parsed.get("verdict") != "NO FACTUAL CLAIMS" else 0,
                "timestamp": time.time(),
                "source_url": image_url if image_url and not image_url.startswith("AI_ANALYZE:") else None
            }
            
            print(f"✅ Analysis successful: {parsed.get('verdict')} ({parsed.get('confidence')}%)")
            return result, 200
        
        except json.JSONDecodeError:
            print(f"⚠️ JSON parsing failed, using fallback")
            return {
                "fact_check_results": [{
                    "claim": "Visual Content Analysis",
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
        print(f"❌ Analysis failed: {e}")
        return {"error": f"Analysis failed: {str(e)}"}, 500

def fact_check_url_with_images(url):
    """MAIN FUNCTION: Extract and fact-check both text and images"""
    try:
        print(f"\n=== STARTING FACT-CHECK FOR: {url} ===")
        
        # Extract content
        content = extract_content_from_url(url)
        text = content.get("text", "").strip()
        image_urls = content.get("image_urls", [])
        
        print(f"EXTRACTION RESULT: Text={len(text)} chars, Images={len(image_urls)}")
        
        all_results = []
        
        # Fact-check text if meaningful content exists
        if text and len(text) > 10:
            try:
                print(f"Analyzing text content...")
                text_result, status_code = fact_check_text(text)
                if status_code == 200 and isinstance(text_result, dict):
                    text_fact_checks = text_result.get('fact_check_results', [])
                    for result in text_fact_checks:
                        result['source_type'] = 'text'
                        all_results.append(result)
                    print(f"Text analysis: {len(text_fact_checks)} claims")
            except Exception as e:
                print(f"Text analysis failed: {e}")
        
        # Fact-check each image individually
        image_analysis_results = []
        for i, img_url in enumerate(image_urls):
            try:
                print(f"Analyzing image/content {i+1}: {img_url}")
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
                    
                    print(f"Image {i+1} analysis: {len(img_fact_checks)} claims")
                        
            except Exception as e:
                print(f"Image {i+1} analysis failed: {e}")
                error_result = {
                    "image_url": img_url,
                    "error": str(e),
                    "claims_found": 0,
                    "fact_check_results": []
                }
                image_analysis_results.append(error_result)
        
        platform = get_platform_name(url)
        
        print(f"FINAL RESULTS: {len(all_results)} total claims, {len(image_analysis_results)} images processed")
        
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
