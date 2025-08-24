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
    """DEBUG VERSION: Extract both text and images with detailed logging"""
    parsed_url = urlparse(url)
    netloc = parsed_url.netloc
    text_content = ""
    image_urls = []
    
    print(f"\n🔍 DEBUG: Starting extraction from: {url}")
    print(f"🔍 DEBUG: Parsed netloc: {netloc}")
    
    try:
        # Enhanced Twitter/X handler with DEBUG
        if 'twitter.com' in netloc or 'x.com' in netloc:
            match = re.search(r'/status/(\d+)', parsed_url.path)
            if match:
                tweet_id = match.group(1)
                print(f"🔍 DEBUG: Tweet ID extracted: {tweet_id}")
                
                # Method 1: Twitter syndication API
                try:
                    api_url = f"https://cdn.syndication.twimg.com/widgets/tweet?id={tweet_id}&lang=en"
                    print(f"🔍 DEBUG: Calling Twitter API: {api_url}")
                    
                    r = requests.get(api_url, headers=DEFAULT_HEADERS, timeout=15)
                    print(f"🔍 DEBUG: Twitter API status: {r.status_code}")
                    
                    if r.status_code == 200:
                        data = r.json()
                        print(f"🔍 DEBUG: Twitter API response keys: {list(data.keys())}")
                        
                        # Debug: Show raw response
                        print(f"🔍 DEBUG: Raw Twitter  {json.dumps(data, indent=2)[:1000]}...")
                        
                        tweet_text = data.get('text', '').strip()
                        print(f"🔍 DEBUG: Raw tweet text: '{tweet_text}'")
                        
                        # Check for photos in response
                        photos = data.get('photos', [])
                        print(f"🔍 DEBUG: Photos array length: {len(photos)}")
                        print(f"🔍 DEBUG: Photos  {photos}")
                        
                        if photos:
                            for i, photo in enumerate(photos):
                                img_url = photo.get('url')
                                print(f"🔍 DEBUG: Photo {i+1} URL: {img_url}")
                                if img_url:
                                    image_urls.append(img_url)
                                    print(f"✅ DEBUG: Added image URL: {img_url}")
                        else:
                            print("❌ DEBUG: No photos found in Twitter API response")
                        
                        # Check for video
                        if data.get('video'):
                            print(f"🔍 DEBUG: Video data found: {data.get('video')}")
                            if data['video'].get('poster'):
                                image_urls.append(data['video']['poster'])
                                print(f"✅ DEBUG: Added video poster: {data['video']['poster']}")
                        
                        # Filter text content
                        if tweet_text and not re.match(r'^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\s@\w\./:-]*$', tweet_text):
                            text_content = tweet_text
                            print(f"✅ DEBUG: Text content accepted: {text_content[:100]}...")
                        else:
                            print(f"❌ DEBUG: Text content rejected (metadata only): {tweet_text}")
                        
                        print(f"🔍 DEBUG: Twitter API final - Images: {len(image_urls)}, Text length: {len(text_content)}")
                        
                except Exception as e:
                    print(f"❌ DEBUG: Twitter API failed: {e}")
                
                # Method 2: oEmbed fallback - ONLY if no images found
                if not image_urls:
                    print(f"🔍 DEBUG: No images from API, trying oEmbed...")
                    try:
                        oembed_url = f"https://publish.twitter.com/oembed?url={url}"
                        print(f"🔍 DEBUG: oEmbed URL: {oembed_url}")
                        
                        r = requests.get(oembed_url, headers=DEFAULT_HEADERS, timeout=15)
                        print(f"🔍 DEBUG: oEmbed status: {r.status_code}")
                        
                        if r.status_code == 200:
                            oembed_data = r.json()
                            print(f"🔍 DEBUG: oEmbed keys: {list(oembed_data.keys())}")
                            
                            html_content = oembed_data.get('html', '')
                            print(f"🔍 DEBUG: oEmbed HTML length: {len(html_content)}")
                            
                            if html_content:
                                soup = BeautifulSoup(html_content, 'lxml')
                                
                                # Look for images in oEmbed HTML
                                imgs = soup.find_all('img')
                                print(f"🔍 DEBUG: Found {len(imgs)} img tags in oEmbed")
                                
                                for i, img in enumerate(imgs):
                                    src = img.get('src')
                                    print(f"🔍 DEBUG: Image {i+1} src: {src}")
                                    if src and _is_image_like(src):
                                        image_urls.append(src)
                                        print(f"✅ DEBUG: Added oEmbed image: {src}")
                                    else:
                                        print(f"❌ DEBUG: Image rejected by _is_image_like: {src}")
                                
                                # Extract text if not already found
                                if not text_content:
                                    blockquote = soup.find('blockquote')
                                    if blockquote:
                                        for link in blockquote.find_all('a'):
                                            link.decompose()
                                        text_content = blockquote.get_text(strip=True)
                                        text_content = re.sub(r'pic\.twitter\.com/\w+', '', text_content)
                                        text_content = text_content.strip()
                                        print(f"✅ DEBUG: oEmbed text extracted: {text_content[:100]}...")
                                
                                print(f"🔍 DEBUG: oEmbed final - Images: {len(image_urls)}, Text: {len(text_content)}")
                                
                    except Exception as e:
                        print(f"❌ DEBUG: oEmbed failed: {e}")
                
                # Method 3: Force add some test images if still none found (for debugging)
                if not image_urls:
                    print(f"🔍 DEBUG: Still no images found, checking if this is a media tweet...")
                    # Look for pic.twitter.com links in the URL or elsewhere
                    if 'pic.twitter.com' in url or '/photo/' in url:
                        print(f"🔍 DEBUG: This appears to be a media tweet but no images extracted")
                    
                    # For debugging, let's try a different approach
                    try:
                        # Try direct scraping with more aggressive headers
                        scrape_headers = {
                            **DEFAULT_HEADERS,
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                            "Sec-Fetch-Dest": "document",
                            "Sec-Fetch-Mode": "navigate",
                            "Sec-Fetch-Site": "none",
                            "Sec-Fetch-User": "?1",
                            "Upgrade-Insecure-Requests": "1",
                            "Cache-Control": "no-cache",
                            "Pragma": "no-cache"
                        }
                        
                        print(f"🔍 DEBUG: Trying direct scraping...")
                        r = requests.get(url, headers=scrape_headers, timeout=15)
                        print(f"🔍 DEBUG: Direct scraping status: {r.status_code}")
                        
                        if r.status_code == 200:
                            # Look for meta tags
                            soup = BeautifulSoup(r.text, 'lxml')
                            
                            # Twitter card images
                            meta_props = ['twitter:image', 'twitter:image:src', 'og:image', 'og:image:url']
                            for prop in meta_props:
                                meta = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop}) or soup.find('meta', attrs={'property': prop})
                                if meta:
                                    content = meta.get('content')
                                    print(f"🔍 DEBUG: Found meta {prop}: {content}")
                                    if content and _is_image_like(content):
                                        image_urls.append(content)
                                        print(f"✅ DEBUG: Added meta image: {content}")
                            
                            print(f"🔍 DEBUG: After meta scraping - Images: {len(image_urls)}")
                            
                    except Exception as e:
                        print(f"❌ DEBUG: Direct scraping failed: {e}")
            else:
                print(f"❌ DEBUG: No tweet ID found in URL")
        
        else:
            print(f"🔍 DEBUG: Not a Twitter URL, using generic handler")
            # Generic handler for other URLs...
            try:
                r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15, allow_redirects=True)
                r.raise_for_status()
                html = r.text
                
                doc = Document(html)
                text_content = BeautifulSoup(doc.summary(), 'lxml').get_text(' ', strip=True)
                if len(text_content) < 150:
                    text_content = BeautifulSoup(html, 'lxml').get_text(' ', strip=True)
                
                soup = BeautifulSoup(html, 'lxml')
                for prop in ['og:image', 'og:image:secure_url', 'twitter:image', 'twitter:image:src']:
                    meta = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
                    if meta and meta.get('content'):
                        img_url = _resolve_url(url, meta['content'])
                        if img_url and _is_image_like(img_url):
                            image_urls.append(img_url)
                
                for img in soup.find_all('img'):
                    for attr in ['src', 'data-src', 'data-lazy-src', 'data-original']:
                        src = img.get(attr)
                        if src:
                            resolved_url = _resolve_url(url, src)
                            if resolved_url and _is_image_like(resolved_url):
                                if not any(skip in resolved_url.lower() for skip in ['avatar', 'profile', 'icon', 'logo', 'badge']):
                                    image_urls.append(resolved_url)
                
                print(f"Generic extraction found {len(image_urls)} images")
            except Exception as e:
                print(f"Generic extraction failed: {e}")
                raise ValueError(f"Failed to fetch URL: {e}")
    
    except Exception as e:
        print(f"Overall extraction failed: {e}")
        return {"text": f"Extraction failed: {e}", "image_urls": []}
    
    # Clean up text - remove common Twitter artifacts
    if text_content:
        text_content = re.sub(r'pic\.twitter\.com/\w+', '', text_content)
        text_content = re.sub(r'https://t\.co/\w+', '', text_content)
        text_content = ' '.join(text_content.split()).strip()
        
        if len(text_content) > 12000:
            text_content = text_content[:12000] + '…'
    
    # Deduplicate images
    unique_images = []
    seen = set()
    for img_url in image_urls:
        if img_url and img_url not in seen and _is_image_like(img_url):
            unique_images.append(img_url)
            seen.add(img_url)
    
    final_images = sorted(unique_images, key=lambda x: (
        0 if 'pbs.twimg.com' in x else
        1 if 'pic.twitter.com' in x else 2
    ))[:5]
    
    print(f"FINAL EXTRACTION RESULT:")
    print(f"  Text: '{text_content[:100]}{'...' if len(text_content) > 100 else ''}' (length: {len(text_content)})")
    print(f"  Images: {len(final_images)}")
    for i, img in enumerate(final_images):
        print(f"    {i+1}: {img}")
    
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
                # Fallback parsing
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
    """ENHANCED: Fact-check image content with better prompting"""
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
                            "ANALYZE THIS IMAGE FOR FACTUAL CLAIMS:\n\n"
                            "1. Read ALL visible text in the image carefully\n"
                            "2. Identify any quotes, statements, statistics, or claims\n"
                            "3. Note any person names, titles, dates, or attributions\n"
                            "4. Look for charts, graphs, or data visualizations\n"
                            "5. Fact-check ANY verifiable claims you find\n\n"
                            "If you find factual claims, verify them thoroughly.\n"
                            "If it's purely decorative/artistic with no factual content, say so.\n\n"
                            "Return ONLY this JSON format:\n"
                            '{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 85, "explanation": "Your detailed analysis of what you see and any fact-checking", "sources": ["url1"]}\n\n'
                            "CRITICAL: Return ONLY the JSON object."
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
        
        print(f"Sending image analysis request for: {image_url or 'uploaded image'}")
        
        payload = {
            "model": "sonar-pro",
            "messages": messages,
            "max_tokens": 800
        }
        
        sonar_resp = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=45)
        
        if sonar_resp.status_code != 200:
            print(f"Image analysis API failed with status: {sonar_resp.status_code}")
            return {"error": f"Image analysis failed: HTTP {sonar_resp.status_code}"}, 500
        
        content = sonar_resp.json()['choices'][0]['message']['content']
        print(f"Image analysis response: {content[:200]}...")
        
        try:
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
            
            print(f"Image analysis successful: {parsed.get('verdict')} ({parsed.get('confidence')}%)")
            return result, 200
        
        except json.JSONDecodeError:
            print(f"Failed to parse JSON, using fallback")
            # Fallback for non-JSON responses
            if "no factual claims" in content.lower():
                verdict = "NO FACTUAL CLAIMS"
                explanation = "This image does not contain verifiable factual claims."
            else:
                verdict = "INSUFFICIENT EVIDENCE"
                explanation = content
            
            return {
                "fact_check_results": [{
                    "claim": "Image Analysis",
                    "result": {
                        "verdict": verdict,
                        "confidence": 75,
                        "explanation": explanation,
                        "sources": []
                    }
                }],
                "claims_found": 1 if verdict != "NO FACTUAL CLAIMS" else 0,
                "timestamp": time.time(),
                "source_url": image_url if image_url else None
            }, 200
    
    except Exception as e:
        print(f"Image analysis exception: {e}")
        return {"error": f"Image analysis failed: {str(e)}"}, 500
def fact_check_url_with_images(url):
    """FINAL FIX: Force image analysis even when Twitter APIs fail"""
    try:
        print(f"\n=== STARTING FACT-CHECK FOR: {url} ===")
        
        # Extract content using existing method
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
        
        # CRITICAL FIX: Force image analysis for Twitter posts even if no images detected
        image_analysis_results = []
        
        # For Twitter posts, try to analyze the page content directly as an image
        if ('twitter.com' in url or 'x.com' in url) and len(image_urls) == 0:
            print(f"Twitter post detected with no images from API - using fallback method")
            
            # Method 1: Try common Twitter image patterns
            tweet_match = re.search(r'/status/(\d+)', url)
            if tweet_match:
                tweet_id = tweet_match.group(1)
                
                # Generate potential Twitter image URLs based on common patterns
                potential_image_urls = [
                    f"https://pbs.twimg.com/media/{tweet_id}.jpg",
                    f"https://pbs.twimg.com/media/{tweet_id}.png", 
                    f"https://pbs.twimg.com/media/{tweet_id}?format=jpg&name=medium",
                    f"https://pbs.twimg.com/media/{tweet_id}?format=png&name=medium"
                ]
                
                # Also try to extract from the original URL by converting to screenshot
                print(f"Trying potential Twitter image URLs...")
                for potential_url in potential_image_urls:
                    try:
                        # Test if URL is accessible
                        test_response = requests.head(potential_url, timeout=5)
                        if test_response.status_code == 200:
                            image_urls.append(potential_url)
                            print(f"Found accessible image: {potential_url}")
                            break
                    except:
                        continue
            
            # Method 2: If still no images, create a special analysis request
            if len(image_urls) == 0:
                print(f"No images found - creating screenshot-based analysis")
                
                # Create a special analysis that asks Perplexity to visit the URL
                try:
                    headers = {
                        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                        "Content-Type": "application/json"
                    }
                    
                    screenshot_prompt = f"""
Visit this Twitter/X URL and analyze any visual content (images, graphics, quotes, charts) in the post:
{url}

Look for:
1. Any images with text, quotes, or factual claims
2. Infographics, charts, or data visualizations  
3. Screenshots of articles or documents
4. Political quotes or statements with attributions

If you find visual content with factual claims, analyze and fact-check them thoroughly.

Return ONLY a JSON object:
{{"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS", "confidence": 85, "explanation": "Your detailed analysis of visual content found in the post", "sources": ["url1"]}}

CRITICAL: If you cannot access the URL or find no visual content, return {{"verdict": "NO FACTUAL CLAIMS", "confidence": 100, "explanation": "Unable to access visual content from this Twitter post", "sources": []}}
"""
                    
                    response = requests.post(
                        PERPLEXITY_URL,
                        headers=headers,
                        json={
                            "model": "sonar-pro",
                            "messages": [{"role": "user", "content": screenshot_prompt}],
                            "max_tokens": 800
                        },
                        timeout=45
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        content_analysis = result['choices'][0]['message']['content']
                        
                        try:
                            clean_content = content_analysis.strip()
                            if clean_content.startswith('json'):
                                clean_content = clean_content[4:].strip()
                            
                            parsed = json.loads(clean_content)
                            
                            # Create image analysis result
                            image_result_summary = {
                                "image_url": url + "#visual-content",
                                "claims_found": 1 if parsed.get("verdict") != "NO FACTUAL CLAIMS" else 0,
                                "fact_check_results": [{
                                    "claim": "Visual Content Analysis",
                                    "result": {
                                        "verdict": parsed.get("verdict", "INSUFFICIENT EVIDENCE"),
                                        "confidence": parsed.get("confidence", 75),
                                        "explanation": parsed.get("explanation", "Analysis completed"),
                                        "sources": parsed.get("sources", [])
                                    }
                                }]
                            }
                            
                            image_analysis_results.append(image_result_summary)
                            
                            # Add to combined results
                            fact_check_copy = image_result_summary["fact_check_results"][0].copy()
                            fact_check_copy['source_type'] = 'image'
                            fact_check_copy['image_url'] = url + "#visual-content"
                            all_results.append(fact_check_copy)
                            
                            print(f"URL-based visual analysis completed: {parsed.get('verdict')}")
                            
                        except json.JSONDecodeError:
                            print(f"Failed to parse screenshot analysis response")
                        
                except Exception as e:
                    print(f"Screenshot analysis failed: {e}")
        
        # Standard image analysis for detected images
        for i, img_url in enumerate(image_urls):
            try:
                print(f"Analyzing image {i+1}: {img_url}")
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
