"""
telegram_agy_bot.py — Thin entry-point shim.

All logic has been extracted into the agy_bot/ package.
This file keeps backward compatibility so the bot can still be launched with:

    python telegram_agy_bot.py

"""

from agy_bot.main import main

if __name__ == "__main__":
    main()
