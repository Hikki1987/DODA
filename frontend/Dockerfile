# Production image — Next.js standalone output (next.config.ts:
# output: "standalone"), so the runtime image needs no node_modules copy
# beyond what Next.js already traced and bundled into .next/standalone.
#
# NEXT_PUBLIC_API_BASE_URL is a build ARG, not a runtime ENV var: Next.js
# inlines every NEXT_PUBLIC_* variable into the client JS bundle at build
# time (`next build`), so setting it only at `docker run` time would have
# no effect on already-built pages — this is a well-known Next.js/Docker
# footgun, not an oversight here.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
# Opts into output: "standalone" (next.config.ts) only for this build —
# CI/local `next build && next start` never sets this, so it keeps
# using the normal, already-proven-green output shape.
ENV DOCKER_BUILD=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
