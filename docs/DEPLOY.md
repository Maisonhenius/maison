# Deployment (Railway)

Referenced from `CLAUDE.md` → Deployment section. The IDs/URLs and the "Still needed"
TODO list live in CLAUDE.md; this file holds the full redeploy recipe, the custom-domain
DNS setup, and the broken-CLI workaround.

## Identifiers

- **Live URL**: canonical `https://www.maisonhenius.com` (also `https://web-production-cc74a0.up.railway.app`)
- **GitHub repo**: https://github.com/Maisonhenius/maison (public, lean ~46MB)
- **Railway project**: `maison-henius` (id: `f45a16f9-e777-4cce-abd1-dcd08c2ccb56`), service `web` (id: `d363d941-07c4-4383-b0a2-c12ebd5a8cbd`), environment `production` (`b99a4d18-a9fc-4742-b874-c0b4d38e5ade`). Owner Railway account: **husein.aldarawish@gmail.com** (NOT osamah96 — relevant for `railway login`).
- **Builder**: Dockerfile (clones from GitHub on Railway servers — bypasses upload size limits)
- **Deploy directory**: `/tmp/claude/maison-docker-deploy/` — ephemeral, recreated each session (see Redeploy steps)

## Redeploy

1. Push changes to `https://github.com/Maisonhenius/maison` `main` branch
2. Recreate deploy dir + Dockerfile (ephemeral — `/tmp` is wiped between sessions):
   ```bash
   mkdir -p /tmp/claude/maison-docker-deploy
   cat > /tmp/claude/maison-docker-deploy/Dockerfile << 'DEOF'
   FROM python:3.11-slim
   RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
   WORKDIR /app
   ARG CACHEBUST=1
   RUN git clone --depth 1 https://github.com/Maisonhenius/maison.git . && echo "bust=$CACHEBUST"
   RUN pip install --no-cache-dir -r requirements.txt
   WORKDIR /app/server
   EXPOSE 3000
   CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-3000}
   DEOF
   ```
3. Deploy: `cd /tmp/claude/maison-docker-deploy && railway up --project f45a16f9-e777-4cce-abd1-dcd08c2ccb56 --environment b99a4d18-a9fc-4742-b874-c0b4d38e5ade --service web --ci -m "<message>"`
4. Verify: `railway logs -n 15` — should show `Uvicorn running on http://0.0.0.0:8080`

**CRITICAL: bump `ARG CACHEBUST=` to a NEW value every deploy.** Docker layer-caches the `RUN git clone` step keyed on the ARG value. If `CACHEBUST` doesn't change between deploys, Docker reuses the previous git clone — your latest commit won't ship and `railway up` will silently deploy stale code. Use a date+suffix string (e.g. `2026-04-26-v3`) so it's always unique and self-documenting. Symptoms when missed: `curl prod | grep <new-thing>` returns nothing, or production file size doesn't match local.

## `railway domain` CLI is broken (v4.36.1)

Returns "Unauthorized. Please run railway login again." on the custom-domain mutation even when fully logged in (reads like `whoami`/`status`/`variables` work). The MCP `generate_domain` hits the same bug. **Workaround**: POST the GraphQL API directly with `user.accessToken` from `~/.railway/config.json` → `https://backboard.railway.com/graphql/v2`, mutation `customDomainCreate(input:{domain,projectId,environmentId,serviceId})`. Use `curl` (local Python urllib lacks the CA bundle → SSLCertVerificationError).

## Custom domain (LIVE)

- Canonical `https://www.maisonhenius.com` — www CNAME → `93jxehuo.up.railway.app`, Railway auto-SSL. Apex `maisonhenius.com` 301-forwards to www via **GoDaddy Forwarding** (GoDaddy can't CNAME an apex). Railway's apex domain entry stays "unverified" by design (forwarded, not CNAME'd) — left in place for a future Cloudflare move (Cloudflare flattens apex CNAMEs + adds the CDN noted in Performance).
- Migrated off Wix (old `www` CNAME was `pointing.wixdns.net`; apex `@` A records are GoDaddy-forwarding IPs, locked/"Can't delete" because the Forwarding feature owns them — change them via Domain Settings → Forwarding, not the DNS table).
