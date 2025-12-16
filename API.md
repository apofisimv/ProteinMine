## ProteinMine Backend API

This document describes the HTTP/JSON API exposed by `ProteinMine/backend/api.py` and how it is used by the Telegram Web App frontend (`frontend/index.html`) and the Telegram Bot (`backend/bot.py`).

---

## Overview

The API is a small Flask application that exposes JSON endpoints under the `/api` prefix. It is responsible for:

- Creating and loading **user accounts** for WebApp players
- Handling the **mining loop** (click → energy consumption → rewards and XP)
- Serving **leaderboards** (global and friends)
- Managing **clan** statistics
- Aggregating **city‑level statistics** for the Turkey map
- Receiving **user tracking** events from the WebApp (GPS + points)
- Generating per‑user **referral links** for the invite‑friend feature

The API uses a shared SQLite database located at `ProteinMine/proteinmine.db` by default, and can be configured via environment variables (see below).

---

## Configuration & Environment

The API loads configuration from environment variables using `python-dotenv`. A `.env` file is expected at `ProteinMine/.`:

- `PROTEINMINE_DB`  
  Absolute or relative path to the SQLite database file.  
  Default: `ProteinMine/proteinmine.db`.

- `TELEGRAM_BOT_TOKEN`  
  Used by `backend/bot.py` (Telegram bot, not directly by the API) to authenticate against the Telegram Bot API.

- `PROGENMINE_WEBAPP_URL`  
  Used by `backend/bot.py` to generate the WebApp button URL in `/start`.

- `TELEGRAM_BOT_USERNAME`  
  Used by `/api/referral/<user_id>` to generate invite links like `https://t.me/<username>?start=ref<user_id>`.

The Flask app is started via:

```bash
python -m ProteinMine.backend.api
```

By default it listens on `http://0.0.0.0:5000`, so the WebApp is usually configured with:

```text
API base URL: /api  (proxied to http://localhost:5000/api in development)
```

---

## Data Model (Database)

The API expects the following tables to exist in `proteinmine.db` (created by `backend/bot.py` and `init_stats_tables()`):

- `users`  
  Core player data:
  - `user_id` (INTEGER PRIMARY KEY, Telegram user id)
  - `protein` (INT, current balance)
  - `energy` (INT, current energy)
  - `xp` (INT)
  - `level` (INT)
  - `last_daily` (TEXT)
  - `daily_streak` (INT)
  - `clan_id` (INT, FK to `clans`)
  - `clan_contribution` (INT)

- `drops`  
  Historical record of rare/epic/legendary drops per user.

- `stats`  
  Per‑user aggregate stats (total clicks, rare_drops, best_combo). These are maintained by `backend/bot.py`.

- `referrals`, `friendships`  
  Tables used by the **invite‑friend** and **friends leaderboard** features.

- `clans`  
  Records per clan: `id`, `name`, `total_protein`, `members_count`.

- `user_track`  
  Created by `init_stats_tables()` in `api.py`. Stores last known GPS + points per Telegram user for the Turkey map and “Top cities” features:
  - `telegram_id`, `username`, `first_name`, `last_name`
  - `city` (detected from lat/lng)
  - `lat`, `lng`
  - `points` (current Protein points from WebApp)
  - `last_seen` (Unix timestamp)

---

## Authentication Model

The WebApp does **not** use a separate JWT or session cookie. Instead:

- The WebApp reads the current Telegram user id from `Telegram.WebApp.initDataUnsafe.user.id` (or falls back to URL/localStorage during local testing).
- Every request to the API includes this user id in the path: `/api/user/<user_id>`, `/api/mine/<user_id>`, etc.
- The API trusts the `user_id` it receives (no extra signature verification is performed). In production, you should validate `initData` according to Telegram’s Mini App docs before using the id.

---

## Endpoint Reference

All endpoints are prefixed with `/api`. JSON is always returned; errors are expressed with HTTP status codes and an `"error"` field.

### `GET /api/user/<int:user_id>`

**Purpose:** Fetch or lazily create the user record for the given `user_id`.

**Behavior:**

1. Looks up `users.user_id = <user_id>`.
2. If not found, automatically inserts a new row: `INSERT INTO users (user_id) VALUES (?)`.
3. Returns the user’s current stats.

**Response:**

```json
{
  "protein": 0,
  "energy": 50,
  "xp": 0,
  "level": 1,
  "maxEnergy": 50
}
```

**Used by:**  
`frontend/index.html` → `loadUser()` on page load and every 5s (via `setInterval(loadUser, 5000)`), to keep the on‑screen counters in sync.

---

### `POST /api/mine/<int:user_id>`

**Purpose:** Perform a single “mine” action from the WebApp (equivalent to tapping the big **MINE** button).

**Behavior:**

1. Loads or auto‑creates the `users` row for `user_id`.
2. If `energy <= 0`: returns `400` with `{"error": "No energy"}`.
3. Randomly chooses a rarity and multiplier:
   - `LEGENDARY` (0.1%, ×100)
   - `EPIC` (1%, ×20)
   - `RARE` (10%, ×5)
   - `COMMON` (else, ×1)
4. Rolls `base_gain = random.randint(1, 5)` and computes `gained = base_gain * multiplier`.
5. Decrements `energy` by 1, adds `gained` to `protein` and `xp`.
6. If `xp >= level * 100`, increments `level` and resets `xp` to `0`, sets `levelup = True`.
7. Updates `users` row and, if the user is in a clan, increments `users.clan_contribution` and `clans.total_protein`.

**Response:**

```json
{
  "success": true,
  "rarity": "RARE",
  "emoji": "⭐",
  "multiplier": 5,
  "gained": 15,
  "protein": 230,
  "energy": 42,
  "xp": 180,
  "level": 3,
  "levelup": false
}
```

**Used by:**  
`frontend/index.html` → `mine()` when the user taps the **MINE** button; the response drives the popup animation and updates local `d.protein`, `d.energy`, `d.xp`, `d.level`.

---

### `GET /api/referral/<int:user_id>`

**Purpose:** Generate a shareable **invite‑friend** link for the given user.

**Behavior:**

- Reads `TELEGRAM_BOT_USERNAME` from the environment.
- Returns a full deep‑link of the form:  
  `https://t.me/<TELEGRAM_BOT_USERNAME>?start=ref<user_id>`.

**Response:**

```json
{ "referral_link": "https://t.me/YourBot?start=ref123456789" }
```

If `TELEGRAM_BOT_USERNAME` is missing:

```json
{ "error": "TELEGRAM_BOT_USERNAME is not configured" }
```

**Used by:**  
`frontend/index.html` → `invite friend` button. The WebApp calls this endpoint, then shows the link and can pass it to the Telegram client for sharing.

> **Note:** When a referred user taps the link and hits `/start` inside the bot, `backend/bot.py` detects `?start=ref<id>`, credits the new user with `+100` protein and the referrer with `+50` protein and `+20` energy, and creates a `referrals` + `friendships` link.

---

### `POST /api/user-track`

**Purpose:** Store the latest **location + score** snapshot for a WebApp user, used to build the **Turkey city heatmap** and “Top miners in your city”‑style features.

**Request body:**

```json
{
  "telegramId": 123456789,
  "username": "someuser",
  "firstName": "Alice",
  "lastName": "Doe",
  "lat": 41.0082,
  "lng": 28.9784,
  "points": 1234
}
```

**Behavior:**

1. Parses and normalizes `telegramId` and `points` to integers.
2. Derives `city` from `lat`/`lng` using `detect_turkey_city()` and the `TURKEY_CITIES` + `CITY_RADIUS_KM` table.
3. Upserts into `user_track` on `telegram_id` (one row per user), updating username, location, points, and `last_seen`.

**Response:**

```json
{
  "ok": true,
  "city": "Istanbul",
  "points": 1234
}
```

**Used by:**  
`frontend/index.html` → `sendUserTrack()` is called after `loadUser()` and after every successful `mine()` to keep server‑side stats up to date.

---

### `GET /api/turkey-stats`

**Purpose:** Provide aggregated **per‑city** statistics for the Turkey map view in the WebApp.

**Behavior:**

- Aggregates all rows in `user_track` where `city IS NOT NULL`:

```sql
SELECT city,
       COUNT(*) AS users,
       COALESCE(SUM(points), 0) AS total_points
FROM user_track
WHERE city IS NOT NULL AND city != ''
GROUP BY city
ORDER BY total_points DESC;
```

**Response:**

```json
{
  "cityStats": [
    { "name": "Istanbul", "points": 12345, "users": 10 },
    { "name": "Ankara",   "points":  6789, "users": 5 }
  ]
}
```

**Used by:**  
`frontend/index.html` → `refreshTurkeyStats()` and `renderTurkeyStatic()` to render the Highcharts map and the summary text under the “Turkey Mining Statistics” tab.

---

### `GET /api/clans`

**Purpose:** Provide **clan leaderboard & map** data.

**Behavior:**

- Reads from `clans`:

```sql
SELECT id, name, total_protein, members_count 
FROM clans 
ORDER BY total_protein DESC;
```

**Response:**

```json
[
  { "id": 2, "name": "Istanbul", "total_protein": 150000, "members_count": 120 },
  { "id": 1, "name": "Ankara",   "total_protein":  95000, "members_count": 80  }
]
```

**Used by:**

- `frontend/index.html` → `renderClanLeaderboard()` for the **Clans** tab in the Leaderboard.
- `frontend/index.html` → `initMap()` to draw colored circles over Turkish cities representing clan strength.

---

### `GET /api/leaderboard/global`

**Purpose:** Global **top players** leaderboard.

**Behavior:**

- Selects top 50 users by `protein`:

```sql
SELECT user_id, protein, level, xp 
FROM users 
ORDER BY protein DESC 
LIMIT 50;
```

**Response:**

```json
[
  { "user_id": 123, "protein": 15000, "level": 7, "xp": 20 },
  { "user_id": 456, "protein": 12000, "level": 6, "xp": 80 }
]
```

**Used by:**  
`frontend/index.html` → `switchLeaderboard('global')` and `renderLeaderboard()` to populate the **Top → Global** tab.

---

### `GET /api/leaderboard/friends/<int:user_id>`

**Purpose:** **Friends** leaderboard for a given user.

**Behavior:**

- Joins `friendships` and `users` to list the top 20 friends ordered by protein:

```sql
SELECT u.user_id, u.protein, u.level, u.xp
FROM   friendships f
JOIN   users u ON (f.friend_id = u.user_id)
WHERE  f.user_id = ?
ORDER BY u.protein DESC
LIMIT  20;
```

**Response:**

```json
[
  { "user_id": 234, "protein": 8000, "level": 5, "xp": 40 },
  { "user_id": 345, "protein": 5000, "level": 4, "xp": 10 }
]
```

**Used by:**  
`frontend/index.html` → `switchLeaderboard('friends')` and `renderLeaderboard()` for the **Friends** tab.

The `friendships` table is maintained by `backend/bot.py` (e.g. `/addfriend` and referral auto‑linking).

---

### `GET /api/user/position/<int:user_id>`

**Purpose:** Return the **global rank** of a given user by protein.

**Behavior:**

```sql
SELECT COUNT(*) + 1
FROM   users
WHERE  protein > (SELECT protein FROM users WHERE user_id = ?);
```

This returns the 1‑based rank: `1` means top player; `2` means second place, etc.

**Response:**

```json
{ "position": 5 }
```

**Used by:**  
`frontend/index.html` → `loadLeaderboard()` to fill the “Your Position” card at the top of the Leaderboard page.

---

## High‑Level Request Flow (WebApp)

1. **WebApp initialization**
   - The WebApp loads `frontend/index.html` inside the Telegram client.
   - JS reads `Telegram.WebApp.initDataUnsafe.user.id` into `userId`.  
     For local testing without Telegram, it falls back to `?user_id=` or a random `localStorage` ID.

2. **Initial user sync**
   - `loadUser()` calls `GET /api/user/<userId>`.  
     If this is the first time the user plays, the API auto‑creates a `users` row with default values.
   - The response is stored in `d = { protein, energy, level, xp, maxEnergy }` and used to render the main “Mine” screen.

3. **Mining loop**
   - When the player taps **MINE**, `mine()` calls `POST /api/mine/<userId>`.
   - The API checks energy, computes a random drop and updates `users` (+ clans).
   - The WebApp:
     - Updates local `d.*` with the returned values.
     - Animates the big circle, shows a popup (`showDropMessage(result)`).
     - Calls `sendUserTrack()` to push the new `points` + GPS to `/api/user-track`.

4. **Leaderboards**
   - When the user switches to **Top** tab, `loadLeaderboard()`:
     - Calls `GET /api/user/position/<userId>` to show “Your Position”.
     - Calls `GET /api/leaderboard/global` / `.../friends/<userId>` / `GET /api/clans` depending on the selected sub‑tab and renders them via `renderLeaderboard()` or `renderClanLeaderboard()`.

5. **Map & Stats**
   - **Clans map** (`Clans` tab): `initMap()` calls `GET /api/clans` and draws circles and markers at clan locations.
   - **Turkey stats** (`Stats` tab): `ensureTurkeyStatic()` → `refreshTurkeyStats()` → `GET /api/turkey-stats` → `renderTurkeyStatic()` to render the Highcharts map.

6. **Invite friend workflow**
   - On the Mine or Top page, when the user taps **“Invite a friend”**:
     - `inviteFriend()` in the frontend calls `GET /api/referral/<userId>`.
     - The API builds `https://t.me/<TELEGRAM_BOT_USERNAME>?start=ref<userId>`.
     - The WebApp shows this link and can ask Telegram to share it.
   - When the invited friend opens the link, Telegram opens the bot with `start` parameter `ref<referrerId>`.
   - `backend/bot.py`’s `/start` handler:
     - Creates a new `users` row for the referred user with bonus protein.
     - Increments the referrer’s `referral_count`, adds **+50 protein** and **+20 energy**, and links them in `referrals` + `friendships`.

---

## Notes & Future Improvements

- **Security / validation**
  - Currently the API trusts the `user_id` provided by the WebApp. For production, you should validate `Telegram.WebApp.initData` signatures and/or introduce your own session tokens.

- **Rate limiting**
  - Consider adding rate limiting or anti‑bot protections around `/api/mine/<id>` to prevent scripted abuse.

- **Error handling**
  - Frontend currently shows generic `alert('Mining failed')` on non‑success; you can extend the API to return more detailed error codes and surface them nicely.


