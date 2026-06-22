# Custom domain cutover — trendingmediagroup.in

Puts the console + API on the owned domain:

| Host | Cloud Run service |
|------|-------------------|
| `api.trendingmediagroup.in` | `agency-os-backend` (control-plane API + OAuth callback) |
| `app.trendingmediagroup.in` | `agency-os-web` (console) |

Do these **in order**. Steps 1–3 are safe anytime. **Step 4 (the `APP_URL` /
`NEXT_PUBLIC_API_URL` flip) must wait until the domain actually resolves with a
valid cert** — Cloud Tasks and Cloud Scheduler call `{APP_URL}/tasks/...`
(`app/tasks/__init__.py`), so flipping `APP_URL` to a not-yet-live domain breaks
the outbox drain + scheduled jobs.

## 1. Verify the domain (one-time)
```bash
gcloud domains verify trendingmediagroup.in   # or via Google Search Console
```
Use the same Google account `gcloud` is authenticated as.

## 2. Create the mappings + add DNS
```bash
./scripts/map_domains.sh            # creates the Cloud Run domain mappings, prints DNS records
```
Add the printed records at your registrar, then wait for the managed certs
(15m–24h). Confirm: `curl -sI https://api.trendingmediagroup.in/` reaches the backend.

## 3. Allow the console origin — already done
`deploy.yml` `ALLOWED_ORIGINS` now includes `https://app.trendingmediagroup.in`
(added in this PR). No action.

## 4. Cut over — ONLY after step 2 resolves (one small PR)
- `deploy.yml`: `APP_URL: https://api.trendingmediagroup.in`
- Frontend build: bake `NEXT_PUBLIC_API_URL=https://api.trendingmediagroup.in` (the
  `web` deploy step's `BACKEND_URL`) so the console calls the API domain.
- Re-run scheduler provisioning (targets `{APP_URL}/tasks/...`).

## 5. Register the OAuth callback
In the Shopify Partner app and the Google Cloud OAuth client, set the redirect URI to:
```
https://api.trendingmediagroup.in/api/v1/onboarding/oauth/callback
```
This is why the domain should be live **before** registering the apps — you set the
final callback once.
