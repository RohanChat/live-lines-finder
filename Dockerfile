# Use an official, slim Python runtime as a parent image
FROM python:3.13-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first to leverage Docker's layer caching
COPY requirements.txt .

# Install Python dependencies
# (optional but helpful: upgrade pip to avoid resolver quirks on 3.13)
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container
# The .dockerignore file will prevent copying unnecessary files like .venv and .env
COPY . .

# Expose (for local clarity only; Cloud Run uses $PORT)
EXPOSE 8080

# IMPORTANT: use shell form so ${PORT} expands from env at runtime
# Bind to 0.0.0.0 so Cloud Run can reach it
CMD sh -lc 'uvicorn src.messaging.web.app:app --host 0.0.0.0 --port ${PORT:-8080}'
