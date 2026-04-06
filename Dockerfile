FROM python:3.11-slim

# Install LibreOffice Writer (headless) and Microsoft-compatible fonts
# fonts-crosextra-carlito = Calibri replacement (metrically compatible)
# fonts-crosextra-caladea = Cambria replacement (metrically compatible)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    fonts-liberation \
    fonts-dejavu \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]