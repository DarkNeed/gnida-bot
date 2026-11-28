"""Owner-only private runtime commands."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from custom_commands import CUSTOM_COMMAND_OWNER_ID


def create_runtime_diagnostics_router(memory):
    router = Router(name="runtime_diagnostics")

    @router.message(F.chat.type == "private", F.from_user.id == CUSTOM_COMMAND_OWNER_ID,
                    Command("память", "memory", ignore_case=True))
    async def memory_command(message: Message):
        await message.answer(memory.telegram_summary(), parse_mode=None)

    return router
