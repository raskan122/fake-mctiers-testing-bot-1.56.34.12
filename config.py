import discord
from discord.ext import commands
from discord import app_commands, Color, PermissionOverwrite, Interaction
import asyncio
from datetime import datetime, timedelta, timezone
import logging

import config
from utils.database import (
    db_write, get_player_data, is_on_cooldown, is_user_verified, get_ticket_data, 
    load_data_from_json, save_data_to_json, get_master_player_record
)
from utils.helpers import (
    create_ticket, get_uuid_from_ign, get_ign_from_uuid,
    handle_ticket_close, update_queue_display, check_permission,
    create_transcript, get_base_region_key, get_bust_url
)
from utils.embeds import (
    create_profile_embed, create_ticket_user_info_embed, create_stats_embed, set_footer
)
from utils.constants import rank_full_names, tier_points, tier_ranking, high_testing_tiers as ht_roles_tuple
class HelpView(discord.ui.View):
    def __init__(self, interaction_user: discord.Member):
        super().__init__(timeout=180)
        self.interaction_user = interaction_user

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.interaction_user.id:
            await interaction.response.send_message("You cannot interact with this menu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Member Guide", style=discord.ButtonStyle.green)
    async def member_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        description = (
            "Welcome to Test Bot! Here's how to get started:\n\n"
            f"1. **Verify:** Go to {interaction.client.get_channel(config.REQUEST_TEST_CHANNEL_ID).mention} and click `Verify Account` to link your Minecraft account.\n\n"
            "2. **Join Waitlist:** Click `Enter Waitlist` and select your region. You'll receive a role and be pinged when testers are available.\n\n"
            "3. **Join Queue:** When you get pinged, go to the appropriate region channel and use the button to join the active queue.\n\n"
            "**Available Commands:**\n"
            "`/profile user [user]`: View a Discord user's profile.\n"
            "`/profile username [name]`: View a profile by Minecraft name.\n"
            "`/leave`: Leave your current waitlist role or active queue."
        )
        embed = discord.Embed(title="Member Guide", description=description, color=discord.Color.green())
        set_footer(embed)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Tester Guide", style=discord.ButtonStyle.blurple)
    async def tester_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.id in [config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID] for role in interaction.user.roles):
            return await interaction.response.send_message("This guide is only available to testers.", ephemeral=True)
        
        description = (
            "Here's how to use the main testing commands:\n\n"
            "**`/start`**\n"
            "Sets you as an active tester. This opens the queue for your region.\n\n"
            "**`/stop`**\n"
            "Ends your active testing session.\n\n"
            "**`/next`**\n"
            "Pulls the next person from the queue and creates a ticket.\n\n"
            "**`/close [ranking]`**\n"
            "Finalizes the test, assigns the rank, and logs the result.\n\n"
            "**`/skip`**\n"
            "Closes a ticket as 'Discontinued' (no rank assigned).\n\n"
            "**In-Ticket Commands**\n"
            "`/add`, `/remove`: Manage ticket access.\n"
            "`/exempt`: Prevents the 3-day auto-close logic.\n\n"
            "**Ticket Aging**\n"
            "Tickets show 🟢 initially, 🟠 after 7 days, and 🔴 after 14 days.\n\n"
            "**Additional Notes:**\n"
            f"Watch the <#{config.QUEUE_JOIN_CHANNEL_ID}> channel for join notifications."
        )
        embed = discord.Embed(title="Tester Guide", description=description, color=discord.Color.blurple())
        set_footer(embed)
        await interaction.response.edit_message(embed=embed, view=self)
class CommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    forceauth_group = app_commands.Group(name="forceauth", description="Manual account linking commands", guild_ids=[config.GUILD_ID])
    setrank_group = app_commands.Group(name="setrank", description="Rank management commands", guild_ids=[config.GUILD_ID])
    setpeaktier_group = app_commands.Group(name="setpeaktier", description="Peak tier management commands", guild_ids=[config.GUILD_ID])
    profile_group = app_commands.Group(name="profile", description="Lookup a player's profile.", guild_ids=[config.GUILD_ID])
    config_group = app_commands.Group(name="config", description="Server configuration commands.", guild_ids=[config.GUILD_ID])        
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, (app_commands.CheckFailure, discord.errors.InteractionResponded)):
            return
        logging.error(f"Ignoring exception in command '{interaction.command.name if interaction.command else 'Unknown'}':", exc_info=error)
        error_message = "An unexpected error occurred. Please try again later."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)
        except (discord.errors.InteractionResponded, discord.errors.NotFound):
            pass
        except Exception as e:
            logging.error(f"Failed to send error message: {e}")

    async def _region_autocomplete(self, interaction: discord.Interaction, current: str):
        regions = ["na", "eu", "as", "au", "sa", "me", "af"]
        return [app_commands.Choice(name=region.upper(), value=region) for region in regions if current.lower() in region.lower()][:25]

    async def _ranking_autocomplete(self, interaction: discord.Interaction, current: str):
        ranks = [r for r in tier_ranking if r != "Unranked"] + ["Remove Rank"]
        
        return [
            app_commands.Choice(name=r, value=r) 
            for r in ranks if current.lower() in r.lower()
        ][:25]

    async def _peak_tier_autocomplete(self, interaction: discord.Interaction, current: str):
        ranks = [r for r in tier_ranking if r != "Unranked"] + ["Remove Peak Tier"]
        
        return [
            app_commands.Choice(name=r, value=r) 
            for r in ranks if current.lower() in r.lower()
        ][:25]
    
    async def _update_player_rank_data(self, interaction: discord.Interaction, discord_id: int, updates: dict):
        member = interaction.guild.get_member(discord_id)
        if member and updates.get("tier") is not None:
            current_rank_roles = [role for role_id in config.rank_roles_dict.values() if (role := interaction.guild.get_role(role_id)) and role in member.roles]
            if current_rank_roles:
                await member.remove_roles(*current_rank_roles, reason=f"Rank update by {interaction.user}")
            
            if updates["tier"] != "Unranked":
                if new_role_id := config.rank_roles_dict.get(updates["tier"]):
                    if new_role := interaction.guild.get_role(new_role_id):
                        await member.add_roles(new_role, reason=f"Rank update by {interaction.user}")
        
        update_clauses = [f"`{key}` = %s" for key in updates.keys()]
        params = list(updates.values()) + [discord_id]
        await db_write(f"UPDATE tiers SET {', '.join(update_clauses)} WHERE discord_id = %s", tuple(params))
    @app_commands.command(name="help", description="Shows a guide on how to use the tierlist commands.")
    @app_commands.guilds(config.GUILD_ID)
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="TestingUHC Help", 
            description="Please select a guide to view instructions for members or testers.", 
            color=discord.Color.blurple()
        )
        set_footer(embed)
        await interaction.response.send_message(embed=embed, view=HelpView(interaction.user), ephemeral=True)
    @config_group.command(name="quota", description="Set the monthly test quota for testers.")
    @app_commands.describe(tests="The number of tests required per month.")
    async def config_quota(self, interaction: discord.Interaction, tests: app_commands.Range[int, 1, 100]):
        if not await check_permission(interaction, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        guild_settings = await load_data_from_json("guild_settings.json", {})
        guild_settings['tester_quota'] = tests
        await save_data_to_json("guild_settings.json", guild_settings)

        await interaction.followup.send(f"✅ The monthly tester quota has been successfully updated to **{tests}** tests.", ephemeral=True)
    @app_commands.command(name="start", description="Put yourself active as a tester.")
    @app_commands.describe(region="Your region (only needed if you don't have a region role assigned)")
    @app_commands.choices(region=[
        app_commands.Choice(name="EU", value="eu"),
        app_commands.Choice(name="NA", value="na"),
        app_commands.Choice(name="AS/AU", value="as"),
    ])
    @app_commands.guilds(config.GUILD_ID)
    async def start(self, interaction: Interaction, region: app_commands.Choice[str] = None):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        # Auto-detect region from role; fall back to the optional parameter
        user_region = None
        for region_key, data in config.REGION_DATA.items():
            if 'maps_to' in data: continue
            if interaction.user.get_role(data.get("region_role_id")):
                user_region = region_key
                break

        if not user_region:
            if region:
                user_region = region.value
            else:
                return await interaction.followup.send(
                    "You don't have a region role. Please pick a region using the `region` option when running `/start`.",
                    ephemeral=True
                )

        active_testers = await load_data_from_json("active_testers.json", {})
        active_testers.setdefault(user_region, [])
        
        if interaction.user.id in active_testers[user_region]:
            return await interaction.followup.send("You are already active.", ephemeral=True)

        active_testers[user_region].append(interaction.user.id)
        await save_data_to_json("active_testers.json", active_testers)
        
        await interaction.followup.send(f"You are now active for {user_region.upper()}.", ephemeral=True)
        do_ping = len(active_testers[user_region]) == 1
        await update_queue_display(self.bot, user_region, ping=do_ping)

    @app_commands.command(name="stop", description="Put yourself inactive as a tester.")
    @app_commands.guilds(config.GUILD_ID)
    async def stop(self, interaction: Interaction):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        active_testers = await load_data_from_json("active_testers.json", {})
        user_was_active = False
        modified_region = None

        for region, testers in active_testers.items():
            if interaction.user.id in testers:
                testers.remove(interaction.user.id)
                user_was_active = True
                modified_region = region
                if not testers:
                    queue_data = await load_data_from_json("queue_data.json", {})
                    queue_data[region] = [] 
                    await save_data_to_json("queue_data.json", queue_data)
                break

        if not user_was_active:
            return await interaction.followup.send("You were not active.", ephemeral=True)
        
        await save_data_to_json("active_testers.json", active_testers)
        await interaction.followup.send("You are now inactive.", ephemeral=True)
        await update_queue_display(self.bot, modified_region, ping=False)

    @app_commands.command(name="forcetest", description="Force create a testing ticket with a user")
    @app_commands.describe(user="Select the user to forcefully test", tester="The tester to assign to the user (Optional)")
    @app_commands.guilds(config.GUILD_ID)
    async def forcetest(self, interaction: discord.Interaction, user: discord.Member, tester: discord.Member = None):
        if not await check_permission(interaction,config.REGULATOR_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        player_data = await get_player_data(user.id)
        if not player_data:
            return await interaction.followup.send("This user is not verified/ranked.", ephemeral=True)

        user_tier = player_data.get('tier', 'Unranked')
        is_ht = user_tier in config.high_testing_tiers
        test_label = "High Tier Test" if is_ht else "Evaluation Test"

        assigned_tester = tester or interaction.user
        
        ticket_channel, error_msg = await create_ticket(interaction.guild, user, assigned_tester, test_label)

        if error_msg:
            return await interaction.followup.send(f"Failed to create ticket: {error_msg}", ephemeral=True)

        last_test_date = player_data.get('last_time_tested')
        last_test_str = f"<t:{int(last_test_date.timestamp())}:R>" if last_test_date else "N/A"

        info_embed = await create_ticket_user_info_embed(user, player_data, last_test_str)
        
        embeds_to_send = [info_embed]

        if not is_ht:
            commenced_embed = discord.Embed(
                title="Test Commenced",
                description=f"{user.mention} is being tested by {assigned_tester.mention}.",
                color=Color.blurple()
            )
            set_footer(commenced_embed)
            embeds_to_send.append(commenced_embed)
    
        initial_msg = await ticket_channel.send(
            content=f"{user.mention} {assigned_tester.mention}",
            embeds=embeds_to_send
        )
        
        try:
            await initial_msg.pin()
        except:
            pass

        await interaction.followup.send(f"Forced {test_label} created: {ticket_channel.mention}", ephemeral=True)

    @app_commands.command(name="next", description="Open a ticket with the next person in queue")
    @app_commands.guilds(config.GUILD_ID)
    async def next(self, interaction: discord.Interaction):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        tester_region = None
        for region_key, data in config.REGION_DATA.items():
            if 'maps_to' in data: continue
            if role := interaction.guild.get_role(data.get("region_role_id")):
                if role in interaction.user.roles:
                    tester_region = region_key
                    break
        
        if not tester_region:
            return await interaction.followup.send("You do not have a region role assigned.", ephemeral=True)

        active_testers = await load_data_from_json("active_testers.json", {})
        if str(interaction.user.id) not in active_testers.get(tester_region, []):
            if interaction.user.id not in active_testers.get(tester_region, []):
                 return await interaction.followup.send(f"You are not an active tester for {tester_region.upper()}.", ephemeral=True)

        queue_data = await load_data_from_json("queue_data.json", {})
        queue = queue_data.get(tester_region, [])
        if not queue:
            return await interaction.followup.send(f"The queue for {tester_region.upper()} is empty.", ephemeral=True)
        
        user_id = queue.pop(0)
        await save_data_to_json("queue_data.json", queue_data)
        
        user_to_test = interaction.guild.get_member(user_id)
        if not user_to_test:
            await update_queue_display(self.bot, tester_region, ping=False)
            return await interaction.followup.send(f"User ID {user_id} left the server. They have been removed.", ephemeral=True)
        waitlist_role_id = config.REGION_DATA[tester_region].get("waitlist_role_id")
        if waitlist_role_id:
            w_role = interaction.guild.get_role(waitlist_role_id)
            if w_role and w_role in user_to_test.roles:
                await user_to_test.remove_roles(w_role)
        ticket_channel, error_msg = await create_ticket(interaction.guild, user_to_test, interaction.user, "Standard Test")

        if error_msg:
            queue.insert(0, user_id) 
            await save_data_to_json("queue_data.json", queue_data)
            await interaction.followup.send(f"Failed to create ticket: {error_msg}", ephemeral=True)
            return
            
        await update_queue_display(self.bot, tester_region, ping=False)
        
        player_data = await get_player_data(user_to_test.id) or {}
        last_test_date = player_data.get('last_time_tested')
        last_test_str = f"<t:{int(last_test_date.timestamp())}:R>" if last_test_date else "N/A"
        
        info_embed = await create_ticket_user_info_embed(user_to_test, player_data, last_test_str)

        commenced_embed = discord.Embed(
            title="Test Commenced",
            description=f"{user_to_test.mention} is being tested by {interaction.user.mention}.",
            color=Color.blurple()
        )
        set_footer(commenced_embed)

        initial_msg = await ticket_channel.send(
            content=f"{user_to_test.mention} {interaction.user.mention}",
            embeds=[info_embed, commenced_embed]
        )
        try:
            await initial_msg.pin()
        except:
            pass
        await interaction.followup.send(f"Ticket created: {ticket_channel.mention}", ephemeral=True)

    @app_commands.command(name="add", description="Add a user to a ticket.")
    @app_commands.describe(user="Select the member to add to the ticket")
    @app_commands.guilds(config.GUILD_ID)
    async def add(self, interaction: discord.Interaction, user: discord.Member):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.MODERATOR_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await get_ticket_data(interaction.channel.id):
            embed = discord.Embed(
                title="Could not recognize channel as testing ticket."
            )
            set_footer(embed)
            return await interaction.followup.send(embed=embed)
        await interaction.channel.set_permissions(user, view_channel=True)
        embed = discord.Embed(title="User Added", description=f"{(user.global_name)} has been added to this ticket.", color=Color.green())
        set_footer(embed)
        await interaction.channel.send(embed=embed)
        await interaction.followup.send(f"{user.mention} has been added to the ticket.", ephemeral=True)

    @app_commands.command(name="remove", description="Remove a user from a ticket.")
    @app_commands.describe(user="Select the member to remove from the ticket")
    @app_commands.guilds(config.GUILD_ID)
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.MODERATOR_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await get_ticket_data(interaction.channel.id):
            embed = discord.Embed(
                title="Could not recognize channel as testing ticket."
            )
            set_footer(embed)
            return await interaction.followup.send(embed=embed)
        await interaction.channel.set_permissions(user, overwrite=None) 
        embed = discord.Embed(title="User Removed", description=f"{(user.global_name)} has been removed from this ticket.", color=Color.red())
        set_footer(embed)
        await interaction.channel.send(embed=embed)
        await interaction.followup.send(f"{user.mention} has been removed from the ticket", ephemeral=True)

    @app_commands.command(name="addspec", description="Add a spectator to a ticket (view only).")
    @app_commands.describe(user="The member to add as a spectator")
    @app_commands.guilds(config.GUILD_ID)
    async def addspec(self, interaction: discord.Interaction, user: discord.Member):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.MODERATOR_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await get_ticket_data(interaction.channel.id):
            embed = discord.Embed(
                title="Could not recognize channel as testing ticket."
            )
            set_footer(embed)
            return await interaction.followup.send(embed=embed)
        overwrite = PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False)
        await interaction.channel.set_permissions(user, overwrite=overwrite)
        
        embed = discord.Embed(
            title="Spectator Added",
            description=f"{user.mention} has been added as a spectator.",
            color=Color.blue()
        )
        set_footer(embed)
        await interaction.channel.send(embed=embed)
        await interaction.followup.send(f"Added {user.mention} as a spectator.", ephemeral=True)

    @app_commands.command(name="lock", description="Toggle lock on the ticket for the testee.")
    @app_commands.guilds(config.GUILD_ID)
    async def lock(self, interaction: discord.Interaction):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.MODERATOR_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        ticket_data = await get_ticket_data(interaction.channel.id)
        if not ticket_data:
            embed = discord.Embed(
                title="Could not recognize channel as testing ticket."
            )
            set_footer(embed)
            return await interaction.followup.send(embed=embed)
        testee = interaction.guild.get_member(ticket_data['tested_user_id'])
        if not testee:
            return await interaction.followup.send("Could not find the tested user in the server.", ephemeral=True)
        current_perms = interaction.channel.overwrites_for(testee)
        new_state = not current_perms.send_messages
        
        current_perms.send_messages = new_state
        current_perms.add_reactions = new_state
        await interaction.channel.set_permissions(testee, overwrite=current_perms)
        
        status_text = "unlocked" if new_state else "locked"
        embed = discord.Embed(
            description=f"This ticket has been **{status_text}** for {testee.mention}.",
            color=Color.orange() if not new_state else Color.green()
        )
        set_footer(embed)
        await interaction.channel.send(embed=embed)
        await interaction.followup.send(f"Ticket {status_text}.", ephemeral=True)

    @app_commands.command(name="rename", description="Rename the current ticket.")
    @app_commands.describe(name="The new name for the ticket channel")
    @app_commands.guilds(config.GUILD_ID)
    async def rename(self, interaction: discord.Interaction, name: str):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.MODERATOR_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        if not await get_ticket_data(interaction.channel.id):
            embed = discord.Embed(
                title="Could not recognize channel as testing ticket."
            )
            set_footer(embed)
            return await interaction.followup.send(embed=embed)
        try:
            prefix = ""
            if "🟢｜" in interaction.channel.name: prefix = "🟢｜"
            elif "🟠｜" in interaction.channel.name: prefix = "🟠｜"
            elif "🔴｜" in interaction.channel.name: prefix = "🔴｜"
            
            new_name = f"{prefix}{name.lower().replace(' ', '-')}"
            await interaction.channel.edit(name=new_name)
            await interaction.followup.send(f"Ticket renamed to `{new_name}`.", ephemeral=True)
        except Exception as e:
            logging.error(f"Rename error: {e}")
            await interaction.followup.send("Failed to rename channel. Ensure I have permissions.", ephemeral=True)

    @app_commands.command(name="tierwipe", description="Reset a player's rank data and remove roles.")
    @app_commands.describe(player="The player to wipe", reason="Reason for the wipe")
    @app_commands.guilds(config.GUILD_ID)
    async def tierwipe(self, interaction: discord.Interaction, player: discord.Member, reason: str):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await is_user_verified(player.id):
            return await interaction.followup.send("This user is not verified in the database.", ephemeral=True)
        await db_write(
            "UPDATE tiers SET tier = 'Unranked', peak_tier = 'Unranked', points = 0 WHERE discord_id = %s", 
            (player.id,)
        )
        all_rank_role_ids = set(config.rank_roles_dict.values())
        roles_to_remove = [role for role in player.roles if role.id in all_rank_role_ids]
        
        if roles_to_remove:
            await player.remove_roles(*roles_to_remove, reason=f"Tierwipe: {reason}")

        embed = discord.Embed(
            title="Tier Wipe Executed",
            description=f"{player.mention}'s stats have been reset to Unranked.",
            color=Color.red()
        )
        embed.add_field(name="Reason", value=reason)
        set_footer(embed)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="close", description="Close a ticket")
    @app_commands.describe(
        ranking="Attained Rank",
        score="The fight score (e.g., 5-2).",
        description="A detailed description of the user's performance."
    )
    @app_commands.choices(ranking=[
        app_commands.Choice(name="HT1", value="HT1"),
        app_commands.Choice(name="LT1", value="LT1"),
        app_commands.Choice(name="HT2", value="HT2"),
        app_commands.Choice(name="LT2", value="LT2"),
        app_commands.Choice(name="HT3", value="HT3"),
        app_commands.Choice(name="LT3", value="LT3"),
        app_commands.Choice(name="HT4", value="HT4"),
        app_commands.Choice(name="LT4", value="LT4"),
        app_commands.Choice(name="HT5", value="HT5"),
        app_commands.Choice(name="LT5", value="LT5"),
        app_commands.Choice(name="Discontinued", value="discontinued"),
    ])
    @app_commands.guilds(config.GUILD_ID)
    async def close(self, interaction: discord.Interaction, ranking: app_commands.Choice[str], score: str, description: str):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        ranking_value = ranking.value
        ticket_data = await get_ticket_data(interaction.channel.id)
        if not ticket_data:
            return await interaction.followup.send("This is not a valid ticket channel.", ephemeral=True)
        
        if ranking_value.lower() == "discontinued":
            await interaction.channel.send(embed=discord.Embed(title="Test Discontinued", color=Color.blurple()))
            await db_write("DELETE FROM testing_tickets WHERE channel_id = %s", (interaction.channel.id,))
            await handle_ticket_close(interaction)
            return

        tested_user_id = ticket_data['tested_user_id']
        player_data = await get_player_data(tested_user_id)
        if not player_data:
            return await interaction.followup.send("Could not find player data for the tested user.", ephemeral=True)

        previous_rank_raw = player_data.get('tier', 'Unranked')
        new_points = tier_points.get(ranking_value, 0)
        current_peak = player_data.get('peak_tier', 'Unranked')
        
        new_peak = current_peak
        if ranking_value in tier_ranking and (current_peak == 'Unranked' or tier_ranking.index(ranking_value) < tier_ranking.index(current_peak)):
            new_peak = ranking_value

        await db_write(
            "UPDATE tiers SET tier = %s, peak_tier = %s, points = %s, last_time_tested = %s WHERE discord_id = %s",
            (ranking_value, new_peak, new_points, datetime.now(timezone.utc), tested_user_id)
        )

        await self._update_player_rank_data(interaction, tested_user_id, {"tier": ranking_value})

        tested_member = interaction.guild.get_member(tested_user_id)

        cooldown_days = 30 if tested_member and tested_member.get_role(config.BOOSTER_ROLE_ID) else (30 if ranking_value in {"HT1", "LT1", "HT2", "LT2", "HT3"} else 30)
        expires_at = datetime.now(timezone.utc) + timedelta(days=cooldown_days)
        await db_write("INSERT INTO cooldowns (discord_id, expires_at) VALUES (%s, %s) ON DUPLICATE KEY UPDATE expires_at = %s", (tested_user_id, expires_at, expires_at))

        for file in ["monthly_tests.json", "alltime_tests.json"]:
            data = await load_data_from_json(file, {})
            data[str(interaction.user.id)] = data.get(str(interaction.user.id), 0) + 1
            await save_data_to_json(file, data)
        
        tested_user_obj = tested_member or await self.bot.fetch_user(tested_user_id)
        user_mention = f"<@{tested_user_id}>"
        ign = player_data.get('minecraft_username', 'N/A')

        result_embed = discord.Embed(color=Color.from_rgb(255, 45, 45))
        result_embed.set_author(name=f"{(tested_user_obj.global_name or tested_user_obj.name)}'s Test Results 🏆", icon_url=tested_user_obj.display_avatar.url if tested_user_obj else None)
        result_embed.add_field(name="Tester:", value=interaction.user.mention, inline=False)
        result_embed.add_field(name="Region:", value=(player_data.get('region') or 'N/A').upper(), inline=False)
        result_embed.add_field(name="Username:", value=ign, inline=False)
        result_embed.add_field(name="Previous Rank:", value=rank_full_names.get(previous_rank_raw, "Unranked"), inline=False)
        result_embed.add_field(name="Rank Earned:", value=rank_full_names.get(ranking_value, "Unranked"), inline=False)
        if bust_url := get_bust_url(player_data.get('uuid')): result_embed.set_thumbnail(url=bust_url)

        res_msg = None
        results_channel = self.bot.get_channel(config.RESULTS_CHANNEL_ID)
        if results_channel:
            res_msg = await results_channel.send(content=user_mention, embed=result_embed)
            for emoji in ["👑", "🥳", "😱", "😭", "😂", "💀"]:
                try: await res_msg.add_reaction(emoji)
                except: pass

        report_channel = self.bot.get_channel(config.TESTER_REPORT_CHANNEL_ID)
        if report_channel:
            report_embed = result_embed.copy()
            report_embed.set_author(name=f"{(tested_user_obj.global_name or tested_user_obj.name)}'s Test Report")
            report_embed.add_field(name="Score", value=score, inline=False)
            report_embed.description = f"```{description}```"
            if res_msg: report_embed.add_field(name="Result Link", value=f"[Jump to Message]({res_msg.jump_url})", inline=False)
            await report_channel.send(embed=report_embed)

        ticket_embed = result_embed.copy()
        ticket_embed.description = "Ticket Closing in 5 seconds. Results processed successfully!"
        await interaction.channel.send(embed=ticket_embed)
        
        await db_write("DELETE FROM testing_tickets WHERE channel_id = %s", (interaction.channel.id,))
        await interaction.followup.send("Results processed successfully.", ephemeral=True)
        await handle_ticket_close(interaction, with_results=True, tester=interaction.user, tested_user_mention=user_mention, rank_name=rank_full_names.get(ranking_value))

    @app_commands.command(name="skip", description="Close a ticket with a discontinuance result.")
    @app_commands.guilds(config.GUILD_ID)
    async def skip(self, interaction: discord.Interaction):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await get_ticket_data(interaction.channel.id):
            return await interaction.followup.send("This is not a ticket channel.", ephemeral=True)
        
        await interaction.channel.send(embed=discord.Embed(title="Test Discontinued", description="Test has been discontinued" , color=Color.blurple()))
        await db_write("DELETE FROM testing_tickets WHERE channel_id = %s", (interaction.channel.id,))
        await interaction.followup.send("Test has been discontinued. Closing in 5 seconds", ephemeral=True)
        await handle_ticket_close(interaction)

    @app_commands.command(name="leave", description="Leave the waitlist or queue.")
    @app_commands.guilds(config.GUILD_ID)
    async def leave(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        queue_data = await load_data_from_json("queue_data.json", {})
        
        user_removed = False
        user_id = interaction.user.id

        for region, queue in queue_data.items():
            if user_id in queue:
                queue.remove(user_id)
                user_removed = True
            elif str(user_id) in queue:
                queue.remove(str(user_id))
                user_removed = True
            
            if user_removed:
                await save_data_to_json("queue_data.json", queue_data)
                await update_queue_display(self.bot, region, ping=False)
                return await interaction.followup.send(f"You have been removed from the {region.upper()} queue.", ephemeral=True)

        roles_to_remove = [
            role for role_id in (config.NA_WAITLIST_ROLE_ID, config.EU_WAITLIST_ROLE_ID, config.AS_AU_WAITLIST_ROLE_ID)
            if (role := interaction.guild.get_role(role_id)) and role in interaction.user.roles
        ]
        
        if roles_to_remove:
            await interaction.user.remove_roles(*roles_to_remove)
            return await interaction.followup.send("You have been removed from the waitlist.", ephemeral=True)
        
        await interaction.followup.send("You are not in any queue or waitlist.", ephemeral=True)

    @app_commands.command(name="exempt", description="Exempt a ticket from Auto-Close.")
    @app_commands.guilds(config.GUILD_ID)
    async def exempt(self, interaction: discord.Interaction):
        if not await check_permission(interaction, config.TESTER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        await db_write("INSERT INTO tickets (channel_id, is_exempt) VALUES (%s, TRUE) ON DUPLICATE KEY UPDATE is_exempt = TRUE", (interaction.channel.id,))
        await interaction.followup.send("The ticket has been marked as exempt.", ephemeral=True)
        
    @app_commands.command(name="unexempt", description="Unexempt a ticket from Auto-Close.")
    @app_commands.guilds(config.GUILD_ID)
    async def unexempt(self, interaction: discord.Interaction):
        if not await check_permission(interaction, config.TESTER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        await db_write("UPDATE tickets SET is_exempt = FALSE WHERE channel_id = %s", (interaction.channel.id,))
        await interaction.followup.send("The ticket has been marked as unexempt.", ephemeral=True)

    @app_commands.command(name="stats", description="Check the tester stats of a member.")
    @app_commands.describe(member="The member to get tester stats of. Defaults to yourself.")
    @app_commands.guilds(config.GUILD_ID)
    async def stats(self, interaction: Interaction, member: discord.Member = None):
        if not await check_permission(interaction, config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID, config.MODERATOR_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        target_member = member or interaction.user

        player_data = await get_player_data(target_member.id)
        if not player_data:
            return await interaction.followup.send(f"{target_member.mention} does not have a verified Minecraft account.", ephemeral=True)
        
        user_region = "N/A"
        for region_key, data in config.REGION_DATA.items():
            if 'maps_to' in data: continue
            role_id = data.get("region_role_id")
            if role_id and target_member.get_role(role_id):
                user_region = region_key
                break

        monthly_tests_data = await load_data_from_json("monthly_tests.json", {})
        alltime_tests_data = await load_data_from_json("alltime_tests.json", {})

        monthly_count = monthly_tests_data.get(str(target_member.id), 0)
        alltime_count = alltime_tests_data.get(str(target_member.id), 0)

        embed = create_stats_embed(
            member=target_member,
            ign=player_data.get('minecraft_username', 'N/A'),
            uuid=player_data.get('uuid'),
            region=user_region,
            monthly=monthly_count,
            all_time=alltime_count
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @profile_group.command(name="user", description="Lookup a discord user's profile")
    @app_commands.describe(user="User to lookup")
    async def profile_user(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.defer(ephemeral=True)
        player_data = await get_player_data(user.id)
        if not player_data:
            return await interaction.followup.send(f"{user.mention} is not ranked.", ephemeral=True)
        
        embed = await create_profile_embed(player_data, discord_user=user)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @profile_group.command(name="username", description="Lookup a player's profile by username")
    @app_commands.describe(username="Username to lookup")
    async def profile_username(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        player_data = await get_player_data(username, by_ign=True)
        if not player_data:
            return await interaction.followup.send(f"Could not find a player named `{username}`.", ephemeral=True)

        user = None
        try:
            user = await self.bot.fetch_user(player_data['discord_id'])
        except discord.NotFound:
            pass
        
        embed = await create_profile_embed(player_data, discord_user=user)
        await interaction.followup.send(embed=embed, ephemeral=True)
        
    @app_commands.command(name="addtester", description="Add tester")
    @app_commands.describe(member="The member to designate as a tester.", region="The region to assign the tester to.")
    @app_commands.choices(region=[
        app_commands.Choice(name="EU", value="eu"),
        app_commands.Choice(name="NA", value="na"),
        app_commands.Choice(name="AS", value="as")
    ])
    @app_commands.guilds(config.GUILD_ID)
    async def addtester(self, interaction: discord.Interaction, member: discord.Member, region: app_commands.Choice[str]):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        region_data = config.REGION_DATA.get(region.value)
        if not region_data: return await interaction.followup.send("Region data not found.", ephemeral=True)

        roles_to_add_ids = [config.TESTER_ROLE_ID, region_data.get("region_role_id")]
        roles_to_add = [role for role_id in roles_to_add_ids if (role := interaction.guild.get_role(role_id))]
            
        if not roles_to_add: return await interaction.followup.send(f"Could not find required roles.", ephemeral=True)
        
        await member.add_roles(*roles_to_add, reason=f"Added as a tester by {interaction.user}")
        await interaction.followup.send(f"{member.mention} has been assigned the Tester role and {region.name} region role.", ephemeral=True)
        
    @app_commands.command(name="removetester", description="Remove tester")
    @app_commands.describe(member="Select the tester to remove their permission")
    @app_commands.guilds(config.GUILD_ID)
    async def removetester(self, interaction: discord.Interaction, member: discord.Member):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        
        roles_to_remove_ids = {config.TESTER_ROLE_ID, config.SENIOR_TESTER_ROLE_ID, config.NA_REGION_ROLE_ID, config.EU_REGION_ROLE_ID, config.AS_AU_REGION_ROLE_ID}
        roles_to_remove = [role for role in member.roles if role.id in roles_to_remove_ids]

        if not roles_to_remove: return await interaction.followup.send(f"{member.mention} does not have any tester roles.", ephemeral=True)
        await member.remove_roles(*roles_to_remove, reason=f"Removed as a tester by {interaction.user}")
        await interaction.followup.send(f"{member.mention} has been removed from all tester roles.", ephemeral=True)

    @app_commands.command(name="stoptester", description="Remove a tester from the active queue")
    @app_commands.describe(member="Select the tester to forcefully stop them from testing")
    @app_commands.guilds(config.GUILD_ID)
    async def stoptester(self, interaction: discord.Interaction, member: discord.Member):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        active_testers = await load_data_from_json("active_testers.json", {})
        
        modified_region = None
        for region, testers in active_testers.items():
            if member.id in testers:
                testers.remove(member.id)
                modified_region = region
                break

        if modified_region:
            await save_data_to_json("active_testers.json", active_testers)
            await interaction.followup.send(f"Forcefully stopped {member.mention}.", ephemeral=True)
            await update_queue_display(self.bot, modified_region, ping=False)
        else:
            await interaction.followup.send(f"{member.mention} was not an active tester.", ephemeral=True)

    @app_commands.command(name="cooldownreset", description="Reset a user's cooldown.")
    @app_commands.describe(user="Select which user to cooldown reset.", reason="The reason for cooldown reset.")
    @app_commands.guilds(config.GUILD_ID)
    async def cooldownreset(self, interaction: discord.Interaction, user: discord.User, reason: str):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        await db_write("DELETE FROM cooldowns WHERE discord_id = %s", (user.id,))
        embed = discord.Embed(description=f"{user.mention}'s cooldown has been **reset**.\n**Reason:** {reason}", color=Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="cooldownset", description="Set a custom cooldown duration for a user.")
    @app_commands.describe(user="The user to modify", days="Number of days for the cooldown", reason="Reason for setting")
    @app_commands.guilds(config.GUILD_ID)
    async def cooldownset(self, interaction: discord.Interaction, user: discord.User, days: int, reason: str):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await get_player_data(user.id):
            return await interaction.followup.send(f"❌ {user.mention} is not verified/ranked in the database. You cannot set a cooldown for them.", ephemeral=True)

        if days < 0:
            return await interaction.followup.send("Cooldown cannot be negative.", ephemeral=True)

        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        await db_write("INSERT INTO cooldowns (discord_id, expires_at) VALUES (%s, %s) ON DUPLICATE KEY UPDATE expires_at = %s", (user.id, expires_at, expires_at))
        
        embed = discord.Embed(description=f"{user.mention}'s cooldown is now **{days} days**.\n**Reason:** {reason}", color=Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)          
    @app_commands.command(name="updatename", description="Update a player's Minecraft username.")
    @app_commands.describe(user="The user to change the name", new_name="The player's *new* Minecraft Username")
    @app_commands.guilds(config.GUILD_ID)
    async def updatename(self, interaction: discord.Interaction, user: discord.User, new_name: str):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)
        new_uuid = await get_uuid_from_ign(new_name)
        if not new_uuid:
            return await interaction.followup.send(f"Could not find a Minecraft account for `{new_name}`.", ephemeral=True)
    
        await db_write("UPDATE players SET minecraft_username = %s, uuid = %s WHERE discord_id = %s", (new_name, new_uuid, user.id))
        await db_write("UPDATE tiers SET minecraft_username = %s, uuid = %s WHERE discord_id = %s", (new_name, new_uuid, user.id))
            
        await interaction.followup.send(f"Updated <@{user.id}>'s account to **{new_name}**.", ephemeral=True)

    @forceauth_group.command(name="set", description="Manually link a player's account.")
    @app_commands.describe(user_id="The Discord User ID to link", username="The player's Minecraft Username")
    async def forceauth_set(self, interaction: discord.Interaction, user_id: str, username: str):
        if not await check_permission(interaction, config.MANAGER_ROLE_ID): return
        await interaction.response.defer()

        try:
            target_id = int(user_id)
        except ValueError:
            return await interaction.followup.send("Invalid Discord User ID provided.", ephemeral=True)

        uuid = await get_uuid_from_ign(username)
        if not uuid: return await interaction.followup.send(f"Could not find a Minecraft account for `{username}`.", ephemeral=True)
        
        await db_write("INSERT INTO players (discord_id, uuid, minecraft_username) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE uuid = VALUES(uuid), minecraft_username = VALUES(minecraft_username)",
                 (target_id, uuid, username))
        await db_write("INSERT INTO tiers (discord_id, uuid, minecraft_username) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE uuid = VALUES(uuid), minecraft_username = VALUES(minecraft_username)",
                 (target_id, uuid, username))
        await interaction.followup.send(f"Successfully linked <@{target_id}> to `{username}`.")

    @forceauth_group.command(name="unlink", description="Manually unlink a player's account by Discord ID or Minecraft name.")
    @app_commands.describe(identifier="The Discord User ID, Minecraft Username, or UUID to unlink")
    async def forceauth_unlink(self, interaction: discord.Interaction, identifier: str):
        if not await check_permission(interaction, config.MANAGER_ROLE_ID): return
        await interaction.response.defer()

        player_data = await get_master_player_record(identifier)
        if not player_data:
            player_data = await get_master_player_record(identifier, by_ign=True)
        if not player_data:
            player_data = await get_master_player_record(identifier, by_uuid=True)

        if not player_data:
            return await interaction.followup.send(f"Could not find a linked account for `{identifier}`.", ephemeral=True)
        
        discord_id_to_unlink = player_data['discord_id']
        ign = player_data.get('minecraft_username', 'Unknown')

        await db_write("DELETE FROM players WHERE discord_id = %s", (discord_id_to_unlink,))
        await db_write("DELETE FROM tiers WHERE discord_id = %s", (discord_id_to_unlink,))
        await db_write("DELETE FROM cooldowns WHERE discord_id = %s", (discord_id_to_unlink,))
        
        await interaction.followup.send(f"Successfully unlinked `{ign}` (Discord ID: `{discord_id_to_unlink}`).")

    async def _setrank_logic(self, interaction: discord.Interaction, discord_id: int, name_str: str, ranking: str, retired: bool, region: str | None):
        new_rank = "Unranked" if ranking == "Remove Rank" else ranking
        if retired and new_rank not in ("HT1", "LT1", "HT2", "LT2"):
            return await interaction.followup.send("❌ Users can only be marked as retired if their rank is LT2 or higher.", ephemeral=True)
        
        new_points = tier_points.get(new_rank, 0)
        player_data = await get_player_data(discord_id) or {}
        
        updates = {"tier": new_rank, "points": new_points, "is_retired": retired}
        if region: updates["region"] = region.lower()
        
        current_peak = player_data.get("peak_tier", "Unranked")
        new_peak = current_peak
        if new_rank != "Unranked" and (current_peak == "Unranked" or tier_ranking.index(new_rank) < tier_ranking.index(current_peak)):
            new_peak = new_rank
        updates["peak_tier"] = new_peak

        await self._update_player_rank_data(interaction, discord_id, updates)
        
        embed = discord.Embed(
            title="Rank Updated",
            description=f"Changed {name_str}'s rank to **{new_rank}**.", 
            color=Color.blurple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setrank_group.command(name="user", description="Update a discord user's rank")
    @app_commands.describe(user="The user to update", ranking="New rank", retired="Set retired status", region="Set player region")
    @app_commands.autocomplete(ranking=_ranking_autocomplete, region=_region_autocomplete)
    async def setrank_user(self, interaction: discord.Interaction, user: discord.User, ranking: str, retired: bool = False, region: str = None):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await get_master_player_record(user.id): 
            return await interaction.followup.send(f"{user.mention} does not have a linked account.", ephemeral=True)
        await self._setrank_logic(interaction, user.id, user.mention, ranking, retired, region)

    @setrank_group.command(name="username", description="Update a player's rank by username")
    @app_commands.describe(username="Minecraft username", ranking="New rank", retired="Set retired status", region="Set player region")
    @app_commands.autocomplete(ranking=_ranking_autocomplete, region=_region_autocomplete)
    async def setrank_username(self, interaction: discord.Interaction, username: str, ranking: str, retired: bool = False, region: str = None):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        player_data = await get_master_player_record(username, by_ign=True)
        if not player_data: return await interaction.followup.send(f"Player `{username}` not found.", ephemeral=True)
        await self._setrank_logic(interaction, player_data['discord_id'], f"`{username}`", ranking, retired, region)
        
    async def _setpeaktier_logic(self, interaction: discord.Interaction, discord_id: int, name_str: str, tier: str):
        new_peak_tier = "Unranked" if tier == "Remove Peak Tier" else tier
        await db_write("UPDATE tiers SET peak_tier = %s WHERE discord_id = %s", (new_peak_tier, discord_id))
        embed = discord.Embed(
            title="Peak Tier Updated",
            description=f"Changed {name_str}'s peak tier to **{new_peak_tier}**.", 
            color=Color.blurple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setpeaktier_group.command(name="user", description="Update a discord user's peak rank")
    @app_commands.describe(user="The user to update", tier="Peak Tier")
    @app_commands.autocomplete(tier=_peak_tier_autocomplete)
    async def setpeaktier_user(self, interaction: discord.Interaction, user: discord.User, tier: str):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        if not await get_master_player_record(user.id): 
            return await interaction.followup.send(f"{user.mention} does not have a linked account.", ephemeral=True)
        await self._setpeaktier_logic(interaction, user.id, user.mention, tier)

    @setpeaktier_group.command(name="username", description="Update a player's peak rank by username")
    @app_commands.describe(username="The Minecraft username to update", tier="Peak Tier")
    @app_commands.autocomplete(tier=_peak_tier_autocomplete)
    async def setpeaktier_username(self, interaction: discord.Interaction, username: str, tier: str):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer(ephemeral=True)

        player_data = await get_master_player_record(username, by_ign=True)
        if not player_data: return await interaction.followup.send(f"Player `{username}` not found.", ephemeral=True)
        await self._setpeaktier_logic(interaction, player_data['discord_id'], f"`{username}`", tier)

    @app_commands.command(name="tiertransfer", description="Transfer all tiers from one player to another.")
    @app_commands.describe(source="UUID or IGN of source", target="UUID or IGN of target", reason="Reason for transfer")
    @app_commands.guilds(config.GUILD_ID)
    async def tiertransfer(self, interaction: discord.Interaction, source: str, target: str, reason: str):
        if not await check_permission(interaction, config.REGULATOR_ROLE_ID, config.MANAGER_ROLE_ID): return
        await interaction.response.defer()
        
        source_data = await get_player_data(source, by_ign=True) or await get_player_data(source, by_uuid=True)
        target_data = await get_player_data(target, by_ign=True) or await get_player_data(target, by_uuid=True)
        
        if not source_data: return await interaction.followup.send("Source player not found in database.", ephemeral=True)
        if not target_data: return await interaction.followup.send("Target player not found in database. They must be verified.", ephemeral=True)

        cols_to_transfer = ['tier', 'peak_tier', 'points', 'region', 'server', 'last_time_tested']
        updates = {col: source_data[col] for col in cols_to_transfer if col in source_data and source_data[col] is not None}
        
        if updates:
            update_clauses = ", ".join([f"`{key}` = %s" for key in updates.keys()])
            params = tuple(list(updates.values()) + [target_data['discord_id']])
            await db_write(f"UPDATE tiers SET {update_clauses} WHERE discord_id = %s", params)
        
        await db_write("DELETE FROM players WHERE uuid = %s", (source_data['uuid'],))
        await db_write("DELETE FROM tiers WHERE uuid = %s", (source_data['uuid'],))
        
        source_ign = source_data.get('minecraft_username', source)
        target_ign = target_data.get('minecraft_username', target)
        
        embed = discord.Embed(title="Tier Transfer Complete", color=Color.green())
        embed.add_field(name="Source", value=f"`{source_ign}`", inline=False)
        embed.add_field(name="Target", value=f"`{target_ign}`", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(CommandsCog(bot))