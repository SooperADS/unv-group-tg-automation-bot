import io, logging

from datetime import date, datetime, timedelta
from os import path
from types import CoroutineType
from typing import Any, Callable

import telegram as tg
import telegram.ext as ext
import telegram.constants as tgc

import module.schedule as schedule
import module.prettifier as pret
from module.consts import *

### Setup ###

TOKEN: str = None # pyright: ignore[reportAssignmentType]
with io.open(TOKEN_FILE, "r") as file:
	TOKEN = file.readline() # pyright: ignore[reportConstantRedefinition]
if type(TOKEN) is not str:
	raise Exception("No Telegram bot token provided")

logging.basicConfig(
	level=logging.INFO,
	format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
	handlers=(
		logging.StreamHandler(),
		logging.FileHandler(path.join(LOGS_DIR, "latest.log"), "w"),
		logging.FileHandler(path.join(LOGS_DIR, f"{datetime.now():%Y.%m.%d %H:%M}.log"), "w")
	)
)

### Logging setup ###

LOG = logging.getLogger("bot")
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.WARN)
logging.getLogger("apscheduler").setLevel(logging.WARN)

RQ_LOG = LOG.getChild("requests")
# RQ_LOG.setLevel(logging.DEBUG)

### Loading configuration data ###

MAIN_SCHEDULE = schedule.from_file(	path.join(CONFIG_DIR, SCHEDULE_FILE), RQ_LOG)

### Handlers ###

type _Command_Callback = Callable[
	[tg.Update, ext.ContextTypes.DEFAULT_TYPE], CoroutineType[Any, Any, Any]
]

def schedule_message_command(
	message_source: Callable[[schedule.Schedule], str]
) -> _Command_Callback:
	async def _callback(update: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
		kwargs, reply, silent = None, None, False

		msg, user = update.effective_message, update.effective_user
		if msg is not None and user is not None:
			RQ_LOG.info(f"{msg.text!r} request by {user.id} in {update.effective_chat.id}")
			ephemeral_message_id: int | None = msg.api_kwargs.get("ephemeral_message_id")
			if ephemeral_message_id is not None:
				kwargs = {
					"ephemeral_message_parameters": {"receiver_user_id": user.id}
				}
				reply = tg.ReplyParameters(
					None, # pyright: ignore[reportArgumentType]
					api_kwargs={ "ephemeral_message_id": ephemeral_message_id }
				)
			else: 
				reply = reply= tg.ReplyParameters(msg.id)
				if ctx.args:
					if "s" in ctx.args:
						silent=True

					if "!" in ctx.args or "del" in ctx.args:
						reply = None
						await ctx.bot.delete_message(msg.chat_id, msg.id)
					elif "#" in ctx.args or "nr" in ctx.args:
						reply = None
		elif user is not None:
			RQ_LOG.warning(f"Message function triggered without message by {user.id}")

		await ctx.bot.send_message(
			chat_id=update.effective_chat.id,
			message_thread_id=msg.message_thread_id,
			disable_notification=silent,
			text=message_source(MAIN_SCHEDULE),
			parse_mode=tgc.ParseMode.MARKDOWN_V2,
			reply_parameters=reply,
			api_kwargs=kwargs
		)

	return _callback

async def _on_start(update: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	RQ_LOG.info(f"Started by user: {update.effective_user}")

	chat_type = update.effective_chat.type
	if chat_type == tgc.ChatType.PRIVATE or chat_type == tgc.ChatType.GROUP:
		await ctx.bot.send_message(
			chat_id=update.effective_chat.id, text="I do absolutely nothing"
		)

_ephemeral_cmd_kwargs = { "is_ephemeral": True }
bot_commands = (
	tg.BotCommand("today", "Текущие расписание на сегодня"),
	tg.BotCommand("etoday", "(НЕ ПУБЛИЧНО) /today", api_kwargs=_ephemeral_cmd_kwargs),
	tg.BotCommand("tomorrow", "Текущие расписание на завтра"),
	tg.BotCommand("etomorrow", "(НЕ ПУБЛИЧНО) /tomorrow", api_kwargs=_ephemeral_cmd_kwargs),
	tg.BotCommand("now", "Информация о текущей/следующей паре"),
	tg.BotCommand("enow", "(НЕ ПУБЛИЧНО) /now", api_kwargs=_ephemeral_cmd_kwargs),
	tg.BotCommand("schedule", "Публикует текущее расписание"),
)

### MAIN ####

if __name__ == '__main__':
	app = ext.ApplicationBuilder().token(TOKEN).build()
	app_queue = app.job_queue

	_on_today_cmd = schedule_message_command(
		lambda s: pret.day_schedule_msg(s, date.today())
	)
	_on_tomorrow_cmd = schedule_message_command(
		lambda s: pret.day_schedule_msg(s, datetime.now() + timedelta(1))
	)
	_on_now_cmd = schedule_message_command(
		lambda s: pret.now_msg(s, datetime.now())
	)

	app.add_handlers((
		ext.CommandHandler("start", _on_start),
		ext.CommandHandler(bot_commands[0].command, _on_today_cmd),
		ext.CommandHandler(bot_commands[1].command, _on_today_cmd),
		ext.CommandHandler(bot_commands[2].command, _on_tomorrow_cmd),
		ext.CommandHandler(bot_commands[3].command, _on_tomorrow_cmd),
		ext.CommandHandler(bot_commands[4].command, _on_now_cmd),
		ext.CommandHandler(bot_commands[5].command, _on_now_cmd),
		ext.CommandHandler(bot_commands[6].command, schedule_message_command(
			lambda s: pret.week_schedule_msg(s, s.current_week_index)
		)),
	))

	async def _app_post_init(_):
		success = await app.bot.set_my_commands(
			bot_commands, tg.BotCommandScopeAllGroupChats(),
		)
		success &= await app.bot.set_my_commands(
			bot_commands, tg.BotCommandScopeAllChatAdministrators(),
		)
		success &= await app.bot.set_my_commands(
			(bot_commands[0], bot_commands[2], bot_commands[4], bot_commands[6]), tg.BotCommandScopeAllPrivateChats()
		)
		
		success &= await app.bot.set_my_commands(bot_commands)

		LOG.info(f"Bot commands setup success: {success}")
		if not success:
			LOG.error("Bot command initialization failed")
			await app.shutdown()
			return

		LOG.info(f"Bot commands: {await app.bot.get_my_commands()}")

	async def _app_post_stop(_):
		await app.bot.delete_my_commands(tg.BotCommandScopeAllPrivateChats())
		await app.bot.delete_my_commands(tg.BotCommandScopeAllGroupChats())
		await app.bot.delete_my_commands(tg.BotCommandScopeAllChatAdministrators())
		await app.bot.delete_my_commands()

		LOG.info("Bot stopped")

	app.post_init = _app_post_init
	app.post_stop = _app_post_stop
	app.run_polling()
