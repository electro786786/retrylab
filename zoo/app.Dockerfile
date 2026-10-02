FROM python:3.11-slim

WORKDIR /app

# Install dependencies (since we used uv, we can just export requirements or install directly)
COPY pyproject.toml .
# We install dependencies via pip for simplicity in the docker image, or copy from a requirements.txt
RUN pip install fastapi uvicorn sqlalchemy asyncpg pydantic pydantic-settings

COPY zoo/app /app/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
