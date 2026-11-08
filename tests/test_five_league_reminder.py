import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
from zoneinfo import ZoneInfo
import zlib

from five_league_reminder import (
    Config,
    resolve_timezone,
    LEAGUES,
    NATIONAL_TEAM_COMPETITIONS,
    Match,
    SCHEDULE_CACHE_VERSION,
    ScheduleParseError,
    WeComError,
    build_daily_source_url,
    build_markdown,
    decode_saicheng_payload,
    load_config,
    load_schedule_cache,
    load_sent_state,
    is_quiet_hours,
    log_current_hour_schedule,
    parse_saicheng_payload,
    parse_schedule_html,
    run_once,
    save_sent_state,
    save_schedule_cache,
    select_due_matches,
    send_wecom_markdown,
    _rotate_alpha,
    _decode_js_unescape,
    _send_test_message,
)


TZ = resolve_timezone("Asia/Shanghai")
NOW = datetime(2026, 8, 30, 13, 50, tzinfo=TZ)


SAICHENG_PAYLOAD = {
    "matches": [
        {
            "id": 3001,
            "title": "葡超 联赛 第4轮",
            "status": 1,
            "match_time": int(datetime(2026, 8, 29, 22, 30, tzinfo=TZ).timestamp()),
            "home": {"name": "阿罗卡"},
            "away": {"name": "马里迪莫"},
            "com_info": {"name": "葡超"},
        },
        {
            "id": 3002,
            "title": "葡超 联赛 第4轮",
            "status": 1,
            "match_time": int(datetime(2026, 8, 29, 22, 30, tzinfo=TZ).timestamp()),
            "home": {"name": "艾华卡"},
            "away": {"name": "圣克拉拉"},
            "com_info": {"name": "葡超"},
        },
        {
            "id": 3003,
            "title": "荷甲 联赛 第4轮",
            "status": 1,
            "match_time": int(datetime(2026, 8, 29, 22, 30, tzinfo=TZ).timestamp()),
            "home": {"name": "SBV精英"},
            "away": {"name": "鹿特丹斯巴达"},
            "com_info": {"name": "荷甲"},
        },
        {
            "id": 3004,
            "title": "英冠 联赛 第4轮",
            "status": 1,
            "match_time": int(datetime(2026, 8, 29, 22, 30, tzinfo=TZ).timestamp()),
            "home": {"name": "英冠主队"},
            "away": {"name": "英冠客队"},
            "com_info": {"name": "英冠"},
        },
        {
            "id": 3005,
            "title": "葡超 联赛 第4轮",
            "status": 2,
            "match_time": int(datetime(2026, 8, 29, 22, 30, tzinfo=TZ).timestamp()),
            "home": {"name": "已结束主队"},
            "away": {"name": "已结束客队"},
            "com_info": {"name": "葡超"},
        },
    ]
}


def encode_saicheng_script(payload):
    encoded_json = quote(json.dumps(payload, ensure_ascii=True), safe="")
    compressed = zlib.compress(encoded_json.encode("ascii"))
    public_text = base64.b64encode(compressed).decode("ascii")
    encrypted_text = _rotate_alpha(public_text, -13)
    return f"window[_t19798[2]] = '{encrypted_text}';"


SAICHENG_SCRIPT = encode_saicheng_script(SAICHENG_PAYLOAD)
SAICHENG_PAGE = """
<html><head>
  <script src="https://static.leisu.com/public/askaliy/askftb/sc-test.js"></script>
</head><body></body></html>
"""

TODAY_LATE_PAYLOAD = {
    "matches": [
        {
            "id": 4001,
            "title": "法甲 联赛 第1轮",
            "status": 1,
            "match_time": int(datetime(2026, 8, 29, 23, 55, tzinfo=TZ).timestamp()),
            "home": {"name": "今晚主队"},
            "away": {"name": "今晚客队"},
            "com_info": {"name": "法甲"},
        }
    ]
}
TOMORROW_MIDNIGHT_PAYLOAD = {
    "matches": [
        {
            "id": 4002,
            "title": "英超 联赛 第1轮",
            "status": 1,
            "match_time": int(datetime(2026, 8, 30, 0, 5, tzinfo=TZ).timestamp()),
            "home": {"name": "跨日主队"},
            "away": {"name": "跨日客队"},
            "com_info": {"name": "英超"},
        }
    ]
}
TODAY_LATE_SCRIPT = encode_saicheng_script(TODAY_LATE_PAYLOAD)
TOMORROW_MIDNIGHT_SCRIPT = encode_saicheng_script(TOMORROW_MIDNIGHT_PAYLOAD)


HTML = """
<html><body>
  <div data-match-index="1">
    <div class="list-title"><span>26/08/30 星期日</span></div>
    <a class="match-item" href="https://live.leisu.com/detail-1001">
      <div>14:05</div><div title="英超 联赛 第1轮">英超</div>
      <div><p><span>未</span></p></div>
      <div class="team first-team"><p title="阿森纳">阿森纳</p></div>
      <div>VS</div>
      <div class="team second-team"><p title="切尔西">切尔西</p></div>
    </a>
  </div>
  <div data-match-index="2">
    <a class="match-item" href="https://live.leisu.com/detail-1002">
      <div>14:10</div><div title="西甲 联赛 第1轮">西甲</div>
      <div><p><span>未</span></p></div>
      <div class="team first-team"><p title="巴塞罗那">巴塞罗那</p></div>
      <div>VS</div>
      <div class="team second-team"><p title="皇家马德里">皇家马德里</p></div>
    </a>
  </div>
  <div data-match-index="3">
    <a class="match-item" href="https://live.leisu.com/detail-1003">
      <div>14:00</div><div title="意甲 联赛 第1轮">意甲</div>
      <div><p><span>未</span></p></div>
      <div class="team first-team"><p title="国际米兰">国际米兰</p></div>
      <div>VS</div>
      <div class="team second-team"><p title="AC米兰">AC米兰</p></div>
    </a>
  </div>
  <div data-match-index="4">
    <a class="match-item" href="https://live.leisu.com/detail-1004">
      <div>14:00</div><div title="英冠 联赛 第1轮">英冠</div>
      <div><p><span>未</span></p></div>
      <div class="team first-team"><p title="利兹联">利兹联</p></div>
      <div>VS</div>
      <div class="team second-team"><p title="德比郡">德比郡</p></div>
    </a>
  </div>
  <div data-match-index="5">
    <a class="match-item" href="https://live.leisu.com/detail-1005">
      <div>14:00</div><div title="德甲 联赛 第1轮">德甲</div>
      <div><p><span>完</span></p></div>
      <div class="team first-team"><p title="拜仁">拜仁</p></div>
      <div>VS</div>
      <div class="team second-team"><p title="多特蒙德">多特蒙德</p></div>
    </a>
  </div>
  <div data-match-index="6">
    <a class="match-item" href="https://live.leisu.com/detail-1006">
      <div>14:00</div><div title="法甲 联赛 第1轮">法甲</div>
      <div><p><span>取消</span></p></div>
      <div class="team first-team"><p title="巴黎">巴黎</p></div>
      <div>VS</div>
      <div class="team second-team"><p title="里昂">里昂</p></div>
    </a>
  </div>
  <div data-match-index="7">
    <div class="list-title"><span>26/08/31 星期一</span></div>
    <a class="match-item" href="https://live.leisu.com/detail-1007">
      <div>14:00</div><div title="法甲 联赛 第2轮">法甲</div>
      <div><p><span>未</span></p></div>
      <div class="team first-team"><p title="马赛">马赛</p></div>
      <div>VS</div>
      <div class="team second-team"><p title="尼斯">尼斯</p></div>
    </a>
  </div>
</body></html>
"""


class FakeResponse:
    def __init__(self, payload=None, *, status=200, json_payload=None):
        self.text = payload or ""
        self.status_code = status
        self._json_payload = json_payload if json_payload is not None else {"errcode": 0}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_payload


class FakeSession:
    def __init__(
        self,
        html=HTML,
        webhook_payload=None,
        script_text=SAICHENG_SCRIPT,
        schedule_pages=None,
        scripts_by_referer=None,
    ):
        self.html = html
        self.webhook_payload = webhook_payload or {"errcode": 0}
        self.script_text = script_text
        self.schedule_pages = schedule_pages or {}
        self.scripts_by_referer = scripts_by_referer or {}
        self.gets = []
        self.posts = []

    def get(self, *args, **kwargs):
        self.gets.append((args, kwargs))
        url = str(args[0]) if args else ""
        if "/sc-" in url:
            headers = kwargs.get("headers") or {}
            return FakeResponse(self.scripts_by_referer.get(headers.get("Referer"), self.script_text))
        return FakeResponse(self.schedule_pages.get(url, self.html))

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse(json_payload=self.webhook_payload)


def make_config(state_file: Path, *, dry_run=False, source_url="https://www.leisu.com/") -> Config:
    reminder_minutes = {
        "英超": 10,
        "西甲": 10,
        "意甲": 10,
        "德甲": 10,
        "法甲": 10,
        "欧冠": 10,
        "葡超": 10,
        "美职联": 10,
        "墨超": 10,
        "荷甲": 10,
        "德乙": 10,
        "澳超": 10,
        "巴西甲": 10,
        "阿甲": 10,
        **{league: 10 for league in NATIONAL_TEAM_COMPETITIONS},
    }
    return Config(
        webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        source_url=source_url,
        timezone_name="Asia/Shanghai",
        timezone=TZ,
        before_minutes=9,
        after_minutes=11,
        league_reminder_minutes=reminder_minutes,
        league_windows={
            league: (max(0, minutes - 1), minutes + 1)
            for league, minutes in reminder_minutes.items()
        },
        state_file=state_file,
        cache_file=state_file.with_name("schedule_cache.json"),
        dry_run=dry_run,
        timeout_seconds=5,
        user_agent="test-agent",
        log_level="INFO",
    )


class ReminderTests(unittest.TestCase):
    def test_national_competitions_keep_specific_names_and_ten_minute_window(self):
        # Real Leisu competition labels, including distinct qualifier names.
        config = load_config({
            "DRY_RUN": "true", "MAJOR_REMINDER_MINUTES": "30",
            "ADDITIONAL_LEAGUE_REMINDER_MINUTES": "荷甲:10",
        })
        for label, expected in (
            ("欧国联", "欧国联"),
            ("世界杯", "世界杯"), ("世界杯附", "世预附加赛"),
            ("世欧预", "世欧预"), ("世亚预", "世亚预"),
            ("世南美预", "世南美预"), ("世非预", "世非预"),
            ("世中北美预", "世中北美预"), ("世大洋预", "世大洋预"),
            ("欧洲杯", "欧洲杯"), ("欧杯预", "欧洲杯预选赛"),
            ("亚洲杯", "亚洲杯"), ("亚洲杯预", "亚洲杯预选赛"),
            ("美洲杯", "美洲杯"), ("非洲杯", "非洲杯"),
            ("非洲杯预", "非洲杯预选赛"), ("美金杯", "金杯赛"),
            ("中北美国联", "中北美国联"), ("欧美杯", "欧美杯"),
        ):
            with self.subTest(label=label):
                row = {
                    **SAICHENG_PAYLOAD["matches"][0],
                    "title": f"{label} 小组赛 第1轮", "com_info": {"name": label},
                    "home": {"name": "法国", "position_fn": "FIFA 3"},
                    "away": {"name": "巴西", "position_fn": "FIFA 7"},
                    "match_time": int((NOW + timedelta(minutes=10)).timestamp()),
                }
                matches = parse_saicheng_payload(
                    {"matches": [row]}, source_url="https://live.leisu.com/saicheng",
                    now=NOW, tz=TZ,
                )
                self.assertEqual([match.league for match in matches], [expected])
                self.assertEqual(config.league_reminder_minutes[expected], 10)
                for lead, is_due in ((8, False), (9, True), (10, True), (11, True), (12, False)):
                    due = select_due_matches(
                        matches, now=matches[0].kickoff - timedelta(minutes=lead),
                        before_minutes=config.before_minutes, after_minutes=config.after_minutes,
                        league_windows=config.league_windows,
                    )
                    self.assertEqual(bool(due), is_due)
                content = build_markdown(matches, now=NOW, reminder_minutes=config.league_reminder_minutes)
                self.assertIn(f"## ⚽ {expected}赛前提醒", content)
                self.assertIn("法国 vs 巴西（提前10分钟）", content)

    def test_national_scope_excludes_youth_women_and_club_competitions(self):
        base = {
            **SAICHENG_PAYLOAD["matches"][0], "title": "世界杯 小组赛", "com_info": {"name": "世界杯"},
            "home": {"name": "法国"}, "away": {"name": "巴西"},
        }
        excluded = (
            {"home": {"name": "法国U21"}},
            {"away": {"name": "巴西 U-20"}},
            {"home": {"name": "法国女足"}},
            {"away": {"name": "Brazil Women"}},
            {"home": {"name": "中国国奥"}},
            {"title": "世界杯 U19 小组赛"},
            {"com_info": {"name": "世界杯 青年"}},
            {"com_info": {"name": "世界杯 女足"}},
            {"com_info": {"name": "球会友谊"}, "title": "球会友谊"},
            {"com_info": {"name": "世俱杯"}, "title": "世俱杯 小组赛"},
            {"com_info": {"name": "洲际杯"}, "title": "洲际杯"},
            {"com_info": {"name": "东盟锦标"}, "title": "东盟锦标"},
            {"com_info": {"name": "U20世界杯"}, "title": "世界杯 U20"},
            {"com_info": {"name": "女世界杯"}, "title": "世界杯 女足"},
        )
        for overrides in excluded:
            with self.subTest(overrides=overrides):
                matches = parse_saicheng_payload(
                    {"matches": [{**base, **overrides}]},
                    source_url="https://live.leisu.com/saicheng", now=NOW, tz=TZ,
                )
                self.assertEqual(matches, [])
        self.assertEqual(len(parse_saicheng_payload(
            {"matches": [base]}, source_url="https://live.leisu.com/saicheng", now=NOW, tz=TZ,
        )), 1)

    def test_national_html_parser_checks_team_names(self):
        html = HTML.replace("英超", "世界杯").replace("世界杯 联赛 第1轮", "世界杯 小组赛 第1轮")
        html = html.replace("阿森纳", "法国").replace("切尔西", "巴西")
        adult = parse_schedule_html(html, now=NOW, tz=TZ)
        self.assertEqual(next(match for match in adult if match.match_id == "1001").league, "世界杯")
        for marker in ("法国U20", "法国女足", "法国青年队"):
            with self.subTest(marker=marker):
                matches = parse_schedule_html(html.replace("法国", marker), now=NOW, tz=TZ)
                self.assertNotIn("1001", [match.match_id for match in matches])

    def test_national_matches_refresh_old_cache_notify_once_and_obey_quiet_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json", source_url="https://live.leisu.com/saicheng")
            row = {
                **SAICHENG_PAYLOAD["matches"][0], "title": "欧国联 小组赛 第1轮", "com_info": {"name": "欧国联"},
                "home": {"name": "法国", "position_fn": "FIFA 3"},
                "away": {"name": "德国", "position_fn": "FIFA 10"},
                "match_time": int((NOW + timedelta(minutes=10)).timestamp()),
            }
            config.cache_file.write_text(json.dumps({
                "version": 7, "source_url": config.source_url,
                "fetched_hour": NOW.replace(minute=0).isoformat(),
                "covered_dates": [NOW.date().isoformat()], "matches": [],
            }), encoding="utf-8")
            session = FakeSession(html=SAICHENG_PAGE, script_text=encode_saicheng_script({"matches": [row]}))
            self.assertEqual(run_once(config, now=NOW, session=session), 1)
            self.assertEqual(run_once(config, now=NOW + timedelta(seconds=30), session=session), 0)
            self.assertEqual(len(session.posts), 1)
            self.assertEqual(len(session.gets), 2)
            content = session.posts[0][1]["json"]["markdown"]["content"]
            self.assertIn("欧国联赛前提醒", content)
            self.assertIn("法国 vs 德国（提前10分钟）", content)
            _, cached_matches = load_schedule_cache(config.cache_file, tz=TZ, source_url=config.source_url)
            self.assertEqual([match.league for match in cached_matches], ["欧国联"])
            original_state = config.state_file.read_bytes()
            quiet_now = NOW.replace(hour=2, minute=0)
            quiet_match = replace(cached_matches[0], kickoff=quiet_now + timedelta(minutes=10))
            with patch("five_league_reminder.get_hourly_schedule", return_value=[quiet_match]):
                self.assertEqual(run_once(config, now=quiet_now, session=session), 0)
            self.assertEqual(len(session.posts), 1)
            self.assertEqual(config.state_file.read_bytes(), original_state)

    def test_low_priority_national_competitions_are_not_reminded_even_with_strong_teams(self):
        for label in (
            "国际友谊", "国际友谊赛", "海湾杯", "阿拉伯杯", "东亚杯", "东南锦",
            "大洋杯", "南亚锦", "西亚锦", "非国锦标", "南非联杯", "FIFA系列赛",
            "麒麟杯", "中国杯", "中国之队锦标赛",
        ):
            with self.subTest(label=label):
                row = {
                    **SAICHENG_PAYLOAD["matches"][0], "title": f"{label} 决赛", "com_info": {"name": label},
                    "home": {"name": "法国", "position_fn": "FIFA 3"},
                    "away": {"name": "巴西", "position_fn": "FIFA 7"},
                }
                self.assertEqual(parse_saicheng_payload(
                    {"matches": [row]}, source_url="https://live.leisu.com/saicheng", now=NOW, tz=TZ,
                ), [])

    def test_national_quality_checks_phase_and_explicit_fifa_rank_boundaries(self):
        for label, title, home_rank, away_rank, accepted in (
            ("非洲杯", "非洲杯 资格赛小组赛 第2轮", "FIFA 184", "FIFA 50", False),
            ("亚洲杯", "亚洲杯 预选赛小组赛 第2轮", "FIFA 30", "FIFA 50", True),
            ("非洲杯", "非洲杯 小组赛 第1轮", "FIFA 184", "FIFA 50", True),
            ("世界杯", "世界杯 小组赛 第1轮", "", "", True),
            ("欧洲杯", "欧洲杯 决赛", "", "", True),
            ("非洲杯", "非洲杯", "", "", False),
            ("世欧预", "世欧预 小组赛 第1轮", "FIFA 30", "FIFA 50", True),
            ("世欧预", "世欧预 小组赛 第1轮", "FIFA 31", "FIFA 50", False),
            ("世欧预", "世欧预 小组赛 第1轮", "FIFA 30", "FIFA 51", False),
            ("欧国联", "欧国联 A联赛 第2轮", "FIFA 20", "FIFA 40", True),
            ("欧国联", "欧国联 D联赛 第2轮", "FIFA 147", "FIFA 173", False),
            ("世亚预", "世亚预 第1轮", "", "FIFA 20", False),
            ("世亚预", "世亚预 第1轮", "土超 15", "FIFA 20", False),
            ("世亚预", "世亚预 第1轮", "15", "FIFA 20", False),
            ("世亚预", "世亚预 第1轮", "FIFA 0", "FIFA 20", False),
            ("世界杯附", "世界杯附 决赛", "FIFA 78", "FIFA 100", True),
        ):
            with self.subTest(label=label, title=title, ranks=(home_rank, away_rank)):
                row = {
                    **SAICHENG_PAYLOAD["matches"][0], "title": title, "com_info": {"name": label},
                    "home": {"name": "主队", "position_fn": home_rank},
                    "away": {"name": "客队", "position_fn": away_rank},
                }
                matches = parse_saicheng_payload(
                    {"matches": [row]}, source_url="https://live.leisu.com/saicheng", now=NOW, tz=TZ,
                )
                self.assertEqual(bool(matches), accepted)

    def test_quality_metadata_survives_cache_and_is_checked_before_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json")
            strong = Match(
                match_id="quality", league="欧国联", kickoff=NOW + timedelta(minutes=10),
                home_team="法国", away_team="德国", status="未", source_url="https://live.leisu.com/detail-1",
                competition_title="欧国联 A联赛 第2轮", home_fifa_rank=30, away_fifa_rank=50,
            )
            weak = replace(strong, match_id="weak", away_fifa_rank=51)
            save_schedule_cache(
                config.cache_file, fetched_hour=NOW.replace(minute=0), source_url=config.source_url,
                matches=[strong, weak],
            )
            _, matches = load_schedule_cache(config.cache_file, tz=TZ, source_url=config.source_url)
            self.assertEqual(matches, [strong])
            self.assertEqual(select_due_matches(
                [strong, weak], now=NOW, before_minutes=9, after_minutes=11,
            ), [strong])
            session = FakeSession()
            with patch("five_league_reminder.get_hourly_schedule", return_value=[weak]):
                self.assertEqual(run_once(config, now=NOW, session=session), 0)
            self.assertEqual(session.posts, [])
            self.assertFalse(config.state_file.exists())

    def test_new_competitions_and_source_aliases_are_parsed(self):
        config = load_config({"DRY_RUN": "true"})
        for label, expected in (
            ("欧冠", "欧冠"), ("欧冠杯", "欧冠"), ("葡超", "葡超"),
            ("美职联", "美职联"), ("美职业", "美职联"),
            ("美职足", "美职联"), ("墨超", "墨超"), ("墨西超", "墨超"),
        ):
            with self.subTest(label=label):
                row = {
                    **SAICHENG_PAYLOAD["matches"][0],
                    "title": f"{label} 联赛 第4轮",
                    "com_info": {"name": label},
                }
                matches = parse_saicheng_payload(
                    {"matches": [row]}, source_url="https://live.leisu.com/saicheng",
                    now=NOW, tz=TZ,
                )
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].league, expected)
                self.assertEqual(config.league_reminder_minutes[expected], 10)
                for minutes, due_expected in ((8, False), (9, True), (10, True), (11, True), (12, False)):
                    with self.subTest(minutes=minutes):
                        due = select_due_matches(
                            matches, now=matches[0].kickoff - timedelta(minutes=minutes),
                            before_minutes=9, after_minutes=11,
                            league_windows=config.league_windows,
                        )
                        self.assertEqual(bool(due), due_expected)

    def test_quiet_hours_boundaries_use_beijing_time(self):
        for hour, minute, second, expected in (
            (1, 59, 59, False), (2, 0, 0, True),
            (6, 59, 59, True), (7, 0, 0, False),
        ):
            local_now = NOW.replace(hour=hour, minute=minute, second=second)
            for instant in (local_now, local_now.astimezone(timezone.utc)):
                with self.subTest(instant=instant):
                    self.assertEqual(is_quiet_hours(instant), expected)

    def test_quiet_run_preserves_sent_state_without_posting(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json")
            # Even a display timezone override must retain Beijing quiet hours.
            config = replace(config, timezone_name="UTC", timezone=timezone.utc)
            quiet_now = NOW.replace(hour=2, minute=0).astimezone(timezone.utc)
            match = Match(
                match_id="quiet", league="美职联", kickoff=quiet_now + timedelta(minutes=10),
                home_team="静默主队", away_team="静默客队", status="未",
                source_url="https://live.leisu.com/detail-6001",
            )
            # An old entry would be pruned during a normal run; quiet mode must not rewrite it.
            save_sent_state(config.state_file, {"old:time": "2025-01-01T00:00:00+08:00"})
            original_bytes = config.state_file.read_bytes()
            session = FakeSession()
            with patch("five_league_reminder.get_hourly_schedule", return_value=[match]):
                self.assertEqual(run_once(config, now=quiet_now, session=session), 0)
            self.assertEqual(session.posts, [])
            self.assertEqual(config.state_file.read_bytes(), original_bytes)

    def test_quiet_run_collects_schedule_without_creating_sent_state(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json")
            session = FakeSession(html=HTML.replace("14:00", "02:10"))
            self.assertEqual(run_once(config, now=NOW.replace(hour=2, minute=0), session=session), 0)
            self.assertTrue(session.gets)
            self.assertTrue(config.cache_file.exists())
            self.assertEqual(session.posts, [])
            self.assertFalse(config.state_file.exists())

    def test_clock_entering_quiet_hours_during_check_blocks_send(self):
        before = NOW.replace(hour=1, minute=59, second=59)
        after = NOW.replace(hour=2, minute=0, second=0)
        match = Match(
            match_id="crossing", league="欧冠", kickoff=after + timedelta(minutes=10),
            home_team="跨界主队", away_team="跨界客队", status="未",
            source_url="https://live.leisu.com/detail-6003",
        )
        # Cover both network delay and work performed immediately before sending.
        for clock_values in ([before, after], [before, before, after]):
            with self.subTest(clock_values=clock_values), tempfile.TemporaryDirectory() as directory:
                config = make_config(Path(directory) / "sent.json")
                session = FakeSession()
                with patch("five_league_reminder.get_hourly_schedule", return_value=[match]), \
                        patch("five_league_reminder.datetime", wraps=datetime) as clock:
                    clock.now.side_effect = clock_values
                    self.assertEqual(run_once(config, session=session), 0)
                self.assertEqual(session.posts, [])
                self.assertFalse(config.state_file.exists())

    def test_explicit_test_message_obeys_quiet_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json")
            session = FakeSession()
            with patch("five_league_reminder.datetime", wraps=datetime) as clock:
                clock.now.return_value = NOW.replace(hour=3, minute=0)
                _send_test_message(config, session)
            self.assertEqual(session.posts, [])

    def test_seven_am_resumes_normal_window_without_backlog_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json")
            resume_now = NOW.replace(hour=7, minute=0)
            expired = Match(
                match_id="expired", league="墨超", kickoff=resume_now + timedelta(minutes=5),
                home_team="过期主队", away_team="过期客队", status="未",
                source_url="https://live.leisu.com/detail-6002",
            )
            due = replace(expired, match_id="due", kickoff=resume_now + timedelta(minutes=10),
                          home_team="恢复主队", away_team="恢复客队")
            session = FakeSession()
            with patch("five_league_reminder.get_hourly_schedule", return_value=[expired, due]):
                self.assertEqual(run_once(config, now=resume_now - timedelta(minutes=10), session=session), 0)
                self.assertEqual(run_once(config, now=resume_now - timedelta(seconds=1), session=session), 0)
                self.assertEqual(session.posts, [])
                self.assertFalse(config.state_file.exists())
                self.assertEqual(run_once(config, now=resume_now, session=session), 1)
                self.assertEqual(run_once(config, now=resume_now + timedelta(seconds=30), session=session), 0)
            self.assertEqual(len(session.posts), 1)
            content = session.posts[0][1]["json"]["markdown"]["content"]
            self.assertIn("恢复主队", content)
            self.assertNotIn("过期主队", content)
            self.assertEqual(set(load_sent_state(config.state_file)), {due.notification_key})

    def test_bundesliga_two_parse_and_reminder_window(self):
        from datetime import timedelta
        config = load_config({"DRY_RUN": "true"})
        matches = parse_schedule_html(
            HTML.replace("英超", "德乙"),
            source_url="https://www.leisu.com/", now=NOW, tz=TZ,
        )
        match = next(match for match in matches if match.league == "德乙")
        for minutes, expected in ((8, False), (9, True), (10, True), (11, True), (12, False), (30, False)):
            with self.subTest(minutes=minutes):
                due = select_due_matches(
                    [match], now=match.kickoff - timedelta(minutes=minutes),
                    before_minutes=9, after_minutes=11,
                    league_windows=config.league_windows,
                )
                self.assertEqual(bool(due), expected)

    def test_daily_source_url_uses_local_date(self):
        self.assertEqual(
            build_daily_source_url("https://live.leisu.com/saicheng", NOW.date()),
            "https://live.leisu.com/saicheng-20260830",
        )

    def test_decode_and_parse_saicheng_payload(self):
        self.assertEqual(_decode_js_unescape("%u963F%u7F57%20-%20%u9A6C"), "阿罗 - 马")
        payload = decode_saicheng_payload(SAICHENG_SCRIPT)
        matches = parse_saicheng_payload(
            payload,
            source_url="https://live.leisu.com/saicheng-20260829",
            now=datetime(2026, 8, 29, 22, 18, tzinfo=TZ),
            tz=TZ,
        )
        self.assertEqual([match.match_id for match in matches], ["3001", "3002", "3003"])
        self.assertEqual(matches[0].league, "葡超")
        self.assertEqual(matches[2].home_team, "SBV精英")
        self.assertEqual(matches[0].kickoff.strftime("%H:%M"), "22:30")

    def test_unsupported_league_is_ignored_and_windows_are_narrow(self):
        matches = parse_saicheng_payload(
            SAICHENG_PAYLOAD,
            source_url="https://live.leisu.com/saicheng-20260829",
            now=datetime(2026, 8, 29, 22, 18, tzinfo=TZ),
            tz=TZ,
        )
        self.assertNotIn("英冠", [match.league for match in matches])
        due = select_due_matches(
            matches,
            now=datetime(2026, 8, 29, 22, 0, tzinfo=TZ),
            before_minutes=9,
            after_minutes=11,
            league_windows={"荷甲": (29, 31)},
        )
        self.assertEqual([match.match_id for match in due], ["3003"])

    def test_major_window_uses_target_with_one_minute_tolerance(self):
        matches = [
            Match(
                match_id="3006",
                league="法甲",
                kickoff=datetime(2026, 8, 29, 23, 10, tzinfo=TZ),
                home_team="斯特拉斯堡",
                away_team="朗斯",
                status="未",
                source_url="https://live.leisu.com/detail-3006",
            ),
            Match(
                match_id="3007",
                league="法甲",
                kickoff=datetime(2026, 8, 29, 23, 8, tzinfo=TZ),
                home_team="已开赛主队",
                away_team="已开赛客队",
                status="未",
                source_url="https://live.leisu.com/detail-3007",
            ),
        ]
        due = select_due_matches(
            matches,
            now=datetime(2026, 8, 29, 23, 0, tzinfo=TZ),
            before_minutes=9,
            after_minutes=11,
        )
        self.assertEqual([match.match_id for match in due], ["3006"])

    def test_logs_current_hour_schedule(self):
        matches = parse_saicheng_payload(
            SAICHENG_PAYLOAD,
            source_url="https://live.leisu.com/saicheng-20260829",
            now=datetime(2026, 8, 29, 22, 18, tzinfo=TZ),
            tz=TZ,
        )
        with self.assertLogs("five_league_reminder", level="INFO") as logs:
            log_current_hour_schedule(
                matches,
                now=datetime(2026, 8, 29, 22, 18, tzinfo=TZ),
            )
        self.assertIn("本小时赛程（3 场）", logs.output[0])
        self.assertIn("SBV精英 vs 鹿特丹斯巴达", logs.output[0])

    def test_parse_filters_leagues_and_statuses(self):
        matches = parse_schedule_html(HTML, now=NOW, tz=TZ)
        self.assertEqual([match.match_id for match in matches], ["1003", "1001", "1002", "1007"])
        self.assertEqual(matches[0].league, "意甲")
        self.assertEqual(matches[0].kickoff.tzinfo, TZ)
        self.assertEqual(matches[1].home_team, "阿森纳")
        self.assertEqual(matches[2].source_url, "https://live.leisu.com/detail-1002")

    def test_parse_fails_when_structure_has_no_rows(self):
        with self.assertRaises(ScheduleParseError):
            parse_schedule_html("<html><body>没有赛程</body></html>", now=NOW, tz=TZ)

    def test_time_window_includes_boundaries(self):
        matches = parse_schedule_html(HTML, now=NOW, tz=TZ)
        due = select_due_matches(matches, now=NOW, before_minutes=10, after_minutes=20)
        self.assertEqual(len(due), 3)
        self.assertEqual(due[0].kickoff.strftime("%H:%M"), "14:00")
        self.assertEqual(due[-1].kickoff.strftime("%H:%M"), "14:10")

    def test_additional_league_uses_its_own_window(self):
        dutch_match = Match(
            match_id="2001",
            league="荷甲",
            kickoff=datetime(2026, 8, 30, 14, 20, tzinfo=TZ),
            home_team="阿贾克斯",
            away_team="埃因霍温",
            status="未",
            source_url="https://live.leisu.com/detail-2001",
        )
        short_window_match = Match(
            match_id="2002",
            league="澳超",
            kickoff=datetime(2026, 8, 30, 14, 0, tzinfo=TZ),
            home_team="悉尼FC",
            away_team="墨尔本城",
            status="未",
            source_url="https://live.leisu.com/detail-2002",
        )
        due = select_due_matches(
            [dutch_match, short_window_match],
            now=NOW,
            before_minutes=9,
            after_minutes=11,
            league_windows={"荷甲": (29, 31), "澳超": (9, 11)},
        )
        self.assertEqual([match.match_id for match in due], ["2002", "2001"])

    def test_markdown_combines_matches(self):
        matches = parse_schedule_html(HTML, now=NOW, tz=TZ)
        due = select_due_matches(matches, now=NOW, before_minutes=10, after_minutes=20)
        content = build_markdown(
            due,
            now=NOW,
            reminder_minutes={"意甲": 10, "英超": 10, "西甲": 10},
        )
        self.assertIn("## ⚽ 意甲、英超、西甲赛前提醒", content)
        self.assertIn("阿森纳 vs 切尔西", content)
        self.assertNotIn("查看比赛", content)
        self.assertNotIn("live.leisu.com", content)
        self.assertIn("提前10分钟", content)
        self.assertNotIn("约提前", content)
        self.assertNotIn("检查时间", content)
        self.assertNotIn("以下比赛", content)

    def test_markdown_single_league_uses_specific_title(self):
        match = Match(
            match_id="2003",
            league="荷甲",
            kickoff=datetime(2026, 8, 30, 14, 20, tzinfo=TZ),
            home_team="阿贾克斯",
            away_team="埃因霍温",
            status="未",
            source_url="https://live.leisu.com/detail-2003",
        )
        content = build_markdown(
            [match],
            now=NOW,
            reminder_minutes={"荷甲": 30},
        )
        self.assertIn("## ⚽ 荷甲赛前提醒", content)
        self.assertIn("- 08-30 14:20　阿贾克斯 vs 埃因霍温（提前30分钟）", content)

    def test_config_uses_configured_targets_with_one_minute_tolerance(self):
        config = load_config(
            {
                "DRY_RUN": "true",
                "MAJOR_REMINDER_MINUTES": "10",
                "ADDITIONAL_LEAGUE_REMINDER_MINUTES": "荷甲:30,澳超:10,巴西甲:10,阿甲:10",
            }
        )
        self.assertEqual(set(config.league_reminder_minutes), set(LEAGUES))
        for league in ("欧冠", "葡超", "美职联", "墨超"):
            self.assertEqual(config.league_reminder_minutes[league], 10)
            self.assertEqual(config.league_windows[league], (9, 11))
        self.assertEqual(config.league_reminder_minutes["荷甲"], 30)
        self.assertEqual(config.league_windows["荷甲"], (29, 31))
        self.assertEqual(config.league_windows["德乙"], (9, 11))
        self.assertEqual(config.league_windows["英超"], (9, 11))

    def test_cache_filters_removed_leagues(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule_cache.json"
            fetched_hour = datetime(2026, 8, 30, 22, 0, tzinfo=TZ)
            active_match = Match(
                match_id="2004",
                league="英超",
                kickoff=datetime(2026, 8, 30, 23, 0, tzinfo=TZ),
                home_team="曼联",
                away_team="切尔西",
                status="未",
                source_url="https://live.leisu.com/detail-2004",
            )
            removed_match = Match(
                match_id="2005",
                league="英冠",
                kickoff=datetime(2026, 8, 30, 23, 0, tzinfo=TZ),
                home_team="波尔图",
                away_team="本菲卡",
                status="未",
                source_url="https://live.leisu.com/detail-2005",
            )
            save_schedule_cache(
                path,
                fetched_hour=fetched_hour,
                source_url="https://live.leisu.com/saicheng",
                matches=[active_match, removed_match],
            )
            _, matches = load_schedule_cache(
                path,
                tz=TZ,
                source_url="https://live.leisu.com/saicheng",
            )
            self.assertEqual([match.match_id for match in matches], ["2004"])

    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sent.json"
            save_sent_state(path, {"1001:time": "2026-08-30T13:50:00+08:00"})
            self.assertEqual(load_sent_state(path)["1001:time"], "2026-08-30T13:50:00+08:00")

    def test_run_once_reuses_hourly_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json", dry_run=True)
            session = FakeSession()
            run_once(config, now=NOW, session=session)
            run_once(config, now=NOW.replace(minute=51), session=session)
            self.assertEqual(len(session.gets), 1)

    def test_saicheng_refresh_replaces_old_cache_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(
                Path(directory) / "sent.json",
                source_url="https://live.leisu.com/saicheng",
            )
            config.cache_file.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "source_url": "https://www.leisu.com/",
                        "fetched_hour": "2026-08-29T22:00:00+08:00",
                        "matches": [],
                    }
                ),
                encoding="utf-8",
            )
            session = FakeSession(html=SAICHENG_PAGE)
            now = datetime(2026, 8, 29, 22, 18, tzinfo=TZ)
            self.assertEqual(run_once(config, now=now.replace(minute=20), session=session), 3)
            self.assertEqual(len(session.gets), 2)
            script_request_url = session.gets[1][0][0]
            self.assertIn("/sc-test.js?refresh=", script_request_url)
            self.assertNotIn("??", script_request_url)
            cached = json.loads(config.cache_file.read_text(encoding="utf-8"))
            self.assertEqual(cached["version"], SCHEDULE_CACHE_VERSION)
            self.assertEqual(cached["source_url"], "https://live.leisu.com/saicheng")
            self.assertEqual(run_once(config, now=now.replace(minute=20, second=30), session=session), 0)
            self.assertEqual(len(session.gets), 2)

    def test_23_hour_prefetches_tomorrow_and_logs_next_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(
                Path(directory) / "sent.json",
                source_url="https://live.leisu.com/saicheng",
            )
            today_url = "https://live.leisu.com/saicheng-20260829"
            tomorrow_url = "https://live.leisu.com/saicheng-20260830"
            session = FakeSession(
                html=SAICHENG_PAGE,
                schedule_pages={today_url: SAICHENG_PAGE, tomorrow_url: SAICHENG_PAGE},
                scripts_by_referer={
                    today_url: TODAY_LATE_SCRIPT,
                    tomorrow_url: TOMORROW_MIDNIGHT_SCRIPT,
                },
            )
            now = datetime(2026, 8, 29, 23, 55, tzinfo=TZ)
            with self.assertLogs("five_league_reminder", level="INFO") as logs:
                self.assertEqual(run_once(config, now=now, session=session), 1)

            self.assertEqual(len(session.gets), 4)
            self.assertEqual(len(session.posts), 1)
            cache = json.loads(config.cache_file.read_text(encoding="utf-8"))
            self.assertEqual(cache["covered_dates"], ["2026-08-29", "2026-08-30"])
            self.assertTrue(any("下小时赛程（1 场）" in line for line in logs.output))
            self.assertTrue(any("跨日主队 vs 跨日客队" in line for line in logs.output))

    def test_run_once_sends_once_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json")
            session = FakeSession()
            self.assertEqual(run_once(config, now=NOW, session=session), 1)
            self.assertEqual(len(session.posts), 1)
            self.assertEqual(run_once(config, now=NOW, session=session), 0)
            self.assertEqual(len(session.posts), 1)

    def test_failed_webhook_does_not_mark_matches_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json")
            session = FakeSession(webhook_payload={"errcode": 40001, "errmsg": "bad"})
            with self.assertRaises(WeComError):
                run_once(config, now=NOW, session=session)
            self.assertFalse(config.state_file.exists())

    def test_dry_run_does_not_send_or_write_state(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config(Path(directory) / "sent.json", dry_run=True)
            session = FakeSession()
            self.assertEqual(run_once(config, now=NOW, session=session), 0)
            self.assertEqual(session.posts, [])
            self.assertFalse(config.state_file.exists())

    def test_wecom_requires_success_code(self):
        session = FakeSession(webhook_payload={"errcode": 0})
        send_wecom_markdown(
            session,
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
            content="test",
            timeout_seconds=5,
        )
        self.assertEqual(len(session.posts), 1)


if __name__ == "__main__":
    unittest.main()
