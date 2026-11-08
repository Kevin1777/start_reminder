#!/usr/bin/env python3
"""提醒指定足球联赛及优质成年男足国家队赛事即将开赛的企业微信机器人。

程序每分钟检查一次提醒时间，但每小时只抓取一次雷速公开赛程并缓存，
避免重复访问网页；各联赛按自己的目标提前时间，在目标时间前后 1 分钟内提醒。
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
import zlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv


LOGGER = logging.getLogger("five_league_reminder")

DEFAULT_SOURCE_URL = "https://live.leisu.com/saicheng"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_STATE_FILE = Path(__file__).resolve().parent / "data" / "sent.json"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

NATIONAL_TEAM_COMPETITIONS: tuple[str, ...] = (
    "世界杯", "世预赛", "世欧预", "世亚预", "世南美预", "世非预",
    "世中北美预", "世大洋预", "世预附加赛",
    "欧洲杯", "欧洲杯预选赛", "欧国联",
    "亚洲杯", "亚洲杯预选赛", "非洲杯", "非洲杯预选赛", "美洲杯",
    "金杯赛", "中北美国联", "欧美杯",
)
NATIONAL_MAIN_CUPS = frozenset(("世界杯", "欧洲杯", "亚洲杯", "非洲杯", "美洲杯", "金杯赛", "欧美杯"))
NATIONAL_STRONG_TEAM_MAX_RANK = 50
NATIONAL_ELITE_TEAM_MAX_RANK = 30

LEAGUES: tuple[str, ...] = (
    "英超",
    "西甲",
    "意甲",
    "德甲",
    "法甲",
    "欧冠",
    "葡超",
    "美职联",
    "墨超",
    "荷甲",
    "德乙",
    "澳超",
    "巴西甲",
    "阿甲",
) + NATIONAL_TEAM_COMPETITIONS
MAJOR_LEAGUES: tuple[str, ...] = ("英超", "西甲", "意甲", "德甲", "法甲")
COMPETITION_LABELS: tuple[tuple[str, str], ...] = (
    ("英超", "英超"),
    ("西甲", "西甲"),
    ("意甲", "意甲"),
    ("德甲", "德甲"),
    ("法甲", "法甲"),
    ("欧冠", "欧冠"),
    ("欧冠杯", "欧冠"),
    ("葡超", "葡超"),
    ("美职联", "美职联"),
    ("美职业", "美职联"),
    ("美职足", "美职联"),
    ("墨超", "墨超"),
    ("墨西超", "墨超"),
    ("荷甲", "荷甲"),
    ("德乙", "德乙"),
    ("澳超", "澳超"),
    ("巴西甲", "巴西甲"),
    ("巴甲", "巴西甲"),
    ("阿甲", "阿甲"),
) + tuple((name, name) for name in NATIONAL_TEAM_COMPETITIONS) + (
    ("世界杯预选赛", "世预赛"),
    ("世预赛欧洲区", "世欧预"),
    ("世界杯欧洲区预选赛", "世欧预"),
    ("世预赛亚洲区", "世亚预"),
    ("世界杯亚洲区预选赛", "世亚预"),
    ("世预赛南美区", "世南美预"),
    ("世界杯南美洲区预选赛", "世南美预"),
    ("世预赛非洲区", "世非预"),
    ("世界杯非洲区预选赛", "世非预"),
    ("世北美预", "世中北美预"),
    ("世预赛中北美区", "世中北美预"),
    ("世界杯中北美洲区预选赛", "世中北美预"),
    ("世预赛大洋洲区", "世大洋预"),
    ("世界杯大洋洲区预选赛", "世大洋预"),
    ("世界杯洲际附加赛", "世预附加赛"),
    ("世界杯附", "世预附加赛"),
    ("欧洲杯预选", "欧洲杯预选赛"),
    ("欧洲杯预", "欧洲杯预选赛"),
    ("欧预赛", "欧洲杯预选赛"),
    ("欧杯预", "欧洲杯预选赛"),
    ("欧洲国家联赛", "欧国联"),
    ("亚洲杯预选", "亚洲杯预选赛"),
    ("亚洲杯预", "亚洲杯预选赛"),
    ("亚预赛", "亚洲杯预选赛"),
    ("非洲杯预选", "非洲杯预选赛"),
    ("非洲杯预", "非洲杯预选赛"),
    ("非洲国家杯", "非洲杯"),
    ("美金杯", "金杯赛"),
    ("中北美金杯赛", "金杯赛"),
    ("中北美洲及加勒比海国家联赛", "中北美国联"),
    ("美洲联", "中北美国联"),
    ("中北美国家联赛", "中北美国联"),
    ("大洋杯", "大洋洲杯"),
    ("国际友谊赛", "国际友谊"),
    ("东南亚锦标赛", "东南锦"),
    ("南亚足球锦标赛", "南亚锦"),
    ("西亚足球锦标赛", "西亚锦"),
    ("阿拉伯国家杯", "阿拉伯杯"),
    ("非洲国家锦标赛", "非国锦"),
    ("非国锦标", "非国锦"),
    ("欧美超级杯", "欧美杯"),
)
DEFAULT_ADDITIONAL_LEAGUE_MINUTES: dict[str, int] = {
    "欧冠": 10,
    "葡超": 10,
    "美职联": 10,
    "墨超": 10,
    "荷甲": 10,
    "德乙": 10,
    "澳超": 10,
    "巴西甲": 10,
    "阿甲": 10,
    **{name: 10 for name in NATIONAL_TEAM_COMPETITIONS},
}
UPCOMING_STATUS = "未"
DATE_RE = re.compile(r"^\s*(\d{2}/\d{2}/\d{2})\s*星期[一二三四五六日]\s*$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
DETAIL_ID_RE = re.compile(r"/detail-(\d+)(?:[/?#]|$)")
SAICHENG_SCRIPT_RE = re.compile(
    r"(?:https?:)?//[^\"']*/askaliy/askftb/sc-[^\"']+\.js(?:\?[^\"']*)?",
    re.IGNORECASE,
)
PUBLIC_PAYLOAD_RE = re.compile(
    r"window\[\s*.*?\]\s*=\s*(['\"])(?P<payload>.*?)\1",
    re.DOTALL,
)
JS_UNICODE_ESCAPE_RE = re.compile(r"%u([0-9a-fA-F]{4})")
SENT_STATE_VERSION = 1
SCHEDULE_CACHE_VERSION = 8
STATE_RETENTION_DAYS = 90
REMINDER_TOLERANCE_MINUTES = 1
BEIJING_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
NON_SENIOR_MEN_RE = re.compile(
    r"女|青年|青少年|少年|国奥|奥运|奥林匹克|U[\s-]?\d{1,2}(?!\d)|"
    r"under[\s-]?\d{1,2}(?!\d)|women|youth|(?:19|20|21|22|23)岁",
    re.IGNORECASE,
)
FIFA_RANK_RE = re.compile(r"FIFA\s+(\d{1,3})", re.IGNORECASE)
NATIONAL_QUALIFYING_STAGE_RE = re.compile(r"预选|资格|外围|附加|qualif|preliminary", re.IGNORECASE)
NATIONAL_MAIN_STAGE_RE = re.compile(
    r"小组|分组|淘汰|决赛|半决赛|四分之一|八分之一|十六强|16强|八强|8强|四强|4强|"
    r"季军|第三名|正赛|(?:[A-P]|\d+)组|final|group|knockout|round of", re.IGNORECASE,
)


class ReminderError(Exception):
    """Expected operational error that should be logged without a traceback."""


class ConfigurationError(ReminderError):
    pass


class ScheduleParseError(ReminderError):
    pass


class StateError(ReminderError):
    pass


class ScheduleCacheError(ReminderError):
    pass


class WeComError(ReminderError):
    pass


@dataclass(frozen=True)
class Match:
    """Normalized match record used by the scheduler and notifier."""

    match_id: str
    league: str
    kickoff: datetime
    home_team: str
    away_team: str
    status: str
    source_url: str
    competition_title: str = ""
    home_fifa_rank: int | None = None
    away_fifa_rank: int | None = None

    @property
    def notification_key(self) -> str:
        """Include kickoff time so a rescheduled match can notify again."""

        return f"{self.match_id}:{self.kickoff.isoformat()}"


@dataclass(frozen=True)
class Config:
    webhook_url: str
    source_url: str
    timezone_name: str
    timezone: tzinfo
    before_minutes: int
    after_minutes: int
    league_reminder_minutes: dict[str, int]
    league_windows: dict[str, tuple[int, int]]
    state_file: Path
    cache_file: Path
    dry_run: bool
    timeout_seconds: float
    user_agent: str
    log_level: str


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _env(environ: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    value = environ.get(name, default)
    if value is None:
        return None
    value = value.strip()
    return value if value else default


def _parse_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = _env(environ, name, str(default))
    try:
        value = int(raw or default)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是整数，当前值为 {raw!r}") from exc
    return value


def _parse_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = _env(environ, name, str(default))
    try:
        value = float(raw or default)
    except ValueError as exc:
        raise ConfigurationError(f"{name} 必须是数字，当前值为 {raw!r}") from exc
    return value


def _parse_bool(environ: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = (_env(environ, name, "true" if default else "false") or "").lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigurationError(f"{name} 必须是 true/false，当前值为 {raw!r}")


def _parse_league_minutes(environ: Mapping[str, str]) -> dict[str, int]:
    raw = _env(
        environ,
        "ADDITIONAL_LEAGUE_REMINDER_MINUTES",
        ",".join(f"{league}:{minutes}" for league, minutes in DEFAULT_ADDITIONAL_LEAGUE_MINUTES.items()),
    )
    result: dict[str, int] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        league_name, separator, minutes_text = item.partition(":")
        if not separator:
            raise ConfigurationError(
                "ADDITIONAL_LEAGUE_REMINDER_MINUTES 格式应为 荷甲:10,澳超:10"
            )
        league_name = league_name.strip()
        if league_name == "巴甲":
            league_name = "巴西甲"
        if league_name not in DEFAULT_ADDITIONAL_LEAGUE_MINUTES:
            raise ConfigurationError(f"不支持的新增联赛: {league_name!r}")
        try:
            minutes = int(minutes_text.strip())
        except ValueError as exc:
            raise ConfigurationError(f"联赛 {league_name} 的提醒分钟数必须是整数") from exc
        if minutes < 0:
            raise ConfigurationError(f"联赛 {league_name} 的提醒分钟数不能为负数")
        result[league_name] = minutes
    return result


def resolve_timezone(timezone_name: str) -> tzinfo:
    """Resolve an IANA timezone, with a Windows-safe Shanghai fallback.

    Windows Python installations do not always ship the IANA timezone database.
    Shanghai has no daylight-saving transitions, so a fixed UTC+8 fallback is
    equivalent for this reminder's use case.
    """

    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        if timezone_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise ConfigurationError(f"无法识别时区 {timezone_name!r}") from exc


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    """Load and validate settings from environment variables."""

    env = os.environ if environ is None else environ
    timezone_name = _env(env, "TIMEZONE", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE
    tz = resolve_timezone(timezone_name)

    major_target = _parse_int(env, "MAJOR_REMINDER_MINUTES", 10)
    if major_target < 0:
        raise ConfigurationError("MAJOR_REMINDER_MINUTES 不能为负数")

    # 每分钟检查一次，因此只给目标提前时间保留前后 1 分钟的轮询容差。
    league_reminder_minutes = {
        league: major_target for league in MAJOR_LEAGUES
    }
    league_reminder_minutes.update(_parse_league_minutes(env))
    league_reminder_minutes.update(
        {league: DEFAULT_ADDITIONAL_LEAGUE_MINUTES.get(league, major_target)
         for league in LEAGUES if league not in league_reminder_minutes}
    )
    league_windows = {
        league: (
            max(0, target - REMINDER_TOLERANCE_MINUTES),
            target + REMINDER_TOLERANCE_MINUTES,
        )
        for league, target in league_reminder_minutes.items()
    }
    before = max(0, major_target - REMINDER_TOLERANCE_MINUTES)
    after = major_target + REMINDER_TOLERANCE_MINUTES

    timeout = _parse_float(env, "HTTP_TIMEOUT_SECONDS", 20.0)
    if timeout <= 0:
        raise ConfigurationError("HTTP_TIMEOUT_SECONDS 必须大于 0")

    state_file = Path(_env(env, "STATE_FILE", str(DEFAULT_STATE_FILE)) or str(DEFAULT_STATE_FILE))
    cache_file = Path(
        _env(env, "CACHE_FILE", str(Path(__file__).resolve().parent / "data" / "schedule_cache.json"))
        or str(Path(__file__).resolve().parent / "data" / "schedule_cache.json")
    )
    dry_run = _parse_bool(env, "DRY_RUN", False)
    webhook_url = _env(env, "WECOM_WEBHOOK_URL", "") or ""
    if not dry_run and not webhook_url:
        raise ConfigurationError(
            "未设置 WECOM_WEBHOOK_URL；如果只想解析并打印消息，请设置 DRY_RUN=true"
        )
    if webhook_url and not webhook_url.startswith(("http://", "https://")):
        raise ConfigurationError("WECOM_WEBHOOK_URL 必须是 http:// 或 https:// 地址")

    return Config(
        webhook_url=webhook_url,
        source_url=_env(env, "SOURCE_URL", DEFAULT_SOURCE_URL) or DEFAULT_SOURCE_URL,
        timezone_name=timezone_name,
        timezone=tz,
        before_minutes=before,
        after_minutes=after,
        league_reminder_minutes=league_reminder_minutes,
        league_windows=league_windows,
        state_file=state_file,
        cache_file=cache_file,
        dry_run=dry_run,
        timeout_seconds=timeout,
        user_agent=_env(env, "USER_AGENT", DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT,
        log_level=(_env(env, "LOG_LEVEL", "INFO") or "INFO").upper(),
    )


def _parse_date_marker(value: str, tz: tzinfo, now: datetime) -> date:
    match = DATE_RE.fullmatch(_normalize(value))
    if not match:
        raise ScheduleParseError(f"无法解析雷速日期标记: {value!r}")

    raw_date = datetime.strptime(match.group(1), "%y/%m/%d").date()
    # 雷速页面使用两位年份；datetime.strptime 已经按当前 Python 规则映射了世纪，
    # 这里改用当前世纪，避免 26/xx 在某些 Python 版本中被解释成 2026 之外的年份。
    current_century = (now.astimezone(tz).year // 100) * 100
    return raw_date.replace(year=current_century + raw_date.year % 100)


def _canonical_league(value: str | None) -> str | None:
    normalized = _normalize(value)
    for label, canonical in sorted(COMPETITION_LABELS, key=lambda item: len(item[0]), reverse=True):
        if normalized == label or normalized.startswith(f"{label} "):
            if canonical not in LEAGUES:
                return None
            if canonical in NATIONAL_TEAM_COMPETITIONS and NON_SENIOR_MEN_RE.search(normalized):
                return None
            return canonical
    return None


def _is_senior_national_match(league: str, *labels: str | None) -> bool:
    """Keep youth and women's teams outside the senior men's scope."""

    return league not in NATIONAL_TEAM_COMPETITIONS or not any(
        NON_SENIOR_MEN_RE.search(_normalize(label)) for label in labels
    )


def _valid_fifa_rank(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _payload_fifa_rank(team: Any) -> int | None:
    if not isinstance(team, dict):
        return None
    match = FIFA_RANK_RE.fullmatch(_normalize(team.get("position_fn")))
    return _valid_fifa_rank(int(match.group(1))) if match else None


def _is_quality_match(match: Match) -> bool:
    if match.league not in LEAGUES:
        return False
    if match.league not in NATIONAL_TEAM_COMPETITIONS:
        return True
    if not _is_senior_national_match(match.league, match.competition_title, match.home_team, match.away_team):
        return False
    # World Cup intercontinental playoffs and the champions' Finalissima are
    # priority fixtures. Qualifiers stored under Asian/African cup names must
    # be recognized by stage before applying the main-tournament exemption.
    if match.league in {"世预附加赛", "欧美杯"}:
        return True
    if (
        match.league in NATIONAL_MAIN_CUPS
        and not NATIONAL_QUALIFYING_STAGE_RE.search(match.competition_title)
        and NATIONAL_MAIN_STAGE_RE.search(match.competition_title)
    ):
        return True
    home_rank = _valid_fifa_rank(match.home_fifa_rank)
    away_rank = _valid_fifa_rank(match.away_fifa_rank)
    if home_rank is None or away_rank is None:
        return False
    return max(home_rank, away_rank) <= NATIONAL_STRONG_TEAM_MAX_RANK and min(
        home_rank, away_rank
    ) <= NATIONAL_ELITE_TEAM_MAX_RANK


def _find_league(row: Tag) -> str | None:
    for node in row.find_all(True):
        league = _canonical_league(node.get("title"))
        if league is not None:
            return league
    return None


def _find_exact_text(row: Tag, pattern: re.Pattern[str], tags: Iterable[str]) -> str | None:
    for node in row.find_all(list(tags)):
        text = _normalize(node.get_text(" ", strip=True))
        if pattern.fullmatch(text):
            return text
    return None


def _find_status(row: Tag) -> str | None:
    statuses = {"未", "中", "完", "取消", "延期", "腰斩"}
    for node in row.find_all(["span", "p", "div"]):
        text = _normalize(node.get_text(" ", strip=True))
        if text in statuses:
            return text
    return None


def _find_team(row: Tag, selector: str) -> str | None:
    node = row.select_one(f"{selector} p[title]") or row.select_one(f"{selector} p")
    if node is None:
        return None
    return _normalize(node.get("title") or node.get_text(" ", strip=True)) or None


def _is_saicheng_url(source_url: str) -> bool:
    path = urlsplit(source_url).path.rstrip("/")
    return re.search(r"/saicheng(?:-\d{8})?$", path, re.IGNORECASE) is not None


def build_daily_source_url(source_url: str, day: date) -> str:
    """Resolve a configured Leisu schedule URL to the requested local date."""

    date_text = day.strftime("%Y%m%d")
    if "{date}" in source_url:
        return source_url.replace("{date}", date_text)

    parsed = urlsplit(source_url)
    path = parsed.path.rstrip("/")
    if re.search(r"/saicheng(?:-\d{8})?$", path, re.IGNORECASE):
        path = re.sub(r"/saicheng(?:-\d{8})?$", f"/saicheng-{date_text}", path, flags=re.IGNORECASE)
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))
    return source_url


def _cache_busted_url(url: str, *, now: datetime) -> str:
    """Avoid a stale CDN copy while keeping the request frequency low."""

    parsed = urlsplit(url)
    query = f"{parsed.query}&" if parsed.query else ""
    query += f"refresh={int(now.timestamp())}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _extract_saicheng_script_url(html: str, *, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script[src]"):
        candidate = urljoin(page_url, str(node.get("src") or ""))
        if SAICHENG_SCRIPT_RE.search(candidate):
            return candidate
    raise ScheduleParseError("雷速赛程页没有找到公开赛程数据脚本，可能是网页结构已变化")


def _rotate_alpha(value: str, shift: int) -> str:
    result: list[str] = []
    for char in value:
        code = ord(char)
        if 65 <= code <= 90:
            char = chr((code - 65 - shift) % 26 + 65)
        elif 97 <= code <= 122:
            char = chr((code - 97 - shift) % 26 + 97)
        result.append(char)
    return "".join(result)


def _decode_js_unescape(value: str) -> str:
    value = JS_UNICODE_ESCAPE_RE.sub(
        lambda match: chr(int(match.group(1), 16)),
        value,
    )
    # JavaScript's legacy unescape() maps %XX to a single Latin-1 code point;
    # the page uses %uXXXX for Chinese text and %XX for punctuation/accents.
    return re.sub(
        r"%([0-9a-fA-F]{2})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )


def decode_saicheng_payload(script_text: str) -> dict[str, Any]:
    """Decode the public compressed payload used by the Leisu schedule page."""

    candidates = [match.group("payload") for match in PUBLIC_PAYLOAD_RE.finditer(script_text)]
    if not candidates:
        raise ScheduleParseError("雷速赛程数据脚本没有找到公开数据载荷")

    last_error: Exception | None = None
    for encoded in sorted(candidates, key=len, reverse=True):
        for shift in range(26):
            try:
                rotated = _rotate_alpha(encoded, shift)
                compressed = base64.b64decode(rotated.encode("ascii"), validate=True)
                text = zlib.decompress(compressed).decode("ascii")
                payload = json.loads(_decode_js_unescape(text))
                if isinstance(payload, dict) and isinstance(payload.get("matches"), list):
                    return payload
            except (UnicodeError, ValueError, zlib.error, json.JSONDecodeError) as exc:
                last_error = exc

    raise ScheduleParseError("无法解码雷速公开赛程数据载荷") from last_error


def _payload_status_is_upcoming(value: Any) -> bool:
    return isinstance(value, (int, str)) and value in {1, "1", UPCOMING_STATUS, "未开赛"}


def _payload_team_name(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    return _normalize(value.get("name")) or None


def parse_saicheng_payload(
    payload: Mapping[str, Any],
    *,
    source_url: str,
    now: datetime,
    tz: tzinfo,
) -> list[Match]:
    """Normalize match records from the public Leisu schedule payload."""

    raw_matches = payload.get("matches")
    if not isinstance(raw_matches, list):
        raise ScheduleParseError("雷速公开赛程数据中没有比赛数组")

    parsed: dict[str, Match] = {}
    for item in raw_matches:
        if not isinstance(item, dict) or not _payload_status_is_upcoming(item.get("status")):
            continue

        competition = item.get("com_info")
        competition_name = competition.get("name") if isinstance(competition, dict) else None
        league = _canonical_league(competition_name) or _canonical_league(item.get("title"))
        if league is None:
            continue

        match_id = str(item.get("id") or "").strip()
        home = _payload_team_name(item.get("home")) or _payload_team_name(item.get("home_team"))
        away = _payload_team_name(item.get("away")) or _payload_team_name(item.get("away_team"))
        raw_kickoff = item.get("match_time")
        if not match_id or not home or not away or raw_kickoff is None or raw_kickoff == "":
            LOGGER.warning("跳过字段不完整的雷速赛程比赛行，比赛编号=%s", match_id or "未知")
            continue
        if not _is_senior_national_match(league, competition_name, item.get("title"), home, away):
            continue

        try:
            timestamp = float(raw_kickoff)
            if timestamp > 10**12:
                timestamp /= 1000
            kickoff = datetime.fromtimestamp(timestamp, tz)
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            LOGGER.warning("跳过开赛时间无效的雷速比赛，比赛编号=%s：%s", match_id, exc)
            continue

        match = Match(
            match_id=match_id,
            league=league,
            kickoff=kickoff,
            home_team=home,
            away_team=away,
            status=UPCOMING_STATUS,
            source_url=urljoin(source_url, f"detail-{match_id}"),
            competition_title=_normalize(item.get("title")),
            home_fifa_rank=_payload_fifa_rank(item.get("home")) or _payload_fifa_rank(item.get("home_team")),
            away_fifa_rank=_payload_fifa_rank(item.get("away")) or _payload_fifa_rank(item.get("away_team")),
        )
        if _is_quality_match(match):
            parsed[match_id] = match

    return sorted(parsed.values(), key=lambda item: item.kickoff)


def parse_schedule_html(
    html: str,
    *,
    source_url: str = DEFAULT_SOURCE_URL,
    now: datetime | None = None,
    tz: tzinfo | None = None,
) -> list[Match]:
    """Parse server-rendered match rows from the Leisu homepage."""

    tz = tz or ZoneInfo(DEFAULT_TIMEZONE)
    now = now or datetime.now(tz)
    now = now.astimezone(tz)
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("div[data-match-index]")
    if not rows:
        raise ScheduleParseError("页面中没有找到雷速比赛行，可能是网页结构已变化")

    current_date: date | None = None
    date_marker_count = 0
    detail_anchor_count = 0
    parsed: dict[str, Match] = {}

    for row in rows:
        title_node = row.select_one(".list-title")
        if title_node is not None:
            marker = _normalize(title_node.get_text(" ", strip=True))
            if DATE_RE.fullmatch(marker):
                current_date = _parse_date_marker(marker, tz, now)
                date_marker_count += 1

        anchor = row.select_one("a.match-item[href*='detail-']") or row.select_one(
            "a[href*='detail-']"
        )
        if anchor is None:
            continue
        detail_anchor_count += 1

        href = anchor.get("href") or ""
        id_match = DETAIL_ID_RE.search(href)
        if id_match is None:
            continue
        match_id = id_match.group(1)

        league = _find_league(row)
        if league is None:
            continue
        status = _find_status(row)
        if status != UPCOMING_STATUS:
            continue
        time_text = _find_exact_text(row, TIME_RE, ("div", "span", "p"))
        home_team = _find_team(row, ".first-team")
        away_team = _find_team(row, ".second-team")
        if current_date is None or time_text is None or not home_team or not away_team:
            LOGGER.warning("跳过字段不完整的比赛行，比赛编号=%s", match_id)
            continue
        if not _is_senior_national_match(
            league, row.get_text(" ", strip=True), home_team, away_team,
            *(node.get("title") for node in row.find_all(True)),
        ):
            continue

        hour, minute = (int(part) for part in time_text.split(":", 1))
        kickoff = datetime.combine(current_date, datetime.min.time(), tzinfo=tz).replace(
            hour=hour, minute=minute
        )
        source_match_url = urljoin(source_url, href)
        match = Match(
            match_id=match_id,
            league=league,
            kickoff=kickoff,
            home_team=home_team,
            away_team=away_team,
            status=status,
            source_url=source_match_url,
            competition_title=" ".join(dict.fromkeys(
                _normalize(node.get("title")) for node in row.find_all(True)
                if _canonical_league(node.get("title")) == league
            )),
        )
        if _is_quality_match(match):
            parsed[match_id] = match

    if date_marker_count == 0:
        raise ScheduleParseError("页面中没有找到日期标记，可能是网页结构已变化")
    if detail_anchor_count == 0:
        raise ScheduleParseError("页面中没有找到比赛详情链接，可能是网页结构已变化")

    return sorted(parsed.values(), key=lambda item: item.kickoff)


def fetch_schedule(
    session: requests.Session,
    *,
    source_url: str,
    timeout_seconds: float,
    user_agent: str,
    now: datetime,
    tz: tzinfo,
) -> list[Match]:
    """Fetch and parse the configured public schedule page once."""

    try:
        response = session.get(
            source_url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ReminderError(f"抓取赛程失败: {exc}") from exc

    if _is_saicheng_url(source_url):
        script_url = _extract_saicheng_script_url(response.text, page_url=source_url)
        try:
            script_response = session.get(
                _cache_busted_url(script_url, now=now),
                headers={
                    "User-Agent": user_agent,
                    "Accept": "application/javascript,text/javascript,*/*;q=0.8",
                    "Referer": source_url,
                },
                timeout=timeout_seconds,
            )
            script_response.raise_for_status()
        except requests.RequestException as exc:
            raise ReminderError(f"抓取雷速公开赛程数据失败: {exc}") from exc

        payload = decode_saicheng_payload(script_response.text)
        return parse_saicheng_payload(payload, source_url=source_url, now=now, tz=tz)

    return parse_schedule_html(response.text, source_url=source_url, now=now, tz=tz)


def _match_to_cache_record(match: Match) -> dict[str, Any]:
    return {
        "match_id": match.match_id,
        "league": match.league,
        "kickoff": match.kickoff.isoformat(),
        "home_team": match.home_team,
        "away_team": match.away_team,
        "status": match.status,
        "source_url": match.source_url,
        "competition_title": match.competition_title,
        "home_fifa_rank": match.home_fifa_rank,
        "away_fifa_rank": match.away_fifa_rank,
    }


def save_schedule_cache(
    path: Path,
    *,
    fetched_hour: datetime,
    source_url: str,
    covered_dates: Iterable[date] | None = None,
    matches: Iterable[Match],
) -> None:
    """Persist the last hourly schedule snapshot atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SCHEDULE_CACHE_VERSION,
        "source_url": source_url,
        "fetched_hour": fetched_hour.isoformat(),
        "covered_dates": [
            item.strftime("%Y-%m-%d")
            for item in (covered_dates or [])
        ],
        "matches": [_match_to_cache_record(match) for match in matches],
    }
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ScheduleCacheError(f"无法写入赛程缓存文件 {path}: {exc}") from exc


def load_schedule_cache(
    path: Path,
    *,
    tz: tzinfo,
    source_url: str,
) -> tuple[datetime, list[Match]] | None:
    """Load the hourly schedule snapshot, returning None when absent."""

    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("缓存根对象不是对象")
        if data.get("version") != SCHEDULE_CACHE_VERSION:
            raise ValueError("缓存版本过期")
        if data.get("source_url") != source_url:
            raise ValueError("缓存数据源已变化")
        covered_dates = data.get("covered_dates")
        if not isinstance(covered_dates, list) or not all(
            isinstance(item, str) and item for item in covered_dates
        ):
            raise ValueError("covered_dates 不是有效日期数组")
        fetched_hour = datetime.fromisoformat(str(data["fetched_hour"]))
        raw_matches = data["matches"]
        if not isinstance(raw_matches, list):
            raise ValueError("matches 不是数组")
        matches: list[Match] = []
        for item in raw_matches:
            if not isinstance(item, dict):
                raise ValueError("比赛记录不是对象")
            league = str(item["league"])
            if league not in LEAGUES:
                # 旧缓存可能还保留已移除的联赛，不能让它们继续参与提醒。
                continue
            kickoff = datetime.fromisoformat(str(item["kickoff"]))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=tz)
            match = Match(
                    match_id=str(item["match_id"]),
                    league=league,
                    kickoff=kickoff.astimezone(tz),
                    home_team=str(item["home_team"]),
                    away_team=str(item["away_team"]),
                    status=str(item["status"]),
                    source_url=str(item["source_url"]),
                    competition_title=_normalize(item.get("competition_title")),
                    home_fifa_rank=_valid_fifa_rank(item.get("home_fifa_rank")),
                    away_fifa_rank=_valid_fifa_rank(item.get("away_fifa_rank")),
                )
            if _is_quality_match(match):
                matches.append(match)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ScheduleCacheError(f"赛程缓存文件格式错误 {path}: {exc}") from exc
    return fetched_hour.astimezone(tz), matches


def get_hourly_schedule(config: Config, *, now: datetime, session: requests.Session) -> list[Match]:
    """Refresh once per local hour, then use the cached schedule for each check."""

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    covered_dates = [now.date()]
    if _is_saicheng_url(config.source_url) and now.hour == 23:
        covered_dates.append(now.date() + timedelta(days=1))
    request_source_urls = [
        build_daily_source_url(config.source_url, day)
        for day in covered_dates
    ] if _is_saicheng_url(config.source_url) else [config.source_url]
    cached: tuple[datetime, list[Match]] | None
    try:
        cached = load_schedule_cache(
            config.cache_file,
            tz=config.timezone,
            source_url=config.source_url,
        )
    except ScheduleCacheError as exc:
        LOGGER.warning("忽略损坏的赛程缓存：%s", exc)
        cached = None

    if cached is not None and cached[0] == current_hour:
        return cached[1]

    fetched: dict[str, Match] = {}
    for request_source_url in request_source_urls:
        try:
            daily_matches = fetch_schedule(
                session,
                source_url=request_source_url,
                timeout_seconds=config.timeout_seconds,
                user_agent=config.user_agent,
                now=now,
                tz=config.timezone,
            )
        except ReminderError:
            if cached is not None:
                LOGGER.warning("刷新赛程失败，继续使用上一份赛程缓存")
                return cached[1]
            raise
        for match in daily_matches:
            fetched[match.match_id] = match
    matches = sorted(fetched.values(), key=lambda item: item.kickoff)

    try:
        save_schedule_cache(
            config.cache_file,
            fetched_hour=current_hour,
            source_url=config.source_url,
            covered_dates=covered_dates,
            matches=matches,
        )
    except ScheduleCacheError as exc:
        LOGGER.warning("赛程已抓取，但缓存写入失败：%s", exc)
    covered_text = ",".join(item.isoformat() for item in covered_dates)
    LOGGER.info(
        "已刷新赛程缓存，共 %d 场待赛（覆盖日期：%s；来源：%s）",
        len(matches),
        covered_text,
        config.source_url,
    )
    return matches


def select_due_matches(
    matches: Iterable[Match],
    *,
    now: datetime,
    before_minutes: int,
    after_minutes: int,
    league_windows: Mapping[str, tuple[int, int]] | None = None,
) -> list[Match]:
    """Return matches whose kickoff is inside the configured reminder window."""

    if now.tzinfo is None:
        raise ValueError("now 必须带时区")
    selected: list[Match] = []
    for match in matches:
        if not _is_quality_match(match):
            continue
        if match.kickoff <= now:
            continue
        match_before, match_after = (league_windows or {}).get(
            match.league,
            (before_minutes, after_minutes),
        )
        lower = now + timedelta(minutes=match_before)
        upper = now + timedelta(minutes=match_after)
        if lower <= match.kickoff <= upper:
            selected.append(match)
    return sorted(selected, key=lambda item: item.kickoff)


def log_current_hour_schedule(matches: Iterable[Match], *, now: datetime) -> None:
    """Log target-league matches scheduled in the current and next local hour."""

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    hour_ranges = (
        ("本小时", current_hour, current_hour + timedelta(hours=1)),
        ("下小时", current_hour + timedelta(hours=1), current_hour + timedelta(hours=2)),
    )
    normalized_matches = list(matches)
    for label, start, end in hour_ranges:
        hour_matches = [
            match
            for match in normalized_matches
            if start <= match.kickoff.astimezone(now.tzinfo) < end
        ]
        hour_matches.sort(key=lambda item: item.kickoff)
        if not hour_matches:
            LOGGER.info("%s没有目标联赛比赛", label)
            continue
        summary = "；".join(
            f"{match.league} {match.kickoff.astimezone(now.tzinfo):%H:%M} "
            f"{match.home_team} vs {match.away_team}"
            for match in hour_matches
        )
        LOGGER.info("%s赛程（%d 场）：%s", label, len(hour_matches), summary)


def load_sent_state(path: Path) -> dict[str, str]:
    """Load sent notification keys; fail closed if the file is corrupt."""

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"无法读取去重状态文件 {path}: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("sent"), dict):
        raise StateError(f"去重状态文件格式错误: {path}")
    return {str(key): str(value) for key, value in data["sent"].items()}


def _prune_state(state: dict[str, str], now: datetime) -> dict[str, str]:
    cutoff = now - timedelta(days=STATE_RETENTION_DAYS)
    result: dict[str, str] = {}
    for key, sent_at in state.items():
        try:
            timestamp = datetime.fromisoformat(sent_at)
        except ValueError:
            result[key] = sent_at
            continue
        if timestamp.tzinfo is None or timestamp >= cutoff:
            result[key] = sent_at
    return result


def save_sent_state(path: Path, state: Mapping[str, str]) -> None:
    """Write state atomically so an interrupted run cannot leave partial JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SENT_STATE_VERSION, "sent": dict(sorted(state.items()))}
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise StateError(f"无法写入去重状态文件 {path}: {exc}") from exc


def _escape_markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_")


def build_markdown(
    matches: Iterable[Match],
    *,
    now: datetime,
    reminder_minutes: Mapping[str, int] | None = None,
) -> str:
    matches = list(matches)
    league_names = list(dict.fromkeys(match.league for match in matches))
    title = "、".join(_escape_markdown_text(league) for league in league_names) or "足球"
    lines = [f"## ⚽ {title}赛前提醒", ""]
    for match in matches:
        kickoff = match.kickoff.astimezone(now.tzinfo).strftime("%m-%d %H:%M")
        lead_minutes = (reminder_minutes or {}).get(match.league)
        if lead_minutes is None:
            lead_minutes = max(0, round((match.kickoff - now).total_seconds() / 60))
        home = _escape_markdown_text(match.home_team)
        away = _escape_markdown_text(match.away_team)
        lines.append(f"- {kickoff}　{home} vs {away}（提前{lead_minutes}分钟）")
    return "\n".join(lines)


def _print_message(content: str) -> None:
    """Print UTF-8 content even when a Windows console defaults to GBK."""

    try:
        print(content)
        return
    except UnicodeEncodeError:
        pass

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
            print(content)
            return
        except (AttributeError, UnicodeEncodeError):
            pass
    # This fallback is mainly for redirected streams and test runners.
    print(content.encode("ascii", errors="backslashreplace").decode("ascii"))


def send_wecom_markdown(
    session: requests.Session,
    *,
    webhook_url: str,
    content: str,
    timeout_seconds: float,
) -> None:
    """Send one Markdown message and require WeCom's errcode to be zero."""

    payload: dict[str, Any] = {"msgtype": "markdown", "markdown": {"content": content}}
    try:
        response = session.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeComError(f"企业微信消息发送失败: {exc}") from exc

    if result.get("errcode") != 0:
        raise WeComError(
            f"企业微信返回错误: errcode={result.get('errcode')!r}, errmsg={result.get('errmsg')!r}"
        )


def is_quiet_hours(now: datetime) -> bool:
    """Suppress pushes during [02:00, 07:00) Beijing time, regardless of host TZ."""

    if now.tzinfo is None:
        raise ValueError("now 必须带时区")
    return 2 <= now.astimezone(BEIJING_TIMEZONE).hour < 7


def run_once(config: Config, *, now: datetime | None = None, session: requests.Session | None = None) -> int:
    """Run one check; return the number of newly notified matches."""

    current = (now or datetime.now(config.timezone)).astimezone(config.timezone)
    http = session or requests.Session()
    matches = get_hourly_schedule(config, now=current, session=http)
    log_current_hour_schedule(matches, now=current)
    # Refresh the clock after network I/O so a check begun before 02:00 cannot
    # send after entering quiet hours. Explicit --now remains deterministic.
    current = (now or datetime.now(config.timezone)).astimezone(config.timezone)
    if is_quiet_hours(current):
        LOGGER.info("北京时间 02:00–07:00 静默时段，跳过推送；07:00 后仅按正常提醒窗口推送")
        return 0
    due = select_due_matches(
        matches,
        now=current,
        before_minutes=config.before_minutes,
        after_minutes=config.after_minutes,
        league_windows=config.league_windows,
    )
    original_state = load_sent_state(config.state_file)
    state = _prune_state(original_state, current)
    pending = [match for match in due if match.notification_key not in state]

    if not pending:
        LOGGER.info("没有需要提醒的新比赛（窗口内比赛数=%d）", len(due))
        if state != original_state:
            save_sent_state(config.state_file, state)
        return 0

    LOGGER.info("发现 %d 场待提醒比赛", len(pending))
    content = build_markdown(
        pending,
        now=current,
        reminder_minutes=config.league_reminder_minutes,
    )
    if config.dry_run:
        _print_message(content)
        LOGGER.info("DRY_RUN=true，未发送 %d 场比赛提醒", len(pending))
        return 0

    if now is None and is_quiet_hours(datetime.now(config.timezone)):
        LOGGER.info("已进入北京时间 02:00–07:00 静默时段，跳过推送")
        return 0
    send_wecom_markdown(
        http,
        webhook_url=config.webhook_url,
        content=content,
        timeout_seconds=config.timeout_seconds,
    )
    sent_at = current.isoformat()
    for match in pending:
        state[match.notification_key] = sent_at
    save_sent_state(config.state_file, state)
    LOGGER.info("已发送 %d 场比赛提醒", len(pending))
    return len(pending)


def _parse_cli_now(value: str | None, tz: tzinfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ConfigurationError(f"--now 不是有效 ISO 时间: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _send_test_message(config: Config, session: requests.Session) -> None:
    if is_quiet_hours(datetime.now(config.timezone)):
        LOGGER.info("北京时间 02:00–07:00 静默时段，跳过测试推送")
        return
    content = (
        "## ⚽ 足球赛前提醒测试\n"
        f"> 发送时间：{datetime.now(config.timezone).strftime('%Y-%m-%d %H:%M')}"
    )
    if config.dry_run:
        _print_message(content)
        LOGGER.info("DRY_RUN=true，未发送测试消息")
        return
    send_wecom_markdown(
        session,
        webhook_url=config.webhook_url,
        content=content,
        timeout_seconds=config.timeout_seconds,
    )
    LOGGER.info("企业微信测试消息发送成功")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="足球联赛及国家队赛事赛前企业微信提醒")
    parser.add_argument(
        "--send-test",
        action="store_true",
        help="向企业微信发送一条测试消息，不抓取赛程",
    )
    parser.add_argument(
        "--now",
        help="覆盖当前时间，供测试使用，例如 2026-08-30T13:50:00+08:00",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="覆盖配置中的 DRY_RUN，只打印消息，不发送",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).resolve().with_name(".env"))
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config({**os.environ, "DRY_RUN": "true"} if args.dry_run else None)
        if args.dry_run and not config.dry_run:
            config = replace(config, dry_run=True)
        logging.basicConfig(
            level=getattr(logging, config.log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(message)s",
        )
        with requests.Session() as session:
            if args.send_test:
                _send_test_message(config, session)
                return 0
            now = _parse_cli_now(args.now, config.timezone)
            run_once(config, now=now, session=session)
        return 0
    except (ReminderError, requests.RequestException) as exc:
        if not LOGGER.handlers:
            logging.basicConfig(level=logging.ERROR, format="%(asctime)s %(levelname)s %(message)s")
        LOGGER.error("任务失败：%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
