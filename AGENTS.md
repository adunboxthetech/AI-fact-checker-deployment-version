# Repository Guidelines

## Project Overview
- Small Flask-based AI fact-checker app.
- Backend entrypoint: `app.py`.
- Core fact-checking logic lives in `api/core.py`.
- Frontend is static: `index.html`, `script.js`, and `style.css`.

## Working Style
- Keep changes minimal and directly related to the request.
- Preserve the current lightweight structure unless the user asks for a larger refactor.
- Prefer fixing root causes over adding one-off workarounds.
- Do not modify `.env` or commit secrets.

## Setup And Run
- Create or activate a local virtual environment before installing dependencies.
- Install dependencies with `pip install -r requirements.txt`.
- Start the backend with `python app.py`.
- The app serves the static frontend from Flask at `http://localhost:5000/` unless `PORT` is overridden.

## Validation
- For backend-only changes, at minimum run targeted sanity checks or the smallest relevant command.
- If behavior changes affect the web flow, verify `/health` and the impacted API route when possible.
- Do not fix unrelated failing issues during validation.

## File Guidance
- `app.py`: Flask routes, static file serving, and app startup.
- `api/core.py`: external API integration and main fact-checking helpers.
- `api/index.py`: alternate API entrypoint; keep behavior aligned with `app.py` when touching shared routes.
- Frontend files should stay framework-free unless the user explicitly requests otherwise.

## Dependency And Output Hygiene
- If you add a new dependency, update `requirements.txt`.
- Keep generated files, caches, and environment folders out of git; update `.gitignore` only if new artifacts are introduced.
- Avoid committing local-only folders such as `.venv`, `__pycache__`, or deployment output.

## Notes For Future Agents
- Assume the Perplexity API key is provided through `.env`.
- Prefer small, readable Python changes and avoid introducing unnecessary abstractions.
- When changing request or response formats, update both backend and frontend code paths together.
