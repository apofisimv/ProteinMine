import threading

from .api import run_api
from .bot import run_bot


def main():
    """
    Entry point that runs both:
    - Flask API (for the WebApp / REST endpoints)
    - Telegram bot (aiogram) via long polling

    The Flask API runs in a background thread, and the Telegram bot runs
    in the main thread so aiogram can manage its asyncio event loop.
    """
    # Start Flask API in a background (daemon) thread
    api_thread = threading.Thread(target=run_api, name="flask-api", daemon=True)
    api_thread.start()
    print("Starting Flask API server...")

    # Run Telegram bot in the main thread (blocking)
    print("Starting Telegram bot...")
    run_bot()


if __name__ == "__main__":
    main()
