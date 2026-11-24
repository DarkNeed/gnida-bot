FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Match Bothost's source mount and keep the default SQLite path at /app/data.
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check

COPY . .
RUN python -c "import main"

EXPOSE 8080
CMD ["python", "main.py"]
