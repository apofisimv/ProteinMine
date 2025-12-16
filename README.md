# 🧬 ProteinMine

Telegram WebApp игра с геолокацией и картами.

## Структура проекта

- `ProteinMine/backend/bot.py` — Telegram‑бот (aiogram)
- `ProteinMine/backend/api.py` — HTTP API (Flask) для WebApp (`/api/...`)
- `ProteinMine/frontend/index.html` — Telegram WebApp фронтенд
- `ProteinMine/proteinmine.db` — SQLite база данных
- `ProteinMine/.gitignore` — настройки git‑игнора

## Зависимости

Все основные зависимости перечислены в `requirements.txt` в корне проекта.

```bash
pip install -r requirements.txt
```

## Запуск бота

```bash
cd ProteinMine
python backend/bot.py
```

## Запуск API (локально)

```bash
cd ProteinMine
python backend/api.py
```

По умолчанию API поднимается на `http://127.0.0.1:5000`, фронтенд ожидает его по пути `/api`.

