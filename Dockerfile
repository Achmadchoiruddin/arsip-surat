FROM python:3.11-slim

# Install Tesseract OCR engine and required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set Tesseract data directory (default location)
ENV TESSDATA_DIR=/usr/share/tesseract-ocr/5/tessdata

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Create necessary directories
RUN mkdir -p uploads static templates

# Copy traineddata files to Tesseract tessdata directory
COPY tessdata/eng.traineddata /usr/share/tesseract-ocr/5/tessdata/eng.traineddata
COPY tessdata/ind.traineddata /usr/share/tesseract-ocr/5/tessdata/ind.traineddata

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Expose port
EXPOSE 8080

# Run entrypoint script
CMD ["/app/entrypoint.sh"]