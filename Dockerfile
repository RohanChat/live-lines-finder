# Use an official, slim Python runtime as a parent image
FROM python:3.13-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first to leverage Docker's layer caching
# We will create this file in the next step.
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container
# The .dockerignore file will prevent copying unnecessary files like .venv
COPY . .

# Expose the port the web app runs on. This doesn't affect other run types.
EXPOSE 8000

# Define the DEFAULT command to run when the container starts.
# This will be for the web app. We will override this for other platforms.
# We use 0.0.0.0 to make it accessible from outside the container.
CMD ["uvicorn", "src.messaging.web.app:app", "--host", "0.0.0.0", "--port", "8000"]