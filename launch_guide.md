# 🚀 Гайд по запуску Job Hunter

## Оглавление

1. [Предварительные требования (что нужно установить)](#1-предварительные-требования-что-нужно-установить)
2. [Получение токенов и ключей](#2-получение-токенов-и-ключей)
3. [Настройка `.env`](#3-настройка-env)
4. [Запуск через Docker Compose (24/7 в фоне)](#4-запуск-через-docker-compose-247-в-фоне)
5. [Запуск локально (без Docker)](#5-запуск-локально-без-docker)
6. [Проверка работоспособности в Real-Time](#6-проверка-работоспособности-в-real-time)
7. [Траблшутинг](#7-траблшутинг)

---

## 1. Предварительные требования (что нужно установить)

В зависимости от способа запуска:

### Вариант А: Запуск через Docker (рекомендуется)
Если запускать через Docker, **ничего кроме Docker устанавливать не нужно** (ни Python, ни библиотеки, ни PostgreSQL). Docker сам поднимет всё окружение внутри контейнеров.
- **Windows / macOS:** Установите [Docker Desktop](https://www.docker.com/products/docker-desktop/).
- **Linux / VPS сервер:** Установите Docker одной командой:
  ```bash
  curl -fsSL https://get.docker.com | sh
  ```

### Вариант Б: Запуск локально в системе (без Docker)
- **Python 3.14+** (или 3.12+): скачайте с [python.org](https://www.python.org/downloads/) (при установке на Windows отметьте «Add python.exe to PATH»).
- **Менеджер пакетов `uv`** (рекомендуется):
  - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Linux/Mac: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  *(Или стандартный `pip` через `requirements.txt`).*
- **PostgreSQL 16**: локальная служба или через `docker compose up -d db`.

---

## 2. Получение токенов и ключей

### 2.1 Telegram-бот

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram.
2. Отправьте команду `/newbot`, укажите имя и username для бота.
3. Скопируйте **токен** (формат: `1234567890:AAH_...`).
4. Узнайте свой числовой **Chat ID** (владельца):
   - Самый простой способ: напишите команду `/start` боту [@userinfobot](https://t.me/userinfobot).
   - Он ответит сообщением со строкой `Id: 123456789`. Это ваш ID.

### 2.2 HH.ru (HeadHunter) OAuth-токен

1. Зарегистрируйте приложение на [dev.hh.ru](https://dev.hh.ru/) под своим аккаунтом HH.
2. Укажите Redirect URI: `http://localhost`.
3. Получите `Client ID` и `Client Secret`.
4. Откройте в браузере ссылку авторизации (подставив ваш `Client ID`):
   ```text
   https://hh.ru/oauth/authorize?response_type=code&client_id=ВАШ_CLIENT_ID&redirect_uri=http://localhost
   ```
5. Нажмите «Разрешить доступ». После редиректа на `http://localhost/?code=XXXXXX` скопируйте значение `code`.
6. Обменяйте код на постоянный `access_token` (в терминале):
   ```bash
   curl -X POST https://hh.ru/oauth/token \
     -d "grant_type=authorization_code" \
     -d "client_id=ВАШ_CLIENT_ID" \
     -d "client_secret=ВАШ_CLIENT_SECRET" \
     -d "code=ВАШ_CODE" \
     -d "redirect_uri=http://localhost"
   ```
7. Из ответа JSON скопируйте `access_token`.

### 2.3 Resume ID (HH)

1. Откройте [hh.ru/resumes](https://hh.ru/resumes) и выберите нужное резюме.
2. В адресной строке браузера будет ссылка: `https://hh.ru/resume/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`.
3. Скопируйте 32-символьный хэш `XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`.

---

## 3. Настройка `.env`

Создайте `.env` файл на основе шаблона:

```bash
cp .env.example .env
```

Заполните ваши параметры:

```dotenv
# === Telegram ===
BOT_TOKEN=1234567890:AAH_ваш_реальный_токен
OWNER_CHAT_ID=123456789

# === База данных ===
# Для Docker Compose хост = имя сервиса "db":
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/jobhunter
# Для локального запуска хост = localhost:
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobhunter

# === HeadHunter ===
HH_ACCESS_TOKEN=ваш_access_token_от_hh
HH_RESUME_ID=ваш_32_символьный_хэш_резюме

# === Стартовые фильтры ===
SEARCH_QUERY=Python OR Удаленно OR Backend
REMOTE_ONLY=true
POLL_INTERVAL_SECONDS=300
DEFAULT_COVER_LETTER=Здравствуйте! Заинтересовала ваша вакансия. Буду рад обсудить детали.
```

---

## 4. Запуск через Docker Compose (24/7 в фоне)

Это **основной способ** работы в проде. Миграции накатываются автоматически, а контейнеры настроены с `restart: always` (автоподъём при перезагрузке системы).

```bash
# 1. Собрать и запустить контейнеры в фоне
docker compose up --build -d

# 2. Проверить статус работы
docker compose ps

# 3. Смотреть живой лог воркера
docker compose logs -f worker
```

### Остановка и перезапуск

```bash
docker compose restart     # Перезапустить бота
docker compose down        # Остановить (данные БД сохраняются в томе pgdata)
docker compose down -v     # Полная очистка вместе с БД
```

---

## 5. Запуск локально (без Docker)

Если вы запускаете проект напрямую в системе:

### 5.1 Поднять PostgreSQL
```bash
docker compose -f docker-compose.test.yml up -d
```

### 5.2 Установить зависимости

**Через uv (рекомендуется):**
```bash
uv sync --all-groups
```

**Или через pip:**
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 5.3 Применить миграции Alembic
```bash
uv run alembic upgrade head
# или:
alembic upgrade head
```

### 5.4 Запустить бота
```bash
uv run python -m app.main
# или:
python -m app.main
```

---

## 6. Проверка работоспособности в Real-Time

### ✅ Шаг 1: Юнит-тесты
```bash
uv run pytest
```
Ожидаемый результат: **87 passed, 5 skipped** (интеграционные тесты Postgres пропускаются, если не задана тестовая БД).

### ✅ Шаг 2: Проверка бота в Telegram
Откройте Telegram, найдите своего бота по username и отправьте `/start`.
- Бот ответит приветственным сообщением.
- Отправьте `/status` — бот покажет текущий режим, поисковый запрос и фильтры.

### ✅ Шаг 3: Проверка реальной базы PostgreSQL (интеграционные тесты)
```powershell
# Запуск тестовой базы
docker compose -f docker-compose.test.yml up -d

# Запуск тестов со строгой проверкой миграций и репозиториев
$env:TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/jobhunter_test"
uv run pytest -m integration

# Остановка тестовой базы
docker compose -f docker-compose.test.yml down -v
```

---

## 7. Траблшутинг

| Ошибка | Причина | Решение |
|---|---|---|
| `ValidationError: OWNER_CHAT_ID` | В `.env` не указан ID владельца | Укажите числовой `OWNER_CHAT_ID` в `.env` |
| `Connection refused` (порт 5432) | PostgreSQL ещё не запустился | Проверьте статус базы: `docker compose ps` |
| `401 / 403 Forbidden` от HH | Истёк OAuth-токен HeadHunter | Обновите `HH_ACCESS_TOKEN` (п. 2.2) |
| Бот не реагирует на команды | Сообщения отправлены с другого Telegram ID | Бот слушает строго `OWNER_CHAT_ID` |
| `search_query не может быть пустым` | Введен пустой поисковый запрос | Укажите непустой текст в команде `/query` |
