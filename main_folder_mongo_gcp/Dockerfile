# Dockerfile for main_folder_mongo (Telegram Bot)
FROM python:3.12.10-slim

# Set environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Set working directory
WORKDIR /app

# Install dependencies
COPY main_folder_mongo_gcp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY main_folder_mongo_gcp/ .

# Expose Cloud Run port
EXPOSE 8080

# Start the bot
CMD ["python", "main.py"]
