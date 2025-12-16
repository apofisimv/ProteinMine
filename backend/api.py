from flask import Flask, jsonify, request
from flask_cors import CORS
import os
import sqlite3
import time
import math

from dotenv import load_dotenv

app = Flask(__name__)
CORS(app)

# Resolve DB path in a way that works both on local (Windows) and server (Linux)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

# Load environment variables from a .env file at the project root (ProteinMine/.env)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

DEFAULT_DB_PATH = os.path.join(ROOT_DIR, "proteinmine.db")
DB_PATH = os.getenv("PROTEINMINE_DB", DEFAULT_DB_PATH)

MAX_ENERGY = 50
ENERGY_REGEN_TIME = 30


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_stats_tables():
    """
    Ensure tables for the statistics / Turkey map exist.
    This is safe to run on every start (CREATE TABLE IF NOT EXISTS).
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_track (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            city TEXT,
            lat REAL,
            lng REAL,
            points INTEGER DEFAULT 0,
            last_seen INTEGER
        )
        """
    )

    conn.commit()
    conn.close()


# Approximate coordinates of main Turkish cities / provinces
TURKEY_CITIES = {
    "Istanbul": (41.015137, 28.97953),
    "Ankara": (39.9334, 32.8597),
    "Izmir": (38.4237, 27.1428),
    "Bursa": (40.1950, 29.0600),
    "Antalya": (36.8969, 30.7133),
    "Adana": (37.0, 35.3213),
    "Konya": (37.8746, 32.4932),
    "Gaziantep": (37.0662, 37.3833),
    "Kayseri": (38.7225, 35.4875),
    "Mersin": (36.8121, 34.6415),
    "Diyarbakır": (37.9144, 40.2306),
    "Samsun": (41.2867, 36.33),
    "Trabzon": (41.0015, 39.7178),
    "Erzurum": (39.9043, 41.2679),
    "Eskişehir": (39.7667, 30.5256),
    "Sakarya": (40.7569, 30.3781),
    "Kocaeli": (40.8533, 29.8815),
    "Malatya": (38.3552, 38.3095),
    "Şanlıurfa": (37.1591, 38.7969),
}

# Rough radius (km) to still count as being "from" a given Turkish city
CITY_RADIUS_KM = 120.0


def haversine_km(lat1, lon1, lat2, lon2):
    """
    Compute approximate distance (km) between 2 lat/lng points.
    """
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def detect_turkey_city(lat, lng):
    """
    Map raw GPS coords to nearest Turkish city (province) name.
    Only returns a city if distance is within CITY_RADIUS_KM.
    """
    if lat is None or lng is None:
        return None

    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return None

    best_city = None
    best_dist = None

    for city_name, (c_lat, c_lng) in TURKEY_CITIES.items():
        dist = haversine_km(lat, lng, c_lat, c_lng)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_city = city_name

    if best_city is not None and best_dist is not None and best_dist <= CITY_RADIUS_KM:
        return best_city

    return None


@app.before_first_request
def _startup():
    # Make sure our stats tables exist before any request hits
    init_stats_tables()


@app.route("/api/user/<int:user_id>", methods=["GET"])
def get_user(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT protein, energy, xp, level 
        FROM users 
        WHERE user_id = ?
    """,
        (user_id,),
    )

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return jsonify({"error": "User not found"}), 404

    return jsonify(
        {
            "protein": row[0],
            "energy": row[1],
            "xp": row[2],
            "level": row[3],
            "maxEnergy": MAX_ENERGY,
        }
    )


@app.route("/api/user-track", methods=["POST"])
def user_track():
    """
    Track a single snapshot from the WebApp:
    - telegramId, username, first/last name
    - lat/lng (optional)
    - current points in the web mini-game

    Frontend JS sends POST /api/user-track with this payload.
    We store one row per Telegram user and update it on every call.
    """
    data = request.get_json(silent=True) or {}

    telegram_id = data.get("telegramId")
    username = data.get("username")
    first_name = data.get("firstName")
    last_name = data.get("lastName")
    points = data.get("points") or 0
    lat = data.get("lat")
    lng = data.get("lng")

    try:
        if telegram_id is not None:
            telegram_id = int(telegram_id)
    except (TypeError, ValueError):
        telegram_id = None

    try:
        points = int(points)
    except (TypeError, ValueError):
        points = 0

    # If no Telegram id we still accept, but it won't be user-unique
    # (rare in real Telegram WebApp usage).
    city = detect_turkey_city(lat, lng)
    now_ts = int(time.time())

    conn = get_db()
    cursor = conn.cursor()

    # Upsert by telegram_id; if it is NULL we just insert a new row each time
    if telegram_id is not None:
        cursor.execute(
            """
            INSERT INTO user_track (
                telegram_id, username, first_name, last_name,
                city, lat, lng, points, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                city = excluded.city,
                lat = excluded.lat,
                lng = excluded.lng,
                points = excluded.points,
                last_seen = excluded.last_seen
            """,
            (
                telegram_id,
                username,
                first_name,
                last_name,
                city,
                float(lat) if lat is not None else None,
                float(lng) if lng is not None else None,
                points,
                now_ts,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO user_track (
                telegram_id, username, first_name, last_name,
                city, lat, lng, points, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                None,
                username,
                first_name,
                last_name,
                city,
                float(lat) if lat is not None else None,
                float(lng) if lng is not None else None,
                points,
                now_ts,
            ),
        )

    conn.commit()
    conn.close()

    return jsonify(
        {
            "ok": True,
            "city": city,
            "points": points,
        }
    )


@app.route("/api/mine/<int:user_id>", methods=["POST"])
def mine(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT protein, energy, xp, level 
        FROM users 
        WHERE user_id = ?
    """,
        (user_id,),
    )

    row = cursor.fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    protein, energy, xp, level = row

    if energy <= 0:
        conn.close()
        return jsonify({"error": "No energy"}), 400

    import random

    roll = random.random()

    if roll < 0.001:
        rarity = "LEGENDARY"
        multiplier = 100
        emoji = "💎"
    elif roll < 0.01:
        rarity = "EPIC"
        multiplier = 20
        emoji = "🔮"
    elif roll < 0.10:
        rarity = "RARE"
        multiplier = 5
        emoji = "⭐"
    else:
        rarity = "COMMON"
        multiplier = 1
        emoji = "🧬"

    base_gain = random.randint(1, 5)
    gained = base_gain * multiplier

    energy -= 1
    protein += gained
    xp += gained

    levelup = False
    if xp >= level * 100:
        level += 1
        xp = 0
        levelup = True

    cursor.execute(
        """
        UPDATE users 
        SET protein = ?, energy = ?, xp = ?, level = ?
        WHERE user_id = ?
    """,
        (protein, energy, xp, level, user_id),
    )

    conn.commit()

    cursor.execute("SELECT clan_id FROM users WHERE user_id = ?", (user_id,))
    clan_row = cursor.fetchone()

    if clan_row and clan_row[0]:
        clan_id = clan_row[0]
        cursor.execute(
            "UPDATE users SET clan_contribution = clan_contribution + ? WHERE user_id = ?",
            (gained, user_id),
        )
        cursor.execute(
            "UPDATE clans SET total_protein = total_protein + ? WHERE id = ?",
            (gained, clan_id),
        )
        conn.commit()

    conn.close()

    return jsonify(
        {
            "success": True,
            "rarity": rarity,
            "emoji": emoji,
            "multiplier": multiplier,
            "gained": gained,
            "protein": protein,
            "energy": energy,
            "xp": xp,
            "level": level,
            "levelup": levelup,
        }
    )


@app.route("/api/turkey-stats", methods=["GET"])
def turkey_stats():
    """
    Aggregate city statistics for the Turkey map.

    Response shape:
    {
      "cityStats": [
        {"name": "Istanbul", "points": 12345, "users": 10},
        ...
      ]
    }
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT city,
               COUNT(*) AS users,
               COALESCE(SUM(points), 0) AS total_points
        FROM user_track
        WHERE city IS NOT NULL AND city != ''
        GROUP BY city
        ORDER BY total_points DESC
        """
    )

    rows = cursor.fetchall()
    conn.close()

    city_stats = []
    for row in rows:
        city_name = row[0]
        users = row[1] or 0
        total_points = row[2] or 0
        if not city_name:
            continue
        city_stats.append(
            {
                "name": city_name,
                "points": int(total_points),
                "users": int(users),
            }
        )

    return jsonify({"cityStats": city_stats})


@app.route("/api/clans", methods=["GET"])
def get_clans():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, name, total_protein, members_count 
        FROM clans 
        ORDER BY total_protein DESC
    """
    )

    rows = cursor.fetchall()
    conn.close()

    clans = []
    for row in rows:
        clans.append(
            {
                "id": row[0],
                "name": row[1],
                "total_protein": row[2],
                "members_count": row[3],
            }
        )

    return jsonify(clans)


@app.route("/api/leaderboard/global", methods=["GET"])
def get_global_leaderboard():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id, protein, level, xp 
        FROM users 
        ORDER BY protein DESC 
        LIMIT 50
    """
    )

    rows = cursor.fetchall()
    conn.close()

    leaderboard = []
    for row in rows:
        leaderboard.append(
            {
                "user_id": row[0],
                "protein": row[1],
                "level": row[2],
                "xp": row[3],
            }
        )

    return jsonify(leaderboard)


@app.route("/api/leaderboard/friends/<int:user_id>", methods=["GET"])
def get_friends_leaderboard(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT u.user_id, u.protein, u.level, u.xp
        FROM friendships f
        JOIN users u ON (f.friend_id = u.user_id)
        WHERE f.user_id = ?
        ORDER BY u.protein DESC
        LIMIT 20
    """,
        (user_id,),
    )

    rows = cursor.fetchall()
    conn.close()

    friends = []
    for row in rows:
        friends.append(
            {
                "user_id": row[0],
                "protein": row[1],
                "level": row[2],
                "xp": row[3],
            }
        )

    return jsonify(friends)


@app.route("/api/user/position/<int:user_id>", methods=["GET"])
def get_user_position(user_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*) + 1
        FROM users
        WHERE protein > (SELECT protein FROM users WHERE user_id = ?)
    """,
        (user_id,),
    )

    position = cursor.fetchone()[0]
    conn.close()

    return jsonify({"position": position})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)


