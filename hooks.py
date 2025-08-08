import os
import hikari
import lightbulb
from lightbulb.prefab import NotOwner

owner_id = int(os.getenv("OWNER_ID"))  # Replace with your actual owner ID

def get_admin_roles() -> list[int]:
    """
    Retrieve a list of admin role IDs from the environment variable.

    Returns:
        list[int]: A list of admin role IDs.
    """
    roles = os.getenv("ADMIN_ROLES")
    if roles:
        return [int(role_id.strip()) for role_id in roles.split(",") if role_id.strip().isdigit()]
    return []

admin_roles = get_admin_roles()

@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
async def fail_if_not_admin_or_owner(_: lightbulb.ExecutionPipeline, ctx: lightbulb.Context) -> None:
    if ctx.user.id != owner_id and not any(role_id in admin_roles for role_id in ctx.member.role_ids):
        await ctx.respond("You do not have permission to use this command.", ephemeral=True)
        raise NotOwner("You must be an admin or the bot owner to use this command.")