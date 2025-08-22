from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv
import json
import time
from urllib.parse import urlparse
import re
from readability import Document
from bs4 import BeautifulSoup

# Load environment variables (only if .env file exists)
try:
    load_dotenv()
except:
    pass  # Continue without .env file

app = Flask(__name__)
CORS(app)

# Perplexity API configuration
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

# Validate API key is available
if not PERPLEXITY_API_KEY:
    print("WARNING: PERPLEXITY_API_KEY environment variable is not set!")

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

# Initialize fact checker with error handling
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
    """Fetch a URL and extract main article text using readability and BeautifulSoup.

    Returns a dict: { 'title': str | None, 'text': str }
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    # Special-case X/Twitter tweets using syndication endpoint to avoid JS/login walls
    parsed = urlparse(url)
    if parsed.netloc in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com", "m.twitter.com"} and "/status/" in parsed.path:
        m = re.search(r"/status/(\d+)", parsed.path)
        if m:
            tweet_id = m.group(1)
            tw = requests.get(
                "https://cdn.syndication.twimg.com/widgets/tweet",
                params={"id": tweet_id, "lang": "en"}, headers=headers, timeout=12
            )
            if tw.status_code == 200:
                try:
                    data = tw.json()
                    text = data.get("text") or data.get("full_text") or data.get("i18n_text") or ""
                    if not text and data.get("body_html"):
                        text = BeautifulSoup(data["body_html"], "lxml").get_text(" ", strip=True)
                    if text:
                        user = data.get("user") or {}
                        handle = user.get("screen_name")
                        title = f"Tweet by @{handle}" if handle else "Tweet"
                        return {"title": title, "text": text}
                except Exception:
                    pass
    resp = requests.get(url, headers=headers, timeout=12)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch URL (status {resp.status_code})")
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        raise ValueError("URL does not appear to be an HTML page")

    html = resp.text
    doc = Document(html)
    title = doc.short_title()
    summary_html = doc.summary()
    soup = BeautifulSoup(summary_html, "lxml")
    main_text = soup.get_text(separator=" ", strip=True)

    # Fallback to full page if readability extraction is too short
    if len(main_text) < 300:
        full_soup = BeautifulSoup(html, "lxml")
        main_text = full_soup.get_text(separator=" ", strip=True)

    # Clean and limit length to keep token usage reasonable
    main_text = " ".join(main_text.split())

    # If content appears boilerplate or is very short, try Jina Reader proxy to fetch readable content
    boilerplate_markers = [
        "enable javascript",
        "javascript is not available",
        "please enable cookies",
        "sign in",
        "you’re being redirected",
    ]
    if len(main_text) < 200 or any(marker in main_text.lower() for marker in boilerplate_markers):
        try:
            # Preserve scheme, host, path, and query for Jina Reader
            q = f"?{parsed.query}" if parsed.query else ""
            wrapped = f"https://r.jina.ai/{parsed.scheme}://{parsed.netloc}{parsed.path}{q}"
            jr = requests.get(wrapped, headers=headers, timeout=14)
            if jr.status_code == 200 and len(jr.text.strip()) > 200:
                main_text = " ".join(jr.text.split())
        except Exception:
            pass

    if len(main_text) > 12000:
        main_text = main_text[:12000] + "…"

    if not main_text or len(main_text) < 100:
        raise ValueError("Could not extract meaningful text from the provided URL")

    return {"title": title, "text": main_text}

@app.route('/')
def home():
    return jsonify({
        "message": "AI Fact-Checker API is running!",
        "endpoints": ["/fact-check", "/health"]
    })

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy", 
        "timestamp": time.time(),
        "api_key_set": bool(PERPLEXITY_API_KEY),
        "fact_checker_initialized": fact_checker is not None
    })

@app.route('/fact-check', methods=['POST'])
def fact_check():
    try:
        # Check if fact_checker is properly initialized
        if fact_checker is None:
            return jsonify({"error": "Fact checker not properly initialized. Check environment variables."}), 500
            
        data = request.get_json()
        if not data:
            return jsonify({"error": "No input provided"}), 400

        input_text = None
        source_url = None

        # Support URL input
        if 'url' in data and data['url']:
            candidate_url = str(data['url']).strip()
            if not is_valid_url(candidate_url):
                return jsonify({"error": "Invalid URL. Only http(s) URLs are supported."}), 400
            try:
                extraction = extract_text_from_url(candidate_url)
                input_text = extraction["text"]
                source_url = candidate_url
            except Exception as e:
                return jsonify({"error": f"Failed to extract content from URL: {str(e)}"}), 400

        # Fallback to raw text
        if input_text is None:
            if 'text' not in data or not str(data['text']).strip():
                return jsonify({"error": "No text provided"}), 400
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
        
        return jsonify({
            "original_text": input_text,
            "claims_found": len(results),
            "fact_check_results": results,
            "timestamp": time.time(),
            "source_url": source_url
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/fact-check-image', methods=['POST'])
def fact_check_image():
    try:
        # Check if fact_checker is properly initialized
        if fact_checker is None:
            return jsonify({"error": "Fact checker not properly initialized. Check environment variables."}), 500
            
        data = request.get_json()
        if not data:
            return jsonify({"error": "No input provided"}), 400

        image_data_url = data.get('image_data_url')
        image_url = data.get('image_url')
        if not image_data_url and not image_url:
            return jsonify({"error": "Provide image_data_url (data URI) or image_url"}), 400

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
            "model": "sonar-pro",  # supports vision per Perplexity docs
            "messages": messages,
            "max_tokens": 500,
        }

        sonar_resp = requests.post(PERPLEXITY_URL, headers=fact_checker.headers, json=payload, timeout=30)
        if sonar_resp.status_code != 200:
            return jsonify({"error": f"Image analysis failed: HTTP {sonar_resp.status_code}"}), 500

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

        return jsonify({
            "original_image": bool(image_data_url) and "data_url" or image_url,
            "claims_found": len(results),
            "fact_check_results": results,
            "timestamp": time.time(),
            "source_url": image_url or None
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Vercel deployment - app is served via wsgi.py
