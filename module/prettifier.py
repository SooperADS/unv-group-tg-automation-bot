from collections.abc import Iterable
from datetime import date, datetime, timedelta
from module.schedule import Lesson, LessonKind, Schedule, SubjectExamKind, day_bounds

def str_date(date: date | None = None) -> str:
	return f"{date or datetime.now():%d.%m.%Y}".replace(".", "\\.")

def str_lesson_time(schedule: Schedule, index: int) -> str:
	s = schedule.get_lesson_time(index)
	e = datetime.combine(datetime.today(), s) + schedule.lessons_duration

	return f"{s:%H:%M} \\- {e:%H:%M}"

def weekday_name(iso_day: int) -> str:
	match iso_day:
		case 1: return "понедельник"
		case 2: return "вторник"
		case 3: return "среда"
		case 4: return "четверг"
		case 5: return "пятница"
		case 6: return "суббота"
		case 7: return "воскресенье"
		case _: pass
	return "?"

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

def lesson_dec(lesson: Lesson) -> str:
	return f'{lesson_kind_dec(lesson.kind) or exam_kind_dec(lesson.subject.exam) or "\\#"}'

def lesson_kind_name(lesson: Lesson) -> str:
	match lesson.kind:
		case LessonKind.LECTURE: return 'лекция'
		case LessonKind.PRACTICE: return 'практика'
		case LessonKind.CONSULTATION: return 'консультация'
		case _: pass
	
	match lesson.subject.exam:
		case SubjectExamKind.SIMPLE: return 'зачёт'
		case SubjectExamKind.DIFF: return 'дифф-зачёт'
		case SubjectExamKind.FULL: return 'экзамен'
		case SubjectExamKind.UNKNOWN: return 'неизвестно'
	
	return '\\#\\#\\#' # pyright: ignore[reportUnreachable]

def _str_lesson_time(i: int, schedule: Schedule) -> str:
	return f"{i + 1} пара \\[*{str_lesson_time(schedule, i)}*\\]"

def str_lesson_in_place(lesson: Lesson, i: int, schedule: Schedule) -> str:
	return (
		f"{_str_lesson_time(i, schedule)} // {lesson_dec(lesson)} "
		f"*{lesson_kind_name(lesson).upper()}* \\[{lesson.subject.name.replace("-", "\\-")}\\]"
	)

def str_lessons_list(
	lessons: Iterable[Lesson | None], schedule: Schedule, *, str_none: bool = False
) -> tuple[str, bool]:
	all_has_chat, lines = True, []
	for i, l in enumerate(lessons):
		if l is not None:
			chat = l.subject.get_chat(l.kind)

			line = str_lesson_in_place(l, i, schedule)
			if chat is not None and chat != schedule.main_chat:
				line += f" [тут]({chat})"
			else:
				all_has_chat = False
			
			lines.append(line)
		elif str_none:
			lines.append(f"{_str_lesson_time(i, schedule)} // 🪟 *ОКНО*")
	return "\n".join(lines), all_has_chat

def day_schedule(schedule: Schedule, date: date | None = None, *, str_none: bool = True) -> str:
	if date is None:
		day, week = schedule.current_day, schedule.current_week_index
	else:
		index = schedule.get_day_index(date)
		week = index.week
		day = schedule.get_day(index)

	if day is not None and len(day) >= 1 and day.count(None) != len(day):
		text, all_has_chat = str_lessons_list(day, schedule, str_none=str_none)
		if not all_has_chat:
			text += (f"\n\n❗️ Пары, для которых не указанна ссылка, проходят в основной группе "
				f"\\([тут]({schedule.main_chat})\\)")
	else:		
		text = "Пар нет"
	
	return f"📌 Расписание на *{str_date(date)}* \\[*{week + 1} неделя*\\]\n\n" + text

def week_schedule(schedule: Schedule, index: int, *, str_none: bool = True) -> str:
	week = schedule.get_week(index)
	if week is None:
		return f"{index} неделя отсутствует в расписании"

	week_number = index + 1 + schedule.first_week
	year, all_has_chat, text = date.today().year, True, f"📌 Расписание на *{index + 1} неделю*\n\n"
	for i, day in enumerate(week.week):
		if day is not None and len(day) >= 1 and day.count(None) != len(day):
			day_text, ahc = str_lessons_list(day, schedule, str_none=str_none)
			all_has_chat &= ahc
		else:		
			day_text = "Пар нет"
		text += (f"◾️ {str_date(date.fromisocalendar(year, week_number, i + 1))} "
			f"\\[*{weekday_name(i + 1)}*\\]\n{day_text}\n\n")
	
	if not all_has_chat:
		text += (f"❗️ Пары, для которых не указанна ссылка, проходят в основной группе "
			f"\\([тут]({schedule.main_chat})\\)")

	return text

def current_lesson(schedule: Schedule, timestamp: datetime) -> str:
	li = schedule.get_lesson_index(timestamp)
	bounds = day_bounds(timestamp, schedule)

	if li.day_index is not None and bounds is not None:
		lesson, j = schedule.always_get_lesson(li.day_part, li.day_index)
		if lesson is not None:
			prefix, next_prefix = "*СЕЙЧАС*: ", "*СЛЕДУЮЩАЯ*: "
			nl, k = schedule.always_get_lesson(li.day_part, j + 1)
			nl_str = None
			lesson_str = str_lesson_in_place(lesson, j, schedule)

			LAST_LESSON_MARKER = " *ПОСЛЕДНЯЯ*\\"

			if nl is not None:
				nl_str = str_lesson_in_place(nl, k, schedule)
				after_lesson, _ = schedule.always_get_lesson(li.day_part, k + 1)
				if after_lesson is None:
					nl_str += LAST_LESSON_MARKER
			else:
				lesson_str += LAST_LESSON_MARKER

			if not (li.is_right_now and li.day_index == j):
				prefix, next_prefix = next_prefix, "*ПОСЛЕ*: "
				if timestamp < bounds[0] - timedelta(hours=1):
					prefix = "⚠️ Учебный день ещё не начался\n" + prefix
			
			return f"{prefix}{lesson_str}" + f"\n{next_prefix}{nl_str}" if nl_str is not None else ""

		if timestamp > bounds[1]:
			return "Пары закончились"

	return "Сегодня пар нет"
