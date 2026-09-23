from collections.abc import Callable
from types import CoroutineType
from typing import Any, NamedTuple, final
from datetime import datetime
from os import path

import logging
import telegram as tg
import telegram.ext as ext
import telegram.constants as tgc

from module.consts import *
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

			if "silent!" in args or "s!" in args:
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
	"offset": "int?"
})
HELP_CMD: _Cmd = ("help", "Помощь по командам", None)
SUBJECTS_CMD: _Cmd = ("subjects", "Информация о предметах", None)
NEXT_CMD: _Cmd = ("next", "Следующая пара по предмету", {
	"subject": "tag | subject_id"
})
S_CMD: _Cmd = ("s", "Получить информацию о предмете", {
	"subject": "tag | subject_id"
})
RELOAD_CMD: _Cmd = ("reload", "Обновить конфигурацию бота. Не вводить без надобности", None)

# PUBLISH_CMD: _Cmd = ("publish", "Публикует сообщение по предмету", {
# 	"subject": "tag"
# })

GLOBAL_CMDS: _Cmd_Group = (
	to_command(HELP_CMD, True),
	to_command(NEXT_CMD, True),
	to_command(SUBJECTS_CMD, True),
	to_command(TODAY_CMD, True),
	to_command(TOMORROW_CMD, True),
	to_command(NOW_CMD, True),
	to_command(SCHEDULE_CMD, True),
	to_command(S_CMD, True),
	to_command(RELOAD_CMD, True),
)
PRIVATE_CMDS: _Cmd_Group = (
	to_command(HELP_CMD),
	to_command(NEXT_CMD),
	to_command(SUBJECTS_CMD),
	to_command(TODAY_CMD),
	to_command(TOMORROW_CMD),
	to_command(NOW_CMD),
	to_command(SCHEDULE_CMD),
	to_command(S_CMD),
	to_command(RELOAD_CMD),
)
DEFAULT_CMDS: _Cmd_Group = GLOBAL_CMDS

GROUP_COMMAND_SET = to_command_set(
	HELP_CMD,
	SUBJECTS_CMD,
	TODAY_CMD,
	TOMORROW_CMD,
	NOW_CMD,
	SCHEDULE_CMD,
	NEXT_CMD,
	S_CMD,
	RELOAD_CMD
)
PRIVATE_COMMAND_SET = to_command_set(
	HELP_CMD,
	SUBJECTS_CMD,
	TODAY_CMD,
	TOMORROW_CMD,
	NOW_CMD,
	SCHEDULE_CMD,
	NEXT_CMD,
	S_CMD,
	RELOAD_CMD
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

def reload_main_schedule():
	sc.reload_schedule(MAIN_SCHEDULE, path.join(CONFIG_DIR, SCHEDULE_FILE), LOG)

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
async def subjects_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	s = MAIN_SCHEDULE
	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), (
		pret.subjects_msg(s)
	))

def _decode_subject_arg(args: list[str] | None, s: sc.Schedule) -> sc.Subject | str:
	tag_or_id = _extract_arg(args, str, 0, None)
	if tag_or_id is None:
		LOG.warning("No subject argument provided")
		return pret.no_req_arg_err("subject")
	
	subject = s.get_subject_by_str(tag_or_id)

	if subject is None:
		LOG.warning(f"Unknown subject {pret.escape_unformatted(f"{tag_or_id!r}")} in schedule {s.name!r}")
		return pret.unknown_subject_err(tag_or_id)
	
	return subject

async def s_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	s = MAIN_SCHEDULE
	subject = _decode_subject_arg(ctx.args, s)

	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), 
		subject if isinstance(subject, str) else pret.s_msg(subject)
	)
async def next_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	s = MAIN_SCHEDULE
	a_co = await _handle_cmd_generic_args(msg, user, u, ctx)
	
	subject = _decode_subject_arg(ctx.args, s)
	await _send_message(msg, *a_co, subject if isinstance(subject, str) else (
		pret.next_msg(s, s.current_lesson_index, subject)
	))

async def reload_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)
	
	reload_main_schedule()
	await _send_message(
		msg, *await _handle_cmd_generic_args(msg, user, u, ctx), pret.reload_msg()
	)
async def help_cmd_h(u: tg.Update, ctx: ext.ContextTypes.DEFAULT_TYPE):
	msg, user = _deconstruct_update(u)

	is_group = chat_type_is_group(msg.chat.type)
	cs = GROUP_COMMAND_SET if is_group else PRIVATE_COMMAND_SET

	await _send_message(msg, *await _handle_cmd_generic_args(msg, user, u, ctx), (
		pret.help_msg(cs, is_group)
	))
