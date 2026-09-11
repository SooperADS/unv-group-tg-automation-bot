import json, io, logging

from datetime import datetime, time, timedelta, date
from dataclasses import dataclass, field
from typing import Any, NamedTuple, final
from enum import Enum

class SubjectExamKind(Enum):
	UNKNOWN = 0
	SIMPLE = 1
	DIFF = 2
	FULL = 3

	@classmethod
	def parse(cls, v: Any) -> SubjectExamKind:
		return cls[v.upper()] if v in cls else cls.UNKNOWN
	
class LessonKind(Enum):
	LECTURE = 1
	PRACTICE = 2
	CONSULTATION = 3
	EXAM = 4

	@classmethod
	def parse(cls, v: Any) -> LessonKind:
		return cls[str(v).upper()]

@final
class DeserializationError(Exception):
	pass

@final
class Lesson(NamedTuple):
	subject: Subject
	kind: LessonKind

	@staticmethod
	def parse(root: list[Any], schedule: Schedule) -> Lesson:
		subject = schedule.get_subject_by_id(str(root[0]))
		if subject is None:
			raise DeserializationError(f'Unknown subject id: {root[0]!r}')
		
		return Lesson(subject, LessonKind.parse(root[1]))

type ScheduleDay = tuple[Lesson | None, ...]
type ScheduleDayNote = ScheduleDay | None

@final
class ScheduleDayIndex(NamedTuple):
	week: int
	weekday: int

type _Schedule_Week = tuple[
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
	week: _Schedule_Week

	@property
	def current_weekday(self) -> ScheduleDay | None:
		return self.week[date.today().weekday()]
	
	def get_day(self, index: int) -> ScheduleDay | None:
		return self.week[index] if index >= 0 and index <= 6 else None

	@staticmethod
	def _parse_day(root: list[Any], index: int, schedule: Schedule) -> ScheduleDayNote:
		if len(root) <= index or root[index] is None:
			return None

		return tuple(((
			Lesson.parse(v, schedule) if v is not None else v
		) for v in root[index] if isinstance(v, list) or v is None))

	@classmethod
	def parse(cls, root: list[Any], key: str | None, schedule: Schedule) -> ScheduleWeek:
		return ScheduleWeek(schedule, key, (
			cls._parse_day(root, 0, schedule),
			cls._parse_day(root, 1, schedule),
			cls._parse_day(root, 2, schedule),
			cls._parse_day(root, 3, schedule),
			cls._parse_day(root, 4, schedule),
			cls._parse_day(root, 5, schedule),
		))

	@classmethod
	def parse_ref_or_def(cls, root: Any, schedule: Schedule) -> ScheduleWeek | None:
		if isinstance(root, str):
			w = schedule.get_week_by_name(root)
			if w is None:
				raise DeserializationError(f'No weak with name {root!r} found')
			
			return w
		elif isinstance(root, list):
			return cls.parse(root, None, schedule)
		elif root is None:
			return None
		else:
			raise DeserializationError(f'Invalid week reference or definition: {root!r}')

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
	
	@staticmethod
	def parse(root: dict[Any, Any], key: str, schedule: Schedule) -> Subject:
		str_key=f'"subjects".{key!r}.{{0!r}}'

		name = _get_existed_key(root, str, "name", "string", str_key=str_key)
		tag = _get_existed_key(root, str, "tag", "string", str_key=str_key)
		exam_s = _get_nullable_key(root, str, "exam", "string", str_key=str_key)
		exam = SubjectExamKind.parse(exam_s)
		
		chat = root.get("chat")
		main_chat, lecture_chat, practice_chat = None, None, None

		if isinstance(chat, dict):
			def _to_link(v: Any) -> str | None:
				return v if isinstance(v, str) else None

			main_chat = _to_link(chat.get("main"))
			lecture_chat = _to_link(chat.get("lecture"))
			practice_chat = _to_link(chat.get("practice"))
		elif isinstance(chat, str):
			main_chat, lecture_chat, practice_chat = chat, chat, chat

		return Subject(schedule, name, tag, key, exam, main_chat, lecture_chat, practice_chat)

def _parse_time(time: str) -> tuple[int, int]:
	if len(time) < 4 or len(time) > 5:
		raise DeserializationError(f'Invalid time string length for {time!r}')

	h, _ , m = time.partition(":")
	r = (int(h), int(m))

	if r[0] < 0 or r[0] >= 24 or r[1] < 0 or r[1] >= 60:
		raise DeserializationError(f'Invalid time: {r[0]:02d}:{r[1]:02d}')

	return r

def _check_key_exists(root: dict[Any, Any], key: str, /, *, str_key: str = "{0!r}"):
	if key not in root:
		raise DeserializationError(f'{str_key} MUST exist'.format(key))
def _get_existed_key[T](
	root: dict[Any, Any], t: type[T], key: str, s: str, /, *, str_key: str = "{0!r}"
) -> T:
	_check_key_exists(root, key, str_key=str_key)
	
	v: T | None = root.get(key)
	if not isinstance(v, t):
		raise DeserializationError(f'{str_key} MUST be {s}'.format(key))
	
	return v
def _get_nullable_key[T](
	root: dict[Any, Any],
	t: type[T],
	key: str, 
	s: str, /, *, 
	str_key: str = "{1!r}", 
	prevent_null: bool = False
) -> T | None:	
	v: T | None = root.get(key)
	if (prevent_null and key in root and v is None) or (not isinstance(v, t) and v is not None):
		msg = f'{str_key} MUST be {s} '
		if not prevent_null:
			msg += "or null "
		raise DeserializationError(msg + "or not exist".format(key))
	
	return v

def current_week() -> int:
	return date.today().isocalendar().week - 1

@final
class LessonIndex(NamedTuple):
	day_index: int | None
	is_right_now: bool

EMPTY_LESSON_INDEX = LessonIndex(None, False)

@final
class FullLessonIndex(NamedTuple):
	lesson_part: LessonIndex	
	day_part: ScheduleDayIndex

	@property
	def week(self) -> int:
		return self.day_part.week
	@property
	def weekday(self) -> int:
		return self.day_part.weekday
	@property
	def day_index(self) -> int | None:
		return self.lesson_part.day_index
	@property
	def is_right_now(self) -> bool:
		return self.lesson_part.is_right_now

	def to_next_lesson(self, schedule: Schedule) -> FullLessonIndex:
		day_index = self.day_index
		if day_index is not None:
			mx, day_index = schedule.max_lessons_count, day_index + 1
			while day_index < mx:
				if schedule.get_lesson(self.day_part, day_index) is not None:
					return FullLessonIndex(
						LessonIndex(day_index, False), self.day_part
					)
				day_index += 1
	
		return FullLessonIndex(EMPTY_LESSON_INDEX, self.day_part)


@dataclass(slots=True)
class Schedule:
	_subject_registry: dict[str, Subject]
	_subject_tags: dict[str, Subject]
	_named_weeks: dict[str, ScheduleWeek]
	_schedule: list[ScheduleWeek | None]

	_sorted_timings: list[time]
	_lessons_duration: timedelta

	_name: str | None = None
	_chat_link: str = ""
	_lessons_start: int = 0

	@property
	def main_chat(self) -> str:
		return self._chat_link
	@property
	def first_week(self) -> int:
		return self._lessons_start
	@property
	def name(self) -> str | None:
		return self._name

	@property
	def lessons_duration(self) -> timedelta:
		return self._lessons_duration
	@property
	def max_lessons_count(self) -> int:
		return len(self._sorted_timings)

	@property
	def current_week_index(self) -> int:
		return current_week() - self._lessons_start
	@property
	def current_lesson_index(self) -> FullLessonIndex:
		return self.get_lesson_index(datetime.now())
	@property
	def current_day_index(self) -> ScheduleDayIndex:
		return self.get_day_index(date.today())

	@property
	def current_day(self) -> ScheduleDayNote:
		return self.get_day(self.current_day_index)
	@property
	def current_lesson(self) -> Lesson | None:
		l, d = self.current_lesson_index
		return self.get_lesson(d, l.day_index) if l.day_index else None

	def __init__(self, root: dict[Any, Any], logger: logging.Logger | None = None) -> None:
		self._subject_registry = dict()
		self._subject_tags = dict()
		self._named_weeks = dict()
		self._schedule = list()

		self._sorted_timings = list()
		self._lessons_duration = timedelta()

		self.load(root, logger)

	def load_general(self, root: dict[Any, Any]):
		str_key='"general".{0!r}'
		chat_link = _get_existed_key(root, str, "chat", "string", str_key=str_key)
		name = _get_nullable_key(root, str, "name", "string", str_key=str_key)
		timings = _get_existed_key(root, list, "timings", "array", str_key=str_key)
		lessons_starts = _get_existed_key(root, int, "starts-at-week", "integer", str_key=str_key)

		if len(timings) < 2:
			raise DeserializationError('"general"."timings" too short')
		elif lessons_starts < 0 or lessons_starts >= 54:
			lessons_starts = 0

		stamps: list[tuple[int, int]] = list()
		for stamp in timings:
			if not isinstance(stamp, str):
				raise DeserializationError(f'Expected string, gotten {stamp!r}')
			stamps.append(_parse_time(stamp))
		
		self._lessons_start = lessons_starts
		self._chat_link = chat_link
		self._name = name

		duration = stamps.pop(0)
		self._lessons_duration = timedelta(hours=duration[0], minutes=duration[1])

		self._sorted_timings.clear()
		for v in stamps:
			self._sorted_timings.append(time(hour=v[0], minute=v[1]))
		
		self._sorted_timings.sort()
	def load_schedule(self, schedule_root: list[Any]):
		self._schedule.clear()

		for v in schedule_root:
			if isinstance(v, dict):
				l = v.get("pattern")
				if not isinstance(l, list):
					raise DeserializationError(f'Invalid week pattern: {l!r}')

				count = v.get("count")
				if not isinstance(count, int) or count <= 0:
					raise DeserializationError(f'Expected integer > 0, gotten: {count!r}')

				w: list[ScheduleWeek | None] = list()
				for rod in l:
					w.append(ScheduleWeek.parse_ref_or_def(rod, self))

				for _ in range(count):
					self._schedule.extend(w)
			else:
				self._schedule.append(ScheduleWeek.parse_ref_or_def(v, self))

	def get_subject_by_id(self, id: str) -> Subject | None:
		return self._subject_registry.get(id)
	def get_subject_by_tag(self, tag: str) -> Subject | None:
		return self._subject_tags.get(tag)
	def get_week_by_name(self, name: str) -> ScheduleWeek | None:
		return self._named_weeks.get(name)
	def get_week(self, index: int) -> ScheduleWeek | None:
		return self._schedule[index] if index >= 0 and len(self._schedule) > index else None

	def get_day_index(self, date: date) -> ScheduleDayIndex:
		iso = date.isocalendar()
		return ScheduleDayIndex(iso.week - 1 - self._lessons_start, iso.weekday - 1)
	def get_lesson_index(self, timestamp: datetime) -> FullLessonIndex:
		today, d = datetime.today(), self._lessons_duration
		di, irn = EMPTY_LESSON_INDEX
		for i, stamp in enumerate(self._sorted_timings):
			v = datetime.combine(today, stamp)
			if timestamp <= v + d:
				di, irn = i, timestamp >= v
				break

		return FullLessonIndex(
			LessonIndex(di, irn),
			self.get_day_index(timestamp)
		)
	def get_lesson_time(self, i: int) -> time:
		return self._sorted_timings[i]

	def get_day(self, index: ScheduleDayIndex) -> ScheduleDayNote:
		w = self.get_week(index.week)
		return w.get_day(index.weekday) if w is not None else None
	def get_lesson(self, i: ScheduleDayIndex, j: int) -> Lesson | None:
		d = self.get_day(i)
		return d[j] if d is not None and d and len(d) > j and j >= 0 else None

	def always_get_lesson(self, i: ScheduleDayIndex, j: int) -> tuple[Lesson | None, int]:
		d = self.get_day(i)
		if d is not None and j >= 0:
			while j < len(d):
				l = d[j]
				if l is not None:
					return l, j
				j += 1

		return None, j

	def load(self, root: dict[Any, Any], logger: logging.Logger | None = None):
		general = _get_existed_key(root, dict, "general", "object")
		subjects = _get_existed_key(root, dict, "subjects", "object")
		schedule = _get_existed_key(root, list, "schedule", "array")

		weeks = _get_nullable_key(
			root, dict, "weeks", "object", prevent_null=True
		)

		self._subject_registry.clear()
		self._subject_tags.clear()
		self._named_weeks.clear()
		self._schedule.clear()

		for k, v in subjects.items():
			if isinstance(k, str) and isinstance(v, dict):
				subject = Subject.parse(v, k, self)
				self._subject_registry[k] = subject
				self._subject_tags[subject.tag] = subject

		if weeks is not None:
			for k, v in weeks.items():
				if isinstance(k, str) and isinstance(v, list):
					self._named_weeks[k] = ScheduleWeek.parse(v, k, self)
		
		self.load_general(general)
		self.load_schedule(schedule)

		if logger is not None and logger.level >= logging.DEBUG:
			logger.debug(f"{self}")

	def get_day_bounds(self, date: date) -> tuple[int, int] | None:
		d = self.get_day(self.get_day_index(date))
		if d is not None:
			f, l = None, None
			for (i, ls) in enumerate(d):
				if ls is not None:
					if f is None:
						f = i
					l = i
			
			if f is not None and l is not None:
				return f, l

		return None

def day_bounds(date: date, schedule: Schedule) -> tuple[datetime, datetime] | None:
	b = schedule.get_day_bounds(date)
	if b is not None:
		return (
			datetime.combine(date, schedule.get_lesson_time(b[0])),
			datetime.combine(date, schedule.get_lesson_time(b[1])) + schedule.lessons_duration,
		)

	return None

def _load_root_from_file(src: str) -> dict[Any, Any]:
	with io.open(src, "r") as sch:
		root = json.load(sch)
		if isinstance(root, dict):
			return root

	raise DeserializationError("Root MUST be object")

def from_file(src: str, logger: logging.Logger | None) -> Schedule:
	if logger is not None:
		logger.info("Load schedule configuration")
	
	r = Schedule(_load_root_from_file(src), logger)
	if logger is not None:
		logger.info("Schedule configuration loaded successfully")

	return r
def reload_schedule(schedule: Schedule, src: str, logger: logging.Logger | None):
	if logger is not None:
		logger.info("Reload schedule configuration")
	
	schedule.load(_load_root_from_file(src))
	if logger is not None:
		logger.info("Schedule configuration reload successfully")
