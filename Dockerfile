FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Cloud Run provides PORT (defaults to 8080)
ENV PORT=8080
CMD ["sh", "-c", "uvicorn precinct.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
