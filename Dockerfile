# Use the official Python image as a base image
# Using a specific version makes the build deterministic
ARG PYTHON_VERSION=3.14-alpine

# --- Build Stage ---
# This stage builds the Python dependencies
FROM docker.io/library/python:${PYTHON_VERSION} AS builder

# Set environment variables for Python
# PYTHONUNBUFFERED: Log messages immediately without buffering
# PIP_DISABLE_PIP_VERSION_CHECK: Reduce runtime by disabling pip version check
ENV PYTHONUNBUFFERED=True
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Set the working directory in the container
WORKDIR /app

# Install build dependencies required for some Python packages
RUN apk add --no-cache build-base

# Copy the requirements file for the web app and install dependencies
# Using a wheelhouse allows for faster installation in the final image
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# --- Production Stage ---
# This stage creates the final production image
FROM docker.io/library/python:${PYTHON_VERSION}

# Set environment variables for Python
# PYTHONUNBUFFERED: Log messages immediately without buffering
# PIP_DISABLE_PIP_VERSION_CHECK: Reduce runtime by disabling pip version check
ENV PYTHONUNBUFFERED=True
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Set the port the application will run on
ENV PORT=8080
# Configure Gunicorn server arguments for production
# --bind: Bind to all network interfaces on the specified port
# --workers: Number of worker processes
# --threads: Number of threads per worker
# --timeout: Timeout for worker processes
# Source: https://cloud.google.com/run/docs/tips/python#optimize_gunicorn
ENV GUNICORN_CMD_ARGS="--bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0"

# Configure Flask application settings
# FLASK_ENV: Set the environment to production
ENV FLASK_ENV="production"

# Expose the port the application runs on
EXPOSE $PORT

# Set the working directory in the container
WORKDIR /app

# Create a non-root user and group for security
RUN addgroup -S appuser && adduser -S -G appuser appuser

# Copy the built Python wheels from the builder stage
COPY --from=builder /wheels /wheels

# Copy the application code into the container
COPY . .

# Install the Python dependencies from the wheels and clean up
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Set appropriate permissions
RUN chown -R appuser:appuser /app

# Switch to the non-root user for security
USER appuser

# Set the command to run the application using Gunicorn
# This command starts the Gunicorn server and runs the Flask app
CMD ["gunicorn", "run:app"]
