from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# Perplexity API configuration
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

def extract_text_from_url(url):
    """Extract text content from a URL"""
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
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            raise ValueError(f"Failed to fetch URL (status {response.status_code})")
        
        # Special handling for Twitter/X using syndication endpoint (WORKING METHOD)
        parsed_url = urlparse(url)
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
                
                # Fallback: Try mobile Twitter URL
                try:
                    mobile_url = f"https://mobile.twitter.com/i/status/{tweet_id}"
                    mobile_response = requests.get(mobile_url, headers=headers, timeout=12)
                    if mobile_response.status_code == 200:
                        mobile_content = mobile_response.text
                        
                        # Look for tweet text in mobile version
                        tweet_patterns = [
                            r'<div[^>]*data-testid="tweetText"[^>]*>(.*?)</div>',
                            r'<div[^>]*class="[^"]*tweet-text[^"]*"[^>]*>(.*?)</div>',
                            r'<div[^>]*class="[^"]*text[^"]*"[^>]*>(.*?)</div>',
                            r'<p[^>]*class="[^"]*tweet-text[^"]*"[^>]*>(.*?)</p>',
                            r'<meta[^>]*name="description"[^>]*content="([^"]*)"',
                            r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"'
                        ]
                        
                        for pattern in tweet_patterns:
                            match = re.search(pattern, mobile_content, re.DOTALL | re.IGNORECASE)
                            if match:
                                tweet_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                                tweet_text = re.sub(r'&[a-zA-Z]+;', ' ', tweet_text)
                                tweet_text = re.sub(r'\s+', ' ', tweet_text).strip()
                                if tweet_text and len(tweet_text) > 20:
                                    return tweet_text
                except Exception:
                    pass
        
        # General text extraction for other sites - COMPLETELY REWRITTEN
        text = response.text
        
        # STEP 1: Remove ALL script, style, and non-content HTML elements
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<aside[^>]*>.*?</aside>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<form[^>]*>.*?</form>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<button[^>]*>.*?</button>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<input[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<select[^>]*>.*?</select>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<textarea[^>]*>.*?</textarea>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # STEP 2: Remove ALL CSS and JS patterns BEFORE HTML tag removal
        text = re.sub(r'\{[^}]*\}', '', text)  # Remove ALL CSS blocks
        text = re.sub(r'[a-zA-Z-]+\s*:\s*[^;]+;', '', text)  # Remove ALL CSS properties
        text = re.sub(r'#[a-zA-Z0-9_-]+', '', text)  # Remove CSS IDs
        text = re.sub(r'\.[a-zA-Z0-9_-]+', '', text)  # Remove CSS classes
        text = re.sub(r'function\s*\([^)]*\)\s*\{[^}]*\}', '', text)  # Remove JS functions
        text = re.sub(r'(var|const|let)\s+[^;]+;', '', text)  # Remove JS declarations
        text = re.sub(r'[a-zA-Z0-9_-]+\s*=\s*[^;]+;', '', text)  # Remove JS assignments
        text = re.sub(r'import\s+[^;]+;', '', text)  # Remove JS imports
        text = re.sub(r'export\s+[^;]+;', '', text)  # Remove JS exports
        
        # STEP 3: Remove remaining HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        
        # STEP 4: Clean up whitespace and normalize
        text = re.sub(r'\s+', ' ', text).strip()
        
        # STEP 5: Split into lines and filter out ANY line that looks like code
        lines = text.split('\n')
        filtered_lines = []
        for line in lines:
            line = line.strip()
            # Only keep lines that look like human-readable text
            if (line and len(line) > 15 and
                line.count(' ') > 2 and  # Must have multiple words
                not re.search(r'[{}:;]', line) and  # No CSS/JS characters
                not re.search(r'function|var|const|let|import|export', line, re.IGNORECASE) and  # No JS keywords
                not re.search(r'background|color|border|margin|padding|font|display|position|width|height', line, re.IGNORECASE) and  # No CSS properties
                not re.match(r'^[.#][a-zA-Z0-9_-]', line) and  # No CSS selectors
                not re.match(r'^[a-zA-Z0-9_-]+\s*[=:]', line) and  # No assignments or properties
                not re.match(r'^[{}]$', line) and  # No just braces
                not re.match(r'^[a-zA-Z0-9_-]+\s*\(', line) and  # No function calls
                line.count('a') + line.count('e') + line.count('i') + line.count('o') + line.count('u') > 3):  # Must have vowels (human text)
                filtered_lines.append(line)
        
        text = ' '.join(filtered_lines)
        
        # STEP 6: If we still have CSS/JS artifacts, do final cleanup
        text = re.sub(r'[a-zA-Z-]+\s*:\s*[^;]+;?', '', text)  # Remove any remaining CSS properties
        text = re.sub(r'\{[^}]*\}', '', text)  # Remove any remaining blocks
        text = re.sub(r'[a-zA-Z0-9_-]+\s*=\s*[^;]+;?', '', text)  # Remove any remaining assignments
        
        # STEP 7: Final cleanup
        text = re.sub(r'\s+', ' ', text).strip()
        
        # STEP 8: If we still don't have good content, try a different approach
        if len(text.strip()) < 30:
            # Look for any text that looks like actual content
            original_text = response.text
            # Try to find text in specific content areas
            content_patterns = [
                r'<main[^>]*>(.*?)</main>',
                r'<article[^>]*>(.*?)</article>',
                r'<section[^>]*>(.*?)</section>',
                r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*text[^"]*"[^>]*>(.*?)</div>',
                r'<p[^>]*>(.*?)</p>'
            ]
            
            for pattern in content_patterns:
                matches = re.findall(pattern, original_text, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    # Clean this specific content
                    clean_match = re.sub(r'<[^>]+>', ' ', match)
                    clean_match = re.sub(r'\{[^}]*\}', '', clean_match)
                    clean_match = re.sub(r'[a-zA-Z-]+\s*:\s*[^;]+;', '', clean_match)
                    clean_match = re.sub(r'\s+', ' ', clean_match).strip()
                    
                    if len(clean_match) > 30 and clean_match.count(' ') > 5:
                        text = clean_match
                        break
                if len(text) > 30:
                    break
        
        # Limit length
        if len(text) > 8000:
            text = text[:8000] + "…"
        
        if not text or len(text) < 20:  # Reduced minimum length requirement
            raise ValueError("Could not extract meaningful text from the provided URL")
        
        return text
        
    except Exception as e:
        raise ValueError(f"Error extracting content: {str(e)}")

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
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        elif image_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_url})

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
                        # Extract text from URL
                        extracted_text = extract_text_from_url(url)
                        response_data, status_code = fact_check_text(extracted_text)
                        # Add source URL to response
                        if status_code == 200 and isinstance(response_data, dict):
                            response_data['source_url'] = url
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
