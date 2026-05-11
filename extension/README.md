# AI Fact Checker Chrome Extension

This is a separate Chrome Extension frontend for the existing Flask backend. The main web app still uses the original `/api/fact-check` and `/api/fact-check-image` routes. The extension uses `/api/extension/fact-check` so it can send richer browser context without changing the web app contract.

## Local Setup

1. Start the backend from the repository root:
   ```bash
   python app.py
   ```
2. Open Chrome and go to `chrome://extensions`.
3. Enable "Developer mode".
4. Click "Load unpacked".
5. Select this `extension` folder.
6. Browse to a social feed, open a post in view, then click the AI Fact Checker extension icon.

The popup defaults to the production backend at `https://anindya-das-ai-fact-checker.vercel.app`. Use the settings button in the popup to point it at `http://localhost:5000` while developing locally.

## How It Works

- `content.js` finds visible post-like DOM containers and picks the candidate nearest the center of the viewport.
- `background.js` can capture the visible tab when the post is image-heavy or has too little extractable text.
- `popup.js` sends the extracted text, URL, image hints, and optional screenshot to the Flask backend.

## Current Platform Coverage

The extractor has targeted selectors for X/Twitter, Reddit, LinkedIn, Facebook, Instagram, Threads, and YouTube, plus a generic webpage fallback. Social platforms change markup often, so this is intentionally heuristic and easy to extend.
