# Single container: React UI + FastAPI API. Used by Hugging Face Spaces (free CPU, no card).
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=ui /ui/dist /app/frontend/dist
# Synthetic demo data (contracts + sample invoices); Spaces run as uid 1000, so it must own /app.
RUN python -m synth.generator --out ../data/synthetic --dev 40 --test 80 && chown -R user /app
USER user
ENV PORT=7860
EXPOSE 7860
CMD uvicorn freight_audit.api:app --host 0.0.0.0 --port ${PORT}
