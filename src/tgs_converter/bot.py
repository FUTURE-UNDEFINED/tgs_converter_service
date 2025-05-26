import os
import sys

from telegram import Bot

token = os.environ.get("TELEGRAM_TOKEN")
if token is None:
    print("Please set TELEGRAM_TOKEN environment variable")
    sys.exit(1)

bot = Bot(token=token)

