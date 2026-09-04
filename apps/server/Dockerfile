# Slika za servis `api`.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# Najprej odvisnosti, da se plast s pip namestitvijo ne gradi ob vsaki
# spremembi kode.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic

# Znotraj vsebnika poslušamo na vseh vmesnikih; omejitev na Tailscale naslov
# naredi preslikava vrat v `docker-compose.yml` (odločitev 8 v planu).
EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
