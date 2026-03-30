import discord
from discord.ext import commands, tasks
import os
import json
import aiofiles
import random
import asyncio
import time
import shutil
from datetime import datetime, timezone

# --------------------------
# ⚡ Bot Setup
# --------------------------
bot = commands.Bot(command_prefix="&", intents=discord.Intents.all(), help_command=None)

# --------------------------
# ⚡ File Paths
# --------------------------
SERVICES_FILE = "services.json"
USER_DATA_FILE = "user_data.json"
BLACKLIST_FILE = "blacklist.json"
CONFIG_FILE = "config.json"
ANALYTICS_FILE = "analytics.json"
STOCK_FOLDER = "Stock"
BACKUP_FOLDER = "Backups"

os.makedirs(STOCK_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

# ---------------------------
# DM QUEUE SYSTEM
# ---------------------------
dm_queue = asyncio.Queue()
dm_worker_started = False

async def dm_worker():
    while True:
        user, content, file_path = await dm_queue.get()

        try:
            dm = await user.create_dm()
            await asyncio.sleep(1.5)

            if file_path:
                await dm.send(content, file=discord.File(file_path))
            else:
                await dm.send(content)

        except Exception as e:
            print("DM Error:", e)

        dm_queue.task_done()

# --------------------------
# ⚡ Default Config/Data
# --------------------------
default_config = {
    "token": "MTQ1NTc4NDUxNTg3NTM3MzA5Nw.GMuDOX.0rTtxltwOtoY5-O6dWevrjLscjVdakJOEj7mAw",
    "log_channel_id": 1488040792495882341,
    "max_amount": 1000,

    "premium_credit_cost": 100,
    "daily_reward": 50,
    "referral_reward": 75,

    "xp_per_gen": 10,
    "xp_per_vouch": 25,
    "xp_per_level": 100,

    "low_stock_threshold": 5,
    "gen_cooldown": 300,
    "max_gens_per_day": 10,
    "abuse_threshold": 15,

    "alert_channel_id": 0,
    "announce_channel_id": 0,

    "level_roles": {
        "5": 0,
        "10": 0,
        "20": 0
    },
    "vouch_roles": {
        "5": 0,
        "10": 0,
        "25": 0
    }
}

default_services = {
    "Free": ["Minecraft", "Bedrock", "Others"],
    "Premium": ["Name Changable", "Unban", "Ranks", "Codes"]
}

default_analytics = {
    "total_generations": 0,
    "service_usage": {}
}

# --------------------------
# ⚡ JSON Helper Functions
# --------------------------
def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4)
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# --------------------------
# ⚡ Load Main Data
# --------------------------
config = load_json(CONFIG_FILE, default_config)
user_data = load_json(USER_DATA_FILE, {})
blacklist_data = load_json(BLACKLIST_FILE, {})
analytics = load_json(ANALYTICS_FILE, default_analytics)

MAX_AMOUNT = config.get("max_amount", 1000)
LOG_CHANNEL_ID = config.get("log_channel_id", 0)


# --------------------------
# ⚡ Helper Functions
# --------------------------
def progress_bar(current, total, length=20):
    if total <= 0:
        total = 1
    filled = int(length * current / total)
    return f"[{'█'*filled}{'─'*(length-filled)}] {current}/{total}"


def generate_fake_nitro(length=16):
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return ''.join(random.choice(chars) for _ in range(length))


def load_services():
    return load_json(SERVICES_FILE, default_services)


def save_services(data):
    save_json(SERVICES_FILE, data)


def get_user_data(user_id: int):
    uid = str(user_id)

    if uid not in user_data:
        user_data[uid] = {
            "credits": 0,
            "xp": 0,
            "level": 1,
            "vouches": 0,
            "total_generations": 0,
            "generation_history": [],
            "referrals_made": 0,
            "referred_by": None,
            "last_daily": 0,
            "daily_streak": 0,
            "last_gen_time": 0,
            "gens_today": 0,
            "last_reset_day": "",
            "received_vouches_from": []
        }
        save_json(USER_DATA_FILE, user_data)

    return user_data[uid]


def is_blacklisted(user_id: int):
    return str(user_id) in blacklist_data


def reset_daily_if_needed(user_id: int):
    data = get_user_data(user_id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if data["last_reset_day"] != today:
        data["gens_today"] = 0
        data["last_reset_day"] = today
        save_json(USER_DATA_FILE, user_data)


def add_xp(user_id: int, amount: int):
    data = get_user_data(user_id)
    data["xp"] += amount
    leveled_up = False

    while data["xp"] >= data["level"] * config.get("xp_per_level", 100):
        data["xp"] -= data["level"] * config.get("xp_per_level", 100)
        data["level"] += 1
        leveled_up = True

    save_json(USER_DATA_FILE, user_data)
    return leveled_up, data["level"]


def record_generation(user_id: int, vault: str, service_name: str):
    data = get_user_data(user_id)
    now = int(time.time())

    data["last_gen_time"] = now
    data["gens_today"] += 1
    data["total_generations"] += 1
    data["generation_history"].append({
        "service": service_name,
        "vault": vault,
        "timestamp": now
    })
    data["generation_history"] = data["generation_history"][-15:]

    save_json(USER_DATA_FILE, user_data)

    analytics["total_generations"] = analytics.get("total_generations", 0) + 1
    analytics["service_usage"][service_name] = analytics["service_usage"].get(service_name, 0) + 1
    save_json(ANALYTICS_FILE, analytics)


def check_gen_access(user_id: int):
    if is_blacklisted(user_id):
        return False, "You are blacklisted from using generator commands."

    data = get_user_data(user_id)
    reset_daily_if_needed(user_id)

    now = time.time()
    cooldown = config.get("gen_cooldown", 300)

    if now - data["last_gen_time"] < cooldown:
        remaining = int(cooldown - (now - data["last_gen_time"]))
        return False, f"You are on cooldown for **{remaining} seconds**."

    if data["gens_today"] >= config.get("max_gens_per_day", 10):
        return False, "You reached your daily generation limit."

    return True, None
    
async def send_low_stock_alert(guild, vault: str, service_name: str, stock_left: int):
    alert_channel_id = config.get("alert_channel_id", 0)
    if not alert_channel_id:
        return

    channel = guild.get_channel(alert_channel_id)
    if not channel:
        return

    threshold = config.get("low_stock_threshold", 5)

    if stock_left > threshold:
        return
        
async def send_restock_announcement(guild, vault: str, service_name: str, new_count: int):
    announce_channel_id = config.get("announce_channel_id", 0)
    if not announce_channel_id:
        return

    channel = guild.get_channel(announce_channel_id)
    if not channel:
        return

    embed = discord.Embed(
        title="<a:restock:1462742077984210975> Service Restocked",
        color=discord.Color.green()
    )
    embed.add_field(name="Vault", value=f"`{vault}`", inline=True)
    embed.add_field(name="Service", value=f"`{service_name}`", inline=True)
    embed.add_field(name="New Stock", value=f"`{new_count}` units", inline=True)
    embed.set_footer(text="Automatic restock announcement")

    await channel.send(embed=embed)

    embed = discord.Embed(
        title="<a:warn:1462880264026980595> Low Stock Alert",
        color=discord.Color.orange()
    )
    embed.add_field(name="Vault", value=f"`{vault}`", inline=True)
    embed.add_field(name="Service", value=f"`{service_name}`", inline=True)
    embed.add_field(name="Stock Left", value=f"`{stock_left}`", inline=True)
    embed.add_field(
        name="Threshold",
        value=f"`{threshold}`",
        inline=True
    )
    embed.set_footer(text="Automatic stock alert system")

    await channel.send(embed=embed)
    
async def check_and_assign_reward_roles(member, level_up: bool = False, vouch_update: bool = False):
    if not member or not member.guild:
        return []

    assigned_roles = []
    data = get_user_data(member.id)

    # Level milestone roles
    if level_up:
        for level_str, role_id in config.get("level_roles", {}).items():
            if not role_id:
                continue

            try:
                required_level = int(level_str)
            except ValueError:
                continue

            if data["level"] >= required_level:
                role = member.guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Reached level {required_level}")
                        assigned_roles.append(f"Level Role: {role.mention}")
                    except Exception as e:
                        print(f"Level role add error: {e}")

    # Vouch milestone roles
    if vouch_update:
        for vouch_str, role_id in config.get("vouch_roles", {}).items():
            if not role_id:
                continue

            try:
                required_vouches = int(vouch_str)
            except ValueError:
                continue

            if data["vouches"] >= required_vouches:
                role = member.guild.get_role(role_id)
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f"Reached {required_vouches} vouches")
                        assigned_roles.append(f"Vouch Role: {role.mention}")
                    except Exception as e:
                        print(f"Vouch role add error: {e}")

    return assigned_roles

# --------------------------
# 📦 STOCK COMMAND
# --------------------------
@bot.command()
async def stock(ctx):
    data = load_services()
    embed = discord.Embed(
        title="<a:restock:1462742077984210975> VexCloud Stock Status <a:restock:1462742077984210975>",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="",
        value="```VexCloud StockZ```",
        inline=False
    )

    # Free section
    free_list = []
    for svc in data["Free"]:
        path = os.path.join(STOCK_FOLDER, "Free", f"{svc}.txt")
        count = sum(1 for _ in open(path, "r", encoding="utf-8")) if os.path.exists(path) else 0
        free_list.append(f"<a:dot:1462717724391243787> {svc} ➜ [ {count} Units ]")
    embed.add_field(name="<a:78116greensparkle:1462875294640902293> Free Inventory", value="\n".join(free_list) or "No services added.", inline=False)

    # Premium section
    premium_list = []
    for svc in data["Premium"]:
        path = os.path.join(STOCK_FOLDER, "Premium", f"{svc}.txt")
        count = sum(1 for _ in open(path, "r", encoding="utf-8")) if os.path.exists(path) else 0
        premium_list.append(f"<a:dot:1462717724391243787> {svc} ➜ [ {count} Units ]")
    embed.add_field(name="<a:PurpleDiamond:1462709876567572638> Premium Inventory", value="\n".join(premium_list) or "No services added.", inline=False)

    embed.set_footer(text="VexCloud Gen Bot | Updated Regularly")

    await ctx.send(embed=embed)

# --------------------------
# ➕ ADD SERVICE
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def addservice(ctx, vault: str, *, service_name: str):
    vault = vault.capitalize()
    data = load_services()

    if vault not in data:
        return await ctx.send(
            "<a:Wrong:1462880110334972038> **Invalid vault!** Use `Free` or `Premium`."
        )

    if service_name in data[vault]:
        return await ctx.send(
            f"<a:warn:1462880264026980595> **{service_name}** already exists in **{vault} Vault**."
        )

    data[vault].append(service_name)
    save_services(data)

    embed = discord.Embed(
        title="<a:78116greensparkle:1462875294640902293> Service Successfully Added",
        color=discord.Color.from_rgb(88, 101, 242),  # premium blurple
        timestamp=ctx.message.created_at
    )

    embed.add_field(
        name="<a:restock:1462742077984210975> Vault",
        value=f"`{vault}`",
        inline=True
    )
    embed.add_field(
        name="<a:Admin_:1462885585340600323>️ Service",
        value=f"`{service_name}`",
        inline=True
    )

    embed.add_field(
        name="<a:tick:1462880393039712370> Status",
        value="Added to inventory successfully",
        inline=False
    )

    embed.set_author(
        name=ctx.author,
        icon_url=ctx.author.display_avatar.url
    )

    embed.set_footer(
        text="Service Management System • Premium",
        icon_url=bot.user.display_avatar.url
    )

    await ctx.send(embed=embed)

# --------------------------
# ❌ REMOVE SERVICE
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def removeservice(ctx, vault: str, *, service_name: str):
    vault = vault.capitalize()
    data = load_services()

    if vault not in data:
        return await ctx.send(
            "<a:Wrong:1462880110334972038> **Invalid vault!** Use `Free` or `Premium`."
        )

    if service_name not in data[vault]:
        return await ctx.send(
            f"<a:warn:1462880264026980595> **{service_name}** not found in **{vault} Vault**."
        )

    data[vault].remove(service_name)
    save_services(data)

    embed = discord.Embed(
        title="<:dustbin:1462880808787247238>️ Service Successfully Removed",
        color=discord.Color.red(),
        timestamp=ctx.message.created_at
    )

    embed.add_field(
        name="<a:restock:1462742077984210975> Vault",
        value=f"`{vault}`",
        inline=True
    )
    embed.add_field(
        name="<a:Admin_:1462885585340600323>️ Service",
        value=f"`{service_name}`",
        inline=True
    )

    embed.add_field(
        name="<a:Wrong:1462880110334972038> Status",
        value="Removed from inventory successfully",
        inline=False
    )

    embed.set_author(
        name=ctx.author,
        icon_url=ctx.author.display_avatar.url
    )

    embed.set_footer(
        text="Service Management System • Premium",
        icon_url=bot.user.display_avatar.url
    )

    await ctx.send(embed=embed)

# --------------------------
# 🔁 RESTOCK COMMAND
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def restock(ctx, vault: str, *, service: str):
    vault = vault.capitalize()
    services = load_services()

    if vault not in services:
        return await ctx.send(
            "<a:Wrong:1462880110334972038> **Invalid vault!** Use `Free` or `Premium`."
        )

    if service not in services[vault]:
        return await ctx.send(
            f"<a:warn:1462880264026980595> **{service}** not found in **{vault} Vault**."
        )

    if not ctx.message.attachments:
        return await ctx.send(
            "<a:file:1462881258391605474> **Please attach a `.txt` file with stock items.**"
        )

    file = ctx.message.attachments[0]

    if not file.filename.endswith(".txt"):
        return await ctx.send(
            "<a:Wrong:1462880110334972038> **Only `.txt` files are supported for restocking.**"
        )

    folder_path = os.path.join(STOCK_FOLDER, vault)
    os.makedirs(folder_path, exist_ok=True)
    file_path = os.path.join(folder_path, f"{service}.txt")

    old_count = 0
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as old_file:
            old_count = sum(1 for line in old_file if line.strip())

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(await file.read())

    new_count = 0
    with open(file_path, "r", encoding="utf-8") as new_file:
        new_count = sum(1 for line in new_file if line.strip())

    if old_count == 0 and new_count > 0:
        await send_restock_announcement(ctx.guild, vault, service, new_count)

    embed = discord.Embed(
        title="<a:restock:1462742077984210975> Stock Restocked Successfully",
        color=discord.Color.from_rgb(67, 181, 129),  # premium green
        timestamp=ctx.message.created_at
    )

    embed.add_field(
        name="<:files:1463037738663153778> Vault",
        value=f"`{vault}`",
        inline=True
    )
    embed.add_field(
        name="<a:Admin_:1462885585340600323>️ Service",
        value=f"`{service}`",
        inline=True
    )
    embed.add_field(
        name="<a:file:1462881258391605474> File Uploaded",
        value=f"`{file.filename}`",
        inline=False
    )
    embed.add_field(
        name="<a:tick:1462880393039712370> Status",
        value="Stock updated and saved successfully",
        inline=False
    )

    embed.set_author(
        name=ctx.author,
        icon_url=ctx.author.display_avatar.url
    )

    embed.set_footer(
        text="Stock Management System • Premium",
        icon_url=bot.user.display_avatar.url
    )

    await ctx.send(embed=embed)

# --------------------------
# Free Gen Command
# --------------------------
@bot.command()
async def fgen(ctx, *, service_name: str):
    allowed_channel = 1488040280295739473
    required_status = "VexCloud Free MCFA Generator"

    # Check correct channel
    if ctx.channel.id != allowed_channel:
        return await ctx.reply(
            f"<a:Wrong:1462880110334972038> You can only use this command in <#{allowed_channel}>!"
        )

    # Check blacklist / cooldown / daily limit
    allowed, reason = check_gen_access(ctx.author.id)
    if not allowed:
        return await ctx.reply(f"<a:warn:1462880264026980595> {reason}")

    # Check required custom status
    member = ctx.author
    has_status = False

    for activity in member.activities:
        if isinstance(activity, discord.CustomActivity) and activity.name == required_status:
            has_status = True
            break

    if not has_status:
        embed_status = discord.Embed(
            title="<a:warn:1462880264026980595> Access Denied!",
            description="You cannot generate a Free Gen account yet.",
            color=discord.Color.red()
        )
        embed_status.add_field(
            name="<a:notepad:1462881677197054149> Requirement",
            value=(
                f"Set your **custom status** to:\n`{required_status}`\n\n"
                "<a:buffering:1462881921947271411> Make sure your **status is visible** "
                "and not invisible/DND."
            ),
            inline=False
        )
        embed_status.add_field(
            name="<a:Wrong:1462880110334972038> Important",
            value="> Without the correct status, Free Gen access will be denied.",
            inline=False
        )
        embed_status.set_footer(text=f"Requested by {ctx.author.name}")
        embed_status.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/569/569540.png")
        return await ctx.reply(embed=embed_status)

    # Stock folder
    folder = os.path.join(STOCK_FOLDER, "Free")
    os.makedirs(folder, exist_ok=True)

    # Case-insensitive file match
    file_path = None
    matched_service_name = service_name
    for file in os.listdir(folder):
        if file.lower() == f"{service_name.lower()}.txt":
            file_path = os.path.join(folder, file)
            matched_service_name = os.path.splitext(file)[0]
            break

    if not file_path:
        return await ctx.reply(
            f"<a:Wrong:1462880110334972038> No stock found for **{service_name}**."
        )

    # Read stock
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        return await ctx.reply(
            f"<a:warn:1462880264026980595> Out of stock for **{matched_service_name}**."
        )

    # Pick account
    chosen = random.choice(lines)
    lines.remove(chosen)

    # Split account safely
    try:
        email, password = chosen.split(":", 1)
    except ValueError:
        return await ctx.reply(
            "<a:Wrong:1462880110334972038> Stock format error. Use `email:password` format."
        )

    # DM delivery first
    try:
        embed_dm = discord.Embed(
            title=f"<a:GIVEAWAY:1462743614550708294> {matched_service_name.upper()} ACCOUNT DELIVERY",
            description=(
                f"Hello **{ctx.author.name}**,\n\n"
                f"Your requested **{matched_service_name.upper()}** account has been **successfully delivered**.\n\n"
                "<a:AnimatedClipboard:1463038917249990719> Use the credentials below carefully."
            ),
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=ctx.message.created_at
        )

        embed_dm.add_field(
            name="<a:card:1462886279946436738> Login Email",
            value=f"||`{email}`||",
            inline=False
        )

        embed_dm.add_field(
            name="<a:password:1463039151275511922> Login Password",
            value=f"||`{password}`||",
            inline=False
        )

        embed_dm.add_field(
            name="<a:warn:1462880264026980595> Usage Guidelines",
            value=(
                "• Do **not** share these credentials\n"
                "• Change password if possible\n"
                "• No replacement guaranteed after delivery\n"
                "• Abuse may result in blacklist"
            ),
            inline=False
        )

        embed_dm.set_footer(
            text=f"Delivered for {ctx.author} • Secure Auto System",
            icon_url=ctx.author.display_avatar.url
        )

        await ctx.author.send(embed=embed_dm)

    except discord.Forbidden:
        return await ctx.reply(
            "<a:warn:1462880264026980595> **I can’t DM you. Please enable your DMs and try again.**"
        )

    # Only remove stock after successful DM
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        # Low stock alert
        await send_low_stock_alert(ctx.guild, "Free", matched_service_name, len(lines))

        # Record generation
        record_generation(ctx.author.id, "Free", matched_service_name)

        # Abuse threshold auto-blacklist
        user_info = get_user_data(ctx.author.id)
        if user_info["total_generations"] >= config.get("abuse_threshold", 15) and str(ctx.author.id) not in blacklist_data:
            blacklist_data[str(ctx.author.id)] = {
                "reason": "Auto-blacklisted for abuse threshold",
                "by": bot.user.id if bot.user else 0,
                "timestamp": int(time.time())
            }
            save_json(BLACKLIST_FILE, blacklist_data)

    # XP reward
    leveled_up, new_level = add_xp(ctx.author.id, config.get("xp_per_gen", 10))
    
    reward_roles = await check_and_assign_reward_roles(ctx.author, level_up=leveled_up)

    # Public confirmation
    embed_public = discord.Embed(
        title="<a:tick:1462880393039712370> Account Generated Successfully!",
        description="> <a:sended:1462883358735597705> Your account has been sent to your DMs.",
        color=discord.Color.from_rgb(47, 49, 54)
    )

    embed_public.add_field(
        name="<a:users:1462883460904517817> Generated By",
        value=f"> {ctx.author.mention}",
        inline=False
    )
    embed_public.add_field(
        name="<a:Purple_Fire:1462883587345879142> Service Generated",
        value=f"> **{matched_service_name}**",
        inline=False
    )
    embed_public.add_field(
        name="<a:Star:1462888016518451573> XP Earned",
        value=f"> `+{config.get('xp_per_gen', 10)} XP`",
        inline=False
    )
    embed_public.add_field(
        name="<a:warn:1462880264026980595> Reminder",
        value="> Please **vouch** in <#1488040293143150724>\n> or you’ll be **blocked from the gen!**",
        inline=False
    )

    if leveled_up:
        embed_public.add_field(
            name="<a:tick:1462880393039712370> Level Up!",
            value=f"> You reached **Level {new_level}**",
            inline=False
        )
        
    if reward_roles:
        embed_public.add_field(
            name="<a:Star:1462888016518451573> Reward Roles Earned",
            value="\n".join(f"> {role}" for role in reward_roles)[:1024],
            inline=False
        )

    embed_public.set_author(
        name="VexCloud | GEN & REWARDS",
        icon_url="https://cdn.discordapp.com/emojis/1462883079243825276.gif"
    )
    embed_public.set_footer(text="Always Active • VexCloud Generator")

    await ctx.reply(embed=embed_public)


# --------------------------
# Premium Gen Command
# --------------------------
@bot.command()
async def pgen(ctx, *, service_name: str):
    allowed_channel = 1488040271697412276

    # Correct channel check
    if ctx.channel.id != allowed_channel:
        return await ctx.reply(
            f"<a:Wrong:1462880110334972038> You can only use this command in <#{allowed_channel}>!"
        )

    # Blacklist / cooldown / daily limit check
    allowed, reason = check_gen_access(ctx.author.id)
    if not allowed:
        return await ctx.reply(f"<a:warn:1462880264026980595> {reason}")

    # Credit check
    user_info = get_user_data(ctx.author.id)
    premium_cost = config.get("premium_credit_cost", 100)

    if user_info["credits"] < premium_cost:
        return await ctx.reply(
            f"<a:warn:1462880264026980595> You need **{premium_cost} credits** to use premium gen.\n"
            f"Your current balance: **{user_info['credits']}**"
        )

    # Stock folder
    folder = os.path.join(STOCK_FOLDER, "Premium")
    os.makedirs(folder, exist_ok=True)

    # Case-insensitive file match
    file_path = None
    matched_service_name = service_name
    for file in os.listdir(folder):
        if file.lower() == f"{service_name.lower()}.txt":
            file_path = os.path.join(folder, file)
            matched_service_name = os.path.splitext(file)[0]
            break

    if not file_path:
        return await ctx.reply(
            f"<a:Wrong:1462880110334972038> No stock found for **{service_name}**."
        )

    # Read stock
    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        return await ctx.reply(
            f"<a:warn:1462880264026980595> Out of stock for **{matched_service_name}**."
        )

    # Pick account
    chosen = random.choice(lines)
    lines.remove(chosen)

    # Split account safely
    try:
        email, password = chosen.split(":", 1)
    except ValueError:
        return await ctx.reply(
            "<a:Wrong:1462880110334972038> Stock format error. Use `email:password` format."
        )

    # DM first
    try:
        embed_dm = discord.Embed(
            title=f"<a:GIVEAWAY:1462743614550708294> {matched_service_name.upper()} PREMIUM ACCOUNT DELIVERED",
            description=(
                f"Hello **{ctx.author.name}**, <a:worryhello:1463040431074840709>\n\n"
                f"Your **{matched_service_name.upper()} Premium Account** has been successfully delivered.\n"
                "Please find the secure credentials below.\n\n"
                "<a:rocket_gif:1462882281168568444> Instant delivery • Limited stock • Auto system"
            ),
            color=discord.Color.gold(),
            timestamp=ctx.message.created_at
        )

        embed_dm.add_field(
            name="<a:card:1462886279946436738> Email / Username",
            value=f"||`{email}`||",
            inline=False
        )

        embed_dm.add_field(
            name="<a:password:1463039151275511922> Password",
            value=f"||`{password}`||",
            inline=False
        )

        embed_dm.add_field(
            name="<a:lightning_l:1462883079243825276> Usage Instructions",
            value=(
                "• Login immediately\n"
                "• Do not share credentials\n"
                "• Change password if possible\n"
                "• No replacement after delivery"
            ),
            inline=False
        )

        embed_dm.add_field(
            name="<a:warn:1462880264026980595> Important Notice",
            value="Accounts are delivered **as-is**.\nMisuse or sharing may result in blacklist.",
            inline=False
        )

        embed_dm.set_footer(
            text=f"Requested by {ctx.author} • Premium Auto Delivery System",
            icon_url=ctx.author.display_avatar.url
        )

        await ctx.author.send(embed=embed_dm)

    except discord.Forbidden:
        return await ctx.reply(
            "<a:warn:1462880264026980595> **I can’t DM you — please enable your DMs and try again.**"
        )

    # Only after successful DM:
    # 1. Save new stock
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # 2. Low stock alert
    await send_low_stock_alert(ctx.guild, "Premium", matched_service_name, len(lines))

    # 3. Deduct credits
    user_info["credits"] -= premium_cost

    # 3. Record generation
    record_generation(ctx.author.id, "Premium", matched_service_name)

    # 4. Abuse threshold auto-blacklist
    if user_info["total_generations"] >= config.get("abuse_threshold", 15) and str(ctx.author.id) not in blacklist_data:
        blacklist_data[str(ctx.author.id)] = {
            "reason": "Auto-blacklisted for abuse threshold",
            "by": bot.user.id if bot.user else 0,
            "timestamp": int(time.time())
        }
        save_json(BLACKLIST_FILE, blacklist_data)

    # 5. XP reward
    leveled_up, new_level = add_xp(ctx.author.id, config.get("xp_per_gen", 10))
    
    reward_roles = await check_and_assign_reward_roles(ctx.author, level_up=leveled_up)

    # Public confirmation
    embed_public = discord.Embed(
        title="<a:BlackCrown:1462888566790029322> Premium Account Generated!",
        description="> <a:Admin_:1462885585340600323> Your premium account has been sent to your DMs.",
        color=discord.Color.gold()
    )

    embed_public.add_field(
        name="<a:users:1462883460904517817> Generated By",
        value=f"> {ctx.author.mention}",
        inline=False
    )

    embed_public.add_field(
        name="<a:PurpleDiamond:1462709876567572638> Service Generated",
        value=f"> **{matched_service_name}**",
        inline=False
    )

    embed_public.add_field(
        name="<a:card:1462886279946436738> Credits Used",
        value=f"> `-{premium_cost}` credits",
        inline=False
    )

    embed_public.add_field(
        name="<a:Star:1462888016518451573> XP Earned",
        value=f"> `+{config.get('xp_per_gen', 10)} XP`",
        inline=False
    )

    embed_public.add_field(
        name="<a:warn:1462880264026980595> Remaining Balance",
        value=f"> `{user_info['credits']}` credits",
        inline=False
    )

    embed_public.add_field(
        name="<a:warn:1462880264026980595> Reminder",
        value="> Please **vouch** in <#1410598255246446664>",
        inline=False
    )

    if leveled_up:
        embed_public.add_field(
            name="<a:tick:1462880393039712370> Level Up!",
            value=f"> You reached **Level {new_level}**",
            inline=False
        )
        
    if reward_roles:
        embed_public.add_field(
            name="<a:Star:1462888016518451573> Reward Roles Earned",
            value="\n".join(f"> {role}" for role in reward_roles)[:1024],
            inline=False
        )

    embed_public.set_author(
        name="VexCloud | GEN & REWARDS",
        icon_url="https://cdn.discordapp.com/emojis/1462883079243825276.gif"
    )
    embed_public.set_footer(text="Always Active • VexCloud Generator")

    await ctx.reply(embed=embed_public)
    
# --------------------------
# 💰 BALANCE / CREDITS COMMANDS
# --------------------------
@bot.command(aliases=["bal", "credits"])
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)

    embed = discord.Embed(
        title=f"{member.display_name}'s Profile",
        color=discord.Color.green()
    )

    embed.add_field(name="Credits", value=f"`{data['credits']}`", inline=True)
    embed.add_field(name="Level", value=f"`{data['level']}`", inline=True)
    embed.add_field(name="XP", value=f"`{data['xp']}`", inline=True)
    embed.add_field(name="Vouches", value=f"`{data['vouches']}`", inline=True)
    embed.add_field(name="Total Gens", value=f"`{data['total_generations']}`", inline=True)
    embed.add_field(name="Daily Streak", value=f"`{data['daily_streak']}`", inline=True)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def addcredits(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("<a:Wrong:1462880110334972038> Amount must be greater than 0.")

    data = get_user_data(member.id)
    data["credits"] += amount
    save_json(USER_DATA_FILE, user_data)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> Credits Added",
        color=discord.Color.green()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Added", value=f"`{amount}`", inline=True)
    embed.add_field(name="New Balance", value=f"`{data['credits']}`", inline=True)
    embed.set_footer(text=f"Action by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def removecredits(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        return await ctx.send("<a:Wrong:1462880110334972038> Amount must be greater than 0.")

    data = get_user_data(member.id)
    data["credits"] = max(0, data["credits"] - amount)
    save_json(USER_DATA_FILE, user_data)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> Credits Removed",
        color=discord.Color.red()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Removed", value=f"`{amount}`", inline=True)
    embed.add_field(name="New Balance", value=f"`{data['credits']}`", inline=True)
    embed.set_footer(text=f"Action by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 🎁 DAILY REWARD SYSTEM
# --------------------------
@bot.command()
async def daily(ctx):
    data = get_user_data(ctx.author.id)
    now = time.time()

    # cooldown check (24h)
    if now - data["last_daily"] < 86400:
        remaining = int(86400 - (now - data["last_daily"]))
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60

        embed = discord.Embed(
            title="<a:warn:1462880264026980595> Already Claimed!",
            description=f"You already claimed your daily reward.\nCome back in **{hours}h {minutes}m**",
            color=discord.Color.red()
        )
        return await ctx.send(embed=embed)

    # streak logic
    if data["last_daily"] != 0 and now - data["last_daily"] <= 172800:
        data["daily_streak"] += 1
    else:
        data["daily_streak"] = 1

    # bonus calculation
    streak_bonus = min(data["daily_streak"] * 10, 100)
    reward = config.get("daily_reward", 50) + streak_bonus

    # update data
    data["credits"] += reward
    data["last_daily"] = now

    save_json(USER_DATA_FILE, user_data)

    # embed
    embed = discord.Embed(
        title="<a:gift:1462886763937370112> Daily Reward Claimed!",
        color=discord.Color.gold()
    )

    embed.add_field(name="Base Reward", value=f"`{config.get('daily_reward', 50)}`", inline=True)
    embed.add_field(name="Streak", value=f"`{data['daily_streak']}`", inline=True)
    embed.add_field(name="Bonus", value=f"`+{streak_bonus}`", inline=True)

    embed.add_field(
        name="<a:card:1462886279946436738> Total Earned",
        value=f"**{reward} credits**",
        inline=False
    )

    embed.set_footer(text=f"Come back tomorrow for more rewards!", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 🔗 REFERRAL SYSTEM
# --------------------------
@bot.command()
async def refer(ctx, member: discord.Member):
    if member.id == ctx.author.id:
        return await ctx.send("<a:Wrong:1462880110334972038> You cannot refer yourself.")

    if member.bot:
        return await ctx.send("<a:Wrong:1462880110334972038> You cannot refer a bot.")

    author_data = get_user_data(ctx.author.id)
    target_data = get_user_data(member.id)

    if target_data["referred_by"] is not None:
        return await ctx.send("<a:warn:1462880264026980595> This user has already been referred before.")

    target_data["referred_by"] = ctx.author.id
    author_data["referrals_made"] += 1
    author_data["credits"] += config.get("referral_reward", 75)

    save_json(USER_DATA_FILE, user_data)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> Referral Successful",
        color=discord.Color.green()
    )
    embed.add_field(name="Referrer", value=ctx.author.mention, inline=True)
    embed.add_field(name="Referred User", value=member.mention, inline=True)
    embed.add_field(name="Reward", value=f"`{config.get('referral_reward', 75)} credits`", inline=True)
    embed.set_footer(text=f"Referral system • Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
async def referrals(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)

    embed = discord.Embed(
        title=f"{member.display_name}'s Referrals",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Total Referrals Made", value=f"`{data['referrals_made']}`", inline=True)

    referred_by = data["referred_by"]
    if referred_by:
        embed.add_field(name="Referred By", value=f"<@{referred_by}>", inline=True)
    else:
        embed.add_field(name="Referred By", value="`No one`", inline=True)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# ⭐ XP / LEVEL COMMANDS
# --------------------------
@bot.command(aliases=["rank"])
async def level(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)

    current_xp = data["xp"]
    current_level = data["level"]
    required_xp = current_level * config.get("xp_per_level", 100)

    progress = int((current_xp / required_xp) * 10) if required_xp > 0 else 0
    progress = max(0, min(progress, 10))
    bar = "█" * progress + "─" * (10 - progress)

    embed = discord.Embed(
        title=f"{member.display_name}'s Level Card",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Level", value=f"`{current_level}`", inline=True)
    embed.add_field(name="XP", value=f"`{current_xp}/{required_xp}`", inline=True)
    embed.add_field(name="Progress", value=f"`[{bar}]`", inline=False)
    embed.add_field(name="Vouches", value=f"`{data['vouches']}`", inline=True)
    embed.add_field(name="Total Gens", value=f"`{data['total_generations']}`", inline=True)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
async def xp(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)

    required_xp = data["level"] * config.get("xp_per_level", 100)

    embed = discord.Embed(
        title=f"{member.display_name}'s XP Stats",
        color=discord.Color.gold()
    )
    embed.add_field(name="Current XP", value=f"`{data['xp']}`", inline=True)
    embed.add_field(name="Current Level", value=f"`{data['level']}`", inline=True)
    embed.add_field(name="XP Needed For Next Level", value=f"`{required_xp - data['xp']}`", inline=True)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 💬 VOUCH SYSTEM
# --------------------------
@bot.command()
async def vouch(ctx, member: discord.Member, *, message: str = None):
    if member.id == ctx.author.id:
        return await ctx.send("<a:Wrong:1462880110334972038> You cannot vouch yourself.")

    if member.bot:
        return await ctx.send("<a:Wrong:1462880110334972038> You cannot vouch a bot.")

    giver_data = get_user_data(ctx.author.id)
    target_data = get_user_data(member.id)

    if str(ctx.author.id) in target_data["received_vouches_from"]:
        return await ctx.send("<a:warn:1462880264026980595> You have already vouched this user.")

    target_data["vouches"] += 1
    target_data["received_vouches_from"].append(str(ctx.author.id))

    leveled_up, new_level = add_xp(member.id, config.get("xp_per_vouch", 25))
    reward_roles = await check_and_assign_reward_roles(member, vouch_update=True)
    save_json(USER_DATA_FILE, user_data)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> Vouch Added",
        color=discord.Color.green()
    )
    embed.add_field(name="Vouched User", value=member.mention, inline=True)
    embed.add_field(name="Given By", value=ctx.author.mention, inline=True)
    embed.add_field(name="Total Vouches", value=f"`{target_data['vouches']}`", inline=True)

    if message:
        embed.add_field(name="Message", value=message[:1024], inline=False)

    embed.add_field(
        name="XP Reward",
        value=f"`+{config.get('xp_per_vouch', 25)} XP`",
        inline=True
    )

    if leveled_up:
        embed.add_field(
            name="<a:Star:1462888016518451573> Level Up",
            value=f"{member.mention} reached **Level {new_level}**",
            inline=False
        )
        
    if reward_roles:
        embed.add_field(
            name="<a:Star:1462888016518451573> Reward Roles Earned",
            value="\n".join(f"> {role}" for role in reward_roles)[:1024],
            inline=False
        )

    embed.set_footer(text=f"Vouch system • Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
async def vouches(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)

    embed = discord.Embed(
        title=f"{member.display_name}'s Vouches",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Total Vouches", value=f"`{data['vouches']}`", inline=True)
    embed.add_field(name="Level", value=f"`{data['level']}`", inline=True)
    embed.add_field(name="XP", value=f"`{data['xp']}`", inline=True)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 📊 STATS / HISTORY COMMANDS
# --------------------------
@bot.command(aliases=["stats"])
async def genstats(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)
    reset_daily_if_needed(member.id)

    history = data.get("generation_history", [])
    recent = history[-5:] if history else []

    if recent:
        recent_text = []
        for entry in reversed(recent):
            service = entry.get("service", "Unknown")
            vault = entry.get("vault", "Unknown")
            ts = entry.get("timestamp", 0)
            recent_text.append(f"• **{service}** ({vault}) - <t:{ts}:R>")
        recent_value = "\n".join(recent_text)
    else:
        recent_value = "`No recent generations.`"

    embed = discord.Embed(
        title=f"{member.display_name}'s Generation Stats",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Total Generations", value=f"`{data['total_generations']}`", inline=True)
    embed.add_field(name="Gens Today", value=f"`{data['gens_today']}`", inline=True)
    embed.add_field(name="Level", value=f"`{data['level']}`", inline=True)
    embed.add_field(name="Recent History", value=recent_value[:1024], inline=False)

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
async def history(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)
    history = data.get("generation_history", [])

    if not history:
        return await ctx.send("<a:warn:1462880264026980595> No generation history found for this user.")

    lines = []
    for i, entry in enumerate(reversed(history[-15:]), start=1):
        service = entry.get("service", "Unknown")
        vault = entry.get("vault", "Unknown")
        ts = entry.get("timestamp", 0)
        lines.append(f"`{i}.` **{service}** • `{vault}` • <t:{ts}:R>")

    embed = discord.Embed(
        title=f"{member.display_name}'s Full History",
        description="\n".join(lines)[:4096],
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Showing last {min(len(history), 15)} generations", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 🚫 BLACKLIST SYSTEM
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def blacklist(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    if member.id == ctx.author.id:
        return await ctx.send("<a:Wrong:1462880110334972038> You cannot blacklist yourself.")

    if member.bot:
        return await ctx.send("<a:Wrong:1462880110334972038> You cannot blacklist a bot.")

    uid = str(member.id)

    if uid in blacklist_data:
        return await ctx.send("<a:warn:1462880264026980595> This user is already blacklisted.")

    blacklist_data[uid] = {
        "reason": reason,
        "by": ctx.author.id,
        "timestamp": int(time.time())
    }
    save_json(BLACKLIST_FILE, blacklist_data)

    embed = discord.Embed(
        title="<a:Wrong:1462880110334972038> User Blacklisted",
        color=discord.Color.red()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="By", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.set_footer(text="Blacklist system", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def unblacklist(ctx, member: discord.Member):
    uid = str(member.id)

    if uid not in blacklist_data:
        return await ctx.send("<a:warn:1462880264026980595> This user is not blacklisted.")

    del blacklist_data[uid]
    save_json(BLACKLIST_FILE, blacklist_data)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> User Unblacklisted",
        color=discord.Color.green()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="By", value=ctx.author.mention, inline=True)
    embed.set_footer(text="Blacklist system", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)


@bot.command()
async def isblacklisted(ctx, member: discord.Member = None):
    member = member or ctx.author
    uid = str(member.id)

    if uid not in blacklist_data:
        embed = discord.Embed(
            title="<a:tick:1462880393039712370> Not Blacklisted",
            description=f"{member.mention} is not blacklisted.",
            color=discord.Color.green()
        )
        embed.set_footer(text="Blacklist checker", icon_url=ctx.author.display_avatar.url)
        return await ctx.send(embed=embed)

    info = blacklist_data[uid]
    reason = info.get("reason", "No reason provided")
    by = info.get("by")
    ts = info.get("timestamp", 0)

    embed = discord.Embed(
        title="<a:Wrong:1462880110334972038> User is Blacklisted",
        color=discord.Color.red()
    )
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Reason", value=reason[:1024], inline=False)
    embed.add_field(name="Blacklisted By", value=f"<@{by}>" if by else "`Unknown`", inline=True)
    embed.add_field(name="Date", value=f"<t:{ts}:F>" if ts else "`Unknown`", inline=True)
    embed.set_footer(text="Blacklist checker", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# ⏰ COOLDOWN TRACKER
# --------------------------
@bot.command(aliases=["cd"])
async def cooldowns(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = get_user_data(member.id)
    reset_daily_if_needed(member.id)

    now = time.time()

    # gen cooldown
    gen_cooldown = config.get("gen_cooldown", 300)
    gen_remaining = max(0, int(gen_cooldown - (now - data["last_gen_time"])))

    if gen_remaining > 0:
        gen_status = f"**{gen_remaining}s** remaining"
    else:
        gen_status = "`Ready`"

    # daily cooldown
    daily_remaining = max(0, int(86400 - (now - data["last_daily"]))) if data["last_daily"] else 0
    if daily_remaining > 0:
        hours = daily_remaining // 3600
        minutes = (daily_remaining % 3600) // 60
        daily_status = f"**{hours}h {minutes}m** remaining"
    else:
        daily_status = "`Ready`"

    # daily usage
    gens_today = data.get("gens_today", 0)
    max_gens = config.get("max_gens_per_day", 10)

    embed = discord.Embed(
        title=f"{member.display_name}'s Cooldowns",
        color=discord.Color.orange()
    )
    embed.add_field(name="Gen Cooldown", value=gen_status, inline=False)
    embed.add_field(name="Daily Reward", value=daily_status, inline=False)
    embed.add_field(name="Daily Gens Used", value=f"`{gens_today}/{max_gens}`", inline=False)

    if is_blacklisted(member.id):
        embed.add_field(
            name="Blacklist Status",
            value="<a:Wrong:1462880110334972038> `Blacklisted`",
            inline=False
        )
    else:
        embed.add_field(
            name="Blacklist Status",
            value="<a:tick:1462880393039712370> `Not Blacklisted`",
            inline=False
        )

    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 📈 STOCK ANALYTICS
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def stockanalytics(ctx):
    total_gens = analytics.get("total_generations", 0)
    service_usage = analytics.get("service_usage", {})

    if not service_usage:
        embed = discord.Embed(
            title="<a:warn:1462880264026980595> No Analytics Data",
            description="No generations have been recorded yet.",
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        return await ctx.send(embed=embed)

    sorted_services = sorted(service_usage.items(), key=lambda x: x[1], reverse=True)
    top_10 = sorted_services[:10]

    lines = []
    medals = ["🥇", "🥈", "🥉"]

    for i, (service, count) in enumerate(top_10, start=1):
        medal = medals[i - 1] if i <= 3 else f"`#{i}`"
        lines.append(f"{medal} **{service}** — `{count}` gens")

    all_services_text = []
    for service, count in sorted_services:
        all_services_text.append(f"• **{service}** — `{count}`")

    embed = discord.Embed(
        title="<a:restock:1462742077984210975> Stock Analytics Dashboard",
        color=discord.Color.blurple()
    )
    embed.add_field(name="Total Generations", value=f"`{total_gens}`", inline=False)
    embed.add_field(name="Top 10 Most Popular Services", value="\n".join(lines)[:1024], inline=False)

    # Agar bahut zyada services hongi to field limit hit na ho
    all_services_joined = "\n".join(all_services_text)
    embed.add_field(
        name="Generation Count Per Service",
        value=all_services_joined[:1024] if all_services_joined else "`No data`",
        inline=False
    )

    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# ⚙️ SET ALERT CHANNEL
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setalertchannel(ctx, channel: discord.TextChannel):
    config["alert_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> Alert Channel Set",
        description=f"Low stock alerts will now be sent to {channel.mention}",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Action by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# ⚙️ SET ANNOUNCEMENT CHANNEL
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def setannouncechannel(ctx, channel: discord.TextChannel):
    config["announce_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> Announcement Channel Set",
        description=f"Restock announcements will now be sent to {channel.mention}",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"Action by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 💾 BACKUP SYSTEM
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def backup(ctx):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = os.path.join(BACKUP_FOLDER, f"backup_{timestamp}")
    os.makedirs(backup_path, exist_ok=True)

    files_to_backup = [
        SERVICES_FILE,
        USER_DATA_FILE,
        BLACKLIST_FILE,
        CONFIG_FILE,
        ANALYTICS_FILE
    ]

    backed_up_files = []

    for file_name in files_to_backup:
        if os.path.exists(file_name):
            shutil.copy2(file_name, os.path.join(backup_path, os.path.basename(file_name)))
            backed_up_files.append(file_name)

    stock_backup_path = os.path.join(backup_path, "Stock")
    if os.path.exists(STOCK_FOLDER):
        shutil.copytree(STOCK_FOLDER, stock_backup_path, dirs_exist_ok=True)

    embed = discord.Embed(
        title="<a:tick:1462880393039712370> Backup Created Successfully",
        color=discord.Color.green()
    )
    embed.add_field(name="Backup Folder", value=f"`{backup_path}`", inline=False)
    embed.add_field(
        name="Files Backed Up",
        value="\n".join(f"• `{file}`" for file in backed_up_files) if backed_up_files else "`No files found`",
        inline=False
    )
    embed.add_field(name="Stock Folder", value="`Included`" if os.path.exists(STOCK_FOLDER) else "`Not found`", inline=False)
    embed.set_footer(text=f"Backup created by {ctx.author}", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
@bot.command()
@commands.has_permissions(administrator=True)
async def listbackups(ctx):
    if not os.path.exists(BACKUP_FOLDER):
        return await ctx.send("<a:warn:1462880264026980595> No backup folder found.")

    backups = [
        folder for folder in os.listdir(BACKUP_FOLDER)
        if os.path.isdir(os.path.join(BACKUP_FOLDER, folder))
    ]

    if not backups:
        return await ctx.send("<a:warn:1462880264026980595> No backups available.")

    backups.sort(reverse=True)
    latest_backups = backups[:10]

    lines = []
    for i, folder in enumerate(latest_backups, start=1):
        lines.append(f"`{i}.` {folder}")

    embed = discord.Embed(
        title="<a:restock:1462742077984210975> Available Backups",
        description="\n".join(lines),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"Showing latest {len(latest_backups)} backups", icon_url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)
    
# --------------------------
# 📚 USER HELP COMMAND
# --------------------------
@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="<a:Star:1462888016518451573> VexCloud Bot • User Commands",
        description="Here are all available user commands:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎮 Generator Commands",
        value=(
            "`&fgen <service>` ➜ Generate a free account\n"
            "`&pgen <service>` ➜ Generate a premium account\n"
            "`&stock` ➜ View current stock\n"
            "`&genhelp` ➜ Free generator access guide"
        ),
        inline=False
    )

    embed.add_field(
        name="💰 Economy Commands",
        value=(
            "`&balance` / `&bal` / `&credits` ➜ View your profile and credits\n"
            "`&daily` ➜ Claim your daily credits\n"
            "`&refer @user` ➜ Refer a user and earn credits\n"
            "`&referrals [user]` ➜ View referral stats"
        ),
        inline=False
    )

    embed.add_field(
        name="⭐ Progression Commands",
        value=(
            "`&level [user]` / `&rank [user]` ➜ View level card\n"
            "`&xp [user]` ➜ View XP stats\n"
            "`&vouch @user [message]` ➜ Vouch a user\n"
            "`&vouches [user]` ➜ View total vouches"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Stats Commands",
        value=(
            "`&genstats [user]` / `&stats [user]` ➜ View generation stats\n"
            "`&history [user]` ➜ View recent generation history\n"
            "`&cooldowns` / `&cd` ➜ View your active cooldowns"
        ),
        inline=False
    )

    embed.add_field(
        name="🚫 Safety / Info",
        value=(
            "`&isblacklisted [user]` ➜ Check blacklist status"
        ),
        inline=False
    )

    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)
    
# --------------------------
# ✨ CREATE EMBED COMMAND
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def createembed(ctx, *, content: str):
    if "|" not in content:
        return await ctx.send(
            "<a:warn:1462880264026980595> Use format: `&createembed Title | Description`"
        )

    title, description = content.split("|", 1)
    title = title.strip()
    description = description.strip()

    if not title:
        return await ctx.send("<a:Wrong:1462880110334972038> Embed title cannot be empty.")

    if not description:
        return await ctx.send("<a:Wrong:1462880110334972038> Embed description cannot be empty.")

    embed = discord.Embed(
        title=title[:256],
        description=description[:4096],
        color=discord.Color.blurple(),
        timestamp=ctx.message.created_at
    )

    embed.set_footer(
        text=f"Created by {ctx.author}",
        icon_url=ctx.author.display_avatar.url
    )

    await ctx.send(embed=embed)

# --------------------------
# Generator Help Command
# --------------------------
@bot.command()
async def genhelp(ctx):
    embed = discord.Embed(
        title="<a:Star:1462888016518451573> How to Access Free Generator <a:Star:1462888016518451573>",
        description="Follow these simple steps to get access to the Free MCFA Generator!",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="<a:NEAxe:1462887890278420502> Step 1",
        value="Set your custom status to:\n VexCloud Free MCFA Generator",
        inline=False
    )
    embed.add_field(
        name="<a:tick:1462880393039712370> Step 2",
        value="You’re done! <a:GIVEAWAY:1462743614550708294> You now have access to the Free Gen.",
        inline=False
    )
    embed.add_field(
        name="<a:rulebook:1462718828546101369> Important Notes",
        value="<a:Wrong:1462880110334972038> Don’t ping any staff for this.\n<a:ticket:1462887294112628776> Need help? Create a ticket in <#1488040341914255360>\n<a:warn:1462880264026980595> Improper custom status = No access granted.",
        inline=False
    )
    embed.set_footer(text=f"Free MCFA Generator • Vex • Requested by {ctx.author.name}")
    await ctx.reply(embed=embed)

# --------------------------
# 🚮 CLEAR ALL ACCOUNTS COMMAND
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def clearacc(ctx, vault: str, *, service_name: str):
    vault = vault.capitalize()
    folder_path = os.path.join(STOCK_FOLDER, vault)
    file_path = os.path.join(folder_path, f"{service_name}.txt")

    if vault not in ["Free", "Premium"]:
        return await ctx.send("<a:Wrong:1462880110334972038> Invalid vault! Use Free or Premium.")
    if not os.path.exists(file_path):
        return await ctx.send(f"<a:warn:1462880264026980595>️ No stock file found for {service_name} in {vault} vault.")

    open(file_path, "w").close()
    embed = discord.Embed(
        title="<:dustbin:1462880808787247238>️ All Accounts Cleared",
        description=f"All accounts for **{service_name}** in {vault} vault have been removed.",
        color=discord.Color.red()
    )
    embed.set_footer(text=f"Action performed by {ctx.author.name}")
    await ctx.send(embed=embed)

# --------------------------
# Admin Command Help
# --------------------------
# --------------------------
# 🛠️ ADMIN HELP COMMAND
# --------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def cmdhelp(ctx):
    embed = discord.Embed(
        title="<a:Admin_:1462885585340600323> VexCloud Bot • Admin Commands",
        description="Here’s the complete admin command list:",
        color=discord.Color.orange()
    )

    embed.add_field(
        name="📦 Stock Management",
        value=(
            "`&addservice <vault> <service>` ➜ Add a service\n"
            "`&removeservice <vault> <service>` ➜ Remove a service\n"
            "`&restock <vault> <service>` ➜ Restock a service with txt file\n"
            "`&clearacc <vault> <service>` ➜ Clear all accounts of a service\n"
            "`&stockanalytics` ➜ View service usage analytics"
        ),
        inline=False
    )

    embed.add_field(
        name="💰 Credit Management",
        value=(
            "`&addcredits @user <amount>` ➜ Add credits to a user\n"
            "`&removecredits @user <amount>` ➜ Remove credits from a user"
        ),
        inline=False
    )

    embed.add_field(
        name="🚫 Moderation",
        value=(
            "`&blacklist @user [reason]` ➜ Blacklist a user\n"
            "`&unblacklist @user` ➜ Remove blacklist\n"
            "`&isblacklisted [user]` ➜ Check blacklist status"
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Channel Setup",
        value=(
            "`&setalertchannel #channel` ➜ Set low stock alert channel\n"
            "`&setannouncechannel #channel` ➜ Set restock announcement channel"
        ),
        inline=False
    )

    embed.add_field(
        name="💾 Backup Tools",
        value=(
            "`&backup` ➜ Create a manual backup\n"
            "`&listbackups` ➜ View latest backups"
        ),
        inline=False
    )

    embed.add_field(
        name="🎁 Extra / Utility",
        value=(
            "`&pay @user <amount> nitro` ➜ Send generated nitro file\n"
            "`&payall <amount> nitro` ➜ Send nitro file to all users\n"
            "`&dtest` ➜ DM test command"
        ),
        inline=False
    )

    embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

# ----------------- PAY COMMAND -----------------
@bot.command()
@commands.cooldown(1, 10, commands.BucketType.user)  # 10s cooldown
async def pay(ctx, member: discord.Member, amount: int, item: str):
    item = item.lower()

    if item != "nitro":
        return await ctx.send("<a:Wrong:1462880110334972038> Only `nitro` payments are supported!")
    
    if amount < 1 or amount > MAX_AMOUNT:
        return await ctx.send(f"<a:warn:1462880264026980595> Amount must be between 1–{MAX_AMOUNT}.")

    # Command delete (optional)
    # await ctx.message.delete(delay=5)

    # Initial embed
    embed = discord.Embed(
        title="<a:card:1462886279946436738> Processing Payment…",
        description=f"Generating **{amount} Nitro codes** for {member.mention}\nPlease wait…",
        color=discord.Color.yellow()
    )
    msg = await ctx.send(embed=embed)

    # Simulate progress
    steps = min(amount, 20)
    for i in range(steps + 1):
        embed.description = (
            f"Generating **{amount} Nitro codes** for {member.mention}\n"
            f"{progress_bar(i, steps)}"
        )
        await msg.edit(embed=embed)
        await asyncio.sleep(0.15)

    # Generate codes
    codes = [f"https://discord.gift/{generate_fake_nitro()}" for _ in range(amount)]

    # Write codes to TXT
    filename = f"{member.id}_nitro.txt"
    async with aiofiles.open(filename, "w") as f:
        await f.write("\n".join(codes))

    # DM Embed
    dm_embed = discord.Embed(
        title="<a:GIVEAWAY:1462743614550708294> You've Received a Nitro Drop!",
        description=(
            f"<a:users:1462883460904517817> From: {ctx.author.mention}\n"
            f"<a:restock:1462742077984210975> Amount: `{amount}` fake Nitro codes\n\n"
            "Your file is attached below. Enjoy your drop! <a:78116greensparkle:1462875294640902293>"
        ),
        color=discord.Color.green()
    )
    dm_embed.set_footer(text="Nitro Delivery System")

    try:
        await member.send(embed=dm_embed, file=discord.File(filename))
    except:
        return await ctx.send("<a:Wrong:1462880110334972038> Unable to DM this user! They might have DMs off.")

    # Success embed in channel
    success_embed = discord.Embed(
        title="<a:tick:1462880393039712370> Payment Successful!",
        description=f"<a:GIVEAWAY:1462743614550708294> Successfully delivered **{amount} Nitro codes** to {member.mention}!\n<a:Admin_:1462885585340600323> Check your DMs!",
        color=discord.Color.blue()
    )
    success_embed.set_footer(text="Operation completed ✔")
    await msg.edit(embed=success_embed)

    # Log channel
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        log_embed = discord.Embed(
            title="<:Money:1462885457254940815> Nitro Payment Log",
            description=(
                f"<a:free:1462885348584456212> **From:** {ctx.author} (`{ctx.author.id}`)\n"
                f"<a:users:1462883460904517817> **To:** {member} (`{member.id}`)\n"
                f"<a:restock:1462742077984210975> **Amount:** {amount} Nitro codes"
            ),
            color=discord.Color.purple()
        )
        await log_channel.send(embed=log_embed)

    # Remove file
    os.remove(filename)
    
@bot.command()
@commands.has_permissions(administrator=True)   # only admins can run it
async def payall(ctx, amount: int, item: str):
    item = item.lower()

    if item != "nitro":
        return await ctx.send("<a:Wrong:1462880110334972038> Only `nitro` is supported in payall!")

    if amount < 1 or amount > MAX_AMOUNT:
        return await ctx.send(f"⚠ Amount must be between 1–{MAX_AMOUNT}.")

    await ctx.send(f"<a:rocket_gif:1462882281168568444> Starting **PayAll Nitro Drop** for **{len(ctx.guild.members)} users**…")

    success = 0
    failed = 0

    for member in ctx.guild.members:
        if member.bot:
            continue  # skip bots

        # generate codes
        codes = [f"https://discord.gift/{generate_fake_nitro()}" for _ in range(amount)]

        # save to file
        filename = f"{member.id}_payall_nitro.txt"
        async with aiofiles.open(filename, "w") as f:
            await f.write("\n".join(codes))

        # try DM
        try:
            await member.send(
                f"<a:Giveaway:1462742290899533990> You received **{amount} Nitro codes** from **{ctx.guild.name}** PayAll event!",
                file=discord.File(filename)
            )
            success += 1
        except:
            failed += 1

        os.remove(filename)
        await asyncio.sleep(0.1)  # to avoid rate limits

    final_msg = (
        f"<a:GIVEAWAY:1462743614550708294> **PayAll Completed!**\n"
        f"<a:tick:1462880393039712370> Delivered: **{success}** users\n"
        f"<a:Wrong:1462880110334972038> Failed (DMs off): **{failed}** users"
    )

    await ctx.send(final_msg)

    # log channel
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"<a:ANNOUNCE:1462742222058557583> **PayAll Nitro Event Finished!**\nDelivered: {success} | Failed: {failed}")
        
@bot.command()
async def dtest(ctx):
    try:
        dm = await ctx.author.create_dm()
        await dm.send("DM working.")
        await ctx.reply("Done.")
    except Exception as e:
        await ctx.reply(f"Error: {e}")
        
# --------------------------
# 🔄 AUTO BACKUP TASK
# --------------------------
@tasks.loop(hours=24)
async def auto_backup_task():
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_path = os.path.join(BACKUP_FOLDER, f"backup_{timestamp}")
    os.makedirs(backup_path, exist_ok=True)

    files_to_backup = [
        SERVICES_FILE,
        USER_DATA_FILE,
        BLACKLIST_FILE,
        CONFIG_FILE,
        ANALYTICS_FILE
    ]

    for file_name in files_to_backup:
        if os.path.exists(file_name):
            shutil.copy2(file_name, os.path.join(backup_path, os.path.basename(file_name)))

    stock_backup_path = os.path.join(backup_path, "Stock")
    if os.path.exists(STOCK_FOLDER):
        shutil.copytree(STOCK_FOLDER, stock_backup_path, dirs_exist_ok=True)

    print(f"[AUTO BACKUP] Backup created at {backup_path}")
    
# --------------------------
# 📦 STOCK MONITOR TASK
# --------------------------
@tasks.loop(minutes=30)
async def stock_monitor_task():
    alert_channel_id = config.get("alert_channel_id", 0)
    if not alert_channel_id:
        return

    channel = bot.get_channel(alert_channel_id)
    if not channel:
        return

    services = load_services()
    threshold = config.get("low_stock_threshold", 5)

    low_stock_lines = []
    out_of_stock_lines = []

    for vault in ["Free", "Premium"]:
        vault_services = services.get(vault, [])
        vault_folder = os.path.join(STOCK_FOLDER, vault)
        os.makedirs(vault_folder, exist_ok=True)

        for service in vault_services:
            file_path = os.path.join(vault_folder, f"{service}.txt")

            count = 0
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    count = sum(1 for line in f if line.strip())

            if count == 0:
                out_of_stock_lines.append(f"• **{service}** (`{vault}`)")
            elif count <= threshold:
                low_stock_lines.append(f"• **{service}** (`{vault}`) — `{count}` left")

    if not low_stock_lines and not out_of_stock_lines:
        return

    embed = discord.Embed(
        title="<a:warn:1462880264026980595> Stock Monitoring Report",
        color=discord.Color.orange()
    )

    if out_of_stock_lines:
        embed.add_field(
            name="🔴 Out of Stock",
            value="\n".join(out_of_stock_lines)[:1024],
            inline=False
        )

    if low_stock_lines:
        embed.add_field(
            name="🟡 Low Stock",
            value="\n".join(low_stock_lines)[:1024],
            inline=False
        )

    embed.add_field(
        name="Threshold",
        value=f"`{threshold}`",
        inline=False
    )
    embed.set_footer(text="Automatic stock monitor • Runs every 30 minutes")

    await channel.send(embed=embed)
    
# --------------------------
# 🚀 READY EVENT
# --------------------------
@bot.event
async def on_ready():
    global dm_worker_started
    print(f"✅ Logged in as {bot.user}")

    if not dm_worker_started:
        asyncio.create_task(dm_worker())
        dm_worker_started = True

    if not auto_backup_task.is_running():
        auto_backup_task.start()

    if not stock_monitor_task.is_running():
        stock_monitor_task.start()

# --------------------------
# RUN BOT
# --------------------------
bot.run(config["token"])