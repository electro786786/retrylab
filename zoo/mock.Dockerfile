FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi "uvicorn[standard]"
COPY zoo/mock_app /app/mock_app
CMD ["uvicorn", "mock_app.main:app", "--host", "0.0.0.0", "--port", "8001"]
