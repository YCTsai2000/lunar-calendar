#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
農曆初一/十五 行事曆產生器（GitHub Actions 版）
"""

import argparse
import datetime
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
    _cc = OpenCC("s2twp")  # 簡體 -> 台灣正體（含慣用詞轉換）
except ImportError:
    sys.exit(
        "找不到 opencc-python-reimplemented 套件，請先執行：\n"
        "    pip install opencc-python-reimplemented --break-system-packages\n"
    )


def to_traditional(text: str) -> str:
    return _cc.convert(text)


CN_MONTH_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]


def ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold_line(line: str, limit: int = 75) -> str:
    line_bytes = line.encode("utf-8")
    if len(line_bytes) <= limit:
        return line

    chunks = []
    current = b""
    for ch in line:
        ch_bytes = ch.encode("utf-8")
        if len(current) + len(ch_bytes) > limit:
            chunks.append(current)
            current = b""
        current += ch_bytes
    if current:
        chunks.append(current)

    folded = chunks[0].decode("utf-8")
    for chunk in chunks[1:]:
        folded += "\r\n " + chunk.decode("utf-8")
    return folded


def get_lucky_hours(lunar) -> str:
    seen = []
    for t in lunar.getTimes():
        zhi = t.getZhi()
        if t.getTianShenLuck() == "吉" and zhi not in seen:
            seen.append(zhi)
    return "、".join(seen) if seen else "無"


def build_event(solar_date: datetime.date, uid_prefix: str, now_stamp: str) -> str:
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
    uid = f"{uid_prefix}{dtstart}@lunar-calendar-script"

    lines = [
        "BEGIN:VEVENT",
        f"DTSTART;VALUE=DATE:{dtstart}",
        f"DTEND;VALUE=DATE:{dtend}",
        f"DTSTAMP:{now_stamp}",
        f"UID:{uid}",
        f"CREATED:{now_stamp}",
        f"DESCRIPTION:{ics_escape(description)}",
        f"LAST-MODIFIED:{now_stamp}",
        "SEQUENCE:0",
        "STATUS:CONFIRMED",
        f"SUMMARY:{ics_escape(summary)}",
        "TRANSP:OPAQUE",
        "END:VEVENT",
    ]
    return "\r\n".join(fold_line(l) for l in lines)


def generate_year_events(year: int, now_stamp: str):
    events = []
    start = datetime.date(year, 1, 1)
    end = datetime.date(year, 12, 31)
    day = start
    while day <= end:
        solar = Solar.fromYmd(day.year, day.month, day.day)
        lunar = solar.getLunar()
        if lunar.getDay() in (1, 15):
            events.append(build_event(day, "LunarCal", now_stamp))
        day += datetime.timedelta(days=1)
    return events


def main():
    parser = argparse.ArgumentParser(description="產生農曆初一/十五的 .ics 行事曆檔")
    parser.add_argument("--year", type=int, help="只產生單一年份（西曆）")
    parser.add_argument("--years-ahead", type=int, default=3,
                         help="從今年起產生連續 N 年（預設 3 年，含今年）")
    parser.add_argument("--output", type=str, default="docs/lunar.ics",
                         help="輸出檔案路徑（預設 docs/lunar.ics，供 GitHub Pages 使用）")
    args = parser.parse_args()

    this_year = datetime.date.today().year

    if args.year:
        target_years = [args.year]
    else:
        target_years = list(range(this_year, this_year + args.years_ahead))

    now_stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    all_events = []
    for y in target_years:
        all_events.extend(generate_year_events(y, now_stamp))

    calname = f"農曆初一/十五（{target_years[0]}-{target_years[-1]}，自動更新）"

    body = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "PRODID:-//LunarCalendarScript//Generate 1.0//EN",
            "VERSION:2.0",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{calname}",
            "X-WR-TIMEZONE:Asia/Taipei",
            "REFRESH-INTERVAL;VALUE=DURATION:P1D",
            "X-PUBLISHED-TTL:P1D",
        ]
    )
    body += "\r\n" + "\r\n".join(all_events)
    body += "\r\nEND:VCALENDAR\r\n"

    import os
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8", newline="") as f:
        f.write(body)

    print(f"已產生 {len(all_events)} 個事件 -> {args.output}")
    print(f"涵蓋年份：{', '.join(str(y) for y in target_years)}")


if __name__ == "__main__":
    main()
