# Файл: Dockerfile
FROM python:3.14-slim

WORKDIR /code

# Установка uv из официального образа
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Копируем спецификацию зависимостей для эффективного кэширования слоев
COPY pyproject.toml uv.lock ./

# Устанавливаем production-зависимости строго из uv.lock
RUN uv sync --frozen --no-dev --no-install-project

# Добавляем виртуальное окружение uv в PATH
ENV PATH="/code/.venv/bin:$PATH"

COPY ./app /code/app
COPY ./migrations /code/migrations
COPY ./alembic.ini /code/alembic.ini

CMD ["sh", "-c", "alembic upgrade head && python -m app.main"]