import discord
from discord.ext import commands
import sqlite3
import asyncio
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="+", intents=intents)

conn = sqlite3.connect("messages.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS message_counts (
    user_id INTEGER,
    guild_id INTEGER,
    channel_id INTEGER,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id, channel_id)
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS event_counts (
    user_id INTEGER,
    guild_id INTEGER,
    channel_id INTEGER,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, guild_id, channel_id)
)
""")
conn.commit()

# guild_id -> {"end_time": datetime, "channel_id": int, "task": asyncio.Task, "name": str}
active_events = {}


@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    cursor.execute("""
        INSERT INTO message_counts (user_id, guild_id, channel_id, count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id, guild_id, channel_id)
        DO UPDATE SET count = count + 1
    """, (message.author.id, message.guild.id, message.channel.id))

    # Agar is server me event chal raha hai, to event counter bhi badhao
    if message.guild.id in active_events:
        cursor.execute("""
            INSERT INTO event_counts (user_id, guild_id, channel_id, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, guild_id, channel_id)
            DO UPDATE SET count = count + 1
        """, (message.author.id, message.guild.id, message.channel.id))

    conn.commit()

    await bot.process_commands(message)


@bot.command()
async def hello(ctx):
    await ctx.send("Hello! Main tumhara bot hoon 🤖")


def build_stats_embed(target, rows, color):
    total = sum(r[1] for r in rows)
    embed = discord.Embed(
        title=f"📊 Stats — {target.display_name}",
        description=f"**Total Messages:** {total}",
        color=color,
        timestamp=datetime.now()
    )
    embed.set_thumbnail(url=target.display_avatar.url)

    channel_text = ""
    for channel_id, count in rows[:15]:
        channel = target.guild.get_channel(channel_id)
        name = channel.mention if channel else f"Unknown ({channel_id})"
        channel_text += f"{name} — **{count}** messages\n"

    embed.add_field(name="Channel-wise Breakdown", value=channel_text or "No data", inline=False)
    embed.set_footer(text=f"Requested for {target.display_name}", icon_url=target.display_avatar.url)
    return embed


@bot.command()
async def mystats(ctx):
    """Apna total aur channel-wise message count dekho"""
    cursor.execute("""
        SELECT channel_id, count FROM message_counts
        WHERE user_id = ? AND guild_id = ?
        ORDER BY count DESC
    """, (ctx.author.id, ctx.guild.id))
    rows = cursor.fetchall()

    if not rows:
        await ctx.send("Abhi tak koi message record nahi mila.")
        return

    embed = build_stats_embed(ctx.author, rows, discord.Color.blue())
    await ctx.send(embed=embed)


@bot.command()
async def userstats(ctx, member: discord.Member):
    """Kisi specific user ka channel-wise breakdown dekho"""
    cursor.execute("""
        SELECT channel_id, count FROM message_counts
        WHERE user_id = ? AND guild_id = ?
        ORDER BY count DESC
    """, (member.id, ctx.guild.id))
    rows = cursor.fetchall()

    if not rows:
        embed = discord.Embed(
            description=f"{member.mention} ka koi record nahi mila.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    embed = build_stats_embed(member, rows, discord.Color.green())
    await ctx.send(embed=embed)


@bot.command()
async def leaderboard(ctx):
    """Server ka top 10 message leaderboard"""
    cursor.execute("""
        SELECT user_id, SUM(count) as total FROM message_counts
        WHERE guild_id = ?
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 10
    """, (ctx.guild.id,))
    rows = cursor.fetchall()

    if not rows:
        await ctx.send("Abhi tak koi data nahi hai.")
        return

    medals = ["🥇", "🥈", "🥉"]
    embed = discord.Embed(
        title="🏆 Message Leaderboard",
        description=f"Top members in **{ctx.guild.name}**",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )

    lb_text = ""
    for i, (user_id, total) in enumerate(rows):
        member = ctx.guild.get_member(user_id)
        name = member.display_name if member else f"Unknown ({user_id})"
        prefix = medals[i] if i < 3 else f"**{i+1}.**"
        lb_text += f"{prefix} {name} — **{total}** messages\n"

    embed.add_field(name="Rankings", value=lb_text, inline=False)
    top_member = ctx.guild.get_member(rows[0][0])
    if top_member:
        embed.set_thumbnail(url=top_member.display_avatar.url)
    embed.set_footer(text=f"Total tracked members: {len(rows)}")

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def resetuser(ctx, member: discord.Member):
    """Kisi specific user ka data reset karo (admin only)"""
    cursor.execute("""
        DELETE FROM message_counts
        WHERE user_id = ? AND guild_id = ?
    """, (member.id, ctx.guild.id))
    conn.commit()

    embed = discord.Embed(
        description=f"✅ {member.mention} ka message data reset kar diya gaya.",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def resetleaderboard(ctx):
    """Poore server ka leaderboard reset karo (admin only)"""
    embed = discord.Embed(
        title="⚠️ Confirm Reset",
        description="Kya tum sach me **poore server** ka leaderboard reset karna chahte ho?\n"
                     "Reply karo `yes` 30 seconds ke andar confirm karne ke liye.",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "yes"

    try:
        await bot.wait_for("message", check=check, timeout=30.0)
    except Exception:
        await ctx.send("❌ Reset cancel ho gaya (timeout).")
        return

    cursor.execute("""
        DELETE FROM message_counts
        WHERE guild_id = ?
    """, (ctx.guild.id,))
    conn.commit()

    confirm_embed = discord.Embed(
        description="✅ Poore server ka leaderboard reset kar diya gaya.",
        color=discord.Color.orange()
    )
    await ctx.send(embed=confirm_embed)


@resetuser.error
async def resetuser_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Ye command sirf admins use kar sakte hain.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Wo user nahi mila. Sahi tarike se mention karo (@username).")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Kisi member ko mention karo. Example: `+resetuser @username`")


def parse_duration(duration_str):
    """
    Duration string ko seconds me convert karta hai.
    Supported formats: '30m' (minutes), '5h' (hours), '2d' (days)
    Agar sirf number diya (jaise '30'), to use minutes maana jayega.
    Return: (seconds, human_readable_text) ya None agar invalid format hai
    """
    duration_str = duration_str.strip().lower()

    unit_map = {
        "m": ("minute(s)", 60),
        "h": ("hour(s)", 3600),
        "d": ("day(s)", 86400),
    }

    if duration_str and duration_str[-1] in unit_map:
        unit_char = duration_str[-1]
        number_part = duration_str[:-1]
    else:
        unit_char = "m"  # default: minutes
        number_part = duration_str

    try:
        value = float(number_part)
    except ValueError:
        return None

    if value <= 0:
        return None

    label, multiplier = unit_map[unit_char]
    seconds = value * multiplier
    readable = f"{number_part} {label}"
    return seconds, readable


@resetleaderboard.error
async def resetleaderboard_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Ye command sirf admins use kar sakte hain.")


def build_event_leaderboard_embed(guild, event_name, finished=True):
    """Event ke messages se leaderboard embed banata hai"""
    cursor.execute("""
        SELECT user_id, SUM(count) as total FROM event_counts
        WHERE guild_id = ?
        GROUP BY user_id
        ORDER BY total DESC
        LIMIT 10
    """, (guild.id,))
    rows = cursor.fetchall()

    title = f"🏁 Event Ended — {event_name}" if finished else f"📊 Live Standings — {event_name}"
    embed = discord.Embed(
        title=title,
        description=f"Event message leaderboard for **{guild.name}**",
        color=discord.Color.purple() if finished else discord.Color.blue(),
        timestamp=datetime.now()
    )

    if not rows:
        embed.add_field(name="Rankings", value="Is event me abhi tak koi message nahi aaya.", inline=False)
        return embed

    medals = ["🥇", "🥈", "🥉"]
    lb_text = ""
    for i, (user_id, total) in enumerate(rows):
        member = guild.get_member(user_id)
        name = member.display_name if member else f"Unknown ({user_id})"
        prefix = medals[i] if i < 3 else f"**{i+1}.**"
        lb_text += f"{prefix} {name} — **{total}** messages\n"

    embed.add_field(name="Rankings", value=lb_text, inline=False)

    top_member = guild.get_member(rows[0][0])
    if top_member:
        embed.set_thumbnail(url=top_member.display_avatar.url)

    return embed


async def run_event_timer(guild_id, seconds, channel_id, event_name):
    """Background task: wait karta hai, phir automatically leaderboard post karta hai"""
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return  # event manually end kiya gaya, is task ko yahi rukna hai

    guild = bot.get_guild(guild_id)
    channel = guild.get_channel(channel_id) if guild else None

    if guild and channel:
        embed = build_event_leaderboard_embed(guild, event_name, finished=True)
        await channel.send(f"⏰ **{event_name}** khatam ho gaya! Final leaderboard:", embed=embed)

    active_events.pop(guild_id, None)


@bot.command()
@commands.has_permissions(administrator=True)
async def startevent(ctx, duration: str, *, event_name: str = "Chat Event"):
    """Naya chat event start karo.
    Examples:
      +startevent 30m Quick Chat        -> 30 minutes
      +startevent 5h Movie Night Chat   -> 5 hours
      +startevent 2d Weekend Fest       -> 2 days
    """
    if ctx.guild.id in active_events:
        await ctx.send("❌ Is server me pehle se ek event chal raha hai. Pehle `+endevent` karo.")
        return

    parsed = parse_duration(duration)
    if parsed is None:
        await ctx.send(
            "❌ Duration ka format galat hai.\n"
            "Use karo: `30m` (minutes), `5h` (hours), ya `2d` (days)\n"
            "Example: `+startevent 2d Weekend Chat Fest`"
        )
        return

    seconds, readable = parsed

    # Purana event data clear karo taaki naya event fresh se start ho
    cursor.execute("DELETE FROM event_counts WHERE guild_id = ?", (ctx.guild.id,))
    conn.commit()

    end_time = datetime.now() + timedelta(seconds=seconds)
    task = bot.loop.create_task(
        run_event_timer(ctx.guild.id, seconds, ctx.channel.id, event_name)
    )

    active_events[ctx.guild.id] = {
        "end_time": end_time,
        "channel_id": ctx.channel.id,
        "task": task,
        "name": event_name
    }

    end_time_str = end_time.strftime('%d %b, %I:%M %p')
    embed = discord.Embed(
        title=f"🎉 Event Started — {event_name}",
        description=f"Duration: **{readable}**\n"
                     f"Ends at: **{end_time_str}**\n\n"
                     f"Ab se jab tak event chalega, sabke messages count honge. "
                     f"Time khatam hote hi is channel me automatically leaderboard aa jayegi!",
        color=discord.Color.teal(),
        timestamp=datetime.now()
    )
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(administrator=True)
async def endevent(ctx):
    """Chalte hue event ko manually khatam karo aur turant leaderboard dikhao"""
    if ctx.guild.id not in active_events:
        await ctx.send("❌ Is server me abhi koi event chal nahi raha.")
        return

    event = active_events.pop(ctx.guild.id)
    event["task"].cancel()  # background timer rok do

    embed = build_event_leaderboard_embed(ctx.guild, event["name"], finished=True)
    await ctx.send(f"🛑 **{event['name']}** manually end kiya gaya. Final leaderboard:", embed=embed)


@bot.command()
async def eventstatus(ctx):
    """Active event ki current standing aur bacha hua time dekho"""
    if ctx.guild.id not in active_events:
        await ctx.send("❌ Is server me abhi koi event chal nahi raha.")
        return

    event = active_events[ctx.guild.id]
    remaining = event["end_time"] - datetime.now()
    total_seconds = max(int(remaining.total_seconds()), 0)

    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    time_left_str = " ".join(parts)

    embed = build_event_leaderboard_embed(ctx.guild, event["name"], finished=False)
    embed.description += f"\n⏳ Time remaining: **{time_left_str}**"
    await ctx.send(embed=embed)


@startevent.error
async def startevent_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Ye command sirf admins use kar sakte hain.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Sahi format: `+startevent <duration> <event naam (optional)>`\n"
            "Duration: `30m`, `5h`, ya `2d`\n"
            "Example: `+startevent 2d Weekend Chat Fest`"
        )


@endevent.error
async def endevent_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Ye command sirf admins use kar sakte hain.")


bot.run("YOUR_BOT_TOKEN")
