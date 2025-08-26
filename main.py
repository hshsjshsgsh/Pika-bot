import discord
from discord.ext import commands
import os
import random
import asyncio
import json
from datetime import datetime, timedelta
from keep_alive import keep_alive

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

class Tournament:
    def __init__(self):
        self.players = []
        self.teams = {}  # {user_id: team_partner_id}
        self.team_invites = {}  # {user_id: inviter_id}
        self.max_players = 0
        self.active = False
        self.channel = None
        self.target_channel = None
        self.message = None
        self.rounds = []
        self.results = []
        self.eliminated = []  # Track eliminated players for placement
        self.fake_count = 1
        self.map = ""
        self.abilities = ""
        self.mode = ""
        self.prize = ""
        self.title = ""

def get_tournament(guild_id):
    """Get tournament for specific guild"""
    if guild_id not in tournaments:
        tournaments[guild_id] = Tournament()
    return tournaments[guild_id]

# Store user data (all server-specific)
user_data = {}  # {guild_id: {user_id: ign}}
tickets = {}  # {guild_id: {channel_id: user_id}}
warnings = {}  # {guild_id: {user_id: [warnings]}}
user_levels = {}  # {guild_id: {user_id: {xp: int, level: int}}}
tp_data = {}  # {guild_id: {user_id: tp_amount}} # Renamed to sp_data for Seasonal Points
sp_data = {} # {guild_id: {user_id: sp_amount}} # Seasonal Points data
bracket_roles = {}  # {guild_id: {user_id: [emoji1, emoji2, emoji3]}}
host_registrations = {}  # {guild_id: {'active': bool, 'max_hosters': int, 'hosters': [], 'channel': None, 'message': None}}
leveling_settings = {}  # {guild_id: {'enabled': bool, 'channel': int}}
welcomer_settings = {}  # {guild_id: {'enabled': bool, 'channel': int}}
automod_settings = {}  # {guild_id: {'enabled': bool, 'spam_detection': bool, 'bad_words': bool, 'log_channel': int}}
tournaments = {}  # {guild_id: Tournament}

# Bad words list for automod
BAD_WORDS = [
    'fuck', 'shit', 'bitch', 'damn', 'ass', 'bastard', 'crap', 'piss',
    'cock', 'dick', 'pussy', 'whore', 'slut', 'nigger', 'nigga', 'faggot',
    'retard', 'gay', 'lesbian', 'homo', 'tranny', 'nazi', 'hitler',
    'kill yourself', 'kys', 'suicide', 'die', 'cancer', 'AIDS', 'rape'
]

# Spam tracking
user_message_history = {}  # {guild_id: {user_id: [(timestamp, content)]}}

TP_RANKS = { # Ranks based on Tournament Points, will be adapted for Seasonal Points
    'Wood': (0, 300),
    'Bronze': (301, 600),
    'Silver': (601, 900),
    'Gold': (901, 1200),
    'Platinum': (1201, 1500),
    'Master': (1501, 1800),
    'Champion': (1801, float('inf'))
}

def get_rank_from_tp(tp):
    for rank, (min_tp, max_tp) in TP_RANKS.items():
        if min_tp <= tp <= max_tp:
            return rank
    return 'Wood'

def get_player_display_name(player, guild_id=None):
    """Get player display name with bracket roles (emojis) if set"""
    if isinstance(player, FakePlayer):
        return player.display_name

    # Priority: nick > display_name > name > str(player)
    base_name = ""
    if hasattr(player, 'user.name') and player.user.name:
        base_name = player.user.name
    elif hasattr(player, 'user.name'):
        base_name = player.user.name
    elif hasattr(player, 'user.name'):
        base_name = player.user.name
    else:
        base_name = str(player)

    # Add bracket role emojis if user has them (after name, not before)
    if guild_id:
        guild_str = str(guild_id)
        if guild_str in bracket_roles and str(player.id) in bracket_roles[guild_str]:
            emojis = ''.join(bracket_roles[guild_str][str(player.id)])
            return f"{base_name} {emojis}"

    return base_name

# Load data
def load_data():
    global user_data, user_levels, leveling_settings, welcomer_settings, tp_data, bracket_roles, automod_settings, sp_data, host_roles, admin_roles
    try:
        with open('user_data.json', 'r') as f:
            data = json.load(f)
            user_data = data.get('user_data', {})
            user_levels = data.get('user_levels', {})
            tp_data = data.get('tp_data', {}) # Keeping tp_data for compatibility if needed, but sp_data is the primary
            sp_data = data.get('sp_data', {}) # Load Seasonal Points data
            bracket_roles = data.get('bracket_roles', {})
            leveling_settings = data.get('leveling_settings', {})
            welcomer_settings = data.get('welcomer_settings', {})
            automod_settings = data.get('automod_settings', {})
            host_roles = data.get('host_roles', {})
            admin_roles = data.get('admin_roles', {})
    except FileNotFoundError:
        pass

def save_data():
    data = {
        'user_data': user_data,
        'user_levels': user_levels,
        'tp_data': tp_data, # Keep tp_data for now
        'sp_data': sp_data, # Save Seasonal Points data
        'bracket_roles': bracket_roles,
        'leveling_settings': leveling_settings,
        'welcomer_settings': welcomer_settings,
        'automod_settings': automod_settings,
        'host_roles': host_roles,
        'admin_roles': admin_roles
    }
    with open('user_data.json', 'w') as f:
        json.dump(data, f)

def check_spam(guild_id, user_id, message_content):
    """Check if user is spamming (more than 3 same messages in 10 seconds)"""
    if guild_id not in user_message_history:
        user_message_history[guild_id] = {}

    if user_id not in user_message_history[guild_id]:
        user_message_history[guild_id][user_id] = []

    now = datetime.now().timestamp()

    # Remove messages older than 10 seconds
    user_message_history[guild_id][user_id] = [
        (timestamp, content) for timestamp, content in user_message_history[guild_id][user_id]
        if now - timestamp < 10
    ]

    # Add current message
    user_message_history[guild_id][user_id].append((now, message_content))

    # Count same messages in the last 10 seconds
    same_message_count = sum(1 for _, content in user_message_history[guild_id][user_id] if content == message_content)

    # Check if user sent more than 3 same messages in 10 seconds
    return same_message_count > 3

def contains_bad_words(text):
    """Check if message contains bad words"""
    text_lower = text.lower()
    for bad_word in BAD_WORDS:
        if bad_word in text_lower:
            return True, bad_word
    return False, None

def add_xp(guild_id, user_id, xp=1):
    guild_str = str(guild_id)
    user_str = str(user_id)

    if guild_str not in user_levels:
        user_levels[guild_str] = {}

    if user_str not in user_levels[guild_str]:
        user_levels[guild_str][user_str] = {'xp': 0, 'level': 1}

    user_levels[guild_str][user_str]['xp'] += xp

    # Calculate level (100 XP per level)
    new_level = (user_levels[guild_str][user_str]['xp'] // 100) + 1
    old_level = user_levels[guild_str][user_str]['level']

    if new_level > old_level:
        user_levels[guild_str][user_str]['level'] = new_level
        return True, new_level

    user_levels[guild_str][user_str]['level'] = new_level
    return False, new_level

def add_tp(guild_id, user_id, tp): # Function for Tournament Points, kept for compatibility
    guild_str = str(guild_id)
    user_str = str(user_id)

    if guild_str not in tp_data:
        tp_data[guild_str] = {}

    if user_str not in tp_data[guild_str]:
        tp_data[guild_str][user_str] = 0

    tp_data[guild_str][user_str] += tp
    save_data()

def add_sp(guild_id, user_id, sp): # Function for Seasonal Points
    guild_str = str(guild_id)
    user_str = str(user_id)

    if guild_str not in sp_data:
        sp_data[guild_str] = {}

    if user_str not in sp_data[guild_str]:
        sp_data[guild_str][user_str] = 0

    sp_data[guild_str][user_str] += sp
    save_data()

@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    load_data()

    # Add persistent views for buttons to work after restart
    bot.add_view(TournamentView())
    bot.add_view(TicketView())
    bot.add_view(AccountView())
    bot.add_view(TournamentConfigView(None))
    bot.add_view(HosterRegistrationView())
    bot.add_view(RegionPanelView())
    bot.add_view(ExperiencePersonalizerView())

    print("🔧 Bot is ready and all systems operational!")

class ExperiencePersonalizerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(emoji="🇪🇺", label="EU", style=discord.ButtonStyle.secondary, custom_id="exp_eu")
    async def select_eu(self, interaction: discord.Interaction, button: discord.ui.Button):
        eu_role = discord.utils.get(interaction.guild.roles, name="EU")
        member_role = discord.utils.get(interaction.guild.roles, name="👥・Member")

        if not eu_role:
            return await interaction.response.send_message("❌ EU role not found!", ephemeral=True)

        # Remove other region roles
        region_roles = ["ASIA", "INW", "US"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            roles_to_add = [eu_role]
            if member_role:
                roles_to_add.append(member_role)
            await interaction.user.add_roles(*roles_to_add)
            await interaction.response.send_message(f"✅ Welcome! You now have the {eu_role.mention} role and are ready to participate!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

    @discord.ui.button(emoji="🌏", label="ASIA", style=discord.ButtonStyle.secondary, custom_id="exp_asia")
    async def select_asia(self, interaction: discord.Interaction, button: discord.ui.Button):
        asia_role = discord.utils.get(interaction.guild.roles, name="ASIA")
        member_role = discord.utils.get(interaction.guild.roles, name="👥・Member")

        if not asia_role:
            return await interaction.response.send_message("❌ ASIA role not found!", ephemeral=True)

        # Remove other region roles
        region_roles = ["EU", "INW", "US"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            roles_to_add = [asia_role]
            if member_role:
                roles_to_add.append(member_role)
            await interaction.user.add_roles(*roles_to_add)
            await interaction.response.send_message(f"✅ Welcome! You now have the {asia_role.mention} role and are ready to participate!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

    @discord.ui.button(emoji="🇮🇳", label="INW", style=discord.ButtonStyle.secondary, custom_id="exp_inw")
    async def select_inw(self, interaction: discord.Interaction, button: discord.ui.Button):
        inw_role = discord.utils.get(interaction.guild.roles, name="INW")
        member_role = discord.utils.get(interaction.guild.roles, name="👥・Member")

        if not inw_role:
            return await interaction.response.send_message("❌ INW role not found!", ephemeral=True)

        # Remove other region roles
        region_roles = ["EU", "ASIA", "US"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            roles_to_add = [inw_role]
            if member_role:
                roles_to_add.append(member_role)
            await interaction.user.add_roles(*roles_to_add)
            await interaction.response.send_message(f"✅ Welcome! You now have the {inw_role.mention} role and are ready to participate!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

    @discord.ui.button(emoji="🇺🇸", label="US", style=discord.ButtonStyle.secondary, custom_id="exp_us")
    async def select_us(self, interaction: discord.Interaction, button: discord.ui.Button):
        us_role = discord.utils.get(interaction.guild.roles, name="US")
        member_role = discord.utils.get(interaction.guild.roles, name="👥・Member")

        if not us_role:
            return await interaction.response.send_message("❌ US role not found!", ephemeral=True)

        # Remove other region roles
        region_roles = ["EU", "ASIA", "INW"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            roles_to_add = [us_role]
            if member_role:
                roles_to_add.append(member_role)
            await interaction.user.add_roles(*roles_to_add)
            await interaction.response.send_message(f"✅ Welcome! You now have the {us_role.mention} role and are ready to participate!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

@bot.event
async def on_member_join(member):
    guild_id = str(member.guild.id)

    # Send experience personalizer
    try:
        embed = discord.Embed(
            title="🌟 Let's personalize your experience!",
            description=f"Welcome to **{member.guild.name}**, {member.mention}!\n\n**On what server do you play?**\nSelect your region below to get started and connect with players from your area:",
            color=0x3498db
        )
        embed.add_field(
            name="🌍 Available Regions:",
            value="🇪🇺 **EU** - Europe\n🌏 **ASIA** - Asia Pacific\n🇮🇳 **INW** - India\n🇺🇸 **US** - United States",
            inline=False
        )
        embed.set_footer(text="Choose your region to complete your server setup!")

        view = ExperiencePersonalizerView()
        await member.send(embed=embed, view=view)
    except discord.Forbidden:
        # If can't send DM, try to send in welcome channel
        if guild_id in welcomer_settings and welcomer_settings[guild_id]['enabled'] and welcomer_settings[guild_id]['channel']:
            channel = bot.get_channel(welcomer_settings[guild_id]['channel'])
            if channel:
                embed = discord.Embed(
                    title="🌟 Let's personalize your experience!",
                    description=f"Welcome to **{member.guild.name}**, {member.mention}!\n\n**On what server do you play?**\nSelect your region below to get started:",
                    color=0x3498db
                )
                embed.add_field(
                    name="🌍 Available Regions:",
                    value="🇪🇺 **EU** - Europe\n🌏 **ASIA** - Asia Pacific\n🇮🇳 **INW** - India\n🇺🇸 **US** - United States",
                    inline=False
                )
                view = ExperiencePersonalizerView()
                await channel.send(embed=embed, view=view)

    # Send welcome message if welcomer is enabled
    if guild_id in welcomer_settings and welcomer_settings[guild_id]['enabled'] and welcomer_settings[guild_id]['channel']:
        channel = bot.get_channel(welcomer_settings[guild_id]['channel'])
        if channel:
            embed = discord.Embed(
                title="🎉 Welcome!",
                description=f"Welcome {member.mention} to **{member.guild.name}**!\n\nWe're happy to have you here! Make sure to read the rules and have fun!",
                color=0x00ff00
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Member #{len(member.guild.members)}")
            await channel.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = str(message.guild.id)

    # Automod system
    if guild_id in automod_settings and automod_settings[guild_id]['enabled']:
        should_delete = False
        violation_reason = ""

        # Check for spam
        if automod_settings[guild_id]['spam_detection'] and check_spam(message.guild.id, message.author.id, message.content):
            should_delete = True
            violation_reason = "Spam Detection (3+ same messages)"

            # Timeout user for 5 minutes for spam
            try:
                await message.author.timeout(timedelta(minutes=5), reason="Spam detected by automod")
            except discord.Forbidden:
                pass

        # Check for bad words
        if not should_delete and automod_settings[guild_id]['bad_words']:
            contains_bad, bad_word = contains_bad_words(message.content)
            if contains_bad:
                should_delete = True
                violation_reason = f"Bad word detected: {bad_word}"

                # Warn user
                if str(message.author.id) not in warnings:
                    warnings[str(message.author.id)] = []

                warnings[str(message.author.id)].append({
                    'reason': f"Automod: Used inappropriate language ({bad_word})",
                    'moderator': bot.user.id,
                    'timestamp': datetime.now().isoformat()
                })

        # Delete message if violation found
        if should_delete:
            try:
                await message.delete()

                # Send warning to user
                try:
                    embed = discord.Embed(
                        title="⚠️ Automod Warning",
                        description=f"Your message was deleted due to: **{violation_reason}**\n\nPlease follow the server rules.",
                        color=0xff0000
                    )
                    await message.author.send(embed=embed)
                except discord.Forbidden:
                    pass

                # Log to automod channel if set
                if automod_settings[guild_id]['log_channel']:
                    log_channel = bot.get_channel(automod_settings[guild_id]['log_channel'])
                    if log_channel:
                        embed = discord.Embed(
                            title="🛡️ Automod Action",
                            description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Reason:** {violation_reason}\n**Action:** Message deleted",
                            color=0xff6600
                        )
                        embed.add_field(name="Original Message", value=f"```{message.content[:1000]}```", inline=False)
                        embed.set_footer(text=f"User ID: {message.author.id}")
                        await log_channel.send(embed=embed)

                return  # Don't process commands if message was deleted
            except discord.NotFound:
                pass

    # Add XP for messages if leveling is enabled
    if guild_id in leveling_settings and leveling_settings[guild_id]['enabled'] and leveling_settings[guild_id]['channel']:
        leveled_up, level = add_xp(message.guild.id, message.author.id)
        if leveled_up:
            channel = bot.get_channel(leveling_settings[guild_id]['channel'])
            if channel:
                embed = discord.Embed(
                    title="🎉 Level Up!",
                    description=f"{message.author.mention} reached **Level {level}**!",
                    color=0xf1c40f
                )
                await channel.send(embed=embed)
        save_data()

    await bot.process_commands(message)

class TeamInviteView(discord.ui.View):
    def __init__(self, inviter_id, invited_id, guild_id):
        super().__init__(timeout=300)
        self.inviter_id = inviter_id
        self.invited_id = invited_id
        self.guild_id = guild_id

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.green)
    async def accept_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invited_id:
            return await interaction.response.send_message("❌ This invite is not for you!", ephemeral=True)

        tournament = get_tournament(self.guild_id)

        # Check if either player is already in a team
        if self.inviter_id in tournament.teams or self.invited_id in tournament.teams:
            embed = discord.Embed(
                title="❌ Team Formation Failed",
                description="One of you is already in a team!",
                color=0xff0000
            )
            return await interaction.response.edit_message(embed=embed, view=None)

        # Create team with correct user IDs
        tournament.teams[self.inviter_id] = self.invited_id
        tournament.teams[self.invited_id] = self.inviter_id

        # Remove all pending invites for both players
        if self.invited_id in tournament.team_invites:
            del tournament.team_invites[self.invited_id]
        if self.inviter_id in tournament.team_invites:
            del tournament.team_invites[self.inviter_id]

        embed = discord.Embed(
            title="🤝 Team Formed!",
            description=f"<@{self.inviter_id}> and <@{self.invited_id}> are now teammates!",
            color=0x00ff00
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.red)
    async def reject_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invited_id:
            return await interaction.response.send_message("❌ This invite is not for you!", ephemeral=True)

        tournament = get_tournament(self.guild_id)

        # Remove invite
        if self.invited_id in tournament.team_invites:
            del tournament.team_invites[self.invited_id]

        embed = discord.Embed(
            title="❌ Invite Rejected",
            description=f"<@{self.invited_id}> rejected the team invitation.",
            color=0xff0000
        )
        await interaction.response.edit_message(embed=embed, view=None)

class TournamentConfigModal(discord.ui.Modal, title="Tournament Configuration"):
    def __init__(self, target_channel):
        super().__init__()
        self.target_channel = target_channel

    title_field = discord.ui.TextInput(
        label="🏆 Tournament Title",
        placeholder="Enter tournament title...",
        default="",
        max_length=100
    )

    map_field = discord.ui.TextInput(
        label="🗺️ Map",
        placeholder="Enter map name...",
        default="",
        max_length=50
    )

    abilities_field = discord.ui.TextInput(
        label="💥 Abilities",
        placeholder="Enter abilities...",
        default="",
        max_length=100
    )

    mode_and_players_field = discord.ui.TextInput(
        label="🎮 Mode & Max Players",
        placeholder="2v2 8 (format: mode maxplayers)",
        default="",
        max_length=20
    )

    prize_field = discord.ui.TextInput(
        label="💶 Prize",
        placeholder="Enter prize...",
        default="",
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Validate target channel
            if not self.target_channel:
                await interaction.response.send_message("❌ Invalid target channel. Please try again.", ephemeral=True)
                return

            # Parse mode and max players
            mode_players_parts = self.mode_and_players_field.value.strip().split()
            if len(mode_players_parts) != 2:
                await interaction.response.send_message("❌ Format should be: mode maxplayers (e.g., '2v2 8')", ephemeral=True)
                return

            mode = mode_players_parts[0]
            max_players = int(mode_players_parts[1])

            if max_players not in [2, 4, 8, 16, 32]:
                await interaction.response.send_message("❌ Max players must be 2, 4, 8, 16 or 32!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Invalid format! Use: mode maxplayers (e.g., '2v2 8')", ephemeral=True)
            return
        except Exception as e:
            print(f"Error in tournament config modal: {e}")
            await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
            return

        # Get server-specific tournament and reset it
        tournament = get_tournament(interaction.guild.id)
        tournament.__init__()
        tournament.max_players = max_players
        tournament.channel = self.target_channel
        tournament.target_channel = self.target_channel
        tournament.title = self.title_field.value
        tournament.map = self.map_field.value
        tournament.abilities = self.abilities_field.value
        tournament.mode = mode
        tournament.prize = self.prize_field.value
        tournament.players = []
        tournament.teams = {}
        tournament.team_invites = {}
        tournament.eliminated = []
        tournament.active = False

        embed = discord.Embed(title=f"🏆 {tournament.title}", color=0x00ff00)
        embed.add_field(name="<:map:1409924163346370560> Map", value=tournament.map, inline=True)
        embed.add_field(name="<:abilities:1402690411759407185> Abilities", value=tournament.abilities, inline=True)
        embed.add_field(name="<:TrioIcon:1402690815771541685> Max Players", value=str(max_players), inline=True)
        embed.add_field(name="🎮 Mode", value=tournament.mode, inline=True)
        embed.add_field(name="<:LotsOfGems:1383151614940151908> Prize", value=tournament.prize, inline=True)

        # Enhanced Stumble Guys rules with colors
        rules_text = (
            "🔹 **NO TEAMING** - Teams are only allowed in designated team modes\n"
            "🔸 **NO GRIEFING** - Don't intentionally sabotage other players\n"
            "🔹 **NO EXPLOITING** - Use of glitches or exploits will result in disqualification\n"
            "🔸 **FAIR PLAY** - Respect all players and play honorably\n"
            "🔹 **NO RAGE QUITTING** - Leaving mid-match counts as a forfeit\n"
            "🔸 **FOLLOW HOST** - Listen to tournament host instructions\n"
            "🔹 **NO TOXICITY** - Keep chat friendly and respectful\n"
            "🔸 **BE READY** - Join matches promptly when called\n"
            "🔹 **NO ALTS** - One account per player only"
        )

        embed.add_field(name="<:notr:1409923674387251280> **{tournament.title} Rules**", value=rules_text, inline=False)

        view = TournamentView()
        # Update the participant count button to show correct max players
        for item in view.children:
            if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                if tournament.mode == "2v2":
                    item.label = f"0 teams/{max_players//2}"
                else:
                    item.label = f"0/{max_players}"
                break

        # Send tournament message
        tournament.message = await self.target_channel.send(embed=embed, view=view)

        # Respond with success
        await interaction.response.send_message("✅ Tournament created successfully!", ephemeral=True)

        print(f"✅ Tournament created: {max_players} max players, Map: {tournament.map}")

class TournamentConfigView(discord.ui.View):
    def __init__(self, target_channel=None):
        super().__init__(timeout=None)
        self.target_channel = target_channel

    @discord.ui.button(label="Set Tournament", style=discord.ButtonStyle.primary, custom_id="set_tournament_config")
    async def set_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if not has_admin_permission(interaction.user, interaction.guild):
                return await interaction.response.send_message("❌ You don't have permission to configure tournaments.", ephemeral=True)

            # Use the channel where the interaction happened if no target channel is set
            target_channel = self.target_channel or interaction.channel

            # Ensure we have a valid channel
            if not target_channel:
                return await interaction.response.send_message("❌ Unable to determine target channel. Please try again.", ephemeral=True)

            modal = TournamentConfigModal(target_channel)
            await interaction.response.send_modal(modal)
        except Exception as e:
            print(f"Error in set_tournament: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

class TournamentView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="tournament_register")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            tournament = get_tournament(interaction.guild.id)

            # Check tournament state
            if tournament.max_players == 0:
                return await interaction.response.send_message("❌ No tournament has been created yet.", ephemeral=True)
            if tournament.active:
                return await interaction.response.send_message("⚠️ Tournament already started.", ephemeral=True)
            if interaction.user in tournament.players:
                return await interaction.response.send_message("❌ You are already registered.", ephemeral=True)

            # For 2v2 mode, check team requirements
            if tournament.mode == "2v2":
                if interaction.user.id not in tournament.teams:
                    return await interaction.response.send_message("❌ You need a teammate to register for 2v2! Use `!invite @user` to invite someone.", ephemeral=True)

                teammate_id = tournament.teams[interaction.user.id]
                teammate = interaction.guild.get_member(teammate_id)

                # Check if teammate exists and is valid
                if not teammate:
                    return await interaction.response.send_message("❌ Your teammate is no longer in this server.", ephemeral=True)

                # Check if either team member is already registered
                if interaction.user in tournament.players or teammate in tournament.players:
                    return await interaction.response.send_message("❌ Your team is already registered.", ephemeral=True)

                # Check if there's space for both team members
                if len(tournament.players) + 2 > tournament.max_players:
                    return await interaction.response.send_message("❌ Tournament is full.", ephemeral=True)

                # Add both team members at the same time to prevent partial registration
                tournament.players.extend([interaction.user, teammate])

                # Update participant count for teams
                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        item.label = f"{len(tournament.players)//2} teams/{tournament.max_players//2}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ Team {interaction.user.display_name} & {teammate.display_name} registered! ({len(tournament.players)//2}/{tournament.max_players//2} teams)", ephemeral=True)

            else:
                # 1v1 mode
                if len(tournament.players) >= tournament.max_players:
                    return await interaction.response.send_message("❌ Tournament is full.", ephemeral=True)

                tournament.players.append(interaction.user)

                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        item.label = f"{len(tournament.players)}/{tournament.max_players}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ {interaction.user.display_name} registered! ({len(tournament.players)}/{tournament.max_players})", ephemeral=True)

        except Exception as e:
            print(f"Error in register_button: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

    @discord.ui.button(label="Unregister", style=discord.ButtonStyle.red, custom_id="tournament_unregister")
    async def unregister_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            tournament = get_tournament(interaction.guild.id)

            if tournament.max_players == 0:
                return await interaction.response.send_message("❌ No tournament has been created yet.", ephemeral=True)
            if tournament.active:
                return await interaction.response.send_message("⚠️ Tournament already started.", ephemeral=True)
            if interaction.user not in tournament.players:
                return await interaction.response.send_message("❌ You are not registered.", ephemeral=True)

            if tournament.mode == "2v2":
                teammate_id = tournament.teams[interaction.user.id]
                teammate = interaction.guild.get_member(teammate_id)

                # Remove both team members
                if interaction.user in tournament.players:
                    tournament.players.remove(interaction.user)
                if teammate in tournament.players:
                    tournament.players.remove(teammate)

                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        item.label = f"{len(tournament.players)//2} teams/{tournament.max_players//2}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ Team {interaction.user.display_name} & {teammate.display_name} unregistered! ({len(tournament.players)//2}/{tournament.max_players//2} teams)", ephemeral=True)

            else:
                tournament.players.remove(interaction.user)

                for item in self.children:
                    if hasattr(item, 'custom_id') and item.custom_id == "participant_count":
                        item.label = f"{len(tournament.players)}/{tournament.max_players}"
                        break

                await interaction.response.edit_message(view=self)
                await interaction.followup.send(f"✅ {interaction.user.display_name} unregistered! ({len(tournament.players)}/{tournament.max_players})", ephemeral=True)

        except Exception as e:
            print(f"Error in unregister_button: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred. Please try again.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

    @discord.ui.button(label="0/0", style=discord.ButtonStyle.secondary, disabled=True, custom_id="participant_count")
    async def participant_count(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="🚀 Start Tournament", style=discord.ButtonStyle.primary, custom_id="start_tournament")
    async def start_tournament(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            tournament = get_tournament(interaction.guild.id)

            if not has_admin_permission(interaction.user, interaction.guild):
                return await interaction.response.send_message("❌ You don't have permission to start tournaments.", ephemeral=True)

            if tournament.max_players == 0:
                return await interaction.response.send_message("❌ No tournament has been created yet.", ephemeral=True)

            if tournament.active:
                return await interaction.response.send_message("❌ Tournament already started.", ephemeral=True)

            # Allow tournament to start even without max players
            if len(tournament.players) < 2:
                return await interaction.response.send_message("❌ Not enough players to start tournament (minimum 2 players).", ephemeral=True)

            await interaction.response.send_message("🚀 Starting tournament...", ephemeral=True)

            # For 2v2 mode, keep teams together when shuffling
            if tournament.mode == "2v2":
                # Group players by teams, then shuffle the teams
                teams_list = []
                processed_players = set()

                for player in tournament.players:
                    if player in processed_players or isinstance(player, FakePlayer):
                        continue

                    if hasattr(player, 'id') and player.id in tournament.teams:
                        teammate_id = tournament.teams[player.id]
                        teammate = next((p for p in tournament.players if hasattr(p, 'id') and p.id == teammate_id), None)
                        if teammate:
                            teams_list.append([player, teammate])
                            processed_players.add(player)
                            processed_players.add(teammate)
                    else:
                        # Single player (shouldn't happen in 2v2 but handle it)
                        teams_list.append([player])
                        processed_players.add(player)

                # Add any fake teams
                for player in tournament.players:
                    if isinstance(player, FakePlayer) and player not in processed_players:
                        if player.id in tournament.teams:
                            teammate_id = tournament.teams[player.id]
                            teammate = next((p for p in tournament.players if isinstance(p, FakePlayer) and p.id == teammate_id), None)
                            if teammate and teammate not in processed_players:
                                teams_list.append([player, teammate])
                                processed_players.add(player)
                                processed_players.add(teammate)

                # Shuffle the teams order, not the team composition
                random.shuffle(teams_list)

                # Flatten back to player list while preserving teams
                tournament.players = []
                for team in teams_list:
                    tournament.players.extend(team)
            else:
                # For 1v1 mode, shuffle normally
                random.shuffle(tournament.players)

            tournament.active = True
            tournament.results = []
            tournament.rounds = []

            if tournament.mode == "2v2":
                teams = []
                for i in range(0, len(tournament.players), 2):
                    teams.append((tournament.players[i], tournament.players[i+1]))

                round_pairs = [(teams[i], teams[i+1]) for i in range(0, len(teams), 2)]
            else:
                round_pairs = [(tournament.players[i], tournament.players[i+1]) for i in range(0, len(tournament.players), 2)]

            tournament.rounds.append(round_pairs)

            embed = discord.Embed(
                title=f"🏆 {tournament.title} - Round 1",
                description=f"**Map:** {tournament.map}\n**Mode:** {tournament.mode}\n**Abilities:** {tournament.abilities}",
                color=0x3498db
            )

            for i, match in enumerate(round_pairs, 1):
                if tournament.mode == "2v2":
                    team_a, team_b = match
                    team_a_str = f"{get_player_display_name(team_a[0], interaction.guild.id)} & {get_player_display_name(team_a[1], interaction.guild.id)}"
                    team_b_str = f"{get_player_display_name(team_b[0], interaction.guild.id)} & {get_player_display_name(team_b[1], interaction.guild.id)}"
                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{team_a_str}** <:VS:1402690899485655201> **{team_b_str}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )
                else:
                    a, b = match
                    player_a = get_player_display_name(a, interaction.guild.id)
                    player_b = get_player_display_name(b, interaction.guild.id)
                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{player_a}** <:VS:1402690899485655201> **{player_b}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )

            embed.set_footer(text="Use !winner @player to record match results")

            # Create a new view without buttons for active tournament
            active_tournament_view = discord.ui.View()
            tournament.message = await interaction.channel.send(embed=embed, view=active_tournament_view)
            await interaction.followup.send("✅ Tournament started successfully!", ephemeral=True)

        except Exception as e:
            print(f"Error in start_tournament: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ An error occurred while starting the tournament.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred while starting the tournament.", ephemeral=True)
            except Exception as follow_error:
                print(f"Failed to send error message: {follow_error}")

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="🎫 Create Ticket", style=discord.ButtonStyle.primary, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        category = discord.utils.get(guild.categories, name="Tickets")

        if not category:
            category = await guild.create_category("Tickets")

        ticket_channel = await guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
        )

        tickets[ticket_channel.id] = interaction.user.id

        embed = discord.Embed(
            title="🎫 Support Ticket",
            description=f"Hello {interaction.user.mention}! Please describe your issue and wait for staff assistance.",
            color=0x00ff00
        )

        await ticket_channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)

class AccountModal(discord.ui.Modal, title="Link Your Account"):
    def __init__(self):
        super().__init__()

    ign_field = discord.ui.TextInput(
        label="🎮 In-Game Name",
        placeholder="Enter your in-game name...",
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild_str = str(interaction.guild.id)
        if guild_str not in user_data:
            user_data[guild_str] = {}
        user_data[guild_str][str(interaction.user.id)] = self.ign_field.value
        save_data()

        # Give linked role if it exists
        linked_role = discord.utils.get(interaction.guild.roles, name="🔗Linked")
        if linked_role and linked_role not in interaction.user.roles:
            try:
                await interaction.user.add_roles(linked_role)
                await interaction.response.send_message(f"✅ Account linked! IGN: `{self.ign_field.value}`\n🔗 You've been given the **Linked** role!", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(f"✅ Account linked! IGN: `{self.ign_field.value}`\n⚠️ Couldn't give Linked role (insufficient permissions)", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ Account linked! IGN: `{self.ign_field.value}`", ephemeral=True)

class AccountView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="🔗 Link Account", style=discord.ButtonStyle.primary, custom_id="link_account")
    async def link_account(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AccountModal()
        await interaction.response.send_modal(modal)

@bot.command()
async def invite(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except:
        pass

    tournament = get_tournament(ctx.guild.id)

    if tournament.mode != "2v2":
        return await ctx.send("❌ Team invites are only available in 2v2 mode.", delete_after=5)

    if ctx.author.id == member.id:
        return await ctx.send("❌ You cannot invite yourself as a teammate.", delete_after=5)

    if ctx.author.id in tournament.teams:
        return await ctx.send("❌ You already have a teammate.", delete_after=5)

    if member.id in tournament.teams:
        return await ctx.send("❌ This user already has a teammate.", delete_after=5)

    if member.bot:
        return await ctx.send("❌ You cannot invite bots as teammates.", delete_after=5)

    # Check if the member already has a pending invite
    if member.id in tournament.team_invites:
        return await ctx.send("❌ This user already has a pending team invitation.", delete_after=5)

    # Set the invite with correct user IDs
    tournament.team_invites[member.id] = ctx.author.id

    embed = discord.Embed(
        title="🤝 Team Invitation",
        description=f"{ctx.author.mention} invited you to be their teammate!",
        color=0x3498db
    )

    view = TeamInviteView(ctx.author.id, member.id, ctx.guild.id)

    try:
        await member.send(embed=embed, view=view)
        await ctx.send(f"✅ Team invitation sent to {member.display_name}!", delete_after=5)
    except discord.Forbidden:
        await ctx.send(f"❌ Could not send DM to {member.display_name}. They may have DMs disabled.", delete_after=5)

@bot.command()
async def leave_team(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    tournament = get_tournament(ctx.guild.id)

    if ctx.author.id not in tournament.teams:
        return await ctx.send("❌ You don't have a teammate.", delete_after=5)

    teammate_id = tournament.teams[ctx.author.id]
    teammate = ctx.guild.get_member(teammate_id)

    # Remove from teams
    del tournament.teams[ctx.author.id]
    del tournament.teams[teammate_id]

    # Unregister team if registered
    if ctx.author in tournament.players:
        tournament.players.remove(ctx.author)
    if teammate in tournament.players:
        tournament.players.remove(teammate)

    await ctx.send(f"✅ You left the team with {teammate.display_name}. Your team has been unregistered from the tournament.", delete_after=10)

@bot.command()
async def tp(ctx, member: discord.Member = None):
    try:
        await ctx.message.delete()
    except:
        pass

    if member is None:
        member = ctx.author

    guild_str = str(ctx.guild.id)
    tp = tp_data.get(guild_str, {}).get(str(member.id), 0)
    rank = get_rank_from_tp(tp)

    embed = discord.Embed(
        title="🏆 Tournament Points",
        description=f"**Player:** {member.display_name}\n**TP:** {tp}\n**Rank:** {rank}",
        color=0xe74c3c
    )

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("📨 TP information sent via DM!", delete_after=3)
    except discord.Forbidden:
        await ctx.send(embed=embed, delete_after=10)

@bot.command()
async def tplb(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_str = str(ctx.guild.id)
    guild_tp_data = tp_data.get(guild_str, {})

    # Sort players by TP
    sorted_players = sorted(guild_tp_data.items(), key=lambda x: x[1], reverse=True)[:10]

    embed = discord.Embed(
        title="🏆 Tournament Points Leaderboard",
        color=0xf1c40f
    )

    if not sorted_players:
        embed.description = "No players have TP yet!"
    else:
        leaderboard_text = ""
        for i, (user_id, tp) in enumerate(sorted_players, 1):
            user = ctx.guild.get_member(int(user_id))
            if user:
                rank = get_rank_from_tp(tp)
                leaderboard_text += f"**{i}.** {user.display_name} - **{rank.upper()}**: {tp} TP\n"

        embed.description = leaderboard_text

    await ctx.send(embed=embed, delete_after=30)

@bot.command()
@commands.has_permissions(administrator=True)
async def tprst(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_str = str(ctx.guild.id)
    if guild_str in tp_data:
        tp_data[guild_str] = {}
        save_data()
        await ctx.send("✅ All Tournament Points have been reset for this server!", delete_after=5)
    else:
        await ctx.send("✅ No Tournament Points to reset in this server!", delete_after=5)

@bot.command()
async def create(ctx, channel: discord.TextChannel):
    try:
        await ctx.message.delete()
    except:
        pass

    if not has_admin_permission(ctx.author, ctx.guild):
        return await ctx.send("❌ You don't have permission to create tournaments.", delete_after=5)

    tournament = get_tournament(ctx.guild.id)
    tournament.target_channel = channel

    embed = discord.Embed(
        title="🏆 Tournament Setup",
        description="Press the button to configure the tournament settings.",
        color=0x00ff00
    )

    view = TournamentConfigView(channel)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def leveling_channel(ctx, channel: discord.TextChannel):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in leveling_settings:
        leveling_settings[guild_id] = {'enabled': False, 'channel': None}

    leveling_settings[guild_id]['channel'] = channel.id
    save_data()
    await ctx.send(f"✅ Leveling channel set to {channel.mention}", delete_after=5)

@bot.command()
async def leveling_enable(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in leveling_settings:
        leveling_settings[guild_id] = {'enabled': False, 'channel': None}

    leveling_settings[guild_id]['enabled'] = not leveling_settings[guild_id]['enabled']
    status = "enabled" if leveling_settings[guild_id]['enabled'] else "disabled"
    save_data()
    await ctx.send(f"✅ Leveling system {status}!", delete_after=5)

@bot.command()
async def welcomer_channel(ctx, channel: discord.TextChannel):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in welcomer_settings:
        welcomer_settings[guild_id] = {'enabled': False, 'channel': None}

    welcomer_settings[guild_id]['channel'] = channel.id
    save_data()
    await ctx.send(f"✅ Welcomer channel set to {channel.mention}", delete_after=5)

@bot.command()
async def welcomer_enable(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in welcomer_settings:
        welcomer_settings[guild_id] = {'enabled': False, 'channel': None}

    welcomer_settings[guild_id]['enabled'] = not welcomer_settings[guild_id]['enabled']
    status = "enabled" if welcomer_settings[guild_id]['enabled'] else "disabled"
    save_data()
    await ctx.send(f"✅ Welcomer system {status}!", delete_after=5)

@bot.command()
async def ticket_panel(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="🎫 Support Tickets",
        description="**Need help?**\n\nClick the button below to create a support ticket. Our staff will assist you as soon as possible!\n\n🔹 **What can we help with?**\n• Technical issues\n• Account problems\n• General questions\n• Report bugs\n• Other concerns",
        color=0x3498db
    )
    embed.set_footer(text="Tickets are private and only visible to you and staff")

    view = TicketView()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def delete_ticket(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    if ctx.channel.id in tickets:
        await ctx.send("🗑️ Deleting ticket in 5 seconds...")
        await asyncio.sleep(5)
        await ctx.channel.delete()
    else:
        await ctx.send("❌ This is not a ticket channel.", delete_after=5)

@bot.command()
async def acc(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="🔗 Account Linking",
        description="**Link your Discord account with your in-game profile!**\n\n🎮 **Why link your account?**\n• Access exclusive features\n• Participate in tournaments\n• Track your progress\n• Get personalized support\n\n📝 **Instructions:**\n• Click the button below\n• Enter your exact in-game name\n• Confirm the details\n\n🌟 **Ready to get started?**",
        color=0xe74c3c
    )
    embed.set_footer(text="Make sure to enter your exact IGN!")

    view = AccountView()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def IGN(ctx, member: discord.Member = None):
    try:
        await ctx.message.delete()
    except:
        pass

    if member is None:
        member = ctx.author

    guild_str = str(ctx.guild.id)
    if guild_str in user_data and str(member.id) in user_data[guild_str]:
        embed = discord.Embed(
            title="🎮 Player Information",
            description=f"**Player:** {member.display_name}\n**IGN:** `{user_data[guild_str][str(member.id)]}`",
            color=0x2ecc71
        )
        await ctx.send(embed=embed, delete_after=10)
    else:
        await ctx.send(f"❌ {member.display_name} hasn't linked their account yet.", delete_after=5)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    try:
        await ctx.message.delete()
    except:
        pass

    if str(member.id) not in warnings:
        warnings[str(member.id)] = []

    warnings[str(member.id)].append({
        'reason': reason,
        'moderator': ctx.author.id,
        'timestamp': datetime.now().isoformat()
    })

    embed = discord.Embed(
        title="⚠️ Warning Issued",
        description=f"**Member:** {member.mention}\n**Reason:** {reason}\n**Moderator:** {ctx.author.mention}\n**Warnings:** {len(warnings[str(member.id)])}",
        color=0xf39c12
    )

    await ctx.send(embed=embed, delete_after=10)

    try:
        await member.send(f"⚠️ You have been warned in **{ctx.guild.name}**\n**Reason:** {reason}")
    except:
        pass

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn_hs(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except:
        pass

    user_warnings = warnings.get(str(member.id), [])

    embed = discord.Embed(
        title="⚠️ Warning History",
        description=f"**Member:** {member.mention}\n**Total Warnings:** {len(user_warnings)}",
        color=0xf39c12
    )

    if user_warnings:
        for i, warning in enumerate(user_warnings[-5:], 1):  # Show last 5 warnings
            moderator = ctx.guild.get_member(warning['moderator'])
            mod_name = moderator.display_name if moderator else "Unknown"
            timestamp = datetime.fromisoformat(warning['timestamp']).strftime("%Y-%m-%d %H:%M")
            embed.add_field(
                name=f"Warning #{len(user_warnings) - 5 + i}",
                value=f"**Reason:** {warning['reason']}\n**Moderator:** {mod_name}\n**Date:** {timestamp}",
                inline=False
            )
    else:
        embed.add_field(name="No Warnings", value="This user has no warnings.", inline=False)

    await ctx.send(embed=embed, delete_after=20)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def warnrmv(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except:
        pass

    if str(member.id) in warnings:
        del warnings[str(member.id)]
        await ctx.send(f"✅ All warnings removed for {member.display_name}!", delete_after=5)
    else:
        await ctx.send(f"❌ {member.display_name} has no warnings to remove.", delete_after=5)

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, time: str, *, reason="No reason provided"):
    try:
        await ctx.message.delete()
    except:
        pass

    # Parse time (e.g., "1h", "30m", "2d")
    time_units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    try:
        time_amount = int(time[:-1])
        time_unit = time[-1].lower()

        if time_unit not in time_units:
            return await ctx.send("❌ Invalid time format! Use s/m/h/d (e.g., 30m, 2h, 1d)", delete_after=5)

        duration = timedelta(seconds=time_amount * time_units[time_unit])
    except (ValueError, IndexError):
        return await ctx.send("❌ Invalid time format! Use s/m/h/d (e.g., 30m, 2h, 1d)", delete_after=5)


    try:
        await member.timeout(duration, reason=reason)
        embed = discord.Embed(
            title="🔇 Member Muted",
            description=f"**Member:** {member.mention}\n**Duration:** {time}\n**Reason:** {reason}\n**Moderator:** {ctx.author.mention}",
            color=0xf39c12
        )
        await ctx.send(embed=embed, delete_after=15)

        try:
            await member.send(f"🔇 You have been muted in **{ctx.guild.name}** for {time}\n**Reason:** {reason}")
        except:
            pass

    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to mute this member.", delete_after=5)

@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except:
        pass

    try:
        await member.timeout(None)
        embed = discord.Embed(
            title="🔊 Member Unmuted",
            description=f"**Member:** {member.mention}\n**Moderator:** {ctx.author.mention}",
            color=0x2ecc71
        )
        await ctx.send(embed=embed, delete_after=10)

        try:
            await member.send(f"🔊 You have been unmuted in **{ctx.guild.name}**")
        except:
            pass

    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unmute this member.", delete_after=5)

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, time: str = None, *, reason="No reason provided"):
    try:
        await ctx.message.delete()
    except:
        pass

    try:
        await member.send(f"🔨 You have been banned from **{ctx.guild.name}**\n**Reason:** {reason}")
    except:
        pass

    await member.ban(reason=reason)

    embed = discord.Embed(
        title="🔨 Member Banned",
        description=f"**Member:** {member.mention}\n**Reason:** {reason}\n**Moderator:** {ctx.author.mention}",
        color=0xe74c3c
    )

    if time:
        embed.add_field(name="Duration", value=time, inline=True)

    await ctx.send(embed=embed, delete_after=15)

@bot.command()
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: int):
    try:
        await ctx.message.delete()
    except:
        pass

    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)

        embed = discord.Embed(
            title="🔓 Member Unbanned",
            description=f"**Member:** {user.mention}\n**Moderator:** {ctx.author.mention}",
            color=0x2ecc71
        )
        await ctx.send(embed=embed, delete_after=10)

    except discord.NotFound:
        await ctx.send("❌ User not found or not banned.", delete_after=5)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unban members.", delete_after=5)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx, *roles: discord.Role):
    try:
        await ctx.message.delete()
    except:
        pass

    # Set default role to not send messages
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)

    # Allow mentioned roles to send messages
    allowed_roles = []
    for role in roles:
        await ctx.channel.set_permissions(role, send_messages=True)
        allowed_roles.append(role.mention)

    embed = discord.Embed(
        title="🔒 Channel Locked",
        color=0xe74c3c
    )

    if allowed_roles:
        embed.description = f"This channel has been locked by {ctx.author.mention}\n\n**Allowed roles:** {', '.join(allowed_roles)}"
    else:
        embed.description = f"This channel has been locked by {ctx.author.mention}\n\n**Access:** Locked for everyone"

    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None)
    embed = discord.Embed(
        title="🔓 Channel Unlocked",
        description=f"This channel has been unlocked by {ctx.author.mention}",
        color=0x2ecc71
    )
    await ctx.send(embed=embed)

@bot.command()
async def embed(ctx, *, text):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(description=text, color=0x3498db)
    await ctx.send(embed=embed)

@bot.command()
async def level(ctx, member: discord.Member = None):
    try:
        await ctx.message.delete()
    except:
        pass

    if member is None:
        member = ctx.author

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)

    if guild_id in user_levels and user_id in user_levels[guild_id]:
        level_data = user_levels[guild_id][user_id]
        embed = discord.Embed(
            title="📊 Level Information",
            description=f"**Player:** {member.display_name}\n**Level:** {level_data['level']}\n**XP:** {level_data['xp']}\n**Next Level:** {(level_data['level'] * 100) - level_data['xp']} XP needed",
            color=0xf1c40f
        )
    else:
        embed = discord.Embed(
            title="📊 Level Information",
            description=f"**Player:** {member.display_name}\n**Level:** 1\n**XP:** 0\n**Next Level:** 100 XP needed",
            color=0xf1c40f
        )

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("📨 Level information sent via DM!", delete_after=3)
    except discord.Forbidden:
        await ctx.send(embed=embed, delete_after=10)

@bot.command()
async def create_linked_role(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    if discord.utils.get(ctx.guild.roles, name="🔗Linked"):
        return await ctx.send("❌ 🔗Linked role already exists!", delete_after=5)

    try:
        await ctx.guild.create_role(name="🔗Linked", color=0x00ff00)
        await ctx.send("✅ 🔗Linked role created successfully!", delete_after=5)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to create roles.", delete_after=5)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def bracketrole(ctx, member: discord.Member, emoji1: str, emoji2: str = "", emoji3: str = ""):
    try:
        await ctx.message.delete()
    except:
        pass

    emojis = [emoji1, emoji2, emoji3]
    # Filter out empty emojis
    emojis = [e for e in emojis if e.strip()]

    if len(emojis) > 3:
        return await ctx.send("❌ You can only set up to 3 emojis!", delete_after=5)

    if len(emojis) == 0:
        return await ctx.send("❌ You must provide at least one emoji!", delete_after=5)

    guild_str = str(ctx.guild.id)
    if guild_str not in bracket_roles:
        bracket_roles[guild_str] = {}

    bracket_roles[guild_str][str(member.id)] = emojis
    save_data()

    emoji_display = ''.join(emojis)
    player_name = member.nick if member.nick else member.display_name
    bracket_name = f"{player_name} {emoji_display}"

    await ctx.send(f"✅ Bracket role set for {member.mention}! Their bracket name: {bracket_name}", delete_after=10)

@bot.command()
async def bracketname(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_str = str(ctx.guild.id)
    if guild_str in bracket_roles and str(ctx.author.id) in bracket_roles[guild_str]:
        emojis = ''.join(bracket_roles[guild_str][str(ctx.author.id)])
        player_name = ctx.author.nick if ctx.author.nick else ctx.author.display_name
        bracket_name = f"{player_name} {emojis}"
    else:
        player_name = ctx.author.nick if ctx.author.nick else ctx.author.display_name
        bracket_name = player_name

    embed = discord.Embed(
        title="🏷️ Your Bracket Name",
        description=f"**Bracket Name:** {bracket_name}",
        color=0x3498db
    )

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("📨 Bracket name sent via DM!", delete_after=3)
    except discord.Forbidden:
        await ctx.send(embed=embed, delete_after=10)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def bracketrolereset(ctx, member: discord.Member = None):
    try:
        await ctx.message.delete()
    except:
        pass

    if member is None:
        member = ctx.author

    guild_str = str(ctx.guild.id)
    if guild_str in bracket_roles and str(member.id) in bracket_roles[guild_str]:
        del bracket_roles[guild_str][str(member.id)]
        # Clean up guild entry if it becomes empty
        if not bracket_roles[guild_str]:
            del bracket_roles[guild_str]
        save_data()

        if member == ctx.author:
            await ctx.send("✅ Your bracket role reset! Your emojis have been removed.", delete_after=5)
        else:
            await ctx.send(f"✅ Bracket role reset for {member.mention}! Their emojis have been removed.", delete_after=5)
    else:
        if member == ctx.author:
            await ctx.send("❌ You don't have any bracket emojis set.", delete_after=5)
        else:
            await ctx.send(f"❌ {member.mention} doesn't have any bracket emojis set.", delete_after=5)

class RegionPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(emoji="🇪🇺", label="EU", style=discord.ButtonStyle.secondary, custom_id="region_eu")
    async def select_eu(self, interaction: discord.Interaction, button: discord.ui.Button):
        eu_role = discord.utils.get(interaction.guild.roles, name="EU")
        if not eu_role:
            return await interaction.response.send_message("❌ EU role not found! Please ask an admin to create the role.", ephemeral=True)

        # Remove other region roles
        region_roles = ["ASIA", "INW", "US"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            await interaction.user.add_roles(eu_role)
            await interaction.response.send_message(f"✅ You now have the {eu_role.mention} role!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

    @discord.ui.button(emoji="🌏", label="ASIA", style=discord.ButtonStyle.secondary, custom_id="region_asia")
    async def select_asia(self, interaction: discord.Interaction, button: discord.ui.Button):
        asia_role = discord.utils.get(interaction.guild.roles, name="ASIA")
        if not asia_role:
            return await interaction.response.send_message("❌ ASIA role not found! Please ask an admin to create the role.", ephemeral=True)

        # Remove other region roles
        region_roles = ["EU", "INW", "US"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            await interaction.user.add_roles(asia_role)
            await interaction.response.send_message(f"✅ You now have the {asia_role.mention} role!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

    @discord.ui.button(emoji="🇮🇳", label="INW", style=discord.ButtonStyle.secondary, custom_id="region_inw")
    async def select_inw(self, interaction: discord.Interaction, button: discord.ui.Button):
        inw_role = discord.utils.get(interaction.guild.roles, name="INW")
        if not inw_role:
            return await interaction.response.send_message("❌ INW role not found! Please ask an admin to create the role.", ephemeral=True)

        # Remove other region roles
        region_roles = ["EU", "ASIA", "US"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            await interaction.user.add_roles(inw_role)
            await interaction.response.send_message(f"✅ You now have the {inw_role.mention} role!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

    @discord.ui.button(emoji="🇺🇸", label="US", style=discord.ButtonStyle.secondary, custom_id="region_us")
    async def select_us(self, interaction: discord.Interaction, button: discord.ui.Button):
        us_role = discord.utils.get(interaction.guild.roles, name="US")
        if not us_role:
            return await interaction.response.send_message("❌ US role not found! Please ask an admin to create the role.", ephemeral=True)

        # Remove other region roles
        region_roles = ["EU", "ASIA", "INW"]
        roles_to_remove = [discord.utils.get(interaction.guild.roles, name=role) for role in region_roles if discord.utils.get(interaction.guild.roles, name=role)]
        roles_to_remove = [role for role in roles_to_remove if role in interaction.user.roles]

        try:
            if roles_to_remove:
                await interaction.user.remove_roles(*roles_to_remove)
            await interaction.user.add_roles(us_role)
            await interaction.response.send_message(f"✅ You now have the {us_role.mention} role!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to manage your roles.", ephemeral=True)

class HosterRegistrationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="Register", style=discord.ButtonStyle.green, custom_id="hoster_register")
    async def register_hoster(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not host_registrations['active']:
            return await interaction.response.send_message("❌ Hoster registration is not active.", ephemeral=True)

        if interaction.user in host_registrations['hosters']:
            return await interaction.response.send_message("❌ You are already registered as a hoster.", ephemeral=True)

        if len(host_registrations['hosters']) >= host_registrations['max_hosters']:
            return await interaction.response.send_message("❌ Maximum number of hosters reached.", ephemeral=True)

        host_registrations['hosters'].append(interaction.user)

        # Update the embed
        embed = discord.Embed(
            title="🎯 Hoster Registration",
            description="Here the hosters will register to host tournaments!",
            color=0x00ff00
        )

        if host_registrations['hosters']:
            hoster_list = ""
            for i, hoster in enumerate(host_registrations['hosters'], 1):
                hoster_name = hoster.nick if hoster.nick else hoster.display_name
                hoster_list += f"{i}. {hoster_name}\n"
            embed.add_field(name="Hosters registered:", value=hoster_list, inline=False)
        else:
            embed.add_field(name="Hosters registered:", value="None yet", inline=False)

        embed.add_field(name="Slots:", value=f"{len(host_registrations['hosters'])}/{host_registrations['max_hosters']}", inline=True)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"✅ {interaction.user.display_name} registered as a hoster!", ephemeral=True)

    @discord.ui.button(label="Unregister", style=discord.ButtonStyle.red, custom_id="hoster_unregister")
    async def unregister_hoster(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not host_registrations['active']:
            return await interaction.response.send_message("❌ Hoster registration is not active.", ephemeral=True)

        if interaction.user not in host_registrations['hosters']:
            return await interaction.response.send_message("❌ You are not registered as a hoster.", ephemeral=True)

        host_registrations['hosters'].remove(interaction.user)

        # Update the embed
        embed = discord.Embed(
            title="🎯 Hoster Registration",
            description="Here the hosters will register to host tournaments!",
            color=0x00ff00
        )

        if host_registrations['hosters']:
            hoster_list = ""
            for i, hoster in enumerate(host_registrations['hosters'], 1):
                hoster_name = hoster.nick if hoster.nick else hoster.display_name
                hoster_list += f"{i}. {hoster_name}\n"
            embed.add_field(name="Hosters registered:", value=hoster_list, inline=False)
        else:
            embed.add_field(name="Hosters registered:", value="None yet", inline=False)

        embed.add_field(name="Slots:", value=f"{len(host_registrations['hosters'])}/{host_registrations['max_hosters']}", inline=True)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"✅ {interaction.user.display_name} unregistered from hosting.", ephemeral=True)

    @discord.ui.button(label="End Register", style=discord.ButtonStyle.secondary, custom_id="end_hoster_register")
    async def end_registration(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ You need 'Manage Channels' permission to end registration.", ephemeral=True)

        host_registrations['active'] = False

        # Keep the existing embed but disable all buttons
        embed = discord.Embed(
            title="🎯 Hoster Registration - CLOSED",
            description="Hoster registration has been closed by a moderator.",
            color=0xff0000
        )

        if host_registrations['hosters']:
            hoster_list = ""
            for i, hoster in enumerate(host_registrations['hosters'], 1):
                hoster_name = hoster.nick if hoster.nick else hoster.display_name
                hoster_list += f"{i}. {hoster_name}\n"
            embed.add_field(name="Final Hosters registered:", value=hoster_list, inline=False)
        else:
            embed.add_field(name="Final Hosters registered:", value="None", inline=False)

        embed.add_field(name="Final Slots:", value=f"{len(host_registrations['hosters'])}/{host_registrations['max_hosters']}", inline=True)

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)

@bot.command()
async def hosterregist(ctx, max_hosters: int):
    try:
        await ctx.message.delete()
    except:
        pass

    if not ctx.author.guild_permissions.manage_channels:
        return await ctx.send("❌ You need 'Manage Channels' permission to start hoster registration.", delete_after=5)

    if max_hosters < 1 or max_hosters > 20:
        return await ctx.send("❌ Maximum hosters must be between 1 and 20.", delete_after=5)

    host_registrations['active'] = True
    host_registrations['max_hosters'] = max_hosters
    host_registrations['hosters'] = []
    host_registrations['channel'] = ctx.channel

    embed = discord.Embed(
        title="🎯 Hoster Registration",
        description="Here the hosters will register to host tournaments!",
        color=0x00ff00
    )

    embed.add_field(name="Hosters registered:", value="None yet", inline=False)
    embed.add_field(name="Slots:", value=f"0/{max_hosters}", inline=True)

    view = HosterRegistrationView()
    host_registrations['message'] = await ctx.send(embed=embed, view=view)

@bot.command()
async def regionpanel(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="🌍 React with your region:",
        description="Click on the buttons below to get your regional role!\n\n🇪🇺 **EU** - @EU\n🌏 **ASIA** - @ASIA\n🇮🇳 **INW** - @INW\n🇺🇸 **US** - @US\n\n*Selecting a new region will remove your previous region role.*",
        color=0x3498db
    )
    embed.set_footer(text="Choose your region to connect with players from your area!")

    view = RegionPanelView()
    await ctx.send(embed=embed, view=view)

@bot.command()
async def experience_personalizer(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="🌟 Let's personalize your experience!",
        description=f"Welcome to **{ctx.guild.name}**!\n\n**On what server do you play?**\nSelect your region below to get started and connect with players from your area:",
        color=0x3498db
    )
    embed.add_field(
        name="🌍 Available Regions:",
        value="🇪🇺 **EU** - Europe\n🌏 **ASIA** - Asia Pacific\n🇮🇳 **INW** - India\n🇺🇸 **US** - United States",
        inline=False
    )
    embed.set_footer(text="Choose your region to complete your server setup!")

    view = ExperiencePersonalizerView()
    await ctx.send(embed=embed, view=view)

@bot.command()
@commands.is_owner()
async def svd(ctx):
    """Server Deletion - Delete all channels and categories, then recreate like svm"""
    try:
        await ctx.message.delete()
    except:
        pass

    guild = ctx.guild

    # Create deletion message
    embed = discord.Embed(
        title="🗑️ Server Deletion & Recreation",
        description="Deleting all channels and categories, then recreating server structure...",
        color=0xff6600
    )

    setup_msg = await ctx.send(embed=embed)

    try:
        # Delete all channels and categories (except the one we're in)
        current_channel = ctx.channel

        # First delete all text and voice channels
        for channel in guild.channels:
            if channel != current_channel and not isinstance(channel, discord.CategoryChannel):
                try:
                    await channel.delete()
                except:
                    pass

        # Then delete all categories
        for category in guild.categories:
            try:
                await category.delete()
            except:
                pass

        # Wait a moment for deletions to process
        await asyncio.sleep(2)

        # Now recreate everything like svm command
        # Create categories in order of importance
        info_category = await guild.create_category("📋 • Information", position=0)
        general_category = await guild.create_category("🎙️ • General", position=1)
        bot_category = await guild.create_category("🤖 • Bot Functions", position=2)
        voice_category = await guild.create_category("🔊 • Voice Channels", position=3)

        # Create text channels with emoji • symbol format
        # Information channels (highest priority)
        rules_channel = await guild.create_text_channel("📜 • rules", category=info_category)
        announcements_channel = await guild.create_text_channel("📢 • announcements", category=info_category)
        tickets_channel = await guild.create_text_channel("🎫 • tickets", category=info_category)
        updates_channel = await guild.create_text_channel("🔄 • updates", category=info_category)

        # General channels
        await guild.create_text_channel("☁️ • general", category=general_category)
        await guild.create_text_channel("💬 • chat", category=general_category)
        await guild.create_text_channel("🎮 • gaming", category=general_category)
        await guild.create_text_channel("📸 • media", category=general_category)
        await guild.create_text_channel("🎵 • music", category=general_category)

        # Bot function channels
        accounts_channel = await guild.create_text_channel("🔗 • link-account", category=bot_category)
        tournaments_channel = await guild.create_text_channel("🏆 • tournaments", category=bot_category)
        leveling_channel = await guild.create_text_channel("📈 • level-ups", category=bot_category)
        welcome_channel = await guild.create_text_channel("👋 • welcome", category=bot_category)
        regions_channel = await guild.create_text_channel("🌍 • regions", category=bot_category)
        commands_channel = await guild.create_text_channel("🤖 • bot-commands", category=bot_category)

        # Create voice channels
        await guild.create_voice_channel("🎤 • General Voice", category=voice_category)
        await guild.create_voice_channel("🎮 • Gaming Voice", category=voice_category)
        await guild.create_voice_channel("🏆 • Tournament Voice", category=voice_category)
        await guild.create_voice_channel("🎵 • Music Voice", category=voice_category)
        await guild.create_voice_channel("📞 • Private Voice", category=voice_category)

        # Auto-setup bot systems
        guild_id = str(guild.id)

        # Setup leveling system
        if guild_id not in leveling_settings:
            leveling_settings[guild_id] = {'enabled': True, 'channel': leveling_channel.id}
        else:
            leveling_settings[guild_id]['enabled'] = True
            leveling_settings[guild_id]['channel'] = leveling_channel.id

        # Setup welcomer system
        if guild_id not in welcomer_settings:
            welcomer_settings[guild_id] = {'enabled': True, 'channel': welcome_channel.id}
        else:
            welcomer_settings[guild_id]['enabled'] = True
            welcomer_settings[guild_id]['channel'] = welcome_channel.id

        save_data()

        # Send ticket panel
        ticket_embed = discord.Embed(
            title="🎫 Support Tickets",
            description="**Need help?**\n\nClick the button below to create a support ticket. Our staff will assist you as soon as possible!\n\n🔹 **What can we help with?**\n• Technical issues\n• Account problems\n• General questions\n• Report bugs\n• Other concerns",
            color=0x3498db
        )
        ticket_embed.set_footer(text="Tickets are private and only visible to you and staff")
        await tickets_channel.send(embed=ticket_embed, view=TicketView())

        # Send account linking panel
        acc_embed = discord.Embed(
            title="🔗 Account Linking",
            description="**Link your Discord account with your in-game profile!**\n\n🎮 **Why link your account?**\n• Access exclusive features\n• Participate in tournaments\n• Track your progress\n• Get personalized support\n\n📝 **Instructions:**\n• Click the button below\n• Enter your exact in-game name\n• Confirm the details\n\n🌟 **Ready to get started?**",
            color=0xe74c3c
        )
        acc_embed.set_footer(text="Make sure to enter your exact IGN!")
        await accounts_channel.send(embed=acc_embed, view=AccountView())

        # Send region panel
        region_embed = discord.Embed(
            title="🌍 React with your region:",
            description="Click on the buttons below to get your regional role!\n\n🇪🇺 **EU** - @EU\n🌏 **ASIA** - @ASIA\n🇮🇳 **INW** - @INW\n🇺🇸 **US** - @US\n\n*Selecting a new region will remove your previous region role.*",
            color=0x3498db
        )
        region_embed.set_footer(text="Choose your region to connect with players from your area!")
        await regions_channel.send(embed=region_embed, view=RegionPanelView())


        # Update the setup message
        success_embed = discord.Embed(
            title="✅ Server Deletion & Recreation Complete!",
            description="Successfully deleted old channels and recreated server structure:",
            color=0x00ff00
        )

        success_embed.add_field(
            name="📂 Categories (Ordered by Priority)",
            value="1. 📋 • Information (with tickets at bottom)\n2. 🎙️ • General\n3. 🤖 • Bot Functions\n4. 🔊 • Voice Channels",
            inline=False
        )

        success_embed.add_field(
            name="📝 Text Channels",
            value="**Info:** 📜 • rules, 📢 • announcements, 🎫 • tickets, 🔄 • updates\n**General:** ☁️ • general, 💬 • chat, 🎮 • gaming\n**Bot:** 🔗 • link-account, 🏆 • tournaments",
            inline=True
        )

        success_embed.add_field(
            name="⚙️ Auto-Enabled Systems",
            value="✅ Leveling System\n✅ Welcomer System\n✅ Ticket Panel\n✅ Account Linking\n✅ Experience Personalizer",
            inline=True
        )

        success_embed.set_footer(text="Your server has been completely recreated with proper hierarchy and ready to use!")

        await setup_msg.edit(embed=success_embed)

    except discord.Forbidden:
        error_embed = discord.Embed(
            title="❌ Permission Error",
            description="I don't have sufficient permissions to delete/create channels and categories. Please ensure I have Administrator permissions.",
            color=0xff0000
        )
        await setup_msg.edit(embed=error_embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Deletion/Recreation Failed",
            description=f"An error occurred during server deletion/recreation: {str(e)}",
            color=0xff0000
        )
        await setup_msg.edit(embed=error_embed)

@bot.command()
@commands.is_owner()
async def svm(ctx):
    """Server Management - Setup complete server structure with roles"""
    try:
        await ctx.message.delete()
    except:
        pass

    guild = ctx.guild

    # Create setup message
    embed = discord.Embed(
        title="🔧 Server Management System",
        description="Setting up complete server structure with roles...",
        color=0x3498db
    )

    setup_msg = await ctx.send(embed=embed)

    try:
        # Create roles first (in order of importance)
        roles_created = []

        # Staff roles (highest priority)
        try:
            owner_role = await guild.create_role(name="👑・Owner", color=0xff0000, hoist=True)
            roles_created.append("👑・Owner")
        except:
            pass

        try:
            admin_role = await guild.create_role(name="🛡️・Admin", color=0xff6600, hoist=True, permissions=discord.Permissions(administrator=True))
            roles_created.append("🛡️・Admin")
        except:
            pass

        try:
            mod_role = await guild.create_role(name="⚖️・Moderator", color=0x00ff00, hoist=True, permissions=discord.Permissions(manage_messages=True, manage_channels=True, kick_members=True, mute_members=True))
            roles_created.append("⚖️・Moderator")
        except:
            pass

        try:
            helper_role = await guild.create_role(name="🤝・Helper", color=0x00ffff, hoist=True)
            roles_created.append("🤝・Helper")
        except:
            pass

        # Tournament roles
        try:
            hoster_role = await guild.create_role(name="🎯・Tournament Hoster", color=0xffd700, hoist=True)
            roles_created.append("🎯・Tournament Hoster")
        except:
            pass

        # Region roles
        try:
            eu_role = await guild.create_role(name="EU", color=0x0066ff)
            roles_created.append("EU")
        except:
            pass

        try:
            asia_role = await guild.create_role(name="ASIA", color=0xff9900)
            roles_created.append("ASIA")
        except:
            pass

        try:
            inw_role = await guild.create_role(name="INW", color=0x00ff00)
            roles_created.append("INW")
        except:
            pass

        try:
            us_role = await guild.create_role(name="US", color=0xff0000)
            roles_created.append("US")
        except:
            pass

        # Special roles
        try:
            linked_role = await guild.create_role(name="🔗・Linked", color=0x00ff00)
            roles_created.append("🔗・Linked")
        except:
            pass

        try:
            member_role = await guild.create_role(name="👥・Member", color=0x99ccff)
            roles_created.append("👥・Member")
        except:
            pass

        # Create categories in order of importance
        info_category = await guild.create_category("📋 • Information", position=0)
        general_category = await guild.create_category("🎙️ • General", position=1)
        bot_category = await guild.create_category("🤖 • Bot Functions", position=2)
        voice_category = await guild.create_category("🔊 • Voice Channels", position=3)

        # Create text channels with emoji • symbol format
        # Information channels (highest priority)
        rules_channel = await guild.create_text_channel("📜 • rules", category=info_category)
        announcements_channel = await guild.create_text_channel("📢 • announcements", category=info_category)
        tickets_channel = await guild.create_text_channel("🎫 • tickets", category=info_category)
        updates_channel = await guild.create_text_channel("🔄 • updates", category=info_category)

        # General channels
        await guild.create_text_channel("☁️ • general", category=general_category)
        await guild.create_text_channel("💬 • chat", category=general_category)
        await guild.create_text_channel("🎮 • gaming", category=general_category)
        await guild.create_text_channel("📸 • media", category=general_category)
        await guild.create_text_channel("🎵 • music", category=general_category)

        # Bot function channels
        accounts_channel = await guild.create_text_channel("🔗 • link-account", category=bot_category)
        tournaments_channel = await guild.create_text_channel("🏆 • tournaments", category=bot_category)
        leveling_channel = await guild.create_text_channel("📈 • level-ups", category=bot_category)
        welcome_channel = await guild.create_text_channel("👋 • welcome", category=bot_category)
        regions_channel = await guild.create_text_channel("🌍 • regions", category=bot_category)
        commands_channel = await guild.create_text_channel("🤖 • bot-commands", category=bot_category)

        # Create voice channels
        await guild.create_voice_channel("🎤 • General Voice", category=voice_category)
        await guild.create_voice_channel("🎮 • Gaming Voice", category=voice_category)
        await guild.create_voice_channel("🏆 • Tournament Voice", category=voice_category)
        await guild.create_voice_channel("🎵 • Music Voice", category=voice_category)
        await guild.create_voice_channel("📞 • Private Voice", category=voice_category)

        # Auto-setup bot systems
        guild_id = str(guild.id)

        # Setup leveling system
        if guild_id not in leveling_settings:
            leveling_settings[guild_id] = {'enabled': True, 'channel': leveling_channel.id}
        else:
            leveling_settings[guild_id]['enabled'] = True
            leveling_settings[guild_id]['channel'] = leveling_channel.id

        # Setup welcomer system
        if guild_id not in welcomer_settings:
            welcomer_settings[guild_id] = {'enabled': True, 'channel': welcome_channel.id}
        else:
            welcomer_settings[guild_id]['enabled'] = True
            welcomer_settings[guild_id]['channel'] = welcome_channel.id

        save_data()

        # Send ticket panel
        ticket_embed = discord.Embed(
            title="🎫 Support Tickets",
            description="**Need help?**\n\nClick the button below to create a support ticket. Our staff will assist you as soon as possible!\n\n🔹 **What can we help with?**\n• Technical issues\n• Account problems\n• General questions\n• Report bugs\n• Other concerns",
            color=0x3498db
        )
        ticket_embed.set_footer(text="Tickets are private and only visible to you and staff")
        await tickets_channel.send(embed=ticket_embed, view=TicketView())

        # Send account linking panel
        acc_embed = discord.Embed(
            title="🔗 Account Linking",
            description="**Link your Discord account with your in-game profile!**\n\n🎮 **Why link your account?**\n• Access exclusive features\n• Participate in tournaments\n• Track your progress\n• Get personalized support\n\n📝 **Instructions:**\n• Click the button below\n• Enter your exact in-game name\n• Confirm the details\n\n🌟 **Ready to get started?**",
            color=0xe74c3c
        )
        acc_embed.set_footer(text="Make sure to enter your exact IGN!")
        await accounts_channel.send(embed=acc_embed, view=AccountView())

        # Send region panel
        region_embed = discord.Embed(
            title="🌍 React with your region:",
            description="Click on the buttons below to get your regional role!\n\n🇪🇺 **EU** - @EU\n🌏 **ASIA** - @ASIA\n🇮🇳 **INW** - @INW\n🇺🇸 **US** - @US\n\n*Selecting a new region will remove your previous region role.*",
            color=0x3498db
        )
        region_embed.set_footer(text="Choose your region to connect with players from your area!")
        await regions_channel.send(embed=region_embed, view=RegionPanelView())

        # Update the setup message
        success_embed = discord.Embed(
            title="✅ Server Management Complete!",
            description="Successfully created server structure with roles and channels:",
            color=0x00ff00
        )

        success_embed.add_field(
            name="👥 Roles Created",
            value=f"**Staff Roles:** 👑・Owner, 🛡️・Admin, ⚖️・Moderator, 🤝・Helper\n**Special Roles:** 🎯・Tournament Hoster, 🔗・Linked, 👥・Member\n**Region Roles:** EU, ASIA, INW, US\n\n**Total:** {len(roles_created)} roles",
            inline=False
        )

        success_embed.add_field(
            name="📂 Categories (Ordered by Priority)",
            value="1. 📋 • Information\n2. 🎙️ • General\n3. 🤖 • Bot Functions\n4. 🔊 • Voice Channels",
            inline=True
        )

        success_embed.add_field(
            name="📝 Text Channels",
            value="**Info:** 📜 • rules, 📢 • announcements, 🔄 • updates\n**General:** ☁️ • general, 💬 • chat, 🎮 • gaming\n**Bot:** 🎫 • tickets, 🔗 • link-account, 🏆 • tournaments",
            inline=True
        )

        success_embed.add_field(
            name="🔊 Voice Channels",
            value="🎤 • General Voice\n🎮 • Gaming Voice\n🏆 • Tournament Voice\n🎵 • Music Voice\n📞 • Private Voice",
            inline=True
        )

        success_embed.add_field(
            name="⚙️ Auto-Enabled Systems",
            value="✅ Leveling System\n✅ Welcomer System\n✅ Ticket Panel\n✅ Account Linking\n✅ Region Selection",
            inline=True
        )

        success_embed.set_footer(text="Your server is now fully configured with proper hierarchy and ready to use!")

        await setup_msg.edit(embed=success_embed)

    except discord.Forbidden:
        error_embed = discord.Embed(
            title="❌ Permission Error",
            description="I don't have sufficient permissions to create roles, channels and categories. Please ensure I have Administrator permissions.",
            color=0xff0000
        )
        await setup_msg.edit(embed=error_embed)
    except Exception as e:
        error_embed = discord.Embed(
            title="❌ Setup Failed",
            description=f"An error occurred during server setup: {str(e)}",
            color=0xff0000
        )
        await setup_msg.edit(embed=error_embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def automod_enable(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in automod_settings:
        automod_settings[guild_id] = {'enabled': False, 'spam_detection': True, 'bad_words': True, 'log_channel': None}

    automod_settings[guild_id]['enabled'] = not automod_settings[guild_id]['enabled']
    status = "enabled" if automod_settings[guild_id]['enabled'] else "disabled"
    save_data()
    await ctx.send(f"✅ Automod system {status}!", delete_after=5)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def automod_spam(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in automod_settings:
        automod_settings[guild_id] = {'enabled': True, 'spam_detection': True, 'bad_words': True, 'log_channel': None}

    automod_settings[guild_id]['spam_detection'] = not automod_settings[guild_id]['spam_detection']
    status = "enabled" if automod_settings[guild_id]['spam_detection'] else "disabled"
    save_data()
    await ctx.send(f"✅ Spam detection {status}!", delete_after=5)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def automod_badwords(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in automod_settings:
        automod_settings[guild_id] = {'enabled': True, 'spam_detection': True, 'bad_words': True, 'log_channel': None}

    automod_settings[guild_id]['bad_words'] = not automod_settings[guild_id]['bad_words']
    status = "enabled" if automod_settings[guild_id]['bad_words'] else "disabled"
    save_data()
    await ctx.send(f"✅ Bad words filter {status}!", delete_after=5)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def automod_log(ctx, channel: discord.TextChannel):
    try:
        await ctx.message.delete()
    except:
        pass

    guild_id = str(ctx.guild.id)
    if guild_id not in automod_settings:
        automod_settings[guild_id] = {'enabled': True, 'spam_detection': True, 'bad_words': True, 'log_channel': None}

    automod_settings[guild_id]['log_channel'] = channel.id
    save_data()
    await ctx.send(f"✅ Automod log channel set to {channel.mention}!", delete_after=5)

# Permission system storage
host_roles = {}  # {guild_id: [role_ids]}
admin_roles = {}  # {guild_id: [role_ids]}

def has_host_permission(member, guild):
    """Check if member has host permission (manage_channels, manage_messages, or assigned host role)"""
    if member.guild_permissions.manage_channels or member.guild_permissions.manage_messages:
        return True
    
    guild_id = str(guild.id)
    if guild_id in host_roles:
        member_role_ids = [role.id for role in member.roles]
        return any(role_id in member_role_ids for role_id in host_roles[guild_id])
    
    return False

def has_admin_permission(member, guild):
    """Check if member has admin permission (administrator or assigned admin role)"""
    if member.guild_permissions.administrator:
        return True
    
    guild_id = str(guild.id)
    if guild_id in admin_roles:
        member_role_ids = [role.id for role in member.roles]
        return any(role_id in member_role_ids for role_id in admin_roles[guild_id])
    
    return False

@bot.command()
async def htr(ctx, role: discord.Role):
    """Set Tournament Host Role - allows role to use tournament commands"""
    try:
        await ctx.message.delete()
    except:
        pass

    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ You need Administrator permission to set host roles.", delete_after=5)

    guild_id = str(ctx.guild.id)
    if guild_id not in host_roles:
        host_roles[guild_id] = []

    if role.id not in host_roles[guild_id]:
        host_roles[guild_id].append(role.id)
        await ctx.send(f"✅ {role.mention} can now host tournaments!", delete_after=5)
    else:
        await ctx.send(f"❌ {role.mention} already has host permissions.", delete_after=5)

@bot.command()
async def adr(ctx, role: discord.Role):
    """Set Admin Role - allows role to use admin commands (except svd/svm)"""
    try:
        await ctx.message.delete()
    except:
        pass

    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ You need Administrator permission to set admin roles.", delete_after=5)

    guild_id = str(ctx.guild.id)
    if guild_id not in admin_roles:
        admin_roles[guild_id] = []

    if role.id not in admin_roles[guild_id]:
        admin_roles[guild_id].append(role.id)
        await ctx.send(f"✅ {role.mention} now has admin permissions!", delete_after=5)
    else:
        await ctx.send(f"❌ {role.mention} already has admin permissions.", delete_after=5)

@bot.command()
async def sps(ctx, member: discord.Member = None):
    """Check Seasonal Points"""
    try:
        await ctx.message.delete()
    except:
        pass

    if member is None:
        member = ctx.author

    guild_str = str(ctx.guild.id)
    sp = sp_data.get(guild_str, {}).get(str(member.id), 0)

    embed = discord.Embed(
        title="🏆 Seasonal Points",
        description=f"**Player:** {member.display_name}\n**SP:** {sp}",
        color=0xe74c3c
    )

    try:
        await ctx.author.send(embed=embed)
        await ctx.send("📨 SP information sent via DM!", delete_after=3)
    except discord.Forbidden:
        await ctx.send(embed=embed, delete_after=10)

@bot.command()
async def sps_lb(ctx):
    """Seasonal Points Leaderboard - Top 5"""
    try:
        await ctx.message.delete()
    except:
        pass

    guild_str = str(ctx.guild.id)
    guild_sp_data = sp_data.get(guild_str, {})

    # Sort players by SP
    sorted_players = sorted(guild_sp_data.items(), key=lambda x: x[1], reverse=True)[:5]

    embed = discord.Embed(
        title="🏆 Seasonal Points Leaderboard (Top 5)",
        color=0xf1c40f
    )

    if not sorted_players:
        embed.description = "No players have SP yet!"
    else:
        leaderboard_text = ""
        for i, (user_id, sp) in enumerate(sorted_players, 1):
            user = ctx.guild.get_member(int(user_id))
            if user:
                leaderboard_text += f"**{i}.** {user.display_name} - **{sp} SP**\n"

        embed.description = leaderboard_text

    await ctx.send(embed=embed, delete_after=30)

@bot.command()
async def sps_rst(ctx):
    """Reset Seasonal Points - Admin only"""
    try:
        await ctx.message.delete()
    except:
        pass

    if not has_admin_permission(ctx.author, ctx.guild):
        return await ctx.send("❌ You don't have permission to reset Seasonal Points.", delete_after=5)

    guild_str = str(ctx.guild.id)
    if guild_str in sp_data:
        sp_data[guild_str] = {}
        save_data()
        await ctx.send("✅ All Seasonal Points have been reset for this server!", delete_after=5)
    else:
        await ctx.send("✅ No Seasonal Points to reset in this server!", delete_after=5)

@bot.command()
async def commands(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="🤖 Bot Commands",
        description="Here are all available commands:",
        color=0x3498db
    )

    # Show admin commands only to users with manage_channels permission
    if ctx.author.guild_permissions.manage_channels:
        embed.add_field(
            name="🏆 Tournament Commands (Admin)",
            value="`!create #channel` - Create tournament\n`!start` - Start tournament\n`!winner @player` - Set round winner\n`!fake [number]` - Add 1-16 fake players (default: 1)\n`!cancel` - Cancel tournament\n`!code <code> @user` - Send code via DM to a specific user\n`!code <code>` - Send match code via DM to all players in the current round",
            inline=False
        )
        
        embed.add_field(
            name="👑 Permission Commands (Admin)",
            value="`!htr @role` - Set Tournament Host Role\n`!adr @role` - Set Admin Role",
            inline=False
        )

        embed.add_field(
            name="🛡️ Moderation Commands (Admin)",
            value="`!warn @user [reason]` - Warn member\n`!warn_hs @user` - Show warning history\n`!warnrmv @user` - Remove all warnings\n`!mute @user <time> [reason]` - Mute member\n`!unmute @user` - Unmute member\n`!ban @user [time] [reason]` - Ban member\n`!unban <user_id>` - Unban member\n`!lock [@role1] [@role2]...` - Lock channel (allow specific roles)\n`!unlock` - Unlock channel",
            inline=False
        )

        embed.add_field(
            name="📊 System Commands (Admin)",
            value="`!leveling_channel #channel` - Set level up channel\n`!leveling_enable` - Toggle leveling system\n`!welcomer_channel #channel` - Set welcome channel\n`!welcomer_enable` - Toggle welcomer system\n`!tprst` - Reset all Tournament Points",
            inline=False
        )

        embed.add_field(
            name="🎫 Support Commands (Admin)",
            value="`!ticket_panel` - Create ticket panel\n`!delete_ticket` - Delete current ticket",
            inline=False
        )

        embed.add_field(
            name="🎯 Hoster Registration (Admin)",
            value="`!hosterregist <max_hosters>` - Create hoster registration panel",
        inline=False
        )

        embed.add_field(
            name="🏷️ Bracket Management (Admin)",
            value="`!bracketrole @user emoji1 [emoji2] [emoji3]` - Set bracket emojis for users\n`!bracketrolereset [@user]` - Reset bracket emojis",
            inline=False
        )

        embed.add_field(
            name="🗑️ Server Management (Owner)",
            value="`!svm` - Complete server management setup\n`!svd` - Delete all channels and recreate structure",
            inline=False
        )

        embed.add_field(
            name="🔗 Account Commands (Admin)",
            value="`!acc` - Account linking panel\n`!IGN [@user]` - Show IGN\n`!level [@user]` - Check level (sent via DM)",
            inline=False
        )

        embed.add_field(
            name="🛡️ Automod Commands (Admin)",
            value="`!automod_enable` - Toggle automod system\n`!automod_spam` - Toggle spam detection\n`!automod_badwords` - Toggle bad words filter\n`!automod_log #channel` - Set automod log channel",
            inline=False
        )

        embed.add_field(
            name="💬 Utility Commands (Admin)",
            value="`!embed <text>` - Create embed\n`!regionpanel` - Create region selection panel\n`!experience_personalizer` - Create experience personalizer panel\n`!commands` - Show this menu",
            inline=False
        )

    # Member commands (always visible to everyone)
    embed.add_field(
        name="🤝 Team Commands",
        value="`!invite @user` - Invite user to team (2v2 mode)\n`!leave_team` - Leave current team",
        inline=False
    )

    embed.add_field(
        name="🏆 Seasonal Points",
        value="`!sps [@user]` - Check Seasonal Points\n`!sps_lb` - View SP leaderboard (Top 5)\n`!sps_rst` - Reset Seasonal Points (Admin)",
        inline=False
    )

    embed.add_field(
        name="🏷️ Bracket Display",
        value="`!bracketname` - Show your bracket name\n`!bracketrolereset` - Reset bracket emojis",
        inline=False
    )

    await ctx.send(embed=embed, delete_after=30)

@bot.command()
async def start(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    tournament = get_tournament(ctx.guild.id)

    if tournament.max_players == 0:
        return await ctx.send("❌ No tournament has been created yet. Use `!create #channel` first.", delete_after=5)

    if tournament.active:
        return await ctx.send("❌ Tournament already started.", delete_after=5)

    if len(tournament.players) < 2:
        return await ctx.send("❌ Not enough players to start tournament (minimum 2 players).", delete_after=5)

    # Add fake players if needed to fill up the tournament or ensure even number for 2v2
    needed_players = tournament.max_players
    if tournament.mode == "2v2":
        # Need even number of teams, so total players must be even
        if tournament.max_players % 2 != 0:
            needed_players = tournament.max_players + 1 # Ensure max_players is even

    players_to_add = needed_players - len(tournament.players)

    if players_to_add > 0:
        await ctx.send(f"Adding {players_to_add} bot player(s) to fill the tournament...", delete_after=5)
        # Add fake players as proper objects
        fake_players_added = []
        for i in range(players_to_add):
            fake_name = f"Bot{tournament.fake_count}"
            fake_id = 761557952975420886 + tournament.fake_count
            fake_player = FakePlayer(fake_name, fake_id)

            # For 2v2 mode, ensure fake players are paired
            if tournament.mode == "2v2":
                if i % 2 == 0: # Start of a potential team
                    fake_players_added.append(fake_player)
                else: # Second player of a team
                    if fake_players_added and fake_players_added[-1] and fake_players_added[-1].id in tournament.teams: # Check if last player is already paired
                        fake_players_added.append(fake_player)
                        # Create team relationship
                        player1 = fake_players_added[-2]
                        player2 = fake_players_added[-1]
                        tournament.teams[player1.id] = player2.id
                        tournament.teams[player2.id] = player1.id
                    else: # This case should ideally not happen if players_to_add is even
                        fake_players_added.append(fake_player) # Add as single player if pairing fails
            else:
                fake_players_added.append(fake_player)

            tournament.fake_count += 1
        tournament.players.extend(fake_players_added)


    # For 2v2 mode, keep teams together when shuffling
    if tournament.mode == "2v2":
        # Group players by teams, then shuffle the teams
        teams_list = []
        processed_players = set()

        for player in tournament.players:
            if player in processed_players or isinstance(player, FakePlayer):
                continue

            if hasattr(player, 'id') and player.id in tournament.teams:
                teammate_id = tournament.teams[player.id]
                teammate = next((p for p in tournament.players if hasattr(p, 'id') and p.id == teammate_id), None)
                if teammate:
                    teams_list.append([player, teammate])
                    processed_players.add(player)
                    processed_players.add(teammate)
            else:
                # Single player (shouldn't happen in 2v2 but handle it)
                teams_list.append([player])
                processed_players.add(player)

        # Add any fake teams
        for player in tournament.players:
            if isinstance(player, FakePlayer) and player not in processed_players:
                if player.id in tournament.teams:
                    teammate_id = tournament.teams[player.id]
                    teammate = next((p for p in tournament.players if isinstance(p, FakePlayer) and p.id == teammate_id), None)
                    if teammate and teammate not in processed_players:
                        teams_list.append([player, teammate])
                        processed_players.add(player)
                        processed_players.add(teammate)

        # Shuffle the teams order, not the team composition
        random.shuffle(teams_list)

        # Flatten back to player list while preserving teams
        tournament.players = []
        for team in teams_list:
            tournament.players.extend(team)
    else:
        # For 1v1 mode, shuffle normally
        random.shuffle(tournament.players)


    tournament.active = True
    tournament.results = []
    tournament.rounds = []

    if tournament.mode == "2v2":
        teams = []
        for i in range(0, len(tournament.players), 2):
            teams.append((tournament.players[i], tournament.players[i+1]))

        round_pairs = [(teams[i], teams[i+1]) for i in range(0, len(teams), 2)]
    else:
        round_pairs = [(tournament.players[i], tournament.players[i+1]) for i in range(0, len(tournament.players), 2)]

    tournament.rounds.append(round_pairs)

    embed = discord.Embed(
        title=f"🏆 {tournament.title} - Round 1",
        description=f"**Map:** {tournament.map}\n**Mode:** {tournament.mode}\n**Abilities:** {tournament.abilities}",
        color=0x3498db
    )

    for i, match in enumerate(round_pairs, 1):
        if tournament.mode == "2v2":
            team_a, team_b = match
            team_a_str = f"{get_player_display_name(team_a[0], ctx.guild.id)} & {get_player_display_name(team_a[1], ctx.guild.id)}"
            team_b_str = f"{get_player_display_name(team_b[0], ctx.guild.id)} & {get_player_display_name(team_b[1], ctx.guild.id)}"
            embed.add_field(
                name=f"⚔️ Match {i}",
                value=f"**{team_a_str}** <:VS:1402690899485655201> **{team_b_str}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                inline=False
            )
        else:
            a, b = match
            player_a = get_player_display_name(a, ctx.guild.id)
            player_b = get_player_display_name(b, ctx.guild.id)
            embed.add_field(
                name=f"⚔️ Match {i}",
                value=f"**{player_a}** <:VS:1402690899485655201> **{player_b}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                inline=False
            )

    embed.set_footer(text="Use !winner @player to record match results")

    # Create a new view without buttons for active tournament
    active_tournament_view = discord.ui.View()
    tournament.message = await ctx.send(embed=embed, view=active_tournament_view)

@bot.command()
async def winner(ctx, member: discord.Member):
    try:
        await ctx.message.delete()
    except:
        pass

    tournament = get_tournament(ctx.guild.id)

    if not tournament.active:
        return await ctx.send("❌ No active tournament.", delete_after=5)

    current_round = tournament.rounds[-1]
    winner_name = get_player_display_name(member, ctx.guild.id)

    # Find and update the match
    match_found = False
    eliminated_players = []
    match_index = -1
    winner_team = None

    for i, match in enumerate(current_round):
        if tournament.mode == "2v2":
            team_a, team_b = match
            # Check if the winning member is in team_a or team_b
            if member in team_a or member in team_b:
                # Determine the winning team and the eliminated team
                if member in team_a:
                    winner_team = team_a
                    eliminated_team = team_b
                else:
                    winner_team = team_b
                    eliminated_team = team_a

                tournament.results.append(winner_team)
                tournament.eliminated.extend(eliminated_team)
                match_found = True
                match_index = i
                break
        else:
            a, b = match
            if member == a or member == b:
                tournament.results.append(member)
                eliminated_players.extend([a if member == b else b])
                match_found = True
                match_index = i
                break

    if not match_found:
        return await ctx.send("❌ This player is not in the current round.", delete_after=5)

    # Add eliminated players to elimination list
    tournament.eliminated.extend(eliminated_players)

    # Update current tournament message to show the winner
    if tournament.message:
        try:
            current_embed = tournament.message.embeds[0]

            # Find and update the specific match field
            if match_index >= 0 and match_index < len(current_embed.fields):
                field = current_embed.fields[match_index]
                if "Match" in field.name:
                    field_value = field.value
                    lines = field_value.split('\n')

                    if tournament.mode == "2v2":
                        winner_team_str = f"{get_player_display_name(winner_team[0], ctx.guild.id)} & {get_player_display_name(winner_team[1], ctx.guild.id)}"
                        lines[1] = f"<:Crown:1409926966236283012> Winner: **{winner_team_str}**"
                    else:
                        lines[1] = f"<:Crown:1409926966236283012> Winner: **{get_player_display_name(member, ctx.guild.id)}**"

                    current_embed.set_field_at(match_index, name=field.name, value='\n'.join(lines), inline=field.inline)
                    await tournament.message.edit(embed=current_embed)

        except Exception as e:
            print(f"Error updating tournament message: {e}")

    # Check if round is complete
    if len(tournament.results) == len(current_round):
        if len(tournament.results) == 1:
            # Tournament finished - determine placements and award TP
            winner_data = tournament.results[0]

            # Calculate placements based on elimination order
            all_eliminated = tournament.eliminated

            # Get the final 4 placements
            placements = [] # List of (place, player_or_team, tp_reward)

            if tournament.mode == "2v2":
                # Group all eliminated players back into teams properly
                eliminated_teams = []
                processed_players = set()

                # Process all eliminated players and group them into teams
                for player in all_eliminated:
                    if player in processed_players:
                        continue

                    if hasattr(player, 'id') and player.id in tournament.teams:
                        teammate_id = tournament.teams[player.id]
                        # Find the teammate in eliminated players
                        teammate = None
                        for p in all_eliminated:
                            if hasattr(p, 'id') and p.id == teammate_id:
                                teammate = p
                                break

                        if teammate and teammate not in processed_players:
                            eliminated_teams.append([player, teammate])
                            processed_players.add(player)
                            processed_players.add(teammate)
                    else:
                        # Single player (shouldn't happen in 2v2 but handle it)
                        eliminated_teams.append([player])
                        processed_players.add(player)

                # 1st place (winner team)
                if isinstance(winner_data, list) and len(winner_data) >= 2:
                    placements.append((1, winner_data, 100))
                    # Award TP to both team members
                    for player in winner_data:
                        if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                            add_tp(ctx.guild.id, player.id, 100)
                            save_data()  # Save after each TP award

                # Assign placements to teams (reverse order - last eliminated gets 2nd place)
                tp_rewards = [70, 50, 50, 30]  # 2nd, 3rd, 4th place rewards

                # Show eliminated teams in reverse order (last eliminated = 2nd place)
                for i in range(min(len(eliminated_teams), 3)):  # Top 3 eliminated teams
                    team = eliminated_teams[-(i+1)]  # Start from last eliminated (2nd place)
                    place = i + 2  # 2nd, 3rd, 4th
                    tp_reward = tp_rewards[i] if i < len(tp_rewards) else 30
                    placements.append((place, team, tp_reward))

                    # Award TP to all team members
                    for player in team:
                        if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                            add_tp(ctx.guild.id, player.id, tp_reward)
                            save_data()  # Save after each TP award

            else: # 1v1 mode
                # 1st place (winner)
                placements.append((1, winner_data, 100))
                if hasattr(winner_data, 'id') and not isinstance(winner_data, FakePlayer):
                    add_tp(ctx.guild.id, winner_data.id, 100)

                # 2nd place (last eliminated)
                if len(all_eliminated) >= 1:
                    placements.append((2, all_eliminated[-1], 70))
                    player = all_eliminated[-1]
                    if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                        add_tp(ctx.guild.id, player.id, 70)

                # 3rd and 4th place
                if len(all_eliminated) >= 2:
                    placements.append((3, all_eliminated[-2], 50))
                    player = all_eliminated[-2]
                    if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                        add_tp(ctx.guild.id, player.id, 50)
                if len(all_eliminated) >= 3:
                    placements.append((4, all_eliminated[-3], 50))
                    player = all_eliminated[-3]
                    if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                        add_tp(ctx.guild.id, player.id, 50)

            # Create styled tournament winners embed - fix winner message
            if tournament.mode == "2v2":
                if isinstance(winner_data, list) and len(winner_data) >= 2:
                    winner_display = f"{get_player_display_name(winner_data[0], ctx.guild.id)} & {get_player_display_name(winner_data[1], ctx.guild.id)}"
                else:
                    winner_display = "Unknown Team"
            else:
                winner_display = get_player_display_name(winner_data, ctx.guild.id)

            embed = discord.Embed(
                title="🏆 Tournament Winners!",
                description=f"Congratulations to **{winner_display}** for winning the\n**{tournament.title}** tournament! 🎉",
                color=0xffd700
            )

            # Add tournament info with custom emojis
            embed.add_field(name="<:map:1407383523261677792> Map", value=tournament.map, inline=True)
            embed.add_field(name="<:abilities:1404513040505765939> Abilities", value=tournament.abilities, inline=True)
            embed.add_field(name="🎮 Mode", value=tournament.mode, inline=True)

            # Create results text without TP display (TP only shown in prizes)
            results_display = ""
            for place, player_or_team, tp in placements:
                if place == 1:
                    emoji = "🥇"
                elif place == 2:
                    emoji = "🥈"
                elif place == 3:
                    emoji = "🥉"
                elif place == 4:
                    emoji = "4️⃣"
                else:
                    emoji = "📍"

                if tournament.mode == "2v2":
                    if isinstance(player_or_team, list) and len(player_or_team) >= 2:
                        team_str = f"{get_player_display_name(player_or_team[0], ctx.guild.id)} & {get_player_display_name(player_or_team[1], ctx.guild.id)}"
                    elif isinstance(player_or_team, list) and len(player_or_team) == 1:
                        team_str = get_player_display_name(player_or_team[0], ctx.guild.id)
                    else:
                        team_str = "Unknown Team"
                else:
                    team_str = get_player_display_name(player_or_team, ctx.guild.id)

                results_display += f"{emoji} {team_str}\n"

            # Add final rankings - ensure we show top 4 for 2v2
            if tournament.mode == "2v2":
                embed.add_field(name="🥇 Final Rankings (Top 4 Teams)", value=results_display, inline=False)
            else:
                embed.add_field(name="🥇 Final Rankings", value=results_display, inline=False)

            # Add prizes section with TP
            prize_text = ""
            for place, player_or_team, tp in placements:
                if place == 1:
                    emoji = "🥇"
                elif place == 2:
                    emoji = "🥈"
                elif place == 3:
                    emoji = "🥉"
                elif place == 4:
                    emoji = "4️⃣"
                else:
                    emoji = "📍"

                place_suffix = "st" if place == 1 else "nd" if place == 2 else "rd" if place == 3 else "th"
                prize_text += f"{emoji} {place}{place_suffix}: {tp} TP per player\n"

            embed.add_field(name="🏆 Prizes", value=prize_text, inline=False)

            # Add winner's avatar if it's a real player
            if tournament.mode == "2v2":
                winner_player_obj = winner_data[0] if isinstance(winner_data, list) else winner_data
            else:
                winner_player_obj = winner_data

            if hasattr(winner_player_obj, 'display_avatar') and not isinstance(winner_player_obj, FakePlayer):
                embed.set_thumbnail(url=winner_player_obj.display_avatar.url)

            # Add footer with tournament ID and timestamp
            embed.set_footer(text=f"Tournament completed • {datetime.now().strftime('%d.%m.%Y %H:%M')}")

            # Create a new view without buttons for the completed tournament
            completed_view = discord.ui.View()
            await ctx.send(embed=embed, view=completed_view)

            # Reset tournament
            tournament.__init__()
        else:
            # Create next round
            next_round_pairs = []
            if tournament.mode == "2v2":
                teams = tournament.results
                for i in range(0, len(teams), 2):
                    if i + 1 < len(teams):
                        next_round_pairs.append((teams[i], teams[i+1]))
            else:
                for i in range(0, len(tournament.results), 2):
                    if i + 1 < len(tournament.results):
                        next_round_pairs.append((tournament.results[i], tournament.results[i+1]))

            tournament.rounds.append(next_round_pairs)
            tournament.results = []

            round_num = len(tournament.rounds)
            embed = discord.Embed(
                title=f"🏆 {tournament.title} - Round {round_num}",
                description=f"**Map:** {tournament.map}\n**Mode:** {tournament.mode}\n**Abilities:** {tournament.abilities}",
                color=0x3498db
            )

            for i, match in enumerate(next_round_pairs, 1):
                if tournament.mode == "2v2":
                    team_a, team_b = match
                    team_a_str = f"{get_player_display_name(team_a[0], ctx.guild.id)} & {get_player_display_name(team_a[1], ctx.guild.id)}"
                    team_b_str = f"{get_player_display_name(team_b[0], ctx.guild.id)} & {get_player_display_name(team_b[1], ctx.guild.id)}"
                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{team_a_str}** <:VS:1402690899485655201> **{team_b_str}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )
                else:
                    a, b = match
                    player_a = get_player_display_name(a, ctx.guild.id)
                    player_b = get_player_display_name(b, ctx.guild.id)
                    embed.add_field(
                        name=f"⚔️ Match {i}",
                        value=f"**{player_a}** <:VS:1402690899485655201> **{player_b}**\n<:Crown:1409926966236283012> Winner: *Waiting...*",
                        inline=False
                    )

            embed.set_footer(text="Use !winner @player to record match results")

            # Create a new view without buttons for active tournament
            active_tournament_view = discord.ui.View()
            tournament.message = await ctx.send(embed=embed, view=active_tournament_view)

    await ctx.send(f"✅ {winner_name} wins their match!", delete_after=5)


class FakePlayer:
    def __init__(self, name, user_id):
        self.display_name = name
        self.name = name
        self.nick = name
        self.id = user_id
        self.mention = f"<@{user_id}>"

    def __str__(self):
        return self.mention

@bot.command()
async def fake(ctx, number: int = 1):
    try:
        await ctx.message.delete()
    except:
        pass

    tournament = get_tournament(ctx.guild.id)

    if number < 1 or number > 16:
        return await ctx.send("❌ Number must be between 1 and 16.", delete_after=5)

    if tournament.max_players == 0:
        return await ctx.send("❌ No tournament created yet.", delete_after=5)

    if tournament.active:
        return await ctx.send("❌ Tournament already started.", delete_after=5)

    available_spots = tournament.max_players - len(tournament.players)

    # For 2v2 mode, we need even number of fake players to form complete teams
    if tournament.mode == "2v2":
        # Calculate how many fake players we need for complete teams
        if number % 2 != 0:
            number += 1  # Make it even for team formation

        if number > available_spots:
            # Adjust to fit available spots and keep even
            number = available_spots - (available_spots % 2)
            if number <= 0:
                return await ctx.send(f"❌ No space for complete fake teams. Need {available_spots} spots.", delete_after=5)
    else:
        if number > available_spots:
            return await ctx.send(f"❌ Only {available_spots} spots available.", delete_after=5)

    # Create fake players as proper objects
    fake_players = []
    for i in range(number):
        fake_name = f"FakePlayer{tournament.fake_count}"
        fake_id = 761557952975420886 + tournament.fake_count
        fake_player = FakePlayer(fake_name, fake_id)
        fake_players.append(fake_player)
        tournament.fake_count += 1

    # For 2v2 mode, create fake teams
    if tournament.mode == "2v2":
        # Pair fake players together as teammates
        for i in range(0, len(fake_players), 2):
            if i + 1 < len(fake_players):
                player1 = fake_players[i]
                player2 = fake_players[i + 1]

                # Create team relationship
                tournament.teams[player1.id] = player2.id
                tournament.teams[player2.id] = player1.id

                # Add both players to tournament
                tournament.players.extend([player1, player2])

    else:
        # For 1v1 mode, just add players normally
        tournament.players.extend(fake_players)

    fake_list = ", ".join([f.display_name for f in fake_players])

    if tournament.mode == "2v2":
        teams_added = len(fake_players) // 2
        await ctx.send(f"🤖 Added {teams_added} fake team{'s' if teams_added > 1 else ''}: {fake_list}\nTotal teams: {len(tournament.players)//2}/{tournament.max_players//2}", delete_after=10)
    else:
        await ctx.send(f"🤖 Added {number} fake player{'s' if number > 1 else ''}: {fake_list}\nTotal players: {len(tournament.players)}/{tournament.max_players}", delete_after=10)

def has_host_permission(member, guild):
    """Check if member has host permission (manage_channels or manage_messages)"""
    return member.guild_permissions.manage_channels or member.guild_permissions.manage_messages

@bot.command()
async def code(ctx, code: str, member: discord.Member = None):
    try:
        await ctx.message.delete()
    except:
        pass

    tournament = get_tournament(ctx.guild.id)

    if not tournament.active:
        return await ctx.send("❌ No active tournament.", delete_after=5)

    # Check if user has permission to send codes (host roles or admin permissions)
    if not has_host_permission(ctx.author, ctx.guild):
        return await ctx.send("❌ You don't have permission to send tournament codes.", delete_after=5)

    # If specific member is mentioned, send only to them
    if member:
        if isinstance(member, FakePlayer):
            return await ctx.send("❌ Cannot send codes to fake players.", delete_after=5)

        host_name = ctx.author.nick if ctx.author.nick else ctx.author.display_name
        code_message = f"<:CUSTOM_PARTY:1402687513323245630> **Round code is**\n```{code}```\n**Hosted by:** {host_name}"

        try:
            await member.send(code_message)
            await ctx.send(f"✅ Code sent to {member.display_name} via DM!", delete_after=5)
        except discord.Forbidden:
            await ctx.send(f"❌ Failed to send DM to {member.display_name}. They may have DMs disabled.", delete_after=10)
        except Exception as e:
            await ctx.send(f"❌ Failed to send DM to {member.display_name}: {str(e)}", delete_after=10)
        return

    # Get all players from current round
    current_round = tournament.rounds[-1]
    round_players = []

    for match in current_round:
        if tournament.mode == "2v2":
            team_a, team_b = match
            # Add all real players from both teams
            for player in team_a + team_b:
                if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                    # Ensure we get the actual member object
                    member_obj = ctx.guild.get_member(player.id) if hasattr(player, 'id') else player
                    if member_obj and member_obj not in round_players:
                        round_players.append(member_obj)
        else:
            a, b = match
            for player in [a, b]:
                if hasattr(player, 'id') and not isinstance(player, FakePlayer):
                    # Ensure we get the actual member object
                    member_obj = ctx.guild.get_member(player.id) if hasattr(player, 'id') else player
                    if member_obj and member_obj not in round_players:
                        round_players.append(member_obj)

    if not round_players:
        return await ctx.send("❌ No real players found in current round.", delete_after=5)

    # Send code to all round players
    host_name = ctx.author.nick if ctx.author.nick else ctx.author.display_name
    code_message = f"<:CUSTOM_PARTY:1402687513323245630> **Round code is**\n```{code}```\n**Hosted by:** {host_name}"

    sent_count = 0
    failed_players = []

    for player in round_players:
        try:
            await player.send(code_message)
            sent_count += 1
        except discord.Forbidden:
            player_name = player.nick if player.nick else player.display_name
            failed_players.append(player_name)
        except Exception as e:
            player_name = player.nick if player.nick else player.display_name
            failed_players.append(f"{player_name} ({str(e)})")

    result_msg = f"✅ Code sent to {sent_count}/{len(round_players)} players via DM!"
    if failed_players:
        result_msg += f"\n❌ Failed to send to: {', '.join(failed_players)}"

    await ctx.send(result_msg, delete_after=15)

@bot.command()
async def cancel(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    tournament = get_tournament(ctx.guild.id)
    tournament.__init__()
    await ctx.send("❌ Tournament cancelled.", delete_after=5)

# Run the bot
if __name__ == "__main__":
    if not TOKEN:
        print("❌ No Discord token found! Please add your bot token to the Secrets.")
        print("Go to the Secrets tool and add:")
        print("Key: TOKEN")
        print("Value: Your Discord bot token")
    else:
        try:
            keep_alive()
            bot.run(TOKEN)
        except Exception as e:
            print(f"❌ Error starting bot: {e}")
