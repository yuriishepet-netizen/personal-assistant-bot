FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run both bot and API
ENV PYTHONPATH=/app
CMD ["sh", "-c", "alembic upgrade head && python -m app.run"]
