#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
農曆初一/十五 —— 直接寫入 iCloud 行事曆版（CalDAV）
"""

import argparse
import datetime
import os
import sys

try:
    from lunar_python import Solar
except ImportError:
    sys.exit(
        "找不到 lunar_python 套件，請先執行：\n"
        "    pip install lunar_python --break-system-packages\n"
    )

try:
    from opencc import OpenCC
    _cc = OpenCC("s2twp")
except ImportError:
    sys.exit(
        "找不到 opencc-python-reimplemented 套件，請先執行：\n"
        "    pip install opencc-python-reimplemented --break-system-packages\n"
    )

try:
    import caldav
except ImportError:
    sys.exit(
        "找不到 caldav 套件，請先執行：\n"
        "    pip install caldav --break-system-packages\n"
    )


ICLOUD_URL = "https://caldav.icloud.com/"
UID_PREFIX = "lunarcal-"

CN_MONTH_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]


def to_traditional(text: str) -> str:
    return _cc.convert(text)


def ics_escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def get_lucky_hours(lunar) -> str:
    seen = []
    for t in lunar.getTimes():
        zhi = t.getZhi()
        if t.getTianShenLuck() == "吉" and zhi not in seen:
            seen.append(zhi)
    return "、".join(seen) if seen else "無"


def build_ics_for_event(solar_date: datetime.date, alarm_hours_before: int, now_stamp: str):
    """回傳 (uid, 這個事件的完整單一 VCALENDAR ics 文字)。"""
    solar = Solar.fromYmd(solar_date.year, solar_date.month, solar_date.day)
    lunar = solar.getLunar()

    yi = to_traditional("、".join(lunar.getDayYi()) or "無")
    ji = to_traditional("、".join(lunar.getDayJi()) or "無")
    chong = to_traditional(lunar.getDayChongDesc())
    sha = to_traditional(lunar.getDaySha())
    lucky_hours = get_lucky_hours(lunar)

    description = "\n".join(
        [
            f"宜：{yi}",
            f"忌：{ji}",
            f"沖：{chong}",
            f"煞：{sha}",
            f"吉時：{lucky_hours}",
        ]
    )

    raw_month = lunar.getMonth()
    is_leap = raw_month < 0
    month_num = abs(raw_month)
    month_cn = ("閏" if is_leap else "") + CN_MONTH_NUM[month_num - 1]
    day_cn = lunar.getDayInChinese()
    summary = f"農曆：{month_cn}月{day_cn}"

    dtstart = solar_date.strftime("%Y%m%d")
    dtend = (solar_date + datetime.timedelta(days=1)).strftime("%Y%m%d")
    uid = f"{UID_PREFIX}{dtstart}@lunar-calendar-script"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//LunarCalendarScript//iCloud 1.0//EN",
        "BEGIN:VEVENT",
        f"DTSTART;VALUE=DATE:{dtstart}",
        f"DTEND;VALUE=DATE:{dtend}",
        f"DTSTAMP:{now_stamp}",
        f"UID:{uid}",
        f"SUMMARY:{ics_escape(summary)}",
        f"DESCRIPTION:{ics_escape(description)}",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{ics_escape(summary)}",
        f"TRIGGER:-PT{alarm_hours_before}H",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return uid, "\r\n".join(lines) + "\r\n"


def generate_year_dates(year: int):
    start = datetime.date(year, 1, 1)
    end = datetime.date(year, 12, 31)
    day = start
    while day <= end:
        solar = Solar.fromYmd(day.year, day.month, day.day)
        lunar = solar.getLunar()
        if lunar.getDay() in (1, 15):
            yield day
        day += datetime.timedelta(days=1)


def get_or_create_calendar(principal, calendar_name: str):
    for cal in principal.calendars():
        if cal.name == calendar_name:
            return cal
    print(f"找不到「{calendar_name}」，自動建立新的行事曆...")
    return principal.make_calendar(name=calendar_name)


def main():
    parser = argparse.ArgumentParser(description="把農曆初一/十五直接寫進 iCloud 行事曆")
    parser.add_argument("--years-ahead", type=int, default=3, help="從今年起產生連續 N 年（預設3年）")
    parser.add_argument(
        "--alarm-hours-before", type=int, default=5,
        help="提醒設在事件前幾小時。事件本身視為當天凌晨00:00，"
             "所以預設5小時＝前一天晚上7點（跟你之前確認過的時間一致）。",
    )
    args = parser.parse_args()

    apple_id = os.environ.get("ICLOUD_APPLE_ID")
    app_password = os.environ.get("ICLOUD_APP_PASSWORD")
    calendar_name = os.environ.get("CALENDAR_NAME", "農曆行事曆")

    if not apple_id or not app_password:
        sys.exit("[錯誤] 缺少 ICLOUD_APPLE_ID 或 ICLOUD_APP_PASSWORD 環境變數")

    print(f"正在連線到 iCloud（{apple_id}）...")
    client = caldav.DAVClient(url=ICLOUD_URL, username=apple_id, password=app_password)
    principal = client.principal()

    target = get_or_create_calendar(principal, calendar_name)
    print(f"使用行事曆：{target.name}")

    print("正在讀取行事曆裡既有的事件...")
    existing = {}
    for ev in target.events():
        try:
            uid = str(ev.icalendar_component.get("UID"))
        except Exception:
            continue
        if uid.startswith(UID_PREFIX):
            existing[uid] = ev
    print(f"既有事件（本程式建立的）：{len(existing)} 筆")

    this_year = datetime.date.today().year
    target_years = list(range(this_year, this_year + args.years_ahead))
    now_stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    desired = {}
    for y in target_years:
        for d in generate_year_dates(y):
            uid, ics_text = build_ics_for_event(d, args.alarm_hours_before, now_stamp)
            desired[uid] = ics_text

    created = updated = unchanged = deleted = 0

    for uid, ics_text in desired.items():
        if uid in existing:
            old_data = existing[uid].data or ""
            if _content_changed(old_data, ics_text):
                existing[uid].data = ics_text
                existing[uid].save()
                updated += 1
            else:
                unchanged += 1
        else:
            target.save_event(ics_text)
            created += 1

    for uid, ev in existing.items():
        if uid not in desired:
            ev.delete()
            deleted += 1

    print(f"完成：新增 {created}，更新 {updated}，不變 {unchanged}，清除 {deleted}")


def _content_changed(old_ics: str, new_ics: str) -> bool:
    def strip_dtstamp(text):
        return "\n".join(line for line in text.splitlines() if not line.startswith("DTSTAMP"))

    return strip_dtstamp(old_ics).strip() != strip_dtstamp(new_ics).strip()


if __name__ == "__main__":
    main()
