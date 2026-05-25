import discord
from discord.ext import commands
import logging

import config
from utils.database import save_data_to_json
from utils.ui import WaitlistView
from utils.embeds import generate_waitlist_embed
from utils.helpers import log_command_exec

class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        if not hasattr(self.bot, 'waitlist_panel_initialized'):
            await self.setup_waitlist_panel()
            self.bot.waitlist_panel_initialized = True

    async def setup_waitlist_panel(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild:
            logging.error("Guild not found, cannot set up waitlist panel.")
            return

        channel = guild.get_channel(config.REQUEST_TEST_CHANNEL_ID) 
        if not channel:
            logging.error(f"Waitlist channel with ID {config.REQUEST_TEST_CHANNEL_ID} not found.")
            return

        embed = generate_waitlist_embed()
        view = WaitlistView()
        logging.info(f"Checking for an existing waitlist panel in '{channel.name}'...")
        try:
            async for message in channel.history(limit=100):

                if message.author.id == self.bot.user.id and message.embeds:
                    if message.embeds[0].title == embed.title and message.embeds[0].description == embed.description:
                        logging.info(f"Found an up-to-date panel (ID: {message.id}). No action needed.")

                        return 
        except (discord.Forbidden, discord.HTTPException) as e:
            logging.error(f"Could not check channel history for channel {channel.id}: {e}")
            return
        logging.info("No up-to-date panel found. Cleaning up and posting a new one.")

        try:
            async for message in channel.history(limit=50):
                if message.author.id == self.bot.user.id:
                    await message.delete()
                    logging.info(f"Deleted old bot message {message.id}")
        except (discord.Forbidden, discord.HTTPException) as e:
            logging.error(f"Failed to delete old panels in channel {channel.id}: {e}")
        try:
            new_msg = await channel.send(embed=embed, view=view)
            await save_data_to_json("waitlist_message.json", {"id": new_msg.id})
            logging.info(f"Posted new waitlist panel message with ID {new_msg.id}")
        except (discord.Forbidden, discord.HTTPException) as e:
            logging.error(f"Failed to send new waitlist panel message: {e}")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command and interaction.command:
            await log_command_exec(interaction)

async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))