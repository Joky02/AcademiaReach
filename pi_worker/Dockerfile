FROM node:20-slim AS dependencies

WORKDIR /app

COPY pi_worker/package.json pi_worker/package-lock.json /app/
RUN npm ci --omit=dev --ignore-scripts

FROM oven/bun:1.3.14-slim

WORKDIR /app

COPY --from=dependencies /app/node_modules /app/node_modules
COPY pi_worker/package.json /app/package.json
COPY --chown=bun:bun pi_worker/server.ts /app/server.ts

USER bun

CMD ["bun", "run", "server.ts", "--socket", "/run/taoci-pi/worker.sock", "--workspace", "/tmp/taoci-pi-workspace"]
