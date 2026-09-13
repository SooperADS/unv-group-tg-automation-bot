from collections.abc import Callable
from types import CoroutineType
from typing import Any, NamedTuple, final
from datetime import datetime

import logging
import telegram as tg
import telegram.ext as ext
import telegram.constants as tgc

import module.prettifier as pret
import module.schedule as sc

# ==============================
#  Helpers
# ==============================

type _Cmd = tuple[str, str, pret.CommandArgs]
type _Cmd_Group = tuple[tg.BotCommand, ...]
type _Cmd_Handler = ext.CommandHandler[ext.ContextTypes.DEFAULT_TYPE, Any]
type _Cmd_Callback = Callable[
	[tg.Update, ext.ContextTypes.DEFAULT_TYPE], CoroutineType[Any, Any, Any]
]

CMD_SCOPE_GROUPS = tg.BotCommandScopeAllGroupChats()
CMD_SCOPE_ADMINS = tg.BotCommandScopeAllChatAdministrators()
CMD_SCOPE_PRIVATE = tg.BotCommandScopeAllPrivateChats()
EPHEMERAL_CMD_KWARGS = { "is_ephemeral": True }

def make_handler(callback: _Cmd_Callback, *cmds: _Cmd, **args: Any) -> _Cmd_Handler:
	return ext.CommandHandler(tuple(v[0] for v in cmds), callback, **args)
def to_command(v: _Cmd, is_ephemeral: bool = False) -> tg.BotCommand:
	return tg.BotCommand(
		v[0], v[1], api_kwargs=EPHEMERAL_CMD_KWARGS if is_ephemeral else None
	)

def to_command_set(*commands: _Cmd) -> pret.CommandSet:
	return dict((v[0], (v[1], v[2])) for v in commands)

@final
class InGroupCommandFlags(NamedTuple):
	post: bool
	silent: bool

	@staticmethod
	def extract(args: list[str] | None) -> InGroupCommandFlags:
		post, s = False, False
		if args is not None:
			post = "post" in args or "!" in args
			s = 's' in args or "silent" in args

			if "post!" in args:
				post, s = True, True
		
		return InGroupCommandFlags(post, s)

def chat_type_is_group(type: str | tgc.ChatType) -> bool:
	return (type == tgc.ChatType.GROUP
		or  type == tgc.ChatType.SUPERGROUP
		or  type == tgc.ChatType.CHANNEL)

# ==============================
#  Commands
# ==============================

TODAY_CMD: _Cmd = ("today", "Текущие расписание на сегодня", None)
TOMORROW_CMD: _Cmd = ("tomorrow", "Текущие расписание на завтра", None)
NOW_CMD: _Cmd = ("now", "Текущая/следующая пара", None)
SCHEDULE_CMD: _Cmd = ("schedule", "Публикует текущее расписание", {
	"offset": "int"
})
HELP_CMD: _Cmd = ("help", "Помощь по командам", None)

GLOBAL_CMDS: _Cmd_Group = (
	to_command(TODAY_CMD, True),
	to_command(TOMORROW_CMD, True),
	to_command(NOW_CMD, True),
	to_command(SCHEDULE_CMD, True),
	to_command(HELP_CMD, True)
)
PRIVATE_CMDS: _Cmd_Group = (
	to_command(TODAY_CMD),
	to_command(TOMORROW_CMD),
	to_command(NOW_CMD),
	to_command(SCHEDULE_CMD),
	to_command(HELP_CMD),
)
DEFAULT_CMDS: _Cmd_Group = GLOBAL_CMDS

GROUP_COMMAND_SET = to_command_set(
	HELP_CMD,
	TODAY_CMD,
	TOMORROW_CMD,
	NOW_CMD,
	SCHEDULE_CMD
)
PRIVATE_COMMAND_SET = to_command_set(
	HELP_CMD,
	TODAY_CMD,
	TOMORROW_CMD,
	NOW_CMD,
	SCHEDULE_CMD
)

async def registry_commands(bot: tg.Bot) -> bool:
	return (await bot.set_my_commands(GLOBAL_CMDS, CMD_SCOPE_GROUPS)
		and await bot.set_my_commands(GLOBAL_CMDS, CMD_SCOPE_ADMINS)
		and await bot.set_my_commands(PRIVATE_CMDS, CMD_SCOPE_PRIVATE)
		and await bot.set_my_commands(DEFAULT_CMDS))
async def remove_commands(bot: tg.Bot) -> bool:
	return (await bot.delete_my_commands(CMD_SCOPE_GROUPS)
		and await bot.delete_my_commands(CMD_SCOPE_ADMINS)
		and await bot.delete_my_commands(CMD_SCOPE_PRIVATE)
		and await bot.delete_my_commands())

# ==============================
#  Handlers
# ==============================

MAIN_SCHEDULE = sc.Schedule(None)
LOG = logging.getLogger("bot.requests")

def _ephemeral_reply(ephemeral_message_id: int) -> tg.ReplyParameters:
	return tg.ReplyParameters(
		None, # pyright: ignore[reportArgumentType]
		api_kwargs={ "ephemeral_message_id": ephemeral_message_id }
	)	
def _ephemeral_api_kwargs(user_id: int) -> dict[str, Any]:
	return { "ephemeral_message_parameters": {"receiver_user_id": user_id} }
def _deconstruct_update(u: tg.Update) -> tuple[tg.Message, tg.User]:
	msg, user = u.effective_message, u.effective_user
	assert msg is not None and user is not None
	LOG.info(f"{msg.text!r} request by {user} in {msg.chat}")
	return msg, user
def _extract_arg[T](args: list[str] | None, fx: Callable[[str], T], index: int, default: T) -> T:
	if args is not None and len(args) > index:
		try:
			return fx(args[index])
		except ValueError:
			pass

	return default

type _Cmd_Reply = tg.ReplyParameters | None
type _Cmd_KWArgs = dict[str, Any] | None

async def _handle_cmd_generic_args(
	msg: tg.Message, user: tg.User, u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE
) -> tuple[_Cmd_KWArgs, _Cmd_Reply, bool]:
	kwargs, reply, silent = None, None, False

	ephemeral_message_id: int | None = msg.api_kwargs.get("ephemeral_message_id")
	if chat_type_is_group(msg.chat.type):
		flags = InGroupCommandFlags.extract(ctx.args)
		if flags.post:
			if ephemeral_message_id is None:
				ctx.application.create_task(msg.delete(), u)
		elif ephemeral_message_id is None:
			reply = tg.ReplyParameters(msg.id, msg.chat.id)
		else:
			reply = _ephemeral_reply(ephemeral_message_id)
			kwargs = _ephemeral_api_kwargs(user.id)

		silent = flags.silent

	return kwargs, reply, silent
async def _send_message(
	msg: tg.Message, kwargs: _Cmd_KWArgs, reply: _Cmd_Reply, silent: bool, text: str
):
	await msg.chat.send_message(
		message_thread_id=msg.message_thread_id,
		disable_notification=silent,
		text=text,
		parse_mode=tgc.ParseMode.MARKDOWN_V2,
		reply_parameters=reply,
		api_kwargs=kwargs
	)

async def on_start(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	LOG.info(f"Started by user: {u.effective_user}")

	chat = u.effective_chat
	assert chat is not None
	if not chat_type_is_group(chat.type):
		await ctx.bot.send_message(chat_id=chat.id, text="I'm useless, you know?")

async def today_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	s = MAIN_SCHEDULE
	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), (
		pret.day_schedule_msg(s, s.current_day_index)
	))
async def tomorrow_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	s = MAIN_SCHEDULE
	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), (
		pret.day_schedule_msg(s, s.current_day_index.add_days(1))
	))
async def now_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	s = MAIN_SCHEDULE
	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), (
		pret.now_msg(s, *s.to_lesson_index(datetime.now()))
	))
async def schedule_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	s = MAIN_SCHEDULE
	offset = _extract_arg(ctx.args, int, 0, 0)
	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), (
		pret.week_schedule_msg(s, s.current_week_index + offset)
	))

async def help_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	is_group = chat_type_is_group(msg.chat.type)
	cs = GROUP_COMMAND_SET if is_group else PRIVATE_COMMAND_SET

	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), (
		pret.help_msg(cs, is_group)
	))
