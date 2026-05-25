import asyncio
import discord
from discord.ext import commands, tasks
import logging
from datetime import datetime, timezone, timedelta

import config
from utils.database import db_fetch_one, get_all_tickets, db_write, load_data_from_json, save_data_to_json
from utils.helpers import update_queue_display, handle_ticket_close
from utils.embeds import set_footer

class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_reset_month = datetime.now(timezone.utc).month
        self.delete_expired_tickets.start()
        self.update_queues_periodically.start()
        self.update_leaderboard_task.start()
        self.monthly_rollover_check.start()

    def cog_unload(self):
        self.delete_expired_tickets.cancel()
        self.update_queues_periodically.cancel()
        self.update_leaderboard_task.cancel()
        self.monthly_rollover_check.cancel()

    @tasks.loop(minutes=1)
    async def delete_expired_tickets(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild: return

        all_tickets = await get_all_tickets()
        now = datetime.now(timezone.utc)
        
        ticket_lifespan = timedelta(days=3)
        warning_threshold = ticket_lifespan - timedelta(minutes=15)

        for ticket in all_tickets:
            channel_id = ticket.get("channel_id")
            exempt_ticket = await db_fetch_one("SELECT is_exempt FROM tickets WHERE channel_id = %s", (channel_id,))
            if exempt_ticket and exempt_ticket.get('is_exempt'):
                continue

            creation_time = ticket.get("creation_time")
            warning_sent = ticket.get("warning_sent", False)
            if not creation_time: continue
            if creation_time.tzinfo is None: creation_time = creation_time.replace(tzinfo=timezone.utc)
            
            age = now - creation_time
            channel = guild.get_channel(channel_id)

            if age >= warning_threshold and age < ticket_lifespan and not warning_sent:
                if channel:
                    pings = f"<@{ticket.get('tested_user_id')}> <@{ticket.get('created_by')}>"
                    try:
                        embed = discord.Embed(
                            title="⚠️ Ticket Expiration Warning",
                            description="This ticket will automatically close in **15 minutes**. If you wish to keep it open, use `/exempt`.",
                            color=discord.Color.orange()
                        )
                        set_footer(embed)
                        await channel.send(content=pings, embed=embed)
                        await db_write("UPDATE testing_tickets SET warning_sent = TRUE WHERE channel_id = %s", (channel_id,))
                    except Exception as e:
                        logging.error(f"Failed warning: {e}")

            elif age >= ticket_lifespan:
                if channel:
                    try:
                        await handle_ticket_close(interaction=None, channel_obj=channel)
                    except:
                        try: await channel.delete()
                        except: pass
                
                await db_write("DELETE FROM testing_tickets WHERE channel_id = %s", (channel_id,))
                await db_write("DELETE FROM tickets WHERE channel_id = %s", (channel_id,))

    @tasks.loop(hours=1)
    async def age_tickets_task(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild: return

        all_tickets = await get_all_tickets()
        now = datetime.now(timezone.utc)

        for ticket in all_tickets:
            channel = guild.get_channel(ticket.get("channel_id"))
            creation_time = ticket.get("creation_time")
            if not channel or not creation_time: continue
            
            if creation_time.tzinfo is None: creation_time = creation_time.replace(tzinfo=timezone.utc)
            age = now - creation_time
            
            new_prefix = "🟢"
            if age > timedelta(days=14): new_prefix = "🔴"
            elif age > timedelta(days=7): new_prefix = "🟠"

            if not channel.name.startswith(new_prefix):
                base_name = channel.name.lstrip("🟢🟠🔴｜")
                try:
                    await channel.edit(name=f"{new_prefix}｜{base_name}")
                except: pass

    @tasks.loop(seconds=10)
    async def update_queues_periodically(self):
        """Forces an update of the queue embed every 10 seconds."""
        await self.bot.wait_until_ready()
        for region_key in config.REGION_DATA:
            if 'maps_to' in config.REGION_DATA.get(region_key, {}):
                continue
            
            try:
                await update_queue_display(self.bot, region_key, ping=False)
                await asyncio.sleep(1) 
            except Exception as e:
                logging.error(f"Error in periodic queue update for {region_key}: {e}")

    @tasks.loop(minutes=30)
    async def update_leaderboard_task(self):
        await self.bot.wait_until_ready()
        if self.bot.is_closed(): return
        guild = self.bot.get_guild(config.GUILD_ID)
        if not guild or not (leaderboard_channel := guild.get_channel(config.LEADERBOARD_CHANNEL_ID)): return
        
        monthly_tests = await load_data_from_json("monthly_tests.json", {})
        alltime_tests = await load_data_from_json("alltime_tests.json", {})
        
        sorted_monthly = sorted(monthly_tests.items(), key=lambda item: item[1], reverse=True)[:10]
        sorted_alltime = sorted(alltime_tests.items(), key=lambda item: item[1], reverse=True)[:10]
        
        current_month_name = datetime.now(timezone.utc).strftime('%B')
        description_parts = []
        description_parts.append("## 🏆 All Time Testing Leaderboard")
        alltime_list = [f"**{i+1}.** <@{tester_id}> — **{tests}** tests" for i, (tester_id, tests) in enumerate(sorted_alltime)] or ["*No all-time tests recorded yet.*"]
        description_parts.append("\n".join(alltime_list))
        description_parts.append(f"\n## 🏅 {current_month_name} Testing Leaderboard")
        monthly_list = [f"**{i+1}.** <@{tester_id}> — **{tests}** tests" for i, (tester_id, tests) in enumerate(sorted_monthly)] or ["*No tests recorded yet for this month.*"]
        description_parts.append("\n".join(monthly_list))
        total_monthly_tests = sum(monthly_tests.values())
        if total_monthly_tests > 0:
            description_parts.append(f"\n**Total Tests in {current_month_name}: {total_monthly_tests:,}**")
        final_description = "\n".join(description_parts)

        embed = discord.Embed(description=final_description, color=discord.Color.gold())
        set_footer(embed)

        leaderboard_msg_data = await load_data_from_json("leaderboard_message.json", {})
        msg_id = leaderboard_msg_data.get("id")
        
        message_to_edit = None
        if msg_id:
            try:
                message_to_edit = await leaderboard_channel.fetch_message(msg_id)
            except (discord.NotFound, discord.Forbidden):
                msg_id = None
        try:
            if message_to_edit:
                if not message_to_edit.embeds or message_to_edit.embeds[0].description != embed.description:
                    await message_to_edit.edit(embed=embed)
            else:
                await leaderboard_channel.purge(limit=10)
                new_msg = await leaderboard_channel.send(embed=embed)
                await save_data_to_json("leaderboard_message.json", {"id": new_msg.id})
        except Exception as e:
            logging.error(f"An unexpected error occurred in update_leaderboard_task: {e}")

    @tasks.loop(hours=1)
    async def monthly_rollover_check(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        if now.month != self.last_reset_month:
            logging.info(f"New month detected ({now.strftime('%B')}). Starting automatic end-of-month process.")
            guild = self.bot.get_guild(config.GUILD_ID)
            if not guild: return

            eom_channel = guild.get_channel(config.TESTS_END_OF_THE_MONTH_CHANNEL_ID)
            failed_quota_channel = guild.get_channel(config.FAILED_QUOTA_TESTERS_CHANNEL_ID)
            if not eom_channel:
                logging.warning("EOM channel not configured. Skipping.")
                return

            monthly_tests = await load_data_from_json("monthly_tests.json", {})
            tester_role = guild.get_role(config.TESTER_ROLE_ID)
            all_current_testers = tester_role.members if tester_role else []
            
            tester_ids_to_check = set(monthly_tests.keys())
            for tester in all_current_testers:
                tester_ids_to_check.add(str(tester.id))

            guild_settings = await load_data_from_json("guild_settings.json", {})
            quota = guild_settings.get('tester_quota', config.TESTER_QUOTA)
            logging.info(f"Using a monthly tester quota of {quota} tests.")
            
            exempt_role = guild.get_role(config.QUOTA_EXEMPT_ROLE_ID)
            tester_data = {tid: monthly_tests.get(tid, 0) for tid in tester_ids_to_check}
            sorted_board = sorted(tester_data.items(), key=lambda x: x[1], reverse=True)
            
            prev_month_name = (now.replace(day=1) - timedelta(days=1)).strftime('%B %Y')
            lb_desc_lines = [f"**{i+1}.** <@{tid}> - `{tests}` tests" for i, (tid, tests) in enumerate(sorted_board) if guild.get_member(int(tid))]
            lb_embed = discord.Embed(title=f"Final Leaderboard - {prev_month_name}", description="\n".join(lb_desc_lines) or "No tests recorded.", color=discord.Color.gold())
            await eom_channel.send(embed=lb_embed)

            demoted_testers = []
            for tester_id_str, tests_completed in tester_data.items():
                member = guild.get_member(int(tester_id_str))
                if not member: continue
                is_exempt = exempt_role and exempt_role in member.roles
                if not is_exempt and tests_completed < quota:
                    demoted_testers.append(f"{member.mention} (`{tests_completed}/{quota}`)")
                    roles_to_remove_ids = {config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID}
                    roles_to_remove = [role for role in member.roles if role.id in roles_to_remove_ids]
                    if roles_to_remove:
                        await member.remove_roles(*roles_to_remove, reason="Failed to meet monthly test quota")

            if demoted_testers:
                demote_description = "The following testers did not meet the monthly quota and have been demoted:\n\n" + "\n".join(demoted_testers)
                demote_embed = discord.Embed(title="Quota Demotions", description=demote_description, color=discord.Color.red())
                target_channel = failed_quota_channel or eom_channel
                await target_channel.send(embed=demote_embed)
            else:
                await eom_channel.send(embed=discord.Embed(title="Quota Check", description="All testers met their monthly quota!", color=discord.Color.green()))
            
            await save_data_to_json("monthly_tests.json", {})
            logging.info(f"EOM process complete. Monthly tests reset.")
            self.last_reset_month = now.month

    @delete_expired_tickets.before_loop
    @update_queues_periodically.before_loop
    @update_leaderboard_task.before_loop
    @monthly_rollover_check.before_loop
    async def before_tasks(self):
        await self.bot.wait_until_ready()
        
async def setup(bot: commands.Bot):
    await bot.add_cog(TasksCog(bot))