import re

from datetime import date, datetime, time
from module.schedule import (
	Lesson, LessonIndex, Schedule, ScheduleDayIndex, Subject,
	LessonNote, ScheduleDayNote,
	LessonKind, SubjectExamKind
)

# ==============================
#  Simple text builders
# ==============================

def escape_unformatted(v: str) -> str:
	return re.sub(r"([_\*\[(~`)\]>#+=\-|{}.!\\])", r"\\\1", v)
def str_date(v: date | None = None) -> str:
	return f"{v or date.today():%d.%m.%Y}".replace(".", "\\.")
def str_time_span(span: tuple[time | datetime, time | datetime]) -> str:
	return f"{span[0]:%H:%M} \\- {span[1]:%H:%M}"
def str_lesson_time(lesson_index: int, schedule: Schedule) -> str:
	return str_time_span(schedule.get_lesson_bounds(lesson_index))
def str_chat_link(label: str, link: str) -> str:
	return f"\\([{label}]({link})\\)"

def weekday_name(index: int) -> str:
	match index:
		case 0: return "понедельник"
		case 1: return "вторник"
		case 2: return "среда"
		case 3: return "четверг"
		case 4: return "пятница"
		case 5: return "суббота"
		case 6: return "воскресенье"
		case _: pass
	return "?"
def exam_kind_name(kind: SubjectExamKind) -> str:
	match kind:
		case SubjectExamKind.SIMPLE: return 'зачёт'
		case SubjectExamKind.DIFF: return 'диф-зачёт'
		case SubjectExamKind.FULL: return 'экзамен'
		case SubjectExamKind.UNKNOWN: return 'неизвестно'

	return '\\#\\#\\#' # pyright: ignore[reportUnreachable]
def lesson_kind_name(lesson: LessonNote) -> str:
	if lesson is None:
		return "окно"

	match lesson.kind:
		case LessonKind.LECTURE: return 'лекция'
		case LessonKind.PRACTICE: return 'практика'
		case LessonKind.CONSULTATION: return 'консультация'
		case _: pass
	
	return exam_kind_name(lesson.subject.exam_kind)
	
def lesson_kind_dec(k: LessonKind) -> str | None:
	match k:
		case LessonKind.LECTURE: return '🔹'
		case LessonKind.PRACTICE: return '🔸'
		case LessonKind.CONSULTATION: return '🌀'
		case _: return None
def exam_kind_dec(k: SubjectExamKind) -> str | None:
	match k:
		case SubjectExamKind.SIMPLE: return '💠'
		case SubjectExamKind.DIFF: return '⚠️'
		case SubjectExamKind.FULL: return '🛑'
		case SubjectExamKind.UNKNOWN: return '❔'
	
	return None # pyright: ignore[reportUnreachable]
def lesson_dec(lesson: LessonNote) -> str:
	if lesson is None:
		return '🪟'
	return f'{lesson_kind_dec(lesson.kind) or exam_kind_dec(lesson.subject.exam_kind) or "\\#"}'

LAST_LESSON_MARKER = "*ПОСЛЕДНЯЯ*"

CURRENT_LESSON_PREFIX = "*СЕЙЧАС:*"
NEXT_LESSON_PREFIX = "*СЛЕДУЮЩАЯ:*"
AFTER_LESSON_PREFIX = "*ПОСЛЕ:*"

# ==============================
#  Text elements builders
# ==============================

def lesson_number_marker(lesson_index: int, schedule: Schedule) -> str:
	return f"{lesson_index + 1} пара \\[*{str_lesson_time(lesson_index, schedule)}*\\]"
def lesson_note_marker(lesson: LessonNote) -> str:
	return f"{lesson_dec(lesson)} *{lesson_kind_name(lesson).upper()}*"
def weekday_marker(v: date) -> str:
	return f"{str_date(v)} \\[*{weekday_name(v.weekday())}*\\]"
def day_marker(day_index: ScheduleDayIndex, schedule: Schedule) -> str:
	date = schedule.to_date(day_index)
	return f"{str_date(date)} \\[*{day_index.week + 1} неделя*\\]"
def str_or_unknown(v: str | None) -> str:
	return "*НЕИЗВЕСТНО*" if v is None else escape_unformatted(v)

def lesson_link(lesson: Lesson) -> str | None:
	chat = lesson.specified_chat
	return None if chat is None else str_chat_link("тут", chat)

def scheduled_lesson_base(lesson: LessonNote, i: int, schedule: Schedule) -> str:
	return f"{lesson_number_marker(i, schedule)} // {lesson_note_marker(lesson)}"
def scheduled_lesson(lesson: LessonNote, i: int, schedule: Schedule) -> str:
	return (scheduled_lesson_base(lesson, i, schedule) +
		("" if lesson is None else f" \\[*{escape_unformatted(lesson.subject.name)}*\\]"))
def scheduled_lesson_with_link(lesson: LessonNote, i: int, schedule: Schedule) -> str:
	text = scheduled_lesson(lesson, i, schedule)
	link = None if lesson is None else lesson_link(lesson)
	return text if link is None else text + ' ' + link

type CommandArgs = dict[str, str | None] | None
type CommandInfo = tuple[str, CommandArgs]
type CommandSet = dict[str, CommandInfo]

def command_with_args(cmd: str, args: CommandArgs) -> str:
	text = f"/{cmd}"
	if args is not None:
		for k, v in args.items():
			text += (f" <`{escape_unformatted(k)}`"
				f"{'' if v is None else f': {escape_unformatted(v)}'}\\>")

	return text
def command_flags(formatted_description: str, /, *names: str) -> str:
	return f"{' или '.join(f'`{escape_unformatted(v)}`' for v in names)} – {formatted_description}"

# ==============================
#  Text blocks builders
# ==============================

def day_is_not_started_yet_note() -> str:
	return "⚠️ Учебный день ещё не начался"
def unspecified_chats_for_lessons_note(main_chat: str) -> str:
	return (f"❗️ Пары, для которых не указанна ссылка, проходят в основной группе "
		f"{str_chat_link('тут', main_chat)}")
def command_info(cmd: str, description: str, args: CommandArgs) -> str:
	return f"{command_with_args(cmd, args)} – {escape_unformatted(description)}"
def day_lessons_list(day: ScheduleDayNote, schedule: Schedule) -> str:
	if day is None or len(day.lessons) <= 0:
		return "*Пар нет*"
	return "\n".join(scheduled_lesson_with_link(
		v, i, schedule
	) for i, v in enumerate(day.lessons))

def subject_info(subject: Subject, id: str) -> str:
	ek = subject.exam_kind
	return (f"*{escape_unformatted(subject.name)}* "
		f"\\[\\#{escape_unformatted(subject.tag)} // `{escape_unformatted(id)}`\\]:\n"
		f"Форма экзамена: {exam_kind_dec(ek)} *{exam_kind_name(ek).upper()}*\n"
		f"Требования к сдачи: {str_or_unknown(subject.exam_requirements)}\n"
		f"Форма сдачи: {str_or_unknown(subject.exam_form)}")

# ==============================
#  Message builders
# ==============================

def day_schedule_msg(schedule: Schedule, day_index: ScheduleDayIndex):
	day, day_date = schedule.get_day(day_index), day_marker(day_index, schedule)
	text = f"📌 Расписание пар на {day_date}\n\n{day_lessons_list(day, schedule)}"
	if day is not None and len(day.lessons) > 0 and not day.all_chat_specified:
		text += f"\n\n{unspecified_chats_for_lessons_note(schedule.main_chat)}"

	return text
def week_schedule_msg(schedule: Schedule, index: int) -> str:
	week_obj = schedule.get_week(index)
	text = f"📌 Расписание пар на *{index + 1} неделю*\n\n"
	if week_obj is None:
		return text + f"⚠️ Неделя отсутствует в расписании"

	all_has_chat = True
	year, week = schedule.to_iso_year_and_week(index)
	for i, day in enumerate(week_obj.week):
		text += '\n\n' if i != 0 else ''
		text += (f"◾️ {weekday_marker(date.fromisocalendar(year, week, i + 1))}\n"
			f"{day_lessons_list(day, schedule)}")

		if day is not None:
			all_has_chat &= day.all_chat_specified
	
	if not all_has_chat:
		text += f"\n\n{unspecified_chats_for_lessons_note(schedule.main_chat)}"

	return text
def now_msg(schedule: Schedule, li: LessonIndex, is_right_now: bool) -> str:
	day = schedule.get_day(li.day_index)
	if day is None or day.bounds is None:
		return "Сегодня пар нет"

	ls = None
	if li.lesson_index is not None:
		ls = day.fetch_lesson(li.lesson_index)

	if ls is None:
		return "Пары закончились"

	ls_irn = is_right_now and li.lesson_index == ls[1]
	text = f"{CURRENT_LESSON_PREFIX if ls_irn else NEXT_LESSON_PREFIX} "
	text += scheduled_lesson_with_link(ls[0], ls[1], schedule)

	next_ls = day.fetch_lesson(ls[1] + 1)
	if next_ls is not None:
		text += f"\n{NEXT_LESSON_PREFIX if ls_irn else AFTER_LESSON_PREFIX} "
		text += scheduled_lesson_with_link(next_ls[0], next_ls[1], schedule)
		
	if next_ls is None or next_ls[1] >= day.bounds[1]:
		text += f" {LAST_LESSON_MARKER}"

	return text
def next_msg(schedule: Schedule, index: LessonIndex, subject: Subject) -> str:
	lp = schedule.search_lesson(index, type=subject)
	text = f"📙 {escape_unformatted(subject.name)}\n\n*ПАРА*: "

	if lp is None:
		text += "⚠️ Отсутствует в расписании"
	else:
		assert lp[0].lesson_index is not None
		text += (f"{scheduled_lesson_base(lp[1], lp[0].lesson_index, schedule)}\n"
			f"*ДАТА*: {day_marker(lp[0].day_index, schedule)}")

	return text

PROJECT_REPO = "https://github.com/SooperADS/unv-group-tg-automation-bot.git"
PROJECT_HOST = "GitHub"

def subjects_msg(schedule: Schedule) -> str:
	infix = '' if schedule.name is None else f"*{escape_unformatted(schedule.name)}* // "
	text = f"📚 {infix}Предметы:"

	for id, subject in schedule.get_subjects():
		text += f"\n\n📗 {subject_info(subject, id)}"

	return text
def help_msg(commands: CommandSet, in_group: bool) -> str:
	text = "🧰 Помощь по командам бота:\n\n" + '\n'.join(command_info(
		c, escape_unformatted(info[0]), info[1]
	) for c, info in commands.items())

	if len(commands) > 0 and in_group:
		text += "\n\n⚙️ Допустимо использовать флаги для настройки поведения некоторых команд:\n\n"

		text += "\n".join((
			command_flags(
				"Ответ публичный, сообщение с командой от пользователя удаляется ботом", "post", '!'
			), 
			command_flags("Ответ отправляется без звука", "silent", 's'),
			command_flags("То же, что и `silent !`", "silent!", "s!")
		))

		text += ("\n\n❗️ Эти флаги работают только в групповых чатах\\."
			" Флаги должны указываться после всех аргументов команды и разделятся пробелами")

	return text + f"\n\n💿 Мой исходный код доступен на [{PROJECT_HOST}]({PROJECT_REPO})"

def error_msg(text: str) -> str:
	return "⚠️ *ОШИБКА*: " + text
def reload_msg() -> str:
	return "✅ Расписание обновлено"
