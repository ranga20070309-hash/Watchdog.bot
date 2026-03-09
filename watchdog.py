import os
import asyncio
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks
from flask import Flask
from threading import Thread

# ---------- tiny web server for Render ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "watchdog alive", 200

@app.route("/health")
def health():
    return {"status": "ok"}, 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()

# ---------- discord watchdog ----------
TOKEN = os.getenv("WATCHDOG_BOT_TOKEN")
MAIN_BOT_ID = int(os.getenv("MAIN_BOT_ID"))
HEARTBEAT_CHANNEL_ID = int(os.getenv("HEARTBEAT_CHANNEL_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

CHECK_EVERY_MINUTES = 3
OFFLINE_AFTER_MINUTES = 6

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

last_state_offline = False

async def send_webhook_message(content: str):
    async with aiohttp.ClientSession() as session:
        async with session.post(WEBHOOK_URL, json={"content": content}) as resp:
            if resp.status >= 400:
                print(f"Webhook failed: {resp.status}")

async def find_heartbeat_message():
    channel = bot.get_channel(HEARTBEAT_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(HEARTBEAT_CHANNEL_ID)

    async for msg in channel.history(limit=30):
        if msg.author.id == MAIN_BOT_ID and msg.content.startswith("HEARTBEAT"):
            return msg
    return None

@tasks.loop(minutes=CHECK_EVERY_MINUTES)
async def monitor_loop():
    global last_state_offline

    try:
        msg = await find_heartbeat_message()

        if msg is None:
            if not last_state_offline:
                await send_webhook_message("🚨 Watchdog alert: heartbeat message not found. Main bot may be offline.")
                last_state_offline = True
            return

        last_update = msg.edited_at or msg.created_at
        now = datetime.now(timezone.utc)
        diff_minutes = (now - last_update).total_seconds() / 60

        if diff_minutes > OFFLINE_AFTER_MINUTES:
            if not last_state_offline:
                await send_webhook_message(
                    f"🚨 Watchdog alert: main bot heartbeat is stale ({diff_minutes:.1f} minutes old). Main bot may be offline."
                )
                last_state_offline = True
        else:
            if last_state_offline:
                await send_webhook_message("✅ Watchdog notice: main bot heartbeat is updating again. Bot is back online.")
                last_state_offline = False

    except Exception as e:
        print(f"Monitor loop error: {e}")

@monitor_loop.before_loop
async def before_monitor_loop():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    print(f"Watchdog bot online: {bot.user} ({bot.user.id})")
    if not monitor_loop.is_running():
        monitor_loop.start()

async def main():
    keep_alive()
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
