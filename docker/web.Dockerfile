# docker/web.Dockerfile
# Stage 1: Build the Vite React frontend.
# Stage 2: Serve the built assets via nginx, proxying /api and /ws to the backend.

# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM node:20-slim AS build

WORKDIR /app

# Copy package manifests first for layer caching.
COPY web/package*.json ./

RUN npm ci

# Copy the full frontend source and build.
COPY web/ ./

# Build output goes to /app/dist
RUN npm run build

# ── Stage 2: serve ──────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Remove default nginx config.
RUN rm /etc/nginx/conf.d/default.conf

# Install our reverse-proxy config.
COPY docker/nginx.conf /etc/nginx/conf.d/petridish.conf

# Copy built assets from the build stage.
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
