# Derpibooru Telegram Bot + Web Dashboard (WS + RBAC)

Асинхронный бот-постер картинок из Derpibooru в Telegram-канал + веб-панель:
- **Публичная галерея** `GET /` (без логина)
- **Live-обновления** через WebSocket `GET /ws`
- **RBAC**: роли **admin** и **viewer**
  - **admin**: доступ к `/settings`, изменение настроек и кнопка "Отправить сейчас"
  - **viewer**: доступ к `/viewer` (read-only страница, без изменения настроек)

## 1) Установка

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -r requirements.txt
```

## 2) Настройка .env

Скопируй пример и заполни:

```bash
cp .env.example .env
```

Обязательные поля:
- `TELEGRAM_TOKEN`
- `CHANNEL_ID`
- `DERPIBOORU_TOKEN`
- `ADMIN_PASSWORD`
- `SESSION_SECRET`

### RBAC
- `ADMIN_USER` / `ADMIN_PASSWORD` — админ
- `VIEWER_USER` / `VIEWER_PASSWORD` — read-only viewer (опционально)

## 3) Запуск

```bash
python -m app.main
```

Открыть в браузере:
- `http://WEB_HOST:WEB_PORT/` — публичная галерея
- `http://WEB_HOST:WEB_PORT/login` — вход
- `http://WEB_HOST:WEB_PORT/settings` — настройки (admin)
- `http://WEB_HOST:WEB_PORT/viewer` — read-only (viewer/admin)

## 4) Терминал (CLI)

CLI работает с `settings.json` (не трогает `.env`), то есть меняет:
- интервал постинга
- filter_id
- группы тегов

Примеры:

```bash
# показать текущие настройки
python -m app.cli show

# изменить интервал
python -m app.cli set-interval 30

# изменить filter_id (или выключить фильтр)
python -m app.cli set-filter 56027
python -m app.cli set-filter none

# задать теги (каждая строка = группа)
python -m app.cli set-tags "pony, solo\nsafe smiling\noc"

# форсировать пост сейчас (через Web API — нужен admin)
python -m app.cli post-now
```

> `post-now` дергает Web API, поэтому нужен запущенный сервер и admin логин/пароль в `.env`.

## 5) Установка как пакет (setup.py)

Можно поставить как пакет и получить команды:

```bash
pip install -e .
derpi-bot
derpi-bot-cli show
```

## 6) Безопасность
- Логин хранится в cookie `session` (HMAC подпись + TTL).
- Настройки и post-now защищены ролью **admin**.
- Viewer может только смотреть `/viewer`.

## 7) Troubleshooting
- Если `/settings` редиректит на `/login` — нет валидной сессии или роль viewer.
- Если Telegram не отправляет — проверь `TELEGRAM_TOKEN` и `CHANNEL_ID`.
