# Файл: Dockerfile
FROM python:3.14-slim

WORKDIR /code

RUN pip install --no-cache-dir \
    pydantic \
    pydantic-settings \
    sqlalchemy[asyncio] \
    asyncpg \
    alembic \
    httpx \
    aiogram

COPY ./app /code/app
COPY ./migrations /code/migrations
COPY ./alembic.ini /code/alembic.ini

CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]