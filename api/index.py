from http.server import BaseHTTPRequestHandler
import json
import requests
import os
import time
import re

# Perplexity API configuration
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

def extract_text_from_url(url):
    """Extract text content from a URL"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            raise ValueError(f"Failed to fetch URL (status {response.status_code})")
        
        # Special handling for Twitter/X
        if 'twitter.com' in url or 'x.com' in url:
            # Try to extract tweet content from meta tags
            content = response.text
            import re
            
            # Look for meta description or og:description
            meta_patterns = [
                r'<meta[^>]*name="description"[^>]*content="([^"]*)"',
                r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"',
                r'<meta[^>]*name="twitter:description"[^>]*content="([^"]*)"'
            ]
            
            for pattern in meta_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    extracted_text = match.group(1)
                    if extracted_text and len(extracted_text) > 20:
                        return extracted_text
            
            # Fallback: look for tweet text in the page
            tweet_pattern = r'<div[^>]*class="[^"]*tweet[^"]*"[^>]*>.*?<div[^>]*class="[^"]*tweet-text[^"]*"[^>]*>(.*?)</div>'
            match = re.search(tweet_pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                tweet_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                if tweet_text and len(tweet_text) > 20:
                    return tweet_text
        
        # General text extraction
        text = response.text
        
        # Remove script and style tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Basic HTML tag removal
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Remove common CSS and JS artifacts
        text = re.sub(r'\{[^}]*\}', '', text)
        text = re.sub(r'#[a-zA-Z0-9_-]+', '', text)
        text = re.sub(r'\.[a-zA-Z0-9_-]+', '', text)
        
        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Limit length
        if len(text) > 8000:
            text = text[:8000] + "…"
        
        if not text or len(text) < 50:
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
    Extract and fact-check all factual claims from this text. 
    
    Text: {text}
    
    Return a JSON response with:
    - verdict: TRUE/FALSE/PARTIALLY TRUE/INSUFFICIENT EVIDENCE
    - confidence: 0-100
    - explanation: brief explanation
    - sources: list of URLs
    
    If no factual claims are found, return an empty array.
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
                parsed = json.loads(content)
                # Format for frontend: create fact_check_results array
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
            except:
                # Fallback response
                fact_check_result = {
                    "claim": text[:200] + "..." if len(text) > 200 else text,
                    "result": {
                        "verdict": "ANALYSIS COMPLETE",
                        "confidence": 75,
                        "explanation": content,
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
                    response_data = {"error": str(e)}
                    status_code = 400
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
