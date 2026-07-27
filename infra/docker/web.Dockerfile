FROM node:22-alpine AS build

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
RUN corepack enable

WORKDIR /app

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile

COPY apps/web ./apps/web

ARG MYSTERY_ATLAS_API_ORIGIN=http://api:8010
ENV MYSTERY_ATLAS_API_ORIGIN=$MYSTERY_ATLAS_API_ORIGIN
ENV NEXT_TELEMETRY_DISABLED=1

RUN pnpm --filter @mystery-atlas/web build

FROM node:22-alpine AS runtime

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV MYSTERY_ATLAS_API_ORIGIN=http://api:8010
RUN corepack enable

WORKDIR /app

COPY --from=build /app/package.json /app/pnpm-lock.yaml /app/pnpm-workspace.yaml ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/apps/web/package.json ./apps/web/package.json
COPY --from=build /app/apps/web/node_modules ./apps/web/node_modules
COPY --from=build /app/apps/web/.next ./apps/web/.next
COPY --from=build /app/apps/web/next.config.ts ./apps/web/next.config.ts

EXPOSE 3100

CMD ["pnpm", "--filter", "@mystery-atlas/web", "start", "--hostname", "0.0.0.0", "--port", "3100"]
