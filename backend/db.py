"""
MongoDB connection and database utilities.
"""
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# MongoDB connection string from environment
# Default connection string (will be overridden by env var if set)
DEFAULT_MONGODB_URI = "mongodb+srv://cryptokingmax:ajgjkdajrys@cluster0.h2ziqqg.mongodb.net/bot?retryWrites=true&w=majority"
MONGODB_URI = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)

# Extract database name from URI if present, otherwise use env var or default "bot"
# MongoDB URIs can have database name in path: mongodb://host/dbname?options
uri_db_name = None
if "/" in MONGODB_URI.split("?")[0]:
    # Extract database name from URI path
    path_part = MONGODB_URI.split("?")[0].split("/")
    if len(path_part) > 1 and path_part[-1]:
        uri_db_name = path_part[-1]

DB_NAME = os.getenv("MONGODB_DB_NAME", uri_db_name or "bot")

# Create MongoDB client
try:
    client = MongoClient(MONGODB_URI)
    # Test connection
    client.admin.command('ping')
    db = client[DB_NAME]
    print(f"Connected to MongoDB database: {DB_NAME}")
except ConnectionFailure as e:
    raise RuntimeError(f"Failed to connect to MongoDB: {e}")


def init_db():
    """
    Initialize MongoDB collections with indexes for better performance.
    This is safe to run on every start.
    """
    # Users collection indexes
    db.users.create_index("user_id", unique=True)
    db.users.create_index("protein")
    db.users.create_index("clan_id")
    
    # Drops collection indexes
    db.drops.create_index("user_id")
    db.drops.create_index("timestamp")
    
    # Stats collection indexes
    db.stats.create_index("user_id", unique=True)
    
    # User track collection indexes
    db.user_track.create_index("telegram_id", unique=True)
    db.user_track.create_index("city")
    db.user_track.create_index("points")
    
    # Clans collection indexes
    db.clans.create_index("id", unique=True)
    db.clans.create_index("total_protein")
    
    # Referrals collection indexes
    db.referrals.create_index([("referrer_id", 1), ("referred_id", 1)], unique=True)
    db.referrals.create_index("referrer_id")
    db.referrals.create_index("referred_id")
    
    # Friendships collection indexes
    db.friendships.create_index([("user_id", 1), ("friend_id", 1)], unique=True)
    db.friendships.create_index("user_id")
    db.friendships.create_index("friend_id")
    
    # Admin messages collection indexes
    db.admin_messages.create_index("admin_id")
    db.admin_messages.create_index("timestamp")
    db.admin_messages.create_index("recipient_user_ids")
    
    # Initialize default clans if they don't exist
    default_clans = [
        {"id": 1, "name": "🏛️ Ankara", "total_protein": 0, "members_count": 0},
        {"id": 2, "name": "🌉 Istanbul", "total_protein": 0, "members_count": 0},
        {"id": 3, "name": "🏖️ Izmir", "total_protein": 0, "members_count": 0},
        {"id": 4, "name": "🏔️ Antalya", "total_protein": 0, "members_count": 0},
        {"id": 5, "name": "🏙️ Bursa", "total_protein": 0, "members_count": 0},
    ]
    
    for clan in default_clans:
        db.clans.update_one(
            {"id": clan["id"]},
            {"$setOnInsert": clan},
            upsert=True
        )


# Initialize on import
init_db()

