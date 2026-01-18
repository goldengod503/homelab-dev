FROM python:3.11-alpine

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN apk add --no-cache wget && \
    pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py .
COPY templates/ templates/
COPY static/ static/

# Create data directory
RUN mkdir -p /data

# Run as non-root user
RUN adduser -D -u 1000 appuser && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 5001

CMD ["python", "app.py"]
