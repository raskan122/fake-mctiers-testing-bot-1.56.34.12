import discord
from discord.ext import commands
import asyncio
import logging
import os

import config
from utils.db_init import init_db

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_cogs():
    await bot.load_extension("cogs.commands")
    await bot.load_extension("cogs.events")
    await bot.load_extension("cogs.tasks")
    await bot.load_extension("cogs.setup")

async def main():
    init_db()
    async with bot:
        await load_cogs()
        await bot.start(os.environ["DISCORD_TOKEN"])

if __name__ == "__main__":
    asyncio.run(main())
