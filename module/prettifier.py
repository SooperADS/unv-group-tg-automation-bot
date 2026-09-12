import re

from datetime import date, datetime, time
from module.schedule import (
	Lesson, LessonIndex, Schedule, ScheduleDayIndex,
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
def lesson_kind_name(lesson: LessonNote) -> str:
	if lesson is None:
		return "окно"

	match lesson.kind:
		case LessonKind.LECTURE: return 'лекция'
		case LessonKind.PRACTICE: return 'практика'
		case LessonKind.CONSULTATION: return 'консультация'
		case _: pass
	
	match lesson.subject.exam:
		case SubjectExamKind.SIMPLE: return 'зачёт'
		case SubjectExamKind.DIFF: return 'диф-зачёт'
		case SubjectExamKind.FULL: return 'экзамен'
		case SubjectExamKind.UNKNOWN: return 'неизвестно'
	
	return '\\#\\#\\#' # pyright: ignore[reportUnreachable]
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
	return f'{lesson_kind_dec(lesson.kind) or exam_kind_dec(lesson.subject.exam) or "\\#"}'

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

def lesson_link(lesson: Lesson) -> str | None:
	chat = lesson.specified_chat
	return None if chat is None else str_chat_link("тут", chat)

def scheduled_lesson(lesson: LessonNote, i: int, schedule: Schedule) -> str:
	return (f"{lesson_number_marker(i, schedule)} // {lesson_note_marker(lesson)}" +
		("" if lesson is None else f" \\[*{escape_unformatted(lesson.subject.name)}*\\]"))
def scheduled_lesson_with_link(lesson: LessonNote, i: int, schedule: Schedule) -> str:
	text = scheduled_lesson(lesson, i, schedule)
	link = None if lesson is None else lesson_link(lesson)
	return text if link is None else text + ' ' + link

# ==============================
#  Text blocks builders
# ==============================

def day_is_not_started_yet_note() -> str:
	return "⚠️ Учебный день ещё не начался"
def unspecified_chats_for_lessons_note(main_chat: str) -> str:
	return (f"❗️ Пары, для которых не указанна ссылка, проходят в основной группе "
		f"{str_chat_link('тут', main_chat)}")
def day_lessons_list(day: ScheduleDayNote, schedule: Schedule) -> str:
	if day is None or len(day.lessons) <= 0:
		return "*Пар нет*"
	return "\n".join(scheduled_lesson_with_link(
		v, i, schedule
	) for i, v in enumerate(day.lessons))

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

	assert li.lesson_index is not None #NOTE: That's assert can't fail
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
