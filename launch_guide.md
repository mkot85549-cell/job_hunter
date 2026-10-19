# 🚀 Гайд по запуску Job Hunter

## Оглавление

1. [Предварительные требования](#1-предварительные-требования)
2. [Получение токенов и ключей](#2-получение-токенов-и-ключей)
3. [Настройка `.env`](#3-настройка-env)
4. [Запуск через Docker Compose](#4-запуск-через-docker-compose)
5. [Запуск локально (без Docker)](#5-запуск-локально-без-docker)
6. [Проверка работоспособности в Real-Time](#6-проверка-работоспособности-в-real-time)
7. [Траблшутинг](#7-траблшутинг)

---

## 1. Предварительные требования

| Инструмент | Версия | Зачем |
|---|---|---|
| **Docker + Docker Compose** | 24+ / v2 | Основной способ запуска (БД + воркер) |
| **Python** | 3.14+ | Для локальной разработки и тестов |
| **Git** | Любая | Клонирование репо |

---

## 2. Получение токенов и ключей

### 2.1 Telegram-бот

1. Откройте [@BotFather](https://t.me/BotFather) в Telegram
2. Отправьте `/newbot`, задайте имя и username
3. Скопируйте **токен** (формат: `1234567890:AAH_...`)
4. Узнайте свой **Chat ID**:
   - Напишите любое сообщение своему боту
   - Откройте `https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates`
   - В ответе найдите `"chat":{"id": 123456789}` — это ваш Chat ID

### 2.2 HH.ru (HeadHunter) OAuth-токен

1. Зарегистрируйте приложение на [dev.hh.ru](https://dev.hh.ru/)
2. Получите `client_id` и `client_secret`
3. Пройдите OAuth-авторизацию:

```
https://hh.ru/oauth/authorize?response_type=code&client_id=ВАШ_CLIENT_ID&redirect_uri=http://localhost
```

4. После редиректа скопируйте `code` из URL
5. Обменяйте code на access_token:

```bash
curl -X POST https://api.hh.ru/token \
  -d "grant_type=authorization_code" \
  -d "client_id=ВАШ_CLIENT_ID" \
  -d "client_secret=ВАШ_CLIENT_SECRET" \
  -d "code=ВАШ_CODE" \
  -d "redirect_uri=http://localhost"
```

6. Из ответа возьмите `access_token`

### 2.3 Resume ID (HH)

1. Откройте [hh.ru/resumes](https://hh.ru/resumes) → выберите резюме
2. В URL будет ID: `https://hh.ru/resume/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`
3. Скопируйте хэш `XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`

---

## 3. Настройка `.env`

Скопируйте шаблон и заполните реальными значениями:

```powershell
cp .env.example .env
```

Отредактируйте `.env`:

```dotenv
# === Telegram ===
BOT_TOKEN=1234567890:AAH_ваш_реальный_токен
TELEGRAM_CHAT_ID=123456789

# === База данных ===
# Для Docker Compose (хост = имя сервиса "db"):
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/jobhunter
# Для локального запуска (хост = localhost):
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobhunter

# === HeadHunter ===
HH_ACCESS_TOKEN=ваш_access_token_от_hh
HH_RESUME_ID=ваш_32_символьный_хэш_резюме

# === Опционально ===
SEARCH_QUERY=Удаленно OR Оператор OR Менеджер
POLL_INTERVAL_SECONDS=300
```

> [!IMPORTANT]
> Для Docker Compose хост базы — `db` (имя сервиса). Для локального запуска — `localhost`.

---

## 4. Запуск через Docker Compose

Это **рекомендуемый** способ. Поднимает PostgreSQL + воркер одной командой.

```powershell
# 1. Собрать и запустить
docker compose up --build -d

# 2. Посмотреть статус
docker compose ps

# 3. Следить за логами в реальном времени
docker compose logs -f worker
```

Ожидаемый вывод при успешном старте:

```
worker-1  | 2026-10-19 13:00:00 [INFO] app.main: Платформа hh: отправлено новых откликов: 3
worker-1  | 2026-10-19 13:00:01 [INFO] app.main: Платформа hh: обработано новых приглашений: 0
worker-1  | 2026-10-19 13:00:02 [INFO] app.main: Платформа zarplata: отправлено новых откликов: 1
worker-1  | 2026-10-19 13:00:02 [INFO] app.main: Платформа zarplata: обработано новых приглашений: 0
```

### Остановка

```powershell
docker compose down        # Остановить (данные БД сохраняются в volume)
docker compose down -v     # Остановить + удалить volume с данными БД
```

---

## 5. Запуск локально (без Docker)

### 5.1 Поднять только PostgreSQL через Docker

```powershell
docker compose up db -d
```

### 5.2 Установить зависимости

```powershell
python -m pip install -e ".[dev]"
# или если используете dependency groups:
python -m pip install -e .
python -m pip install pytest pytest-asyncio pytest-cov ruff
```

### 5.3 Изменить DATABASE_URL в `.env`

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/jobhunter
```

### 5.4 Запустить воркер

```powershell
python -m app.main
```

---

## 6. Проверка работоспособности в Real-Time

### ✅ Шаг 1: Юнит-тесты (не требуют токенов / БД)

```powershell
python -m pytest tests/ -v
```

Ожидаемый результат: **65 passed**

```
tests/test_adapters.py     ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓  (16 passed)
tests/test_core.py         ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓  (27 passed)
tests/test_orchestrator.py ✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓✓  (22 passed)
```

### ✅ Шаг 2: Проверить Telegram-бота

Убедитесь, что бот работает и может отправлять сообщения:

```powershell
# Подставьте свои значения
$BOT_TOKEN = "1234567890:AAH_ваш_токен"
$CHAT_ID = "123456789"

curl "https://api.telegram.org/bot$BOT_TOKEN/sendMessage?chat_id=$CHAT_ID&text=Job+Hunter+is+alive!"
```

В Telegram должно прийти сообщение **«Job Hunter is alive!»**

### ✅ Шаг 3: Проверить подключение к БД

```powershell
# При запущенном docker compose:
docker compose exec db psql -U postgres -d jobhunter -c "SELECT 1 AS connected;"
```

Ожидаемый ответ:

```
 connected
-----------
         1
```

### ✅ Шаг 4: Проверить HH API (токен живой?)

```powershell
$HH_TOKEN = "ваш_access_token"

curl -H "Authorization: Bearer $HH_TOKEN" -H "HH-User-Agent: JobHunterBot/1.0" "https://api.hh.ru/me"
```

Успешный ответ — JSON с данными вашего аккаунта. Ошибка `403` → токен истёк, нужно обновить.

### ✅ Шаг 5: Запустить воркер и следить за Real-Time логами

```powershell
# Docker:
docker compose logs -f worker

# Или локально:
python -m app.main
```

**Что проверять в логах:**

| Лог | Значение |
|---|---|
| `отправлено новых откликов: N` | ✅ Бот нашёл и отправил отклики |
| `обработано новых приглашений: N` | ✅ Бот проверил приглашения |
| `Ошибка при опросе площадки hh` | ⚠️ Проблема с API — смотрите traceback |
| `Сбой запроса... Попытка 2/3` | ⚠️ Retry сработал (обычно нормально) |

### ✅ Шаг 6: Проверить данные в БД после первого цикла

```powershell
docker compose exec db psql -U postgres -d jobhunter -c "
  SELECT platform, item_type, COUNT(*) as total
  FROM processed_items
  GROUP BY platform, item_type
  ORDER BY platform;
"
```

Ожидаемый вывод после первого цикла:

```
 platform | item_type  | total
----------+------------+-------
 hh       | vacancy    |    12
 hh       | invitation |     0
 zarplata | vacancy    |     3
 zarplata | invitation |     0
```

### ✅ Шаг 7: Проверить получение Telegram-уведомления

Если вам пришло приглашение на HH — бот отправит в Telegram сообщение вида:

```
🎯 Новый положительный отклик!

📌 Вакансия: Python Developer
📲 Теги ТГ: @recruiter_name

💬 Текст приглашения:
> Здравствуйте, мы заинтересованы в вашем резюме...
```

> [!TIP]
> Чтобы не ждать реальное приглашение, можно уменьшить `POLL_INTERVAL_SECONDS=30` в `.env` — бот будет опрашивать API каждые 30 секунд вместо 5 минут.

---

## 7. Траблшутинг

### Бот не запускается

| Ошибка | Причина | Решение |
|---|---|---|
| `ValidationError: bot_token` | `.env` не найден или поле пустое | Проверьте что `.env` в корне проекта |
| `Connection refused` на порту 5432 | PostgreSQL не запущен | `docker compose up db -d` |
| `asyncpg.InvalidPasswordError` | Неверный пароль БД | Проверьте `DATABASE_URL` в `.env` |

### API отвечает ошибкой

| Код | Причина | Решение |
|---|---|---|
| `401 Unauthorized` | Токен HH невалиден | Перевыпустите OAuth-токен (п. 2.2) |
| `403 Forbidden` | Токен истёк (HH токены живут ~14 дней) | Обновите access_token через refresh_token |
| `429 Too Many Requests` | Превышен лимит запросов | Бот сам ретраит — увеличьте `POLL_INTERVAL_SECONDS` |

### Telegram не приходят уведомления

1. Проверьте `TELEGRAM_CHAT_ID` — он должен быть числом (не username)
2. Убедитесь, что вы **написали боту первое сообщение** (бот не может написать первым)
3. Проверьте токен через Шаг 2 выше

### Сброс данных (начать с чистого листа)

```powershell
docker compose down -v
docker compose up --build -d
```

> [!CAUTION]
> Флаг `-v` удалит все данные из PostgreSQL. Бот начнёт заново откликаться на все вакансии.
