ARG WEB_SOURCE=web-built
FROM node:22-alpine AS web-built
WORKDIR /web
COPY oc-web/package.json oc-web/package-lock.json ./
RUN npm ci
COPY oc-web/ ./
RUN npm run build

FROM scratch AS web-prebuilt
COPY oc-web/dist/ /web/dist/

FROM ${WEB_SOURCE} AS web

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/wbot
COPY requirements-oc.txt ./
RUN pip install --no-cache-dir -r requirements-oc.txt \
    && useradd --uid 10001 --create-home wbot \
    && mkdir /data && chown wbot:wbot /data
COPY app/ ./app/
COPY wbot/ ./wbot/
COPY --from=web /web/dist ./oc-web/dist/
USER wbot
CMD ["python", "-m", "app.oc", "serve", "--state-dir", "/data", "--port", "18892", "--agent-port", "18893"]
