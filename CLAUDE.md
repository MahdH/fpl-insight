# FPL Insight

Fantasy Premier League insight app. FastAPI backend (`app/`), plain HTML/CSS/JS frontend (`public/`, no build step), deployed on Vercel.

## Rules

- **Always run the app locally at the end of every task and show the result.** Start the server, open it in the Browser pane on the page that changed (load a sample team ID such as `43024` when My Team is involved), and leave the server running so the result can be seen. Say the URL in the final message. Do this even for backend-only changes by showing the affected page or endpoint output.
- Keep tests green: run `pytest` (Python 3.10 in CI, 3.12 on Vercel) before finishing any change to `app/` or `tests/`.
- Don't commit or push unless asked.

## Commands

Run locally (from the repo root; use `python -m uvicorn`, because the `venv/bin/uvicorn` launcher script points at an old folder path):

```bash
./venv/bin/python -m uvicorn app.main:app --port 8123
```

Then open http://localhost:8123 (Transfer Lab) and http://localhost:8123/my-team.

Install or refresh dependencies: `./venv/bin/python -m pip install -r requirements-dev.txt`

Run tests: `./venv/bin/python -m pytest`

## Layout

- `app/main.py`: API routes and caching. `app/model.py`: expected-points model. `app/transfers.py`: squad-aware transfer swaps.
- `public/`: pages and assets, served from Vercel's CDN. `public/src/` holds `styles.css`, `ui.js`, `app.js` (dashboard) and `my-team.js`.
- `vercel.json` only sets `cleanUrls`. Vercel auto-detects `app/main.py` as the FastAPI entrypoint, so there is no `api/` folder and no rewrites.
