# Use slim Python 3.12 image
FROM python:3.12.10-slim

# Environment configs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Working directory inside container
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files into container
COPY . .

# Expose both ports
EXPOSE 8443

# Register webhook, then run the bot
CMD ["sh", "-c", "python set_webhook.py && python main.py"]