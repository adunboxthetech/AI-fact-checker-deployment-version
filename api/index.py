from http.server import BaseHTTPRequestHandler
import json
import requests
import os
from dotenv import load_dotenv
import time
from urllib.parse import urlparse
import re

# Load environment variables
try:
    load_dotenv()
except:
    pass

# Perplexity API configuration
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

class FactChecker:
    def __init__(self):
        self.api_key = PERPLEXITY_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def extract_claims(self, text):
        """Extract factual claims from user input"""
        prompt = f"""
        Extract all factual claims from this text that can be fact-checked. 
        Return only the claims as a numbered list, nothing else:
        
        Text: {text}
        """
        
        try:
            response = requests.post(
                PERPLEXITY_URL,
                headers=self.headers,
                json={
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                claims_text = result['choices'][0]['message']['content']
                # Parse numbered list into array
                claims = [line.strip() for line in claims_text.split('\n') 
                         if line.strip() and any(char.isdigit() for char in line[:3])]
                return claims
            return ["Unable to extract claims"]
            
        except Exception as e:
            return [f"Error extracting claims: {str(e)}"]
    
    def fact_check_claim(self, claim):
        """Fact-check a single claim using Sonar API"""
        prompt = f"""
        Fact-check this claim with high accuracy. Provide:
        1. Verdict (TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE)
        2. Confidence level (0-100%)
        3. Brief explanation (2-3 sentences)
        4. Key sources used as a list of canonical URLs. Each source MUST be a full http(s) URL. Do not include reference numbers or titles, only URLs.
        
        Claim: {claim}
        
        Format your response as JSON with keys: verdict, confidence, explanation, sources
        """
        
        try:
            response = requests.post(
                PERPLEXITY_URL,
                headers=self.headers,
                json={
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                fact_check_result = result['choices'][0]['message']['content']

                # Try to parse as JSON
                try:
                    parsed = json.loads(fact_check_result)
                    # Normalize sources: ensure list of http(s) URLs when possible
                    urls = []
                    if isinstance(parsed, dict) and isinstance(parsed.get('sources'), list):
                        for s in parsed['sources']:
                            try:
                                s_str = str(s).strip()
                            except Exception:
                                continue
                            if re.match(r'^https?://', s_str, flags=re.I):
                                urls.append(s_str)
                    # If no URL sources, try to extract from explanation text
                    if not urls and isinstance(parsed, dict) and isinstance(parsed.get('explanation'), str):
                        urls = re.findall(r'https?://[^\s)\]}]+', parsed['explanation'], flags=re.I)
                    if urls:
                        parsed['sources'] = urls[:5]
                    return parsed
                except Exception:
                    # Fallback to structured text with URL extraction
                    urls = re.findall(r'https?://[^\s)\]}]+', fact_check_result, flags=re.I)
                    return {
                        "verdict": "ANALYSIS COMPLETE",
                        "confidence": 75,
                        "explanation": fact_check_result,
                        "sources": urls[:5] if urls else ["Perplexity Sonar Analysis"]
                    }
            
            return {
                "verdict": "ERROR",
                "confidence": 0,
                "explanation": "Failed to verify claim",
                "sources": []
            }
            
        except Exception as e:
            return {
                "verdict": "ERROR",
                "confidence": 0,
                "explanation": f"Error: {str(e)}",
                "sources": []
            }

# Initialize fact checker
try:
    fact_checker = FactChecker()
except Exception as e:
    print(f"Error initializing FactChecker: {e}")
    fact_checker = None

def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False

def extract_text_from_url(url: str) -> dict:
    """Fetch a URL and extract main article text using simple text extraction."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            raise ValueError(f"Failed to fetch URL (status {resp.status_code})")
        
        # Simple text extraction - just get the text content
        text = resp.text
        
        # Basic HTML tag removal
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Limit length
        if len(text) > 8000:
            text = text[:8000] + "…"
        
        if not text or len(text) < 100:
            raise ValueError("Could not extract meaningful text from the provided URL")
        
        return {"title": "Extracted Content", "text": text}
        
    except Exception as e:
        raise ValueError(f"Error extracting content: {str(e)}")

def handle_fact_check(data):
    """Handle fact-check request"""
    try:
        if fact_checker is None:
            return {"error": "Fact checker not properly initialized. Check environment variables."}, 500
            
        if not data:
            return {"error": "No input provided"}, 400

        input_text = None
        source_url = None

        # Support URL input
        if 'url' in data and data['url']:
            candidate_url = str(data['url']).strip()
            if not is_valid_url(candidate_url):
                return {"error": "Invalid URL. Only http(s) URLs are supported."}, 400
            try:
                extraction = extract_text_from_url(candidate_url)
                input_text = extraction["text"]
                source_url = candidate_url
            except Exception as e:
                return {"error": f"Failed to extract content from URL: {str(e)}"}, 400

        # Fallback to raw text
        if input_text is None:
            if 'text' not in data or not str(data['text']).strip():
                return {"error": "No text provided"}, 400
            input_text = str(data['text']).strip()
        
        # Extract claims from input text
        claims = fact_checker.extract_claims(input_text)
        
        # Fact-check each claim
        results = []
        for claim in claims:
            if claim.strip():
                fact_check_result = fact_checker.fact_check_claim(claim)
                results.append({
                    "claim": claim,
                    "result": fact_check_result
                })
        
        return {
            "original_text": input_text,
            "claims_found": len(results),
            "fact_check_results": results,
            "timestamp": time.time(),
            "source_url": source_url
        }
    
    except Exception as e:
        return {"error": str(e)}, 500

def handle_fact_check_image(data):
    """Handle image fact-check request"""
    try:
        if fact_checker is None:
            return {"error": "Fact checker not properly initialized. Check environment variables."}, 500
            
        if not data:
            return {"error": "No input provided"}, 400

        image_data_url = data.get('image_data_url')
        image_url = data.get('image_url')
        if not image_data_url and not image_url:
            return {"error": "Provide image_data_url (data URI) or image_url"}, 400

        # Build Perplexity multimodal prompt for claim extraction from image
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "Analyze this image. Extract all factual claims that a third-party could verify. "
                        "Return ONLY the claims as a numbered list."
                    )}
                ]
            }
        ]
        if image_data_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_data_url})
        elif image_url:
            messages[0]["content"].append({"type": "image_url", "image_url": image_url})

        payload = {
            "model": "sonar-pro",
            "messages": messages,
            "max_tokens": 500,
        }

        sonar_resp = requests.post(PERPLEXITY_URL, headers=fact_checker.headers, json=payload, timeout=30)
        if sonar_resp.status_code != 200:
            return {"error": f"Image analysis failed: HTTP {sonar_resp.status_code}"}, 500

        content = sonar_resp.json()['choices'][0]['message']['content']
        # Convert numbered list into claims
        claims = [line.strip() for line in content.split('\n') if line.strip() and any(c.isdigit() for c in line[:3])]
        if not claims:
            claims = [content.strip()]

        # Fact-check each claim via existing pipeline
        results = []
        for claim in claims:
            if claim.strip():
                fc = fact_checker.fact_check_claim(claim)
                results.append({"claim": claim, "result": fc})

        return {
            "original_image": bool(image_data_url) and "data_url" or image_url,
            "claims_found": len(results),
            "fact_check_results": results,
            "timestamp": time.time(),
            "source_url": image_url or None
        }

    except Exception as e:
        return {"error": str(e)}, 500

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/health':
            response_data = {
                "status": "healthy", 
                "timestamp": time.time(),
                "api_key_set": bool(PERPLEXITY_API_KEY),
                "fact_checker_initialized": fact_checker is not None
            }
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode())
        else:
            # Serve static files
            try:
                with open(f'..{self.path}', 'rb') as f:
                    content = f.read()
                
                # Determine content type
                if self.path.endswith('.html'):
                    content_type = 'text/html'
                elif self.path.endswith('.css'):
                    content_type = 'text/css'
                elif self.path.endswith('.js'):
                    content_type = 'application/javascript'
                elif self.path.endswith('.png'):
                    content_type = 'image/png'
                else:
                    content_type = 'text/plain'
                
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'File not found')
    
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
            response_data, status_code = handle_fact_check(data)
        elif self.path == '/api/fact-check-image':
            response_data, status_code = handle_fact_check_image(data)
        else:
            response_data = {"error": "Endpoint not found"}
            status_code = 404
        
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode())
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
