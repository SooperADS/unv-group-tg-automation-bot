import json, io, logging

from datetime import datetime, time, timedelta, date
from typing import Any, NamedTuple, Never, final
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from itertools import repeat
from enum import Enum

# ==============================
#  Decode helpers
# ==============================

_STR_TYPE = "string"
_DICT_TYPE = "object"
_LIST_TYPE = "array"
_INT_TYPE = "integer"
_FLOAT_TYPE = "number"
_NULL_TYPE = "null"
_BOOL_TYPE = "boolean"

type _Primitive = str | int | float | bool | list[Any] | dict[str, Any]
type _At = str | None

@final
class DeserializationError(Exception):
	def __init__(self, msg: str, at: _At) -> None:
		super().__init__(f"{msg} at {at or '<root>'}")

_PRIMITIVE_MAP = {
	str: _STR_TYPE,
	int: _INT_TYPE,
	float: _FLOAT_TYPE,
	list: _LIST_TYPE,
	dict: _DICT_TYPE,
	bool: _BOOL_TYPE
}
_AT_ROOT = None

def _primitive_name(kind: type[_Primitive]) -> str:
	return _PRIMITIVE_MAP.get(kind, "???")
def _sub(at: str | None, k: str | int) -> str:
	if isinstance(k, int):
		return f"{at or ''}[{k}]"
	elif at is not None:
		return f"{at}.{k!r}"

	return f"{k!r}"

def _raise_unexpected_list_len(len: int, expected: str | int, at: _At) -> Never:
	raise DeserializationError(f"List length {len}, expected {expected}", at)
def _raise_unexpected_type(v: Any, at: _At, *expected: str) -> Never:
	raise DeserializationError(f"Expected {" or ".join(expected)}, gotten {v!r}", at)
def _raise_unknown_instance(v: Any, cls: type[Any], at: _At) -> Never:
	raise DeserializationError(f"Unknown {cls.__name__} {v!r}", at)

def _object_get_existed[K: _Primitive](
	obj: dict[str, Any], t: type[K], key: str, at: _At, *, default: K | None = None
) -> K:
	if key not in obj:
		raise DeserializationError(f"Expected key, but it doesn't exist", _sub(at, key))
	
	v: K | None = obj.get(key, default)
	if not isinstance(v, t):
		has_default = default is not None
		if has_default and key in obj:
			return default
 
		_raise_unexpected_type(v, _sub(at, key), _primitive_name(t), *(
			(_NULL_TYPE,) if has_default else ()
		))
	return v
def _object_get_existed_enum[E: Enum](
	obj: dict[str, Any], t: type[E], key: str, at: _At, *, default: E | None = None
) -> E:
	return decode_enum(_object_get_existed(
		obj, str, key, at, default=None if default is None else default.name
	), _sub(at, key), t)
def _object_get_provided[K: _Primitive](
	obj: dict[str, Any],
	t: type[K],
	key: str,
	at: _At, *,
	default: K | None = None,
	allow_null: bool = False
) -> K | None:
	if key in obj:
		v: K | None = obj.get(key)
		if (not allow_null and v is None) or (not isinstance(v, t) and v is not None):
			_raise_unexpected_type(v, _sub(at, key), _primitive_name(t), *(
				(_NULL_TYPE,) if allow_null else ()
			))
	else:
		v = default

	return v

def _check_int_range(v: int, min: int | None, max: int | None, at: _At):
	if (min is not None and v < min) or (max is not None and v > max):
		range_text = f"[{'-inf' if min is None else min}; {'+inf' if max is None else max}]"
		raise DeserializationError(f"Expected integer in {range_text}", at)
def _decode_time_hm(src: Any, at: _At) -> tuple[int, int]:
	if not isinstance(src, str):
		_raise_unexpected_type(src, at, _STR_TYPE)

	try:
		v = time.strptime(src, "%H:%M")
		return v.hour, v.minute
	except ValueError:
		raise DeserializationError(f"Invalid time: {src!r}", at)

# ==============================
#  Deserializable types and
#  their decoders
# ==============================

class SubjectExamKind(Enum):
	UNKNOWN = 0
	SIMPLE = 1
	DIFF = 2
	FULL = 3

class LessonKind(Enum):
	LECTURE = 1
	PRACTICE = 2
	CONSULTATION = 3
	EXAM = 4

def decode_enum[E: Enum](v: Any, at: _At, enum: type[E]) -> E:
	if not isinstance(v, str):
		_raise_unexpected_type(v, at, _STR_TYPE)

	v = v.upper()
	if not hasattr(enum, v):
		_raise_unknown_instance(v, enum, at)

	return enum[v]

@final
class Lesson(NamedTuple):
	subject: Subject
	kind: LessonKind

	@property
	def specified_chat(self) -> str | None:
		return self.subject.get_chat(self.kind)

type LessonNote = Lesson | None
type Lessons = tuple[LessonNote, ...]
type LessonsBounds = tuple[int, int]

def _decode_lesson(list: list[Any], schedule: Schedule, at: _At) -> Lesson:
	if len(list) != 2:
		_raise_unexpected_list_len(len(list), 2, at)
	
	subject_id, lesson_kind = list[0], list[1]
	if not isinstance(subject_id, str):
		_raise_unexpected_type(subject_id, _sub(at, 0), _STR_TYPE)
	
	subject = schedule.get_subject_by_id(subject_id)
	if subject is None:
		_raise_unknown_instance(subject, Subject, _sub(at, 1))

	return Lesson(subject, decode_enum(lesson_kind, _sub(at, 1), LessonKind))

def get_lessons_bounds(lessons: Lessons, start: int) -> LessonsBounds | None:
	first, last = None, None
	for (i, note) in enumerate(lessons):
		if note is not None:
			if first is None or i <= start:
				first = i
			last = i
	
	if first is not None and last is not None:
		return first, last
	
	return None
	
def is_chat_specified_for_all_lessons(lessons: Lessons) -> bool:
	for l in lessons:
		if l is not None and l.specified_chat is None:
			return False
	
	return True

@dataclass(frozen=True, slots=True, init=False)
class ScheduleDay:
	lessons: Lessons

	bounds: LessonsBounds | None
	all_chat_specified: bool

	@property
	def first_lesson(self) -> int | None:
		return self.bounds[0] if self.bounds is not None else None
	@property
	def last_lesson(self) -> int | None:
		return self.bounds[1] if self.bounds is not None else None

	def __init__(self, lessons: Lessons):
		object.__setattr__(self, "lessons", lessons)
		object.__setattr__(self, "bounds", get_lessons_bounds(lessons, 0))
		object.__setattr__(self, "all_chat_specified", is_chat_specified_for_all_lessons(lessons))

	def get_lesson(self, index: int) -> LessonNote:
		return self.lessons[index] if len(self.lessons) > index else None
	def fetch_lesson(self, start: int) -> tuple[Lesson, int] | None:
		while start < len(self.lessons):
			current = self.lessons[start]
			if current is not None:
				return current, start
			start += 1
		
		return None

def _decode_schedule_day(day: list[Any], schedule: Schedule, at: _At) -> ScheduleDay:
	if len(day) < 1:
		_raise_unexpected_list_len(len(day), ">= 1", at)

	def _decode_item(i: int, v: Any) -> LessonNote:
		if v is None:
			return None
		elif not isinstance(v, list):
			_raise_unexpected_type(v, _sub(at, i), _LIST_TYPE, _NULL_TYPE)
		return _decode_lesson(v, schedule, _sub(at, i))

	return ScheduleDay(tuple((
		_decode_item(i, v) for i, v in enumerate(day)
	)))

type ScheduleDayNote = ScheduleDay | None
type ScheduleWeekDays = tuple[
	ScheduleDayNote, # пн
	ScheduleDayNote, # вт
	ScheduleDayNote, # ср
	ScheduleDayNote, # чт
	ScheduleDayNote, # пт
	ScheduleDayNote, # сб
	# вс (всегда None)
]

@dataclass(frozen=True, slots=True)
class ScheduleWeek:
	schedule: Schedule = field(repr=False)

	name: str | None
	week: ScheduleWeekDays

	@property
	def current_weekday(self) -> ScheduleDayNote:
		return self.get_day(date.today().weekday())
	
	def get_day(self, weekday: int) -> ScheduleDayNote:
		return self.week[weekday] if weekday < len(self.week) else None
	def get_lesson(self, weekday: int, index: int) -> LessonNote:
		day = self.get_day(weekday)
		return day.get_lesson(index) if day is not None else None

type ScheduleWeekNote = ScheduleWeek | None

def _decode_week(week: list[Any], name: str | None, schedule: Schedule, at: _At) -> ScheduleWeek:
	days = len(week)
	if len(week) < 1:
		_raise_unexpected_list_len(len(week), ">= 1", at)

	def _decode_item(i: int) -> ScheduleDay | None:
		if i >= days:
			return None
		
		v = week[i]
		if v is None:
			return None
		elif not isinstance(v, list):
			_raise_unexpected_type(v, _sub(at, i), _LIST_TYPE, _NULL_TYPE)
		return _decode_schedule_day(v, schedule, _sub(at, i))

	return ScheduleWeek(schedule, name, (
		_decode_item(0),
		_decode_item(1),
		_decode_item(2),
		_decode_item(3),
		_decode_item(4),
		_decode_item(5),
	))

def _raw_decode_week_ref(ref: str | None, schedule: Schedule, at: _At) -> ScheduleWeekNote:
	if ref is None:
		return None

	w = schedule.get_week_by_name(ref)
	if w is None:
		_raise_unknown_instance(w, ScheduleWeek, at)
	return w
def _decode_week_ref_or_def(week: Any, schedule: Schedule, at: _At) -> ScheduleWeekNote:
	if isinstance(week, str) or week is None:
		return _raw_decode_week_ref(week, schedule, at)
	elif isinstance(week, list):
		return _decode_week(week, None, schedule, at)

	raise _raise_unexpected_type(week, at, _STR_TYPE, _LIST_TYPE, _NULL_TYPE)

def _decode_scheduled_week(week: Any, schedule: Schedule, at: _At) -> Iterable[ScheduleWeekNote]:
	if isinstance(week, str) or week is None:
		return (_raw_decode_week_ref(week, schedule, at),)
	elif isinstance(week, list):
		return (_decode_week(week, None, schedule, at),)
	elif isinstance(week, dict):
		pattern = _object_get_existed(week, list, "pattern", at)
		count = _object_get_existed(week, int, "count", at)

		_check_int_range(count, 0, None, _sub(at, "count"))
		def _result_gen() -> Generator[ScheduleWeekNote, Any, None]:
			for i, rod in enumerate(pattern):
				v = _decode_week_ref_or_def(rod, schedule, _sub(at, i))
				for r in repeat(v, count):
					yield r
		
		return _result_gen()

	raise _raise_unexpected_type(week, at, _LIST_TYPE, _STR_TYPE, _DICT_TYPE, _NULL_TYPE)

@dataclass(frozen=True, slots=True)
class Subject:
	schedule: Schedule = field(repr=False)

	name: str
	tag: str
	id: str
	
	exam_kind: SubjectExamKind
	exam_requirements: str | None
	exam_form: str | None

	main_chat: str | None = None
	lecture_chat: str | None = None
	practice_chat: str | None = None
	
	def get_chat(self, kind: LessonKind) -> str | None:
		match kind:
			case LessonKind.LECTURE: return self.lecture_chat
			case LessonKind.PRACTICE: return self.practice_chat
			case _: return self.main_chat

def _decode_subject(subject: dict[str, Any], id: str, schedule: Schedule, at: _At) -> Subject:
	name = _object_get_existed(subject, str, "name", at)
	tag = _object_get_existed(subject, str, "tag", at)
	exam = _object_get_existed(subject, dict, "exam", at)
	
	chat = subject.get("chat")
	mc, lc, pc = None, None, None

	if isinstance(chat, dict):
		cat = _sub(at, "chat")
		mc = _object_get_provided(chat, str, "main", cat, allow_null=True)
		lc = _object_get_provided(chat, str, "lecture", cat, allow_null=True)
		pc = _object_get_provided(chat, str, "practice", cat, allow_null=True)
	elif isinstance(chat, str):
		mc, lc, pc = chat, chat, chat

	eat = _sub(at, "exam")
	exam_form = _object_get_provided(exam, str, "form", eat, allow_null=True)
	exam_kind = _object_get_existed_enum(
		exam, SubjectExamKind, "kind", eat, default=SubjectExamKind.UNKNOWN
	)
	exam_rq = _object_get_provided(
		exam, str, "requirements", eat, allow_null=True
	)

	return Subject(
		schedule, name, tag, id, exam_kind,
		exam_rq, exam_form,
		mc, lc, pc
	)
	
# ==============================
#  Schedule class and their
#  helpers
# ==============================

type TimeSpan = tuple[time, time]
type DateTimeSpan = tuple[datetime, datetime]

@final
class ScheduleDayIndex(NamedTuple):
	week: int
	weekday: int

	@property
	def is_valid(self) -> bool:
		return self.weekday >= 0 and self.weekday <= 6

	def extend(self, lesson_index: int | None = None) -> LessonIndex:
		return LessonIndex(self, lesson_index)
	def add_days(self, count: int) -> ScheduleDayIndex:
		nw = self.weekday + count
		w = nw // 7 + self.week
		return ScheduleDayIndex(w, nw % 7)

type ScheduleDayPair = tuple[ScheduleDayIndex, ScheduleDay]

@final
class LessonIndex(NamedTuple):
	day_index: ScheduleDayIndex
	lesson_index: int | None

	@property
	def is_valid(self) -> bool:
		return self.day_index.is_valid >= 0 and (
			self.lesson_index is None or self.lesson_index >= 0
		)

	@property
	def week(self) -> int:
		return self.day_index.week
	@property
	def weekday(self) -> int:
		return self.day_index.weekday

type LessonIndexResult = LessonIndex | None
type LessonPair = tuple[LessonIndex, Lesson]

def timedelta_as_time(v: timedelta) -> time:
	return time((v.seconds // 3600) % 24, (v.seconds // 60) % 60)
def weeks_for_year(year: int) -> int:
    return date(year, 12, 28).isocalendar().week
def day_starting_point(day: date) -> datetime:
	return datetime.combine(day, time())

def span_with_date(span: TimeSpan, d: date | None = None) -> DateTimeSpan:
	d = d or date.today()
	return datetime.combine(d, span[0]), datetime.combine(d, span[1])

@dataclass(slots=True)
class Schedule:
	_subject_registry: dict[str, Subject]
	_subject_tags: dict[str, Subject]
	_named_weeks: dict[str, ScheduleWeek]
	_schedule: tuple[ScheduleWeekNote, ...]

	_sorted_timings: tuple[timedelta, ...]
	_lessons_duration: timedelta

	_name: str | None = None
	_chat_link: str = ""
	_first_week: int = 0
	_first_year: int = 0

	@property
	def first_week(self) -> int:
		return self._first_week
	@property
	def first_year(self) -> int:
		return self._first_year

	@property
	def main_chat(self) -> str:
		return self._chat_link
	@property
	def name(self) -> str | None:
		return self._name

	@property
	def lessons_duration(self) -> timedelta:
		return self._lessons_duration
	@property
	def max_lessons(self) -> int:
		return len(self._sorted_timings)

	@property
	def current_week_index(self) -> int:
		# NEED_CHECK: Maybe incorrect algorithm
		iso = date.today().isocalendar()
		w, y = iso.week, iso.year

		while y > self._first_year + 1:
			y -= 1
			w += weeks_for_year(y)

		return w - self._first_week - 1
	@property
	def current_week(self) -> ScheduleWeekNote:
		return self.get_week(self.current_week_index)
	
	@property
	def current_day_index(self) -> ScheduleDayIndex:
		return self.to_day_index(date.today())
	@property
	def current_day(self) -> ScheduleDayNote:
		return self.get_day(self.current_day_index)

	@property
	def current_lesson_index(self) -> LessonIndex:
		return self.to_lesson_index(datetime.now())[0]
	@property
	def current_lesson(self) -> LessonNote:
		return self.get_lesson(self.current_lesson_index)

	def __init__(self, root: dict[Any, Any] | None) -> None:
		self._subject_registry = dict()
		self._subject_tags = dict()
		self._named_weeks = dict()
		
		self._schedule = ()
		self._sorted_timings = ()
		self._lessons_duration = timedelta()
		if root is not None:
			self.load(root)

	def load_general(self, root: dict[str, Any]):
		AT = _sub(_AT_ROOT, "general")

		### LOAD ROOTS ###
		chat_link = _object_get_existed(root, str, "chat", AT)
		name = _object_get_provided(root, str, "name", AT, allow_null=True)
		timings = _object_get_existed(root, dict, "timings", AT)

		### LOAD TIMINGS OBJECT ###
		AT_TIMINGS = _sub(_AT_ROOT, "timings")
		lessons = _object_get_existed(timings, list, "lessons", AT_TIMINGS)
		lesson_d = _object_get_existed(timings, str, "lesson-duration", AT_TIMINGS)
		first_w = _object_get_existed(timings, int, "first-week", AT_TIMINGS)
		first_y = _object_get_existed(timings, int, "first-year", AT_TIMINGS)
		
		_check_int_range(first_w, 0, 52, _sub(AT_TIMINGS, "first-week"))
		_check_int_range(first_y, 2000, 2100, _sub(AT_TIMINGS, "first-year"))
	
		if len(lessons) < 1:
			_raise_unexpected_list_len(len(lessons), ">= 1", AT)
		
		stamps: list[tuple[int, int]] = list()
		for i, stamp in enumerate(lessons):
			stamps.append(_decode_time_hm(stamp, _sub(AT, i)))

		stamps.sort()
		d = _decode_time_hm(lesson_d, _sub(
			AT_TIMINGS, "lesson-duration"
		))

		### SETUP ###
		self._lessons_duration = timedelta(hours=d[0], minutes=d[1])
		self._sorted_timings = tuple((
			timedelta(hours=v[0], minutes=v[1]) for v in stamps
		))

		self._name = name
		self._chat_link = chat_link
		self._first_week = first_w
		self._first_year = first_y
	def load_schedule(self, root: list[Any]):
		AT = _sub(_AT_ROOT, "general")

		def _repetition_unpack(schedule: Schedule) -> Generator[ScheduleWeekNote, Any, None]:
			for i, week in enumerate(root):
				for v in _decode_scheduled_week(week, schedule, _sub(AT, i)):
					yield v
		self._schedule = tuple(_repetition_unpack(self))
	def load(self, root: dict[str, Any]):
		### LOAD ROOTS ###
		general: dict[str, Any] = _object_get_existed(root, dict, "general", _AT_ROOT)
		subjects: dict[str, Any] = _object_get_existed(root, dict, "subjects", _AT_ROOT)
		schedule = _object_get_existed(root, list, "schedule", _AT_ROOT)
		weeks: dict[str, Any] | None = _object_get_provided(root, dict, "weeks", _AT_ROOT)

		### SETUP ###
		self._subject_registry.clear()
		self._subject_tags.clear()
		self._named_weeks.clear()

		AT_SUBJECTS = _sub(_AT_ROOT, "subjects")
		for k, v in subjects.items():
			at = _sub(AT_SUBJECTS, k)
			if not isinstance(v, dict):
				_raise_unexpected_type(v, at, _DICT_TYPE)

			s = _decode_subject(v, k, self, at)
			self._subject_registry[k] = s
			self._subject_tags[s.tag] = s

		AT_WEEKS = _sub(_AT_ROOT, "weeks")
		if weeks is not None:
			for k, v in weeks.items():
				at = _sub(AT_WEEKS, k)
				if not isinstance(v, list):
					_raise_unexpected_type(v, at, _DICT_TYPE)
				self._named_weeks[k] = _decode_week(v, k, self, at)
		
		self.load_general(general)
		self.load_schedule(schedule)

	def get_subject_by_id(self, id: str) -> Subject | None:
		return self._subject_registry.get(id)
	def get_subject_by_tag(self, tag: str) -> Subject | None:
		return self._subject_tags.get(tag)
	def get_subjects(self) -> Iterable[tuple[str, Subject]]:
		return self._subject_registry.items()
	def get_week_by_name(self, name: str) -> ScheduleWeekNote:
		return self._named_weeks.get(name)
	
	def get_week(self, index: int) -> ScheduleWeekNote:
		return self._schedule[index] if index >= 0 and len(self._schedule) > index else None
	def get_day(self, index: ScheduleDayIndex) -> ScheduleDayNote:
		week = self.get_week(index.week)
		return None if week is None else week.get_day(index.weekday)
	def get_lesson(self, index: LessonIndexResult) -> LessonNote:
		if index is not None and index.lesson_index is not None:
			day = self.get_day(index.day_index)
			if day is not None: 
				return day.get_lesson(index.lesson_index)
		return None

	def get_lesson_timestamp(self, n: int) -> timedelta:
		return self._sorted_timings[n]
	def get_lesson_bounds(self, n: int) -> TimeSpan:
		start = self.get_lesson_timestamp(n)
		return timedelta_as_time(start), timedelta_as_time(start + self._lessons_duration)

	def lessons_bounds_to_span(self, bounds: LessonsBounds) -> TimeSpan:
		return (timedelta_as_time(self.get_lesson_timestamp(bounds[0])),
			 timedelta_as_time(self.get_lesson_timestamp(bounds[1]) + self._lessons_duration))

	def to_day_index(self, date: date) -> ScheduleDayIndex:
		iso = date.isocalendar()
		return ScheduleDayIndex(iso.week - 1 - self._first_week, iso.weekday - 1)
	def to_lesson_index(self, timestamp: datetime) -> tuple[LessonIndex, bool]:
		today, d = day_starting_point(date.today()), self._lessons_duration
		di, irn = None, False
		for i, stamp in enumerate(self._sorted_timings):
			v = today + stamp
			if timestamp <= v + d:
				di, irn = i, timestamp >= v
				break

		return self.to_day_index(timestamp).extend(di), irn

	def search_lesson(
		self,
		start: LessonIndexResult,
		number: int = 1, *,
		type: Subject | None = None,
		kind: LessonKind | None = None
	) -> LessonPair | None:
		n = number
		for li, ls in self.lessons(start):
			if (type is None or ls.subject == type) and (kind is None or ls.kind == kind):
				if n <= 0:
					return li, ls

				n -= 1
		
		return None
	
	def to_iso_year_and_week(self, week_index: int) -> tuple[int, int]:
		# NEED_CHECK:
		m = 1 if week_index >= 0 else -1
		yrd, wfy = 0, weeks_for_year(self.first_year)
		while week_index >= wfy:
			yrd += m
			week_index -= wfy * m
		
		return self.first_year + yrd, self.first_week + week_index + 1
	def to_date(self, index: ScheduleDayIndex) -> date:
		y, w = self.to_iso_year_and_week(index.week)
		return date.fromisocalendar(y, w, index.weekday + 1)

	def weeks(self, start: int | None = None) -> Iterable[ScheduleWeekNote]:
		i, l = start or 0, len(self._schedule)
		
		while i < l:
			yield self._schedule[i]
			i += 1		
	def days(self, start: ScheduleDayIndex | None = None) -> Iterable[ScheduleDayPair]:
		i, j, l = 0, 0, len(self._schedule)
		if start is not None:
			i, j = start.week, start.weekday
		
		while i < l:
			w = self._schedule[i]

			if w is not None:
				while j < len(w.week):
					day = w.get_day(j)
					if day is not None:
						yield ScheduleDayIndex(i, j), day

					j += 1
			j = 0
			i += 1
	def lessons(self, start: LessonIndexResult = None) -> Iterable[LessonPair]:
		i, di = 0, None
		if start is not None:
			i, di = start.lesson_index or 0, start.day_index
		
		for awi, day in self.days(di):
			while i < len(day.lessons):
				lesson = day.get_lesson(i)
				if lesson is not None:
					yield LessonIndex(awi, i), lesson

				i += 1
			i = 0

# ==============================
#  Global initialization helpers
# ==============================

def _load_root_from_file(src: str) -> dict[Any, Any]:
	with io.open(src, "r") as sch:
		root = json.load(sch)
		if isinstance(root, dict):
			return root

		_raise_unexpected_type(root, _AT_ROOT, _DICT_TYPE)

def from_file(src: str, logger: logging.Logger | None) -> Schedule:
	if logger is not None:
		logger.info("Load schedule configuration")
	
	r = Schedule(_load_root_from_file(src))
	if logger is not None:
		logger.info("Schedule configuration loaded successfully")

	return r
def reload_schedule(schedule: Schedule, src: str, logger: logging.Logger | None):
	if logger is not None:
		logger.info("Reload schedule configuration")
	
	schedule.load(_load_root_from_file(src))
	if logger is not None:
		logger.info("Schedule configuration reload successfully")
