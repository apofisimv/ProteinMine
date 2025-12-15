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
    
    cursor.execute("""
        UPDATE users 
        SET protein = ?, energy = ?, xp = ?, level = ?
        WHERE user_id = ?
    """, (protein, energy, xp, level, user_id))
    
    conn.commit()
    
    cursor.execute("SELECT clan_id FROM users WHERE user_id = ?", (user_id,))
    clan_row = cursor.fetchone()
    
    if clan_row and clan_row[0]:
        clan_id = clan_row[0]
        cursor.execute(
            "UPDATE users SET clan_contribution = clan_contribution + ? WHERE user_id = ?",
            (gained, user_id)
        )
        cursor.execute(
            "UPDATE clans SET total_protein = total_protein + ? WHERE id = ?",
            (gained, clan_id)
        )
        conn.commit()
    
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

@app.route('/api/clans', methods=['GET'])
def get_clans():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, total_protein, members_count 
        FROM clans 
        ORDER BY total_protein DESC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    clans = []
    for row in rows:
        clans.append({
            "id": row[0],
            "name": row[1],
            "total_protein": row[2],
            "members_count": row[3]
        })
    
    return jsonify(clans)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
