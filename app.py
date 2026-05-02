import os
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

# Load environment variables before importing core utilities
try:
    load_dotenv()
except Exception:
    pass

from api.core import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    _get_env_var_insensitive,
    fact_check_image_input,
    fact_check_text_input,
    fact_check_url_input,
)

app = Flask(__name__)
CORS(app)


import mimetypes

ALLOWED_EXTENSIONS = {
    ".html",
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".woff",
    ".woff2",
    ".ttf",
}


@app.route("/")
def home():
    from flask import send_from_directory

    return send_from_directory(".", "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    import os

    from flask import abort, send_from_directory

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        abort(404)
    return send_from_directory(".", filename)


@app.route("/health")
@app.route("/api/health")
def health_check():
    groq_set = bool(_get_env_var_insensitive("GROQ_API_KEY") or GROQ_API_KEY)
    gemini_set = bool(
        _get_env_var_insensitive("GEMINI_API_KEY")
        or GEMINI_API_KEY
        or _get_env_var_insensitive("GOOGLE_API_KEY")
    )
    return jsonify(
        {
            "status": "healthy",
            "timestamp": time.time(),
            "groq_api_key_set": groq_set,
            "gemini_api_key_set": gemini_set,
            "primary_provider": "groq"
            if groq_set
            else ("gemini" if gemini_set else "none"),
        }
    )


@app.route("/fact-check", methods=["POST"])
@app.route("/api/fact-check", methods=["POST"])
def fact_check():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    url = data.get("url", "")

    if not text and not url:
        return jsonify({"error": "No text or URL provided"}), 400

    if url:
        response_data, status_code = fact_check_url_input(url)
    else:
        response_data, status_code = fact_check_text_input(text)

    return jsonify(response_data), status_code


@app.route("/fact-check-image", methods=["POST"])
@app.route("/api/fact-check-image", methods=["POST"])
def fact_check_image():
    data = request.get_json(silent=True) or {}
    image_data_url = data.get("image_data_url")
    image_url = data.get("image_url")

    if not image_data_url and not image_url:
        return jsonify({"error": "Provide image_data_url (data URI) or image_url"}), 400

    if image_data_url and len(image_data_url) > 10 * 1024 * 1024:
        return jsonify(
            {"error": "Image data URL is too large. Please use a smaller image."}
        ), 400

    response_data, status_code = fact_check_image_input(image_data_url, image_url)
    return jsonify(response_data), status_code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
