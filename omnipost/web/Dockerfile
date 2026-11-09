# =============================================================================
# VBL Law Chambers — Advocate Content Portal
# Multi-stage build: Vite builds the React bundle, Express serves it + the API
# on a single port (3300). No Vite dev server runs in production.
# =============================================================================

# Node 24 is the Active LTS line (supported to April 2028); 22 reaches end of
# life in April 2027. Both stages use the same major so the lockfile resolves
# identically in each.

# --- Stage 1: build the React frontend -------------------------------------
FROM node:24-alpine AS builder

WORKDIR /app

# Install all dependencies (including devDependencies — Vite is needed to build)
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# --- Stage 2: production runtime -------------------------------------------
FROM node:24-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production

# Only production dependencies land in the final image. React, react-dom and
# lucide-react are devDependencies: Vite compiles them into dist/ in stage 1,
# and nothing the server imports needs them (verify-imports.mjs below proves
# that on every build).
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

# Application server plus the compiled frontend from stage 1.
#
# server.js is NOT self-contained: it imports ./db.js and four modules under
# ./publishing/, which in turn pull in the platform adapters. An earlier
# revision copied server.js alone. The image built cleanly, every test passed
# on the host, and the container then died on its first boot with
#   ERR_MODULE_NOT_FOUND: Cannot find module '/app/db.js'
# — which Render reports only as a failed deploy.
COPY server.js db.js auth.js n8n-client.js drive-sync.js verify-imports.mjs ./
COPY publishing ./publishing
COPY --from=builder /app/dist ./dist

# Prove the import graph resolves. A hand-maintained list of COPY directives
# goes stale the moment a new module is imported; this turns that into a build
# failure instead of a 3am production crash.
RUN node verify-imports.mjs

# Writable state directories, owned by the user that will actually run.
#
# server.js creates data/ and uploads/ at import time. Everything COPYed above
# lands root-owned, so with `USER node` and a root-owned /app the very first
# statement of the program failed:
#
#   Error: EACCES: permission denied, mkdir '/app/data'
#
# The container exited before serving a single request. This was invisible
# until the image actually ran: it sat behind the missing-module crash, and a
# host-side test has the directories already present and is not running as an
# unprivileged user inside /app.
#
# These are also the mount points for the named volumes in
# docker-compose.prod.yml — a fresh named volume inherits the ownership of the
# image directory it covers, so creating them correctly here is what makes the
# production mounts writable too.
RUN mkdir -p /app/data /app/uploads/media && chown -R node:node /app/data /app/uploads

# Run as the built-in unprivileged node user
USER node

EXPOSE 3300

# ?shallow=1 deliberately: a liveness probe that round-trips to Supabase turns
# somebody else's outage into a restart loop. The full form is for diagnosis.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "const p=process.env.PORT||process.env.WEB_PORT||3300;fetch('http://127.0.0.1:'+p+'/api/health?shallow=1').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

# Heap cap: 256MB, deliberately.
#
# This used to be 400, with a comment saying Node would otherwise size its heap
# from the HOST's memory. Measured on node:22 and node:24 inside a 512MB
# cgroup, that is not true: the default limit is already cgroup-derived
# (259MB). The 400 flag therefore RAISED the ceiling, letting V8 grow to 400MB
# of old space before collecting hard - which, plus young generation, code
# space and socket/stream buffers, is past 512MB, so the container would be
# OOM-killed rather than garbage-collect.
#
# 256 keeps it where Node itself would put it, but explicitly, so it does not
# depend on the host exposing its cgroup limit correctly. The portal's measured
# heap is a few tens of MB; this is a ceiling, not a working size.
#
# Node is PID 1 here. server.js installs SIGTERM/SIGINT handlers because PID 1
# otherwise ignores SIGTERM and every stop ends in SIGKILL.
CMD ["node", "--max-old-space-size=256", "server.js"]
