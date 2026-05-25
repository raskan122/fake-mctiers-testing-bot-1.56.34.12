This is a comprehensive README.md designed specifically for the Tier Testing Bot code you provided. It covers installation, Discord configuration, MySQL database schema creation, and legal requirements.

⚔️ Tier Testing Bot (MCTIERS Edition)

A professional-grade Discord bot designed for Minecraft PvP communities to manage skill-based tier testing. This bot automates the verification process, manages regional queues, handles testing tickets with automatic aging, and tracks tester statistics.

📜 License & Credits

Author: Poppyly
License: CC BY-NC 4.0

Non-Commercial: You may not use this material for commercial purposes.

Attribution: You must give appropriate credit to the original author.

Notice: Do not remove the credits in main.py.

🛠 Prerequisites

Before starting, ensure you have the following:

Python 3.10 or higher

MySQL Database Server (Local or hosted like PlanetScale, Aiven, or a VPS)

Discord Bot Token (via Discord Developer Portal)

Hosting: Minimum 100MB RAM, 50% CPU, and 1GB Storage.

🚀 Step 1: Discord Server Setup

Enable Developer Mode: Go to User Settings > Advanced > Developer Mode (On).

Create Roles: You need roles for:

Staff: Owner, Manager, Regulator, Moderator.

Testers: Senior Tester, Tester.

Tiers: HT1 through LT5, plus Unranked.

Regions: EU, NA, AS/AU.

Create Channels:

A Verification/Waitlist channel (where the bot posts the panel).

Regional queue channels (NA, EU, AS).

Logging, Results, Leaderboard, and Transcript channels.

Create Categories: Separate categories for NA, EU, AS, and High Tier testing tickets.

📁 Step 2: Configuration

Environment Variables: Create a .env file in the root directory:

code
Env
download
content_copy
expand_less
DISCORD_BOT_TOKEN=your_token_here
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=tier_testing

Bot Config: Open config.py and fill in all the IDs you gathered in Step 1. Ensure the REGION_DATA dictionary matches your channel and category IDs.

🗄️ Step 3: Database Setup

You must create the database and the tables manually. Run the following SQL queries in your MySQL console or PHPMyAdmin:

code
SQL
download
content_copy
expand_less
CREATE DATABASE tier_testing;
USE tier_testing;

-- Table for basic player linking
CREATE TABLE players (
    discord_id BIGINT PRIMARY KEY,
    uuid VARCHAR(36),
    minecraft_username VARCHAR(32)
);

-- Table for player ranks and stats
CREATE TABLE tiers (
    discord_id BIGINT PRIMARY KEY,
    uuid VARCHAR(36),
    minecraft_username VARCHAR(32),
    tier VARCHAR(10) DEFAULT 'Unranked',
    peak_tier VARCHAR(10) DEFAULT 'Unranked',
    points INT DEFAULT 0,
    region VARCHAR(10),
    server VARCHAR(50),
    last_time_tested DATETIME,
    is_retired BOOLEAN DEFAULT FALSE
);

-- Table for active testing tickets
CREATE TABLE testing_tickets (
    channel_id BIGINT PRIMARY KEY,
    tested_user_id BIGINT,
    created_by BIGINT,
    creation_time DATETIME,
    warning_sent BOOLEAN DEFAULT FALSE
);

-- Table for ticket settings (Exemptions)
CREATE TABLE tickets (
    channel_id BIGINT PRIMARY KEY,
    is_exempt BOOLEAN DEFAULT FALSE
);

-- Table for player cooldowns
CREATE TABLE cooldowns (
    discord_id BIGINT PRIMARY KEY,
    expires_at DATETIME
);
📥 Step 4: Installation

Clone/Download the bot files to your hosting environment.

Install Dependencies:

run this in your console: pip install discord.py mysql-connector-python python-dotenv pytz chat-exporter aiohttp
▶️ Step 5: Running the Bot

Start the bot:

run this in your console: python main.py

On the first run, the bot will:

Sync Slash Commands (this may take a few minutes).

Initialize the Waitlist Panel in the channel defined in config.py.

Setup persistent views for buttons.

🎮 Command Overview
Member Commands

/profile user / /profile username: View a player's rank and stats.

/leave: Exit a queue or waitlist.

/help: Opens the interactive guide.

Tester Commands

/start: Set yourself as an active tester (opens the queue).

/stop: Set yourself as inactive (closes the queue).

/next: Pull the next player from the queue and create a ticket.

/close: Finalize a test, assign a rank, and log results.

/skip: Close a ticket without a result (Discontinued).

/exempt: Prevent a ticket from being auto-closed after 3 days.

Admin/Management

/setrank: Manually change a user's tier.

/forceauth set: Manually link a Discord account to a Minecraft account.

/cooldownreset: Reset a player's testing cooldown.

/config quota: Set the required number of tests per month for testers.

⚠️ Important Notes

Auto-Cleanup: The bot automatically deletes testing tickets after 3 days unless /exempt is used. It sends a warning 15 minutes before deletion.

Monthly Rollover: At the end of every month, the bot:

Resets the monthly_tests.json counts.

Posts a final leaderboard.

Automatically removes the Tester role from anyone who failed to meet the set quota.

Queue Pings: Ensure the bot has permissions to mention @here in the queue channels.

Need Help? Ensure the Bot has Administrator permissions during setup to avoid permission errors with channel creation and role management.