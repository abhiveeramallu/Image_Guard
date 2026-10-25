# Deployment

Nothing has been deployed by this project; the files below are configuration only and have not been verified on the hosts.

## Backend → Render (or any Python host)
1. Push the repo. In Render choose **New → Blueprint** (uses `render.yaml`) or create a Web Service with root dir `backend`.
2. Build: `pip install -r requirements.txt` · Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers`
3. Health check path: `/api/health`.
4. Env vars: `IMAGEGUARD_WATERMARK_KEY` (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`; store it as a secret and back it up: losing or rotating it makes existing watermarks unverifiable), optionally `IMAGEGUARD_LOCALIZATION_MODEL_PATH` (the model file must exist on the instance, e.g. baked into the image or on a persistent disk; see docs/MODELS.md), `IMAGEGUARD_ENVIRONMENT=production`, `IMAGEGUARD_CORS_ORIGINS=https://<your-frontend-origin>` (exact origin, no trailing slash, no `*`). Optional limits: see `backend/.env.example`.
5. Free tiers have small RAM (≈512 MB) and spin down when idle. `render.yaml` sets `IMAGEGUARD_MAX_IMAGE_PIXELS=8000000`; measured peak memory is ≈35 MB per megapixel for detection (see TESTING.md), so raise it only on larger instances.

The filesystem is ephemeral and this app does not use it: results are held in RAM for 15 minutes and vanish on restart/redeploy, so users should download what they need.

## Frontend → Vercel
1. Import the repo, set **Root Directory** `frontend`. Build `npm run build`, output `dist` (both in `vercel.json`, which also adds the SPA fallback rewrite).
2. Env var `VITE_API_URL=https://<your-render-service>.onrender.com`. Redeploy after changing it (Vite inlines it at build time).
3. Add the resulting Vercel URL to the backend's `IMAGEGUARD_CORS_ORIGINS`.

## Before making it public
Rate limiting is per IP and in-memory; put a CDN/WAF in front for real abuse protection. There is no authentication.


## Notes for 1.1
* `onnxruntime` is in `requirements.txt` (CPU). It adds roughly 15–20 MB; memory for model inference depends on the model.
* `render.yaml` declares `IMAGEGUARD_WATERMARK_KEY` with `sync: false`; set it in the dashboard. Without it the invisible-watermark feature reports itself unavailable.
* The multi-method analysis runs all selected methods in one request; for large images the free tier may be slow. Nothing in 1.1 has been deployed or verified on Render/Vercel.
