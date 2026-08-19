# backend 镜像：FastAPI + 小红书采集需要的签名算法（execjs 调 node 执行 static/*.js，
# 这些 js 用 require("crypto-js")，需要 node_modules 在同一 cwd 下才能 resolve）。
FROM python:3.11-slim

WORKDIR /app

# requirements.txt 里所有带 C 扩展的包（bcrypt/cryptography/lxml/Pillow/pandas/numpy）在
# manylinux 上都有预编译 wheel，验证过 pip install 不需要编译，因此不装 build-essential
# ——实测能让镜像小 ~420MB。--no-install-recommends 去掉 curl/gnupg/nodejs 各自的推荐附加包。
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm install --omit=dev

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 评论页面级爬取（page_crawler.py）依赖 Playwright chromium；--with-deps 会顺带
# apt 装齐 chromium 运行所需的系统库（Dockerfile 默认 root 执行，apt 可用）
RUN python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8010

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
