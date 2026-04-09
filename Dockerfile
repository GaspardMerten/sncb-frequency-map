# --- Stage 1: Build frontend ---
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python API ---
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY logic/ logic/
COPY routers/ routers/
COPY services/ services/
COPY templates/ templates/
COPY static/ static/
COPY main.py __init__.py .env* provinces.geojson ./
COPY --from=frontend /app/frontend/dist frontend/dist/

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]