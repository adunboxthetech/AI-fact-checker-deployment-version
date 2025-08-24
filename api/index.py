from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from readability import Document

# Perplexity API configuration
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

def extract_text_from_url(url):
    """Extract text content from a URL with robust social media handling"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    try:
        parsed_url = urlparse(url)
        
        # Special handling for Reddit - try JSON API first
        if parsed_url.netloc in {"reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"}:
            try:
                # Convert to JSON URL
                json_url = url if url.endswith('.json') else (url.rstrip('/') + '.json')
                rj_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/json"
                }
                rj = requests.get(json_url, headers=rj_headers, timeout=15)
                if rj.status_code == 200:
                    data = rj.json()
                    # Standard post JSON: [post, comments]
                    try:
                        post = (data[0]["data"]["children"][0]["data"] if isinstance(data, list) else data["data"]["children"][0]["data"])
                        title = post.get("title", "")
                        selftext = post.get("selftext", "") or post.get("body", "")
                        text = f"{title}. {selftext}".strip()
                        if len(text) > 30:
                            return text
                    except Exception as e:
                        # If JSON parsing fails, try to extract from the raw JSON
                        if isinstance(data, dict) and "data" in data:
                            try:
                                children = data["data"].get("children", [])
                                if children and isinstance(children[0], dict) and "data" in children[0]:
                                    post_data = children[0]["data"]
                                    title = post_data.get("title", "")
                                    selftext = post_data.get("selftext", "") or post_data.get("body", "")
                                    text = f"{title}. {selftext}".strip()
                                    if len(text) > 30:
                                        return text
                            except Exception:
                                pass
            except Exception as e:
                # JSON approach failed, continue to HTML approach
                pass
        
        # Special handling for Twitter/X using syndication endpoint
        if parsed_url.netloc in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "m.twitter.com"} and "/status/" in parsed_url.path:
            m = re.search(r"/status/(\d+)", parsed_url.path)
            if m:
                tweet_id = m.group(1)
                
                # Try Twitter syndication endpoint first
                try:
                    tw = requests.get(
                        "https://cdn.syndication.twimg.com/widgets/tweet",
                        params={"id": tweet_id, "lang": "en"}, headers=headers, timeout=12
                    )
                    if tw.status_code == 200:
                        data = tw.json()
                        text = data.get("text") or data.get("full_text") or data.get("i18n_text") or ""
                        if not text and data.get("body_html"):
                            text = BeautifulSoup(data["body_html"], "lxml").get_text(" ", strip=True)
                        if text and len(text) > 20:
                            return text
                except Exception:
                    pass
                
                # Fallback: Try Twitter's oEmbed endpoint
                try:
                    oembed_url = f"https://publish.twitter.com/oembed?url=https://twitter.com/i/status/{tweet_id}&omit_script=true"
                    oembed_response = requests.get(oembed_url, headers=headers, timeout=12)
                    if oembed_response.status_code == 200:
                        oembed_data = oembed_response.json()
                        if oembed_data.get("html"):
                            # Extract text from oEmbed HTML
                            soup = BeautifulSoup(oembed_data["html"], "lxml")
                            # Remove all links and formatting, keep only text
                            for tag in soup.find_all(['a', 'strong', 'em', 'b', 'i']):
                                tag.unwrap()
                            text = soup.get_text(" ", strip=True)
                            if text and len(text) > 20:
                                return text
                except Exception:
                    pass
        
        # Try direct HTML request
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200:
                # Parse HTML content
                html = response.text
                
                # Use readability for better content extraction
                try:
                    doc = Document(html)
                    title = doc.short_title()
                    summary_html = doc.summary()
                    soup = BeautifulSoup(summary_html, "lxml")
                    main_text = soup.get_text(separator=" ", strip=True)
                    
                    # If readability extraction is too short, try fallback
                    if len(main_text) < 100:
                        # Fallback to full page extraction
                        full_soup = BeautifulSoup(html, "lxml")
                        main_text = full_soup.get_text(separator=" ", strip=True)
                except Exception:
                    # If readability fails, use direct BeautifulSoup
                    soup = BeautifulSoup(html, "lxml")
                    main_text = soup.get_text(separator=" ", strip=True)
                
                # Clean up the text
                main_text = re.sub(r'\s+', ' ', main_text).strip()
                
                if len(main_text) > 50:
                    return main_text
                    
        except Exception as e:
            # HTML approach failed
            pass
        
        # Final fallback: Try Jina Reader proxy
        try:
            q = f"?{parsed_url.query}" if parsed_url.query else ""
            wrapped = f"https://r.jina.ai/{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}{q}"
            jr = requests.get(wrapped, headers=headers, timeout=18)
            if jr.status_code == 200 and len(jr.text.strip()) > 50:
                return re.sub(r'\s+', ' ', jr.text).strip()
        except Exception as e:
            pass
        
        # If all methods fail, raise an error
        raise ValueError(f"Failed to extract content from URL after trying multiple methods")
        
    except Exception as e:
        raise ValueError(f"Error extracting content: {str(e)}")

def extract_content_from_url(url):
    """Extract both text and image URLs from a URL using multiple strategies"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    try:
        parsed_url = urlparse(url)
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            # Fall back to robust text extractor (handles Reddit JSON and Jina Reader)
            text = extract_text_from_url(url)
            soup = BeautifulSoup('', 'lxml')
        else:
            # Parse HTML content
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Extract text content (existing logic)
            text = extract_text_from_url(url)
        
        # Extract image URLs using multiple strategies
        image_urls = []
        
        # Strategy 1: Extract from HTML img tags (only if we have HTML)
        if soup and soup.find_all:
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if src:
                    # Convert relative URLs to absolute
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = f"{parsed_url.scheme}://{parsed_url.netloc}{src}"
                    elif not src.startswith('http'):
                        src = f"{parsed_url.scheme}://{parsed_url.netloc}/{src}"
                    
                    # Filter out small images, icons, and common non-content images
                    if (src and 
                        not any(skip in src.lower() for skip in ['avatar', 'icon', 'logo', 'emoji', 'favicon', 'analytics', 'tracking', 'ads']) and
                        not any(skip in img.get('class', []) for skip in ['avatar', 'icon', 'logo', 'emoji']) and
                        not any(skip in (img.get('alt', '') or '').lower() for skip in ['avatar', 'icon', 'logo', 'emoji'])):
                        image_urls.append(src)
        
        # Strategy 2: Platform-specific extraction
        platform_images = extract_platform_specific_images(url, parsed_url, headers, text)
        image_urls.extend(platform_images)
        
        # Strategy 3: Look for image URLs in text content
        text_image_urls = extract_image_urls_from_text(text, url)
        image_urls.extend(text_image_urls)
        
        # Strategy 4: Look for Open Graph and Twitter Card images
        if soup and soup.find_all:
            og_images = extract_og_images(soup, parsed_url)
            image_urls.extend(og_images)
        
        # Remove duplicates and filter
        unique_images = []
        seen = set()
        for img_url in image_urls:
            if img_url and img_url not in seen:
                seen.add(img_url)
                unique_images.append(img_url)
        
        return {
            "text": text,
            "image_urls": unique_images
        }
        
    except Exception as e:
        raise ValueError(f"Error extracting content: {str(e)}")

def extract_platform_specific_images(url, parsed_url, headers, text):
    """Extract images using platform-specific methods"""
    image_urls = []
    
    # Twitter/X
    if parsed_url.netloc in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and "/status/" in parsed_url.path:
        try:
            m = re.search(r"/status/(\d+)", parsed_url.path)
            if m:
                tweet_id = m.group(1)
                
                # Twitter oEmbed API
                oembed_url = f"https://publish.twitter.com/oembed?url=https://twitter.com/i/status/{tweet_id}&omit_script=true"
                oembed_response = requests.get(oembed_url, headers=headers, timeout=12)
                if oembed_response.status_code == 200:
                    oembed_data = oembed_response.json()
                    if oembed_data.get("html"):
                        oembed_html = oembed_data["html"]
                        # Extract pic.twitter.com short links first
                        pic_urls = re.findall(r'pic\.twitter\.com/[a-zA-Z0-9]+', oembed_html)
                        for pic_url in pic_urls:
                            full_pic_url = f"https://{pic_url}"
                            image_urls.append(full_pic_url)
                        # Also try to extract direct pbs.twimg.com media links
                        pbs_urls = re.findall(r'https://pbs\.twimg\.com/media/[^"\s>]+', oembed_html)
                        image_urls.extend(pbs_urls)
                
                # Twitter syndication endpoint often includes direct media
                try:
                    tw = requests.get(
                        "https://cdn.syndication.twimg.com/widgets/tweet",
                        params={"id": tweet_id, "lang": "en"}, headers=headers, timeout=12
                    )
                    if tw.status_code == 200:
                        data = tw.json()
                        photos = data.get("photos") or []
                        for p in photos:
                            media_url = p.get("url") or p.get("media_url_https") or p.get("media_url")
                            if media_url:
                                image_urls.append(media_url)
                        # Some cards include image under "card" -> binding_values
                        try:
                            card = data.get("card") or {}
                            bindings = card.get("binding_values") or {}
                            for v in bindings.values():
                                if isinstance(v, dict) and v.get("type") == "IMAGE" and isinstance(v.get("image_value"), dict):
                                    u = v["image_value"].get("url")
                                    if u:
                                        image_urls.append(u)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
    
    # Reddit
    elif parsed_url.netloc in {"reddit.com", "www.reddit.com", "old.reddit.com"}:
        try:
            # Prefer Reddit JSON for reliable media discovery
            json_url = url if url.endswith('.json') else (url.rstrip('/') + '.json')
            rj_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json"
            }
            rj = requests.get(json_url, headers=rj_headers, timeout=12)
            if rj.status_code == 200:
                data = rj.json()
                try:
                    post = (data[0]["data"]["children"][0]["data"] if isinstance(data, list) else data["data"]["children"][0]["data"])
                except Exception:
                    post = {}
                
                # Direct URL field
                cand = post.get("url_overridden_by_dest") or post.get("url")
                if isinstance(cand, str) and re.search(r'\.(jpg|jpeg|png|gif|webp)(?:\?|$)', cand, re.I):
                    image_urls.append(cand)
                
                # Preview images
                preview = post.get("preview") or {}
                for img in (preview.get("images") or []):
                    src = (img.get("source") or {}).get("url") or ""
                    if src:
                        image_urls.append(src.replace('&amp;', '&'))
                    for res in (img.get("resolutions") or []):
                        u = res.get("url")
                        if u:
                            image_urls.append(u.replace('&amp;', '&'))
                
                # Gallery images
                media_meta = post.get("media_metadata") or {}
                gallery = post.get("gallery_data") or {}
                if media_meta:
                    if gallery and isinstance(gallery.get("items"), list):
                        for it in gallery["items"]:
                            m = media_meta.get(it.get("media_id")) or {}
                            if isinstance(m, dict):
                                s = (m.get("s") or {}).get("u") or ""
                                if s:
                                    image_urls.append(s.replace('&amp;', '&'))
                                for p in (m.get("p") or []):
                                    u = p.get("u")
                                    if u:
                                        image_urls.append(u.replace('&amp;', '&'))
                    else:
                        for m in media_meta.values():
                            if isinstance(m, dict):
                                s = (m.get("s") or {}).get("u") or ""
                                if s:
                                    image_urls.append(s.replace('&amp;', '&'))
                
                # Secure media thumbnails
                sm = post.get("secure_media") or {}
                thumb = (sm.get("oembed") or {}).get("thumbnail_url")
                if thumb:
                    image_urls.append(thumb)
            
            # Fallback: regex for i.redd.it and imgur links in text
            reddit_images = re.findall(r'https://i\.redd\.it/[a-zA-Z0-9_\-]+\.(?:jpg|jpeg|png|gif|webp)', text)
            image_urls.extend(reddit_images)
            imgur_images = re.findall(r'https://i?\.imgur\.com/[a-zA-Z0-9_\-]+\.(?:jpg|jpeg|png|gif|webp)', text)
            image_urls.extend(imgur_images)
        except Exception:
            pass
    
    # Instagram
    elif parsed_url.netloc in {"instagram.com", "www.instagram.com"}:
        try:
            # Instagram often has direct image URLs
            instagram_images = re.findall(r'https://scontent-[a-z0-9-]+\.cdninstagram\.com/[^"\s]+', text)
            image_urls.extend(instagram_images)
        except Exception:
            pass
    
    # Facebook
    elif parsed_url.netloc in {"facebook.com", "www.facebook.com", "fb.com", "www.fb.com"}:
        try:
            # Facebook often has direct image URLs
            facebook_images = re.findall(r'https://scontent-[a-z0-9-]+\.fbcdn\.net/[^"\s]+', text)
            image_urls.extend(facebook_images)
        except Exception:
            pass
    
    return image_urls


def process_image_url(image_url):
    """Process image URLs to handle redirects and protected URLs"""
    try:
        # For Twitter pic.twitter.com URLs, try to resolve to pbs.twimg.com
        if 'pic.twitter.com' in image_url:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            try:
                r = requests.get(image_url, headers=headers, timeout=12, allow_redirects=True)
                if r.status_code == 200:
                    m = re.search(r'https://pbs\.twimg\.com/media/[^"\s>]+', r.text)
                    if not m:
                        m = re.search(r'https://pbs\.twimg\.com/[^"\s>]+', r.text)
                    if not m:
                        m = re.search(r'property="og:image"\s+content="(https://pbs\.twimg\.com/[^"\s>]+)"', r.text)
                    if m:
                        return m.group(1)
            except Exception:
                pass
            # Fall back to original short URL if parsing fails
            return image_url
        
        # For other URLs, return as is
        return image_url
    except Exception:
        # If processing fails, return the original URL
        return image_url

def extract_image_urls_from_text(text, base_url):
    """Extract image URLs from text content"""
    image_urls = []
    
    # Common image URL patterns
    patterns = [
        r'https://[^"\s]+\.(?:jpg|jpeg|png|gif|webp)',
        r'https://[^"\s]+\.(?:jpg|jpeg|png|gif|webp)\?[^"\s]*',
        r'https://pic\.twitter\.com/[a-zA-Z0-9]+',
        r'https://imgur\.com/[a-zA-Z0-9]+',
        r'https://i\.redd\.it/[a-zA-Z0-9]+\.(?:jpg|jpeg|png|gif)',
        r'https://scontent-[a-z0-9-]+\.cdninstagram\.com/[^"\s]+',
        r'https://scontent-[a-z0-9-]+\.fbcdn\.net/[^"\s]+'
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        image_urls.extend(matches)
    
    return image_urls

def extract_og_images(soup, parsed_url):
    """Extract Open Graph and Twitter Card images"""
    image_urls = []
    
    # Open Graph images
    og_images = soup.find_all('meta', property='og:image')
    for og_img in og_images:
        src = og_img.get('content')
        if src:
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = f"{parsed_url.scheme}://{parsed_url.netloc}{src}"
            elif not src.startswith('http'):
                src = f"{parsed_url.scheme}://{parsed_url.netloc}/{src}"
            image_urls.append(src)
    
    # Twitter Card images
    twitter_images = soup.find_all('meta', attrs={'name': 'twitter:image'})
    for twitter_img in twitter_images:
        src = twitter_img.get('content')
        if src:
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = f"{parsed_url.scheme}://{parsed_url.netloc}{src}"
            elif not src.startswith('http'):
                src = f"{parsed_url.scheme}://{parsed_url.netloc}/{src}"
            image_urls.append(src)
    
    return image_urls

def fact_check_text(text):
    """Simple fact-check function"""
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

            
            # Try to parse as JSON, fallback to simple response
            try:
                # First, try to clean the content if it has "json" prefix
                clean_content = content.strip()
                if clean_content.startswith('json '):
                    clean_content = clean_content[5:].strip()
                
                parsed = json.loads(clean_content)
                # Format for frontend: create fact_check_results array
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
            except:
                # If the content looks like JSON but failed to parse, try to extract useful parts
                if '"verdict"' in content and '"explanation"' in content:
                    # Try to extract key parts using regex
                    verdict_match = re.search(r'"verdict":\s*"([^"]+)"', content, re.IGNORECASE)
                    confidence_match = re.search(r'"confidence":\s*(\d+)', content, re.IGNORECASE)
                    explanation_match = re.search(r'"explanation":\s*"([^"]+)"', content, re.IGNORECASE)
                    sources_match = re.search(r'"sources":\s*\[(.*?)\]', content, re.IGNORECASE | re.DOTALL)
                    
                    verdict = verdict_match.group(1) if verdict_match else "INSUFFICIENT EVIDENCE"
                    confidence = int(confidence_match.group(1)) if confidence_match else 75
                    explanation = explanation_match.group(1) if explanation_match else content
                    sources = ["Perplexity Analysis"]
                    

                    
                    if sources_match:
                        # Try to extract URLs from sources
                        sources_text = sources_match.group(1)
                        # Look for URLs in the sources text, handling quoted strings
                        url_matches = re.findall(r'https?://[^"\s,]+', sources_text)
                        if url_matches:
                            sources = url_matches
                        else:
                            # Fallback: try to extract from the full content
                            all_urls = re.findall(r'https?://[^"\s,]+', content)
                            if all_urls:
                                sources = all_urls[:5]  # Limit to first 5 URLs
                    
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
                else:
                    # Fallback response
                    fact_check_result = {
                        "claim": text[:200] + "..." if len(text) > 200 else text,
                        "result": {
                            "verdict": "INSUFFICIENT EVIDENCE",
                            "confidence": 75,
                            "explanation": content,
                            "sources": ["Perplexity Analysis"]
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
    """Fact-check claims from an image using Perplexity's multimodal capabilities"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # Build Perplexity multimodal prompt for direct fact-checking
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "You are a visual fact-checking expert. Analyze this image comprehensively using your visual understanding capabilities. "
                        "Look at the image as a whole - examine charts, graphs, text, images, symbols, and visual elements. "
                        "Identify any factual claims, statistics, data, or statements that can be verified. "
                        "For charts/graphs: Analyze the data, labels, sources, and methodology. "
                        "For text: Read and verify any claims, quotes, or statements. "
                        "For images: Identify any factual content, dates, names, or verifiable information. "
                        "If the image contains factual claims, provide a thorough fact-check analysis. "
                        "If the image is purely visual (art, abstract, decorative) with no factual content, indicate this. "
                        "Return ONLY a valid JSON object with this exact structure: "
                        "{"
                        '"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS",'
                        '"confidence": 0-100,'
                        '"explanation": "Your detailed visual analysis here",'
                        '"sources": ["url1", "url2"]'
                        "}"
                        "CRITICAL: Return ONLY the JSON object, no other text. Use your visual understanding to analyze the image content, not just extract text."
                    )}
                ]
            }
        ]
        
        # Handle different types of image URLs
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        elif image_url:
            # Try to handle redirect URLs and protected URLs
            processed_url = process_image_url(image_url)
            messages[0]["content"].append({"type": "image_url", "image_url": processed_url})

        payload = {
            "model": "sonar-pro",  # supports vision per Perplexity docs
            "messages": messages,
            "max_tokens": 800,
        }

        sonar_resp = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=30)
        if sonar_resp.status_code != 200:
            return {"error": f"Image analysis failed: HTTP {sonar_resp.status_code}"}, 500

        content = sonar_resp.json()['choices'][0]['message']['content']
        
        # Try to parse the response as JSON
        try:
            # Clean the content if it has "json" prefix
            clean_content = content.strip()
            if clean_content.startswith('json '):
                clean_content = clean_content[5:].strip()
            
            parsed = json.loads(clean_content)
            
            # Create the result structure
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
            # If JSON parsing fails, try to extract useful information
            if "no factual claims" in content.lower() or "no claims" in content.lower():
                return {
                    "fact_check_results": [{
                        "claim": "Image Analysis",
                        "result": {
                            "verdict": "NO FACTUAL CLAIMS",
                            "confidence": 100,
                            "explanation": "This image does not contain any factual claims that can be verified. It may be an artistic image, abstract content, or visual content without specific factual statements.",
                            "sources": []
                        }
                    }],
                    "claims_found": 0,
                    "timestamp": time.time(),
                    "source_url": image_url if image_url else None
                }, 200
            else:
                # Try to extract verdict and explanation from the text
                verdict_match = re.search(r'"verdict":\s*"([^"]+)"', content, re.IGNORECASE)
                confidence_match = re.search(r'"confidence":\s*(\d+)', content, re.IGNORECASE)
                explanation_match = re.search(r'"explanation":\s*"([^"]+)"', content, re.IGNORECASE)
                
                verdict = verdict_match.group(1) if verdict_match else "INSUFFICIENT EVIDENCE"
                confidence = int(confidence_match.group(1)) if confidence_match else 75
                explanation = explanation_match.group(1) if explanation_match else content
                
                return {
                    "fact_check_results": [{
                        "claim": "Image Analysis",
                        "result": {
                            "verdict": verdict,
                            "confidence": confidence,
                            "explanation": explanation,
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
    """Fact-check both text and images from a URL using multimodal analysis"""
    try:
        # Extract both text and images from URL
        content = extract_content_from_url(url)
        text = content["text"]
        image_urls = content["image_urls"]
        
        # If we have images, use multimodal analysis
        if image_urls and len(image_urls) > 0:
            # Use the first image for multimodal analysis
            primary_image_url = image_urls[0]
            
            # Create a comprehensive prompt that includes both text and image context
            multimodal_prompt = f"""
            You are a comprehensive fact-checking expert. Analyze this social media post which contains both text and visual content.
            
            TEXT CONTENT: {text}
            
            VISUAL CONTENT: This post also contains an image that may contain additional factual claims, charts, graphs, screenshots, or visual information.
            
            TASK: Perform a thorough fact-check analysis considering both the text content and any factual claims visible in the image. Look for:
            - Claims in the text
            - Claims visible in the image (charts, graphs, text in images, screenshots, etc.)
            - Statistics, data, or numbers shown visually
            - Dates, names, or other factual information in the image
            - Any discrepancies between text and visual content
            
            RESPONSE FORMAT: Return ONLY a valid JSON object with this exact structure:
            {{
                "verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS",
                "confidence": 0-100,
                "explanation": "Your comprehensive analysis covering both text and visual content",
                "sources": ["url1", "url2"],
                "text_claims": ["claim1", "claim2"],
                "visual_claims": ["visual_claim1", "visual_claim2"]
            }}
            
            CRITICAL: Return ONLY the JSON object, no other text. Analyze both text and visual content comprehensively.
            """
            
            # Use multimodal analysis with the image
            try:
                image_result = fact_check_image_multimodal("", primary_image_url, multimodal_prompt)
                if isinstance(image_result, tuple):
                    image_data, image_status = image_result
                    if image_status == 200 and isinstance(image_data, dict) and 'fact_check_results' in image_data:
                        # Update the claim to reflect multimodal analysis
                        for result in image_data['fact_check_results']:
                            result['claim'] = f"Multimodal Analysis: Text + Image from {get_platform_name(url)}"
                        return image_data, 200
            except Exception as e:
                # If multimodal analysis fails, fall back to text-only analysis
                pass
        
        # Fallback to text-only analysis if no images or multimodal analysis fails
        if text and len(text.strip()) > 5:
            text_result = fact_check_text(text)
            if isinstance(text_result, tuple):
                text_data, text_status = text_result
                if text_status == 200 and isinstance(text_data, dict) and 'fact_check_results' in text_data:
                    # Add information about detected images if any
                    if image_urls:
                        for result in text_data['fact_check_results']:
                            result['claim'] = f"Text Analysis (with {len(image_urls)} image(s) detected): {result.get('claim', 'Content Analysis')}"
                    return text_data, 200
        
        # If no results, create a default response
        results = [{
            "claim": f"Content Analysis from {get_platform_name(url)}",
            "result": {
                "verdict": "NO FACTUAL CLAIMS",
                "confidence": 100,
                "explanation": "The content does not contain any factual claims that can be verified.",
                "sources": []
            }
        }]
        
        return {
            "fact_check_results": results,
            "claims_found": len(results),
            "timestamp": time.time(),
            "source_url": url,
            "images_detected": len(image_urls)
        }, 200
        
    except Exception as e:
        return {"error": f"URL analysis failed: {str(e)}"}, 500

def fact_check_image_multimodal(image_data_url, image_url, custom_prompt):
    """Fact-check claims from an image using Perplexity's multimodal capabilities with custom prompt"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # Build Perplexity multimodal prompt
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": custom_prompt}
                ]
            }
        ]
        
        # Handle different types of image URLs
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        elif image_url:
            # Try to handle redirect URLs and protected URLs
            processed_url = process_image_url(image_url)
            messages[0]["content"].append({"type": "image_url", "image_url": processed_url})

        payload = {
            "model": "sonar-pro",  # supports vision per Perplexity docs
            "messages": messages,
            "max_tokens": 800,
        }

        sonar_resp = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=30)
        if sonar_resp.status_code != 200:
            return {"error": f"Image analysis failed: HTTP {sonar_resp.status_code}"}, 500

        content = sonar_resp.json()['choices'][0]['message']['content']
        
        # Try to parse the response as JSON
        try:
            # Clean the content if it has "json" prefix
            clean_content = content.strip()
            if clean_content.startswith('json '):
                clean_content = clean_content[5:].strip()
            
            parsed = json.loads(clean_content)
            
            # Create the result structure
            result = {
                "fact_check_results": [{
                    "claim": "Multimodal Analysis",
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
            # If JSON parsing fails, try to extract useful information
            if "no factual claims" in content.lower() or "no claims" in content.lower():
                return {
                    "fact_check_results": [{
                        "claim": "Multimodal Analysis",
                        "result": {
                            "verdict": "NO FACTUAL CLAIMS",
                            "confidence": 100,
                            "explanation": "This content does not contain any factual claims that can be verified.",
                            "sources": []
                        }
                    }],
                    "claims_found": 0,
                    "timestamp": time.time(),
                    "source_url": image_url if image_url else None
                }, 200
            else:
                # Try to extract verdict and explanation from the text
                verdict_match = re.search(r'"verdict":\s*"([^"]+)"', content, re.IGNORECASE)
                confidence_match = re.search(r'"confidence":\s*(\d+)', content, re.IGNORECASE)
                explanation_match = re.search(r'"explanation":\s*"([^"]+)"', content, re.IGNORECASE)
                
                verdict = verdict_match.group(1) if verdict_match else "INSUFFICIENT EVIDENCE"
                confidence = int(confidence_match.group(1)) if confidence_match else 75
                explanation = explanation_match.group(1) if explanation_match else content
                
                return {
                    "fact_check_results": [{
                        "claim": "Multimodal Analysis",
                        "result": {
                            "verdict": verdict,
                            "confidence": confidence,
                            "explanation": explanation,
                            "sources": []
                        }
                    }],
                    "claims_found": 1,
                    "timestamp": time.time(),
                    "source_url": image_url if image_url else None
                }, 200

    except Exception as e:
        return {"error": f"Multimodal analysis failed: {str(e)}"}, 500

def get_platform_name(url):
    """Get the platform name from a URL"""
    if 'twitter.com' in url or 'x.com' in url or 'pic.twitter.com' in url:
        return "Twitter/X"
    elif 'reddit.com' in url or 'i.redd.it' in url:
        return "Reddit"
    elif 'instagram.com' in url or 'cdninstagram.com' in url:
        return "Instagram"
    elif 'facebook.com' in url or 'fb.com' in url or 'fbcdn.net' in url:
        return "Facebook"
    elif 'imgur.com' in url:
        return "Imgur"
    else:
        return "social media"

def fact_check_text(text):
    """Simple fact-check function"""
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

            
            # Try to parse as JSON, fallback to simple response
            try:
                # First, try to clean the content if it has "json" prefix
                clean_content = content.strip()
                if clean_content.startswith('json '):
                    clean_content = clean_content[5:].strip()
                
                parsed = json.loads(clean_content)
                # Format for frontend: create fact_check_results array
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
            except:
                # If the content looks like JSON but failed to parse, try to extract useful parts
                if '"verdict"' in content and '"explanation"' in content:
                    # Try to extract key parts using regex
                    verdict_match = re.search(r'"verdict":\s*"([^"]+)"', content, re.IGNORECASE)
                    confidence_match = re.search(r'"confidence":\s*(\d+)', content, re.IGNORECASE)
                    explanation_match = re.search(r'"explanation":\s*"([^"]+)"', content, re.IGNORECASE)
                    sources_match = re.search(r'"sources":\s*\[(.*?)\]', content, re.IGNORECASE | re.DOTALL)
                    
                    verdict = verdict_match.group(1) if verdict_match else "INSUFFICIENT EVIDENCE"
                    confidence = int(confidence_match.group(1)) if confidence_match else 75
                    explanation = explanation_match.group(1) if explanation_match else content
                    sources = ["Perplexity Analysis"]
                    

                    
                    if sources_match:
                        # Try to extract URLs from sources
                        sources_text = sources_match.group(1)
                        # Look for URLs in the sources text, handling quoted strings
                        url_matches = re.findall(r'https?://[^"\s,]+', sources_text)
                        if url_matches:
                            sources = url_matches
                        else:
                            # Fallback: try to extract from the full content
                            all_urls = re.findall(r'https?://[^"\s,]+', content)
                            if all_urls:
                                sources = all_urls[:5]  # Limit to first 5 URLs
                    
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
                else:
                    # Fallback response
                    fact_check_result = {
                        "claim": text[:200] + "..." if len(text) > 200 else text,
                        "result": {
                            "verdict": "INSUFFICIENT EVIDENCE",
                            "confidence": 75,
                            "explanation": content,
                            "sources": ["Perplexity Analysis"]
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
    """Fact-check claims from an image using Perplexity's multimodal capabilities"""
    if not PERPLEXITY_API_KEY:
        return {"error": "API key not configured"}, 500
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        # Build Perplexity multimodal prompt for direct fact-checking
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "You are a visual fact-checking expert. Analyze this image comprehensively using your visual understanding capabilities. "
                        "Look at the image as a whole - examine charts, graphs, text, images, symbols, and visual elements. "
                        "Identify any factual claims, statistics, data, or statements that can be verified. "
                        "For charts/graphs: Analyze the data, labels, sources, and methodology. "
                        "For text: Read and verify any claims, quotes, or statements. "
                        "For images: Identify any factual content, dates, names, or verifiable information. "
                        "If the image contains factual claims, provide a thorough fact-check analysis. "
                        "If the image is purely visual (art, abstract, decorative) with no factual content, indicate this. "
                        "Return ONLY a valid JSON object with this exact structure: "
                        "{"
                        '"verdict": "TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE/NO FACTUAL CLAIMS",'
                        '"confidence": 0-100,'
                        '"explanation": "Your detailed visual analysis here",'
                        '"sources": ["url1", "url2"]'
                        "}"
                        "CRITICAL: Return ONLY the JSON object, no other text. Use your visual understanding to analyze the image content, not just extract text."
                    )}
                ]
            }
        ]
        
        # Handle different types of image URLs
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        elif image_url:
            # Try to handle redirect URLs and protected URLs
            processed_url = process_image_url(image_url)
            messages[0]["content"].append({"type": "image_url", "image_url": processed_url})

        payload = {
            "model": "sonar-pro",  # supports vision per Perplexity docs
            "messages": messages,
            "max_tokens": 800,
        }

        sonar_resp = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=30)
        if sonar_resp.status_code != 200:
            return {"error": f"Image analysis failed: HTTP {sonar_resp.status_code}"}, 500

        content = sonar_resp.json()['choices'][0]['message']['content']
        
        # Try to parse the response as JSON
        try:
            # Clean the content if it has "json" prefix
            clean_content = content.strip()
            if clean_content.startswith('json '):
                clean_content = clean_content[5:].strip()
            
            parsed = json.loads(clean_content)
            
            # Create the result structure
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
            # If JSON parsing fails, try to extract useful information
            if "no factual claims" in content.lower() or "no claims" in content.lower():
                return {
                    "fact_check_results": [{
                        "claim": "Image Analysis",
                        "result": {
                            "verdict": "NO FACTUAL CLAIMS",
                            "confidence": 100,
                            "explanation": "This image does not contain any factual claims that can be verified. It may be an artistic image, abstract content, or visual content without specific factual statements.",
                            "sources": []
                        }
                    }],
                    "claims_found": 0,
                    "timestamp": time.time(),
                    "source_url": image_url if image_url else None
                }, 200
            else:
                # Try to extract verdict and explanation from the text
                verdict_match = re.search(r'"verdict":\s*"([^"]+)"', content, re.IGNORECASE)
                confidence_match = re.search(r'"confidence":\s*(\d+)', content, re.IGNORECASE)
                explanation_match = re.search(r'"explanation":\s*"([^"]+)"', content, re.IGNORECASE)
                
                verdict = verdict_match.group(1) if verdict_match else "INSUFFICIENT EVIDENCE"
                confidence = int(confidence_match.group(1)) if confidence_match else 75
                explanation = explanation_match.group(1) if explanation_match else content
                
                return {
                    "fact_check_results": [{
                        "claim": "Image Analysis",
                        "result": {
                            "verdict": verdict,
                            "confidence": confidence,
                            "explanation": explanation,
                            "sources": []
                        }
                    }],
                    "claims_found": 1,
                    "timestamp": time.time(),
                    "source_url": image_url if image_url else None
                }, 200

    except Exception as e:
        return {"error": f"Image analysis failed: {str(e)}"}, 500

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
        
        if self.path == '/api/fact-check':
            # Handle both text and URL inputs
            text = data.get('text', '')
            url = data.get('url', '')
            
            if not text and not url:
                response_data = {"error": "No text or URL provided"}
                status_code = 400
            else:
                try:
                    if url:
                        # Extract and fact-check both text and images from URL
                        response_data, status_code = fact_check_url_with_images(url)
                    else:
                        # Use provided text
                        response_data, status_code = fact_check_text(text)
                except Exception as e:
                    response_data = {"error": f"Content extraction failed: {str(e)}"}
                    status_code = 400
        elif self.path == '/api/fact-check-image':
            # Handle image-based fact checking
            image_data_url = data.get('image_data_url', '')
            image_url = data.get('image_url', '')
            
            if not image_data_url and not image_url:
                response_data = {"error": "No image data URL or image URL provided"}
                status_code = 400
            else:
                # Check image data URL size (limit to 10MB)
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
