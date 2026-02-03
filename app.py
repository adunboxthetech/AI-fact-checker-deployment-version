from flask import Flask, request, jsonify
from flask_cors import CORS
import time
import os
from dotenv import load_dotenv

# Load environment variables before importing core utilities
try:
    load_dotenv()
except Exception:
    pass

from api.core import (
    PERPLEXITY_API_KEY,
    fact_check_text_input,
    fact_check_url_input,
    fact_check_image_input,
)

app = Flask(__name__)
CORS(app)


@app.route('/')
def home():
    return app.send_from_directory('.', 'index.html')


@app.route('/<path:filename>')
def serve_static(filename):
    return app.send_from_directory('.', filename)


@app.route('/health')
@app.route('/api/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "api_key_set": bool(PERPLEXITY_API_KEY),
    })


@app.route('/fact-check', methods=['POST'])
@app.route('/api/fact-check', methods=['POST'])
def fact_check():
    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    url = data.get('url', '')

    if not text and not url:
        return jsonify({"error": "No text or URL provided"}), 400

    if url:
        response_data, status_code = fact_check_url_input(url)
    else:
        response_data, status_code = fact_check_text_input(text)

    return jsonify(response_data), status_code


@app.route('/fact-check-image', methods=['POST'])
@app.route('/api/fact-check-image', methods=['POST'])
def fact_check_image():
    data = request.get_json(silent=True) or {}
    image_data_url = data.get('image_data_url')
    image_url = data.get('image_url')

    if not image_data_url and not image_url:
        return jsonify({"error": "Provide image_data_url (data URI) or image_url"}), 400

    if image_data_url and len(image_data_url) > 10 * 1024 * 1024:
        return jsonify({"error": "Image data URL is too large. Please use a smaller image."}), 400

    response_data, status_code = fact_check_image_input(image_data_url, image_url)
    return jsonify(response_data), status_code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
