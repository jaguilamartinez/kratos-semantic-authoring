FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-kratos.txt .
RUN python -m pip install --no-cache-dir --requirement requirements-kratos.txt

COPY worker/app.py worker/run_case.py ./

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
