# Dockerfile for main_folder_mongo (Telegram Bot)
FROM python:3.12.10-slim

# Set environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Install dependencies
COPY main_folder_mongo_gcp/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main_folder_mongo_gcp/ .

EXPOSE 8080

# Register webhook and start the bot
CMD ["sh", "-c", "python set_webhook.py && python main.py"]
