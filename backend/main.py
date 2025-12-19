import os
import threading

from .api import run_api
from .bot import run_bot


def main():
    """
    Entry point that runs both:
    - Flask API (for the WebApp / REST endpoints)
    - Telegram bot (aiogram) via long polling

    The bot runs in a background thread; the Flask app runs in the main thread.
    """
    # Start Telegram bot in a background (daemon) thread
    bot_thread = threading.Thread(target=run_bot, name="telegram-bot", daemon=True)
    bot_thread.start()

    # Run Flask API (this will block until the process is stopped)
    print("Starting Flask API server...")
    run_api()


if __name__ == "__main__":
    main()



