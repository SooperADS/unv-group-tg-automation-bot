import json, io, logging

from collections.abc import Generator, Iterable
from datetime import datetime, time, timedelta, date
from dataclasses import dataclass, field
from typing import Any, NamedTuple, Never, final
from enum import Enum
from warnings import deprecated
from itertools import repeat

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
		if (not allow_null and v is None) or not isinstance(v, t):
			_raise_unexpected_type(v, _sub(at, key), _primitive_name(t), *(
				(_NULL_TYPE,) if allow_null else ()
			))
	else:
		v = default

	return v

def decode_time_hm(src: Any, at: _At) -> tuple[int, int]:
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
		return self.week[weekday] if weekday <= len(self.week) else None
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

		if count < 0:
			count = 0 #TODO: raise an error

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
	exam: SubjectExamKind

	main_chat: str | None = None
	lecture_chat: str | None = None
	practice_chat: str | None = None
	
	def get_chat(self, kind: LessonKind) -> str | None:
		result: None | str = None
		if kind is LessonKind.LECTURE:
			result = self.lecture_chat
		elif kind is LessonKind.PRACTICE:
			result = self.practice_chat
		
		return result or self.main_chat

def _decode_subject(subject: dict[str, Any], id: str, schedule: Schedule, at: _At) -> Subject:
	name = _object_get_existed(subject, str, "name", at)
	tag = _object_get_existed(subject, str, "tag", at)
	exam = _object_get_existed_enum(
		subject, SubjectExamKind, "exam", at, default=SubjectExamKind.UNKNOWN
	)
	
	chat = subject.get("chat")
	mc, lc, pc = None, None, None

	if isinstance(chat, dict):
		mc = _object_get_provided(subject, str, "main", at, allow_null=True)
		lc = _object_get_provided(subject, str, "lecture", at, allow_null=True)
		pc = _object_get_provided(subject, str, "practice", at, allow_null=True)
	elif isinstance(chat, str):
		mc, lc, pc = chat, chat, chat

	return Subject(schedule, name, tag, id, exam, mc, lc, pc)
	
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

	def extend(self, lesson_index: int | None = None) -> LessonIndex:
		return LessonIndex(self, lesson_index)

@final
class LessonIndex(NamedTuple):
	day_index: ScheduleDayIndex
	lesson_index: int | None

	@property
	def week(self) -> int:
		return self.day_index.week

	@property
	def weekday(self) -> int:
		return self.day_index.weekday

def _timedelta_as_time(v: timedelta) -> time:
	return time((v.seconds // 3600) % 24, (v.seconds // 60) % 60)

def current_week() -> int:
	return date.today().isocalendar().week - 1

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

	#TODO: replace with year + week tuple or something else
	_lessons_start: int = 0

	@property
	def main_chat(self) -> str:
		return self._chat_link
	@property
	@deprecated("Invalid starting point representation. Need to be rewritten")
	def first_week(self) -> int:
		return self._lessons_start
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
		return current_week() - self._lessons_start
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

	def __init__(self, root: dict[Any, Any]) -> None:
		self._subject_registry = dict()
		self._subject_tags = dict()
		self._named_weeks = dict()
		
		self._schedule = ()
		self._sorted_timings = ()
		self._lessons_duration = timedelta()
		self.load(root)

	def load_general(self, root: dict[str, Any]):
		AT = _sub(_AT_ROOT, "general")

		chat_link = _object_get_existed(root, str, "chat", AT)
		name = _object_get_provided(root, str, "name", AT, allow_null=True)
		timings = _object_get_existed(root, list, "timings", AT)
		lessons_starts = _object_get_existed(root, int, "starts-at-week", AT)

		if len(timings) < 2:
			_raise_unexpected_list_len(len(timings), ">= 1", AT)
		elif lessons_starts < 0 or lessons_starts >= 54:
			lessons_starts = 0 #TODO: raise an error

		stamps: list[tuple[int, int]] = list()
		for i, stamp in enumerate(timings):
			stamps.append(decode_time_hm(stamp, _sub(AT, i)))
		
		self._lessons_start = lessons_starts
		self._chat_link = chat_link
		self._name = name

		duration = stamps.pop(0)
		self._lessons_duration = timedelta(hours=duration[0], minutes=duration[1])

		stamps.sort()
		self._sorted_timings = tuple((
			timedelta(hours=v[0], minutes=v[1]) for v in stamps
		))
	def load_schedule(self, root: list[Any]):
		AT = _sub(_AT_ROOT, "general")

		def _repetition_unpack(schedule: Schedule) -> Generator[ScheduleWeekNote, Any, None]:
			for i, week in enumerate(root):
				for v in _decode_scheduled_week(week, schedule, _sub(AT, i)):
					yield v
		self._schedule = tuple(_repetition_unpack(self))
	def load(self, root: dict[str, Any]):
		general: dict[str, Any] = _object_get_existed(root, dict, "general", _AT_ROOT)
		subjects: dict[str, Any] = _object_get_existed(root, dict, "subjects", _AT_ROOT)
		schedule = _object_get_existed(root, list, "schedule", _AT_ROOT)
		weeks: dict[str, Any] | None = _object_get_provided(root, dict, "weeks", _AT_ROOT)

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
	def get_week_by_name(self, name: str) -> ScheduleWeekNote:
		return self._named_weeks.get(name)
	
	def get_week(self, index: int) -> ScheduleWeekNote:
		return self._schedule[index] if index >= 0 and len(self._schedule) > index else None
	def get_day(self, index: ScheduleDayIndex) -> ScheduleDayNote:
		week = self.get_week(index.week)
		return None if week is None else week.get_day(index.weekday)
	def get_lesson(self, index: LessonIndex) -> LessonNote:
		if index.lesson_index is not None:
			day = self.get_day(index.day_index)
			if day is not None: 
				return day.get_lesson(index.lesson_index)
		return None

	def get_lesson_timestamp(self, n: int) -> timedelta:
		return self._sorted_timings[n]
	def get_lesson_bounds(self, n: int) -> TimeSpan:
		start = self.get_lesson_timestamp(n)
		return _timedelta_as_time(start), _timedelta_as_time(start + self._lessons_duration)

	def lessons_bounds_to_span(self, bounds: LessonsBounds) -> TimeSpan:
		return (_timedelta_as_time(self.get_lesson_timestamp(bounds[0])),
			 _timedelta_as_time(self.get_lesson_timestamp(bounds[1]) + self._lessons_duration))

	#TODO: from_day_index, from_lesson_index

	def to_day_index(self, date: date) -> ScheduleDayIndex:
		iso = date.isocalendar()
		return ScheduleDayIndex(iso.week - 1 - self._lessons_start, iso.weekday - 1)
	def to_lesson_index(self, timestamp: datetime) -> tuple[LessonIndex, bool]:
		today, d = datetime.today(), self._lessons_duration
		di, irn = None, False
		for i, stamp in enumerate(self._sorted_timings):
			v = today + stamp
			if timestamp <= v + d:
				di, irn = i, timestamp >= v
				break

		return self.to_day_index(timestamp).extend(di), irn

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
