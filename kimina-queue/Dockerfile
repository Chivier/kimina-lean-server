FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml README.md ./
COPY server ./server

# Install dependencies
RUN uv pip install --system -e .

# Expose port
EXPOSE 8010

# Run the server
CMD ["python", "-m", "server"]