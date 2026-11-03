# Stage 1: build the React app
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: API + the built app on one port
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY data/seed ./data/seed
COPY --from=web /web/dist ./frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
