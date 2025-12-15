from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import time

app = Flask(__name__)
CORS(app)

DB_PATH = "/opt/proteinmine/proteinmine.db"
MAX_ENERGY = 50
ENERGY_REGEN_TIME = 30

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT protein, energy, xp, level 
        FROM users 
        WHERE user_id = ?
    """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row is None:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "protein": row[0],
        "energy": row[1],
        "xp": row[2],
        "level": row[3],
        "maxEnergy": MAX_ENERGY
    })

@app.route('/api/mine/<int:user_id>', methods=['POST'])
def mine(user_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # Получаем пользователя
    cursor.execute("""
        SELECT protein, energy, xp, level 
        FROM users 
        WHERE user_id = ?
    """, (user_id,))
    
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    
    protein, energy, xp, level = row
    
    if energy <= 0:
        conn.close()
        return jsonify({"error": "No energy"}), 400
    
    # Определяем редкость
    import random
    roll = random.random()
    
    if roll < 0.001:  # LEGENDARY
        rarity = "LEGENDARY"
        multiplier = 100
        emoji = "💎"
    elif roll < 0.01:  # EPIC
        rarity = "EPIC"
        multiplier = 20
        emoji = "🔮"
    elif roll < 0.10:  # RARE
        rarity = "RARE"
        multiplier = 5
        emoji = "⭐"
    else:  # COMMON
        rarity = "COMMON"
        multiplier = 1
        emoji = "🧬"
    
    # Считаем награду
    base_gain = random.randint(1, 5)
    gained = base_gain * multiplier
    
    # Обновляем данные
    energy -= 1
    protein += gained
    xp += gained
    
    # Level up
    levelup = False
    if xp >= level * 100:
        level += 1
        xp = 0
        levelup = True
    
    # Сохраняем в базу
    cursor.execute("""
        UPDATE users 
        SET protein = ?, energy = ?, xp = ?, level = ?
        WHERE user_id = ?
    """, (protein, energy, xp, level, user_id))
    
    conn.commit()
    
    # ============================
    # CLAN CONTRIBUTION UPDATE
    # ============================
    print(f"[CLAN DEBUG] Mining: user={user_id}, gained={gained}")
    
    cursor.execute("SELECT clan_id FROM users WHERE user_id = ?", (user_id,))
    clan_row = cursor.fetchone()
    
    if clan_row and clan_row[0]:
        clan_id = clan_row[0]
        print(f"[CLAN DEBUG] User in clan {clan_id}, updating contribution")
        
        cursor.execute(
            "UPDATE users SET clan_contribution = clan_contribution + ? WHERE user_id = ?",
            (gained, user_id)
        )
        cursor.execute(
            "UPDATE clans SET total_protein = total_protein + ? WHERE id = ?",
            (gained, clan_id)
        )
        conn.commit()
        print(f"[CLAN DEBUG] Clan contribution updated!")
    else:
        print(f"[CLAN DEBUG] User not in any clan")
    
    conn.close()
    
    return jsonify({
        "success": True,
        "rarity": rarity,
        "emoji": emoji,
        "multiplier": multiplier,
        "gained": gained,
        "protein": protein,
        "energy": energy,
        "xp": xp,
        "level": level,
        "levelup": levelup
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
