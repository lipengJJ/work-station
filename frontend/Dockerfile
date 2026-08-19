# frontend 镜像：多阶段构建。只编译 apps/web-antd 这一个变体（build:antd 是仓库自带的脚本），
# 生产环境用 nginx 提供静态文件，并把 /api/ 反代到 backend 容器（见 nginx.conf）。
FROM node:22-slim AS builder

# buildx 多平台构建时注入；用于缓存按平台隔离，避免 amd64/arm64 并发写同一 pnpm store
ARG TARGETARCH

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV NODE_OPTIONS=--max-old-space-size=8192
ENV CI=true

RUN npm i -g corepack

WORKDIR /app
COPY . /app

RUN --mount=type=cache,id=pnpm-${TARGETARCH},target=/pnpm/store pnpm install --frozen-lockfile
RUN pnpm run build:antd

FROM nginx:stable-alpine AS production

COPY --from=builder /app/apps/web-antd/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
