from http.server import BaseHTTPRequestHandler
import json
import time

from api.core import (
    fact_check_text_input,
    fact_check_url_input,
    fact_check_image_input,
)


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict) -> None:
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def do_GET(self):
        if self.path == '/api/health':
            self._send_json(200, {
                "status": "healthy",
                "timestamp": time.time(),
            })
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        if self.path == '/api/fact-check':
            text = data.get('text', '')
            url = data.get('url', '')
            if not text and not url:
                self._send_json(400, {"error": "No text or URL provided"})
                return
            if url:
                response_data, status_code = fact_check_url_input(url)
            else:
                response_data, status_code = fact_check_text_input(text)
            self._send_json(status_code, response_data)
            return

        if self.path == '/api/fact-check-image':
            image_data_url = data.get('image_data_url')
            image_url = data.get('image_url')
            if not image_data_url and not image_url:
                self._send_json(400, {"error": "No image data URL or image URL provided"})
                return
            if image_data_url and len(image_data_url) > 10 * 1024 * 1024:
                self._send_json(400, {"error": "Image data URL is too large. Please use a smaller image."})
                return
            response_data, status_code = fact_check_image_input(image_data_url, image_url)
            self._send_json(status_code, response_data)
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()
