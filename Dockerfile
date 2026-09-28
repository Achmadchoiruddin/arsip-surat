FROM python:3.11-slim

# Install Tesseract OCR engine and required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ind \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set Tesseract path
ENV TESSDATA_DIR=/tessdata

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Create necessary directories
RUN mkdir -p uploads tessdata static templates

# Copy traineddata files if they exist
COPY tessdata/ind.traineddata tessdata/ 2>/dev/null || true
COPY tessdata/eng.traineddata tessdata/ 2>/dev/null || true

# Expose port
EXPOSE 8080

# Run gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "app:app"]