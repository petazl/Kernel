import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
from collections import defaultdict, deque
import os
import json
import re
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# Your server ID for instant slash-command updates
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0"))

# Channel where the role-selection panels will be created
ROLES_CHANNEL_ID = int(os.getenv("ROLES_CHANNEL_ID", "0"))

# Channel where welcome messages will be sent
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))

# Channel where Kernel will send moderation/watchdog logs
MOD_LOG_CHANNEL_ID = int(os.getenv("MOD_LOG_CHANNEL_ID", "0"))

# Channel where the rules will be posted
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", "0"))

# Role ID for the exec role, used in the rules message
EXEC_ROLE_ID = int(os.getenv("EXEC_ROLE_ID", "0"))

# File used to remember role/message IDs between restarts
SETUP_FILE = "role_setup.json"

# Watchdog settings
WATCHDOG_WORDS = [
    "internship",
    "internships",
    "job",
    "jobs",
]

WATCHDOG_LIMIT = 3
WATCHDOG_WINDOW = 5 * 60
WATCHDOG_TIMEOUT = 5
WARNING_DELETE_AFTER = 10


# ============================================================
# INTENTS
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True


# ============================================================
# BOT
# ============================================================

class KernelBot(commands.Bot):

    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents
        )

        self.setup_data = self.load_setup_data()

    # Load saved role/message information
    def load_setup_data(self):

        if not os.path.exists(SETUP_FILE):
            return {
                "setup_complete": False,
                "roles": {},
                "messages": []
            }

        try:

            with open(
                SETUP_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            data.setdefault("setup_complete", False)
            data.setdefault("roles", {})
            data.setdefault("messages", [])

            return data

        except (json.JSONDecodeError, OSError):

            print("WARNING: Could not read role_setup.json.")
            print("Starting with a fresh setup state.")

            return {
                "setup_complete": False,
                "roles": {},
                "messages": []
            }

    # Save role/message information
    def save_setup_data(self):

        with open(
            SETUP_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                self.setup_data,
                f,
                indent=4
            )

    async def setup_hook(self):

        print("Kernel is starting...")

        # Register persistent role buttons
        self.add_view(RoleView(self))

        # Sync slash commands
        if TEST_GUILD_ID:

            guild = discord.Object(
                id=TEST_GUILD_ID
            )

            self.tree.copy_global_to(
                guild=guild
            )

            await self.tree.sync(
                guild=guild
            )

            print("Slash commands synced to test server.")

        else:

            await self.tree.sync()

            print("Global slash commands synced.")

    async def on_ready(self):

        print("--------------------------------")
        print(f"Logged in as {self.user}")
        print(f"Bot ID: {self.user.id}")
        print("--------------------------------")

        if self.setup_data["setup_complete"]:

            print("Role setup data loaded successfully.")

            print(
                f"Stored roles: "
                f"{len(self.setup_data['roles'])}"
            )

            print(
                f"Stored messages: "
                f"{len(self.setup_data['messages'])}"
            )

        else:

            print("Role setup has not been completed.")


bot = KernelBot()


# ============================================================
# ROLE DEFINITIONS
# ============================================================

ROLE_GROUPS = {

    "study": {

        "title": "Level of Study",

        "description": (
            "Select your current level of study. "
            "You can only have one study-level role."
        ),

        "single_select": True,

        "roles": {

            "study_1": "1st Year",
            "study_2": "2nd Year",
            "study_3": "3rd Year",
            "study_4": "4th Year",
            "study_pg": "Postgraduate",
            "study_prospective": "Prospective Student",
            "study_graduate": "Graduate",

        }
    },


    "course": {

        "title": "Course",

        "description": (
            "Select your course area. "
            "You can only have one course role."
        ),

        "single_select": True,

        "roles": {

            "course_engineering": "Engineering",
            "course_cs": "Computer Science",
            "course_cse": "Computer Systems Engineering",
            "course_maths": "Maths",
            "course_other_stem": "Other STEM",
            "course_non_stem": "Non-STEM",

        }
    },


    "announcements": {

        "title": "Get Announcements",

        "description": (
            "Choose which UWES announcements you'd like "
            "to receive. You can select as many as you want."
        ),

        "single_select": False,

        "roles": {

            "announce_hacksprint": "Hacksprint",
            "announce_social": "Social",
            "announce_academic": "Academic",
            "announce_gaming": "Gaming",
            "announce_design_jam": "Design Jam",

        }
    }
}


# ============================================================
# ROLE HELPERS
# ============================================================

def get_saved_role_id(role_key):

    return bot.setup_data["roles"].get(
        role_key
    )


def get_role_by_key(guild, role_key):

    role_id = get_saved_role_id(
        role_key
    )

    if not role_id:
        return None

    return guild.get_role(
        int(role_id)
    )


# ============================================================
# ROLE BUTTON
# ============================================================

class RoleButton(discord.ui.Button):

    def __init__(
        self,
        bot_instance,
        group_key,
        role_key,
        label
    ):

        self.bot_instance = bot_instance
        self.group_key = group_key
        self.role_key = role_key

        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,

            # Stable custom ID means buttons still work
            # after Kernel restarts.
            custom_id=(
                f"kernel_role:"
                f"{group_key}:"
                f"{role_key}"
            )
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        guild = interaction.guild

        if guild is None:

            await interaction.response.send_message(
                "This button can only be used inside the server.",
                ephemeral=True
            )

            return

        # Look up the real Discord role ID from saved data
        role = get_role_by_key(
            guild,
            self.role_key
        )

        if role is None:

            await interaction.response.send_message(
                "I couldn't find that role. "
                "An administrator may need to run "
                "`/reset_roles` and `/setup_roles` again.",
                ephemeral=True
            )

            return

        group = ROLE_GROUPS[
            self.group_key
        ]

        # ----------------------------------------------------
        # SINGLE SELECT
        # ----------------------------------------------------

        if group["single_select"]:

            roles_to_remove = []

            for other_role_key in group["roles"]:

                if other_role_key == self.role_key:
                    continue

                other_role = get_role_by_key(
                    guild,
                    other_role_key
                )

                if (
                    other_role
                    and other_role in interaction.user.roles
                ):

                    roles_to_remove.append(
                        other_role
                    )

            # Clicking your current role removes it
            if role in interaction.user.roles:

                await interaction.user.remove_roles(
                    role
                )

                await interaction.response.send_message(
                    f"Removed **{role.name}**.",
                    ephemeral=True
                )

                return

            # Remove other roles in this category
            if roles_to_remove:

                await interaction.user.remove_roles(
                    *roles_to_remove
                )

            await interaction.user.add_roles(
                role
            )

            await interaction.response.send_message(
                f"Assigned **{role.name}**.",
                ephemeral=True
            )

        # ----------------------------------------------------
        # MULTI SELECT
        # ----------------------------------------------------

        else:

            if role in interaction.user.roles:

                await interaction.user.remove_roles(
                    role
                )

                await interaction.response.send_message(
                    f"Removed **{role.name}**.",
                    ephemeral=True
                )

            else:

                await interaction.user.add_roles(
                    role
                )

                await interaction.response.send_message(
                    f"Added **{role.name}**.",
                    ephemeral=True
                )


# ============================================================
# ROLE VIEW
# ============================================================

class RoleView(discord.ui.View):

    def __init__(self, bot_instance):

        super().__init__(
            timeout=None
        )

        self.bot_instance = bot_instance

        # Create persistent buttons using stable role keys
        for group_key, group in ROLE_GROUPS.items():

            for role_key, role_name in group["roles"].items():

                self.add_item(
                    RoleButton(
                        bot_instance,
                        group_key,
                        role_key,
                        role_name
                    )
                )


# ============================================================
# WATCHDOG
# ============================================================

user_violations = defaultdict(
    deque
)


WATCHDOG_PATTERN = re.compile(
    r"\b(?:internship|internships|job|jobs)\b",
    re.IGNORECASE
)


async def send_mod_log(
    guild,
    member,
    channel,
    action,
    triggered_word,
    violation_count,
    message_content
):

    if not MOD_LOG_CHANNEL_ID:
        return

    log_channel = guild.get_channel(
        MOD_LOG_CHANNEL_ID
    )

    if log_channel is None:
        return

    embed = discord.Embed(
        title="⚠️ WATCHDOG VIOLATION",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )

    # User @mention and username
    embed.add_field(
        name="User",
        value=f"{member.mention} ({member})",
        inline=False
    )

    # Discord user ID
    embed.add_field(
        name="User ID",
        value=f"`{member.id}`",
        inline=False
    )

    # Channel where violation occurred
    embed.add_field(
        name="Channel",
        value=channel.mention,
        inline=True
    )

    # Keyword that triggered watchdog
    embed.add_field(
        name="Keyword",
        value=f"`{triggered_word}`",
        inline=True
    )

    # Current strike count
    embed.add_field(
        name="Violations",
        value=f"{violation_count}/{WATCHDOG_LIMIT}",
        inline=True
    )

    # Action taken
    embed.add_field(
        name="Action",
        value=action,
        inline=False
    )

    # Original message
    # Discord embed fields have a 1024-character limit
    embed.add_field(
        name="Message",
        value=(
            message_content[:1024]
            if message_content
            else "*No message content*"
        ),
        inline=False
    )

    try:

        await log_channel.send(
            embed=embed
        )

    except discord.Forbidden:

        print(
            "WATCHDOG ERROR: Kernel cannot send "
            "messages to the mod-log channel."
        )


async def handle_watchdog(message):

    if message.author.bot:
        return False

    match = WATCHDOG_PATTERN.search(
        message.content
    )

    if not match:
        return False

    user_id = message.author.id
    now = discord.utils.utcnow()

    violations = user_violations[
        user_id
    ]

    # Remove violations older than the 5-minute window
    while violations:

        age = (
            now - violations[0]
        ).total_seconds()

        if age > WATCHDOG_WINDOW:

            violations.popleft()

        else:

            break

    violations.append(
        now
    )

    triggered_word = match.group(0)
    original_message = message.content

    # --------------------------------------------------------
    # DELETE OFFENDING MESSAGE
    # --------------------------------------------------------

    try:

        await message.delete()

    except discord.Forbidden:

        print(
            "WATCHDOG ERROR: "
            "Kernel cannot delete messages."
        )

    except discord.NotFound:

        pass

    # --------------------------------------------------------
    # TIMEOUT AFTER 3 VIOLATIONS
    # --------------------------------------------------------

    if len(violations) >= WATCHDOG_LIMIT:

        if isinstance(
            message.author,
            discord.Member
        ):

            try:

                timeout_until = (
                    now +
                    timedelta(
                        minutes=WATCHDOG_TIMEOUT
                    )
                )

                await message.author.timeout(
                    timeout_until,
                    reason=(
                        "Repeated use of prohibited "
                        "watchdog terms."
                    )
                )

                await send_mod_log(
                    guild=message.guild,
                    member=message.author,
                    channel=message.channel,
                    action=(
                        f"{WATCHDOG_TIMEOUT}-minute timeout"
                    ),
                    triggered_word=triggered_word,
                    violation_count=len(violations),
                    message_content=original_message
                )

                # Public warning
                warning = await message.channel.send(
                    f"⚠️ **WATCHDOG VIOLATION**\n"
                    f"{message.author.mention} please censor "
                    f"that word. **You have reached "
                    f"{WATCHDOG_LIMIT} strikes and have been "
                    f"timed out for {WATCHDOG_TIMEOUT} minutes.**"
                )

                await warning.delete(
                    delay=WARNING_DELETE_AFTER
                )

            except discord.Forbidden:

                print(
                    "WATCHDOG ERROR: "
                    "Kernel cannot timeout this member."
                )

                await send_mod_log(
                    guild=message.guild,
                    member=message.author,
                    channel=message.channel,
                    action=(
                        "Timeout FAILED - missing permissions"
                    ),
                    triggered_word=triggered_word,
                    violation_count=len(violations),
                    message_content=original_message
                )

            except discord.HTTPException as e:

                print(
                    f"WATCHDOG ERROR: {e}"
                )

        # Reset violation counter
        violations.clear()

    # --------------------------------------------------------
    # NORMAL WARNING
    # --------------------------------------------------------

    else:

        remaining = (
            WATCHDOG_LIMIT -
            len(violations)
        )

        await send_mod_log(
            guild=message.guild,
            member=message.author,
            channel=message.channel,
            action="Message deleted - warning issued",
            triggered_word=triggered_word,
            violation_count=len(violations),
            message_content=original_message
        )

        # Public warning
        warning = await message.channel.send(
            f"⚠️ **WATCHDOG VIOLATION**\n"
            f"{message.author.mention} please censor "
            f"that word. **{remaining} strike"
            f"{'s' if remaining != 1 else ''} remaining.**"
        )

        await warning.delete(
            delay=WARNING_DELETE_AFTER
        )

    return True


# ============================================================
# MESSAGE EVENT
# ============================================================

@bot.event
async def on_message(message):

    print(
        f"Message from {message.author}: "
        f"{message.content}"
    )

    if message.author.bot:
        return

    # If watchdog catches the message,
    # don't process it further
    if await handle_watchdog(message):
        return

    await bot.process_commands(
        message
    )


# ============================================================
# SETUP ROLES
# ============================================================

@bot.tree.command(
    name="setup_roles",
    description="Set up the UWES role-selection panels."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setup_roles(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    # Find the configured roles channel
    channel = interaction.guild.get_channel(
        ROLES_CHANNEL_ID
    )

    if channel is None:

        await interaction.followup.send(
            "I couldn't find the configured roles channel.",
            ephemeral=True
        )

        return

    # --------------------------------------------------------
    # CHECK EXISTING SETUP
    # --------------------------------------------------------

    if bot.setup_data["setup_complete"]:

        existing_messages = []

        for message_id in bot.setup_data["messages"]:

            try:

                message = await channel.fetch_message(
                    int(message_id)
                )

                existing_messages.append(
                    message
                )

            except discord.NotFound:

                pass

            except discord.HTTPException:

                pass

        # Don't create duplicate panels if the old ones exist
        if existing_messages:

            await interaction.followup.send(
                "Role selection has already been set up.\n\n"
                "If you want to rebuild it, run "
                "`/reset_roles` first.",
                ephemeral=True
            )

            return

        # Old panels no longer exist, so clear their IDs
        bot.setup_data["setup_complete"] = False
        bot.setup_data["messages"] = []

        bot.save_setup_data()

    # --------------------------------------------------------
    # CREATE ROLES
    # --------------------------------------------------------

    await interaction.followup.send(
        "Setting up UWES roles...",
        ephemeral=True
    )

    for group_key, group in ROLE_GROUPS.items():

        for role_key, role_name in group["roles"].items():

            # Check whether we already know this role
            existing_role = get_role_by_key(
                interaction.guild,
                role_key
            )

            if existing_role is not None:
                continue

            # Check whether a role with this name already exists
            role = discord.utils.get(
                interaction.guild.roles,
                name=role_name
            )

            if role is None:

                try:

                    role = await interaction.guild.create_role(
                        name=role_name,
                        reason="UWES Kernel role setup"
                    )

                except discord.Forbidden:

                    await interaction.followup.send(
                        "I don't have permission to create roles.\n"
                        "Give Kernel the **Manage Roles** permission.",
                        ephemeral=True
                    )

                    return

            # Save actual Discord role ID
            bot.setup_data["roles"][role_key] = str(
                role.id
            )

    bot.save_setup_data()

    # --------------------------------------------------------
    # LEVEL OF STUDY PANEL
    # --------------------------------------------------------

    study_embed = discord.Embed(
        title="🎓 Level of Study",
        description=(
            "Select your current level of study.\n\n"
            "You can only have **one** "
            "level-of-study role."
        ),
        color=discord.Color.blurple()
    )

    study_view = discord.ui.View(
        timeout=None
    )

    for role_key, role_name in ROLE_GROUPS[
        "study"
    ]["roles"].items():

        study_view.add_item(
            RoleButton(
                bot,
                "study",
                role_key,
                role_name
            )
        )

    study_message = await channel.send(
        embed=study_embed,
        view=study_view
    )

    bot.setup_data["messages"].append(
        str(study_message.id)
    )

    # --------------------------------------------------------
    # COURSE PANEL
    # --------------------------------------------------------

    course_embed = discord.Embed(
        title="📚 Course",
        description=(
            "Select the course area that best "
            "describes you.\n\n"
            "You can only have **one** course role."
        ),
        color=discord.Color.blurple()
    )

    course_view = discord.ui.View(
        timeout=None
    )

    for role_key, role_name in ROLE_GROUPS[
        "course"
    ]["roles"].items():

        course_view.add_item(
            RoleButton(
                bot,
                "course",
                role_key,
                role_name
            )
        )

    course_message = await channel.send(
        embed=course_embed,
        view=course_view
    )

    bot.setup_data["messages"].append(
        str(course_message.id)
    )

    # --------------------------------------------------------
    # ANNOUNCEMENT PANEL
    # --------------------------------------------------------

    announcement_embed = discord.Embed(
        title="📢 Get Announcements",
        description=(
            "Choose the types of announcements "
            "you'd like to receive.\n\n"
            "You can select **multiple** roles."
        ),
        color=discord.Color.blurple()
    )

    announcement_view = discord.ui.View(
        timeout=None
    )

    for role_key, role_name in ROLE_GROUPS[
        "announcements"
    ]["roles"].items():

        announcement_view.add_item(
            RoleButton(
                bot,
                "announcements",
                role_key,
                role_name
            )
        )

    announcement_message = await channel.send(
        embed=announcement_embed,
        view=announcement_view
    )

    bot.setup_data["messages"].append(
        str(announcement_message.id)
    )

    # Save completed setup
    bot.setup_data["setup_complete"] = True

    bot.save_setup_data()

    await interaction.followup.send(
        "✅ Role selection has been set up successfully!",
        ephemeral=True
    )


# ============================================================
# RESET ROLES
# ============================================================

@bot.tree.command(
    name="reset_roles",
    description="Reset the Kernel role-selection setup."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def reset_roles(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    channel = interaction.guild.get_channel(
        ROLES_CHANNEL_ID
    )

    deleted_count = 0

    # Delete old role-selection messages
    if channel:

        for message_id in bot.setup_data["messages"]:

            try:

                message = await channel.fetch_message(
                    int(message_id)
                )

                await message.delete()

                deleted_count += 1

            except discord.NotFound:

                pass

            except discord.HTTPException:

                pass

    # Reset saved setup state
    bot.setup_data = {
        "setup_complete": False,
        "roles": {},
        "messages": []
    }

    bot.save_setup_data()

    await interaction.followup.send(
        "✅ Role setup has been reset.\n\n"
        f"Deleted `{deleted_count}` old role panels.\n"
        "You can now run `/setup_roles` again.",
        ephemeral=True
    )


# ============================================================
# SETUP RULES
# ============================================================

@bot.tree.command(
    name="setup_rules",
    description="Post the UWES server rules."
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def setup_rules(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not RULES_CHANNEL_ID:

        await interaction.followup.send(
            "The rules channel hasn't been configured in `.env`.",
            ephemeral=True
        )

        return

    channel = interaction.guild.get_channel(
        RULES_CHANNEL_ID
    )

    if channel is None:

        await interaction.followup.send(
            "I couldn't find the configured rules channel.",
            ephemeral=True
        )

        return

    rules_message = (
        "# 📜 UWES Server Rules\n"
        "Welcome to the **University of Warwick Electronics Society!**\n\n"

        "## 1. Be welcoming\n"
        "- Help make UWES a friendly and approachable community for everyone.\n"
        "## 2. All experience levels are welcome\n"
        "- Whether you're new to electronics or an experienced engineer, everyone is welcome here.\n"
        "## 3. Respect everyone\n"
        "- No discrimination, bullying, harassment, or targeting of others.\n"
        "## 4. Use the appropriate channels\n"
        "- Keep discussions relevant to the channel you're using.\n"
        "## 5. Keep content appropriate\n"
        "- No NSFW, excessively offensive, or otherwise inappropriate content.\n"
        "## 6. Respect privacy and personal space\n"
        "- Don't share someone's personal information, messages, images, or other content without permission.\n"
        "## 7. Disagree respectfully\n"
        "- Technical disagreements are fine, but keep discussions constructive and avoid personal attacks.\n"
        "## 8. Take safety seriously\n"
        "- Be responsible when working with electronics, batteries, high voltages, tools, and other potentially hazardous equipment.\n"
        "## 9. Clean up after yourself\n"
        "- Leave society equipment and spaces clean, organised, and ready for the next person.\n"
        "## 10. No unsolicited advertising or selling\n"
        "- Don't advertise products, services, servers, events, or businesses without permission.\n"
        "## 11. No illegal or harmful content\n"
        "- Don't share content that facilitates illegal activity, serious harm, or malicious behaviour.\n\n"

        "## 🛠️ Need help?\n"
        "Contact **support@uwes.co.uk** or "f"<@&{EXEC_ROLE_ID}>.\n\n"

        "---\n"
        "*University of Warwick Electronics Society • UWES*"
    )

    await channel.send(rules_message)

    await interaction.followup.send(
        "✅ UWES rules have been posted successfully!",
        ephemeral=True
    )


@setup_rules.error
async def setup_rules_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        await interaction.response.send_message(
            "❌ You need Administrator permissions "
            "to use this command.",
            ephemeral=True
        )

    else:

        print(
            f"setup_rules error: {error}"
        )

        if interaction.response.is_done():

            await interaction.followup.send(
                "Something went wrong while posting "
                "the rules. Check the console.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "Something went wrong while posting "
                "the rules. Check the console.",
                ephemeral=True
            )
            
            
# ============================================================
# WELCOME MESSAGE
# ============================================================

@bot.event
async def on_member_join(member):

    if not WELCOME_CHANNEL_ID:
        return

    channel = member.guild.get_channel(
        WELCOME_CHANNEL_ID
    )

    if channel is None:
        return

    embed = discord.Embed(
        title="Welcome to UWES! 👋",
        description=(
            f"Welcome {member.mention}!\n\n"
            "We're the University of Warwick's "
            "Electronics Society.\n\n"
            "Check out the rules and grab your roles "
            "in the role-selection channel."
        ),
        color=discord.Color.blurple()
    )

    await channel.send(
        embed=embed
    )


# ============================================================
# ERROR HANDLING
# ============================================================

@setup_roles.error
async def setup_roles_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        await interaction.response.send_message(
            "❌ You need Administrator permissions "
            "to use this command.",
            ephemeral=True
        )

    else:

        print(
            f"setup_roles error: {error}"
        )

        if interaction.response.is_done():

            await interaction.followup.send(
                "Something went wrong while setting up "
                "the roles. Check the console.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "Something went wrong while setting up "
                "the roles. Check the console.",
                ephemeral=True
            )


@reset_roles.error
async def reset_roles_error(
    interaction: discord.Interaction,
    error
):

    if isinstance(
        error,
        app_commands.errors.MissingPermissions
    ):

        await interaction.response.send_message(
            "❌ You need Administrator permissions "
            "to use this command.",
            ephemeral=True
        )

    else:

        print(
            f"reset_roles error: {error}"
        )

        if interaction.response.is_done():

            await interaction.followup.send(
                "Something went wrong while resetting "
                "the roles. Check the console.",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "Something went wrong while resetting "
                "the roles. Check the console.",
                ephemeral=True
            )


# ============================================================
# START KERNEL
# ============================================================

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN was not found in your .env file."
    )


bot.run(TOKEN)