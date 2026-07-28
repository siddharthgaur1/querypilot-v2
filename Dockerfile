FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY querypilot_v2 ./querypilot_v2

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "querypilot_v2.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
