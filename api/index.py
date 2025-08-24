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
    if re.search(r'\.(jpg|jpeg|png|gif|webp)$', pu.path, re.I):
        return True
    # Allow known image hosts even without extension
    return any(h in pu.netloc for h in ["pbs.twimg.com", "i.redd.it", "i.imgur.com"])

def extract_content_from_url(url: str) -> dict:
    """Extracts text and image URLs from a given URL with platform-specific logic."""
    parsed_url = urlparse(url)
    netloc = parsed_url.netloc
    text_content = ""
    image_urls = []

    try:
        # Twitter/X handler
        if 'twitter.com' in netloc or 'x.com' in netloc:
            match = re.search(r'/status/(\d+)', parsed_url.path)
            if match:
                tweet_id = match.group(1)
                # Use Twitter's syndication API for reliable content
                api_url = f"https://cdn.syndication.twimg.com/widgets/tweet?id={tweet_id}&lang=en"
                try:
                    r = requests.get(api_url, headers=DEFAULT_HEADERS, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        text_content = data.get('text', '')
                        for photo in data.get('photos', []):
                            image_urls.append(photo.get('url'))
                        if data.get('video'):
                            image_urls.append(data['video'].get('poster'))
                except Exception:
                    pass # Fallback to generic scraper if API fails

        # Reddit handler
        elif 'reddit.com' in netloc or 'redd.it' in netloc:
            json_url = _build_reddit_json_url(url)
            try:
                r = requests.get(json_url, headers=DEFAULT_HEADERS, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    post_data = data[0]['data']['children'][0]['data']
                    text_content = f"{post_data.get('title', '')} {post_data.get('selftext', '')}".strip()
                    
                    # Extract images from various Reddit structures
                    if post_data.get('url_overridden_by_dest') and _is_image_like(post_data['url_overridden_by_dest']):
                        image_urls.append(post_data['url_overridden_by_dest'])
                    if 'preview' in post_data:
                        for img in post_data['preview'].get('images', []):
                            image_urls.append(img['source']['url'].replace('&amp;', '&'))
                    if 'media_metadata' in post_data:
                        for media_id in post_data['media_metadata']:
                            media = post_data['media_metadata'][media_id]
                            if media['e'] == 'Image':
                                image_urls.append(media['s']['u'].replace('&amp;', '&'))
            except Exception:
                pass # Fallback to generic scraper

        # Generic URL handler (fallback for social media or primary for other sites)
        if not text_content:
            try:
                r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
                r.raise_for_status()
                html = r.text
                doc = Document(html)
                text_content = BeautifulSoup(doc.summary(), 'lxml').get_text(' ', strip=True)
                if len(text_content) < 150: # If readability fails, use full body
                    text_content = BeautifulSoup(html, 'lxml').get_text(' ', strip=True)
                
                soup = BeautifulSoup(html, 'lxml')
                # OpenGraph and Twitter Card images
                for prop in ['og:image', 'og:image:secure_url', 'twitter:image']:
                    meta = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
                    if meta and meta.get('content'):
                        image_urls.append(_resolve_url(url, meta['content']))
                # Find all `img` tags
                for img in soup.find_all('img'):
                    src = img.get('src') or img.get('data-src')
                    if src:
                        image_urls.append(_resolve_url(url, src))

            except requests.RequestException as e:
                raise ValueError(f"Failed to fetch URL: {e}")
            except Exception as e:
                raise ValueError(f"Failed to parse content: {e}")

    except Exception as e:
        return {"text": f"Extraction failed: {e}", "image_urls": []}

    # Clean up and final processing
    text_content = ' '.join(text_content.split())
    if len(text_content) > 12000:
        text_content = text_content[:12000] + '…'

    # Filter and deduplicate image URLs
    unique_images = sorted(list(set(filter(None, image_urls))))
    final_images = [img for img in unique_images if _is_image_like(img)]

    return {
        "text": text_content or "No text content found.",
        "image_urls": final_images[:10] # Limit to 10 images
    }

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
                        # annotate response with image metadata
                        image_data['images_detected'] = len(image_urls)
                        image_data['selected_image_url'] = primary_image_url
                        image_data['source_url'] = url
                        image_data['debug_image_urls'] = image_urls[:10]
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
                    text_data['images_detected'] = len(image_urls)
                    text_data['source_url'] = url
                    text_data['debug_image_urls'] = image_urls[:10]
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
            "original_text": text,
            "claims_found": len(results),
            "source_url": url,
            "images_detected": len(image_urls),
            "debug_image_urls": image_urls[:10]
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
