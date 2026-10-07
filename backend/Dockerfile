FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
# Bake the synthetic demo data (contracts + sample invoices) into the image.
RUN python -m synth.generator --out ../data/synthetic --dev 40 --test 80
ENV PORT=8000
CMD uvicorn freight_audit.api:app --host 0.0.0.0 --port ${PORT}
