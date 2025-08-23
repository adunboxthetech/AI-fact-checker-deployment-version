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
        
        # Special handling for Twitter/X
        if 'twitter.com' in url or 'x.com' in url:
            content = response.text
            
            # Try multiple extraction strategies for Twitter/X
            
            # Strategy 1: Look for structured data (most reliable)
            structured_patterns = [
                r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                r'<script[^>]*type="application/json"[^>]*>(.*?)</script>'
            ]
            
            for pattern in structured_patterns:
                matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
                for match in matches:
                    try:
                        data = json.loads(match)
                        if isinstance(data, dict):
                            # Look for tweet text in structured data
                            if 'text' in data:
                                tweet_text = data['text']
                                if tweet_text and len(tweet_text) > 20:
                                    return tweet_text
                            elif 'description' in data:
                                desc = data['description']
                                if desc and len(desc) > 20:
                                    return desc
                    except:
                        continue
            
            # Strategy 2: Look for meta tags with tweet content
            meta_patterns = [
                r'<meta[^>]*name="description"[^>]*content="([^"]*)"',
                r'<meta[^>]*property="og:description"[^>]*content="([^"]*)"',
                r'<meta[^>]*name="twitter:description"[^>]*content="([^"]*)"',
                r'<meta[^>]*property="twitter:description"[^>]*content="([^"]*)"',
                r'<meta[^>]*name="twitter:title"[^>]*content="([^"]*)"',
                r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"'
            ]
            
            for pattern in meta_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    extracted_text = match.group(1)
                    # Clean up the extracted text
                    extracted_text = re.sub(r'&[a-zA-Z]+;', ' ', extracted_text)
                    extracted_text = re.sub(r'&amp;', '&', extracted_text)
                    extracted_text = re.sub(r'&lt;', '<', extracted_text)
                    extracted_text = re.sub(r'&gt;', '>', extracted_text)
                    extracted_text = re.sub(r'&quot;', '"', extracted_text)
                    extracted_text = re.sub(r'\s+', ' ', extracted_text).strip()
                    if extracted_text and len(extracted_text) > 20:
                        return extracted_text
            
            # Strategy 3: Look for tweet text in HTML attributes
            tweet_attr_patterns = [
                r'data-text="([^"]*)"',
                r'data-tweet-text="([^"]*)"',
                r'data-content="([^"]*)"'
            ]
            
            for pattern in tweet_attr_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    tweet_text = match.group(1)
                    tweet_text = re.sub(r'&[a-zA-Z]+;', ' ', tweet_text)
                    tweet_text = re.sub(r'\s+', ' ', tweet_text).strip()
                    if tweet_text and len(tweet_text) > 20:
                        return tweet_text
            
            # Strategy 4: Look for tweet content in specific divs
            tweet_div_patterns = [
                r'<div[^>]*data-testid="tweetText"[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*tweet-text[^"]*"[^>]*>(.*?)</div>',
                r'<span[^>]*class="[^"]*tweet-text[^"]*"[^>]*>(.*?)</span>',
                r'<div[^>]*class="[^"]*text[^"]*"[^>]*>(.*?)</div>'
            ]
            
            for pattern in tweet_div_patterns:
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    tweet_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                    tweet_text = re.sub(r'&[a-zA-Z]+;', ' ', tweet_text)
                    tweet_text = re.sub(r'\s+', ' ', tweet_text).strip()
                    if tweet_text and len(tweet_text) > 20:
                        return tweet_text
            
            # Strategy 5: Try mobile version of the URL
            try:
                mobile_url = url.replace('x.com', 'mobile.twitter.com').replace('twitter.com', 'mobile.twitter.com')
                mobile_response = requests.get(mobile_url, headers=headers, timeout=15)
                if mobile_response.status_code == 200:
                    mobile_content = mobile_response.text
                    
                    # Look for tweet text in mobile version
                    mobile_patterns = [
                        r'<div[^>]*class="[^"]*tweet-text[^"]*"[^>]*>(.*?)</div>',
                        r'<div[^>]*class="[^"]*text[^"]*"[^>]*>(.*?)</div>',
                        r'<p[^>]*class="[^"]*tweet-text[^"]*"[^>]*>(.*?)</p>'
                    ]
                    
                    for pattern in mobile_patterns:
                        match = re.search(pattern, mobile_content, re.DOTALL | re.IGNORECASE)
                        if match:
                            tweet_text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                            tweet_text = re.sub(r'&[a-zA-Z]+;', ' ', tweet_text)
                            tweet_text = re.sub(r'\s+', ' ', tweet_text).strip()
                            if tweet_text and len(tweet_text) > 20:
                                return tweet_text
            except:
                pass
            
            # Strategy 6: Smart content extraction - look for human-readable text
            # Remove all HTML tags first
            clean_content = re.sub(r'<[^>]+>', ' ', content)
            clean_content = re.sub(r'&[a-zA-Z]+;', ' ', clean_content)
            clean_content = re.sub(r'\s+', ' ', clean_content).strip()
            
            # Split into lines and look for meaningful text
            lines = clean_content.split('\n')
            meaningful_lines = []
            
            for line in lines:
                line = line.strip()
                # Less aggressive filtering - only block obvious CSS/JS
                if (line and len(line) > 20 and 
                    'javascript' not in line.lower() and 
                    'enable javascript' not in line.lower() and
                    'browser' not in line.lower() and
                    'error' not in line.lower() and
                    'script' not in line.lower() and
                    # Only block lines that are purely CSS/JS
                    not (line.count('{') > 0 and line.count('}') > 0 and ':' in line and ';' in line) and
                    # Block obvious CSS property lines
                    not (line.count(':') > 0 and line.count(';') > 0 and len(line) < 100) and
                    # Block obvious JavaScript lines
                    not (line.startswith('function') or line.startswith('var ') or line.startswith('const ') or line.startswith('let ')) and
                    # Block import/export statements
                    not (line.startswith('import ') or line.startswith('export ')) and
                    # Block control flow statements
                    not (line.startswith('if (') or line.startswith('for (') or line.startswith('while (')) and
                    # Block return statements
                    not line.startswith('return ') and
                    # Block obvious CSS selectors
                    not (line.startswith('#') and ':' in line) and
                    not (line.startswith('.') and ':' in line)):
                    meaningful_lines.append(line)
            
            if meaningful_lines:
                return ' '.join(meaningful_lines[:3])
            
            # Strategy 7: Try to extract from the page title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', content, re.IGNORECASE)
            if title_match:
                title_text = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                title_text = re.sub(r'&[a-zA-Z]+;', ' ', title_text)
                title_text = re.sub(r'\s+', ' ', title_text).strip()
                if title_text and len(title_text) > 20 and 'twitter' not in title_text.lower() and 'x.com' not in title_text.lower():
                    return title_text
            
            # Strategy 8: Last resort - try to find any text that looks like a tweet
            # Look for text that contains common tweet patterns
            tweet_patterns = [
                r'([A-Z][^.!?]*[.!?])',  # Sentences starting with capital letters
                r'([^<>{}:;]+)',  # Text without HTML, CSS, or JS characters
            ]
            
            for pattern in tweet_patterns:
                matches = re.findall(pattern, clean_content)
                for match in matches:
                    match = match.strip()
                    if (match and len(match) > 30 and 
                        'javascript' not in match.lower() and
                        'css' not in match.lower() and
                        'error' not in match.lower() and
                        'script' not in match.lower() and
                        not match.startswith('{') and
                        not match.startswith('}') and
                        not match.startswith('#') and
                        not match.startswith('.') and
                        ':' not in match[:20] and  # Avoid CSS properties at the start
                        ';' not in match[-10:]):   # Avoid CSS statements at the end
                        return match
            
            # Strategy 9: Look for text that resembles actual tweet content
            # Split content into chunks and analyze each one
            chunks = re.split(r'[{}:;]', clean_content)
            for chunk in chunks:
                chunk = chunk.strip()
                # Look for chunks that look like real text (not CSS/JS)
                if (chunk and len(chunk) > 50 and
                    chunk.count(' ') > 5 and  # Multiple words
                    chunk.count('a') > 3 and   # Contains common letters
                    chunk.count('e') > 3 and
                    not any(css_word in chunk.lower() for css_word in ['background', 'color', 'border', 'margin', 'padding', 'font', 'display', 'position']) and
                    not any(js_word in chunk.lower() for js_word in ['function', 'var', 'const', 'let', 'return', 'if', 'for', 'while', 'import', 'export']) and
                    not chunk.startswith('#') and
                    not chunk.startswith('.') and
                    not chunk.startswith('@') and
                    not chunk.startswith('http')):
                    return chunk
            
            # Strategy 10: Try to extract from any remaining text that looks human-readable
            # Look for the longest piece of text that doesn't contain obvious CSS/JS markers
            remaining_text = clean_content
            # Remove obvious CSS/JS patterns
            remaining_text = re.sub(r'[{}:;]', ' ', remaining_text)
            remaining_text = re.sub(r'\s+', ' ', remaining_text).strip()
            
            # Split into sentences and find the longest meaningful one
            sentences = re.split(r'[.!?]', remaining_text)
            best_sentence = ""
            for sentence in sentences:
                sentence = sentence.strip()
                if (sentence and len(sentence) > 30 and
                    sentence.count(' ') > 3 and
                    not any(bad_word in sentence.lower() for bad_word in ['javascript', 'css', 'error', 'script', 'function', 'var', 'const', 'let']) and
                    not sentence.startswith('#') and
                    not sentence.startswith('.') and
                    len(sentence) > len(best_sentence)):
                    best_sentence = sentence
            
            if best_sentence:
                return best_sentence
            
            # If all strategies fail, try to extract any meaningful text from the page
            # Look for any text that might be human-readable content
            clean_content = re.sub(r'<[^>]+>', ' ', content)
            clean_content = re.sub(r'\{[^}]*\}', '', clean_content)
            clean_content = re.sub(r'[a-zA-Z-]+\s*:\s*[^;]+;', '', clean_content)
            clean_content = re.sub(r'\s+', ' ', clean_content).strip()
            
            # Split into chunks and find the most promising one
            chunks = re.split(r'[.!?]', clean_content)
            best_chunk = ""
            for chunk in chunks:
                chunk = chunk.strip()
                if (chunk and len(chunk) > 30 and
                    chunk.count(' ') > 5 and
                    not any(bad_word in chunk.lower() for bad_word in ['javascript', 'css', 'error', 'script', 'function', 'var', 'const', 'let', 'background', 'color', 'border', 'margin', 'padding', 'font', 'display', 'position']) and
                    not chunk.startswith('#') and
                    not chunk.startswith('.') and
                    not chunk.startswith('{') and
                    not chunk.startswith('}') and
                    len(chunk) > len(best_chunk)):
                    best_chunk = chunk
            
            if best_chunk:
                return best_chunk
            
            # If still no content, provide a helpful error message
            raise ValueError("Unable to extract meaningful content from this Twitter/X URL. Twitter/X heavily relies on JavaScript to load content dynamically, making it difficult to extract content from direct URL requests. This is a common limitation with modern social media platforms.")
        
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
                    import re
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
