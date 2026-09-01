# -*- coding: utf-8 -*-
"""반복 일정 규칙 엔진.

규칙은 [주기] × [기준] 의 조합으로 표현한다.

    period : "day" | "week" | "month" | "quarter"
    basis  : "day" | "business_day" | "weekday" | "before_end" | "before_end_bd"
             (month / quarter 주기에서만 사용)

    day     : business_only
    week    : weekdays[], interval, anchor
    month   : basis + (n | weekday | k), months[]  ← 실행할 월 제한
    quarter : basis + (n | weekday | k)            ← 달력 분기(1·4·7·10월 시작)

    holiday_shift : "none" | "prev" | "next"   (기본 prev — 회사 일정은 영업일 기준)
"""
from datetime import date, timedelta
import calendar

# 대한민국 공휴일(양력 확정분). data.json 의 holidays 로 추가할 수 있다.
DEFAULT_HOLIDAYS = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01", "2026-03-02",
    "2026-05-05", "2026-05-24", "2026-05-25", "2026-06-03", "2026-06-06", "2026-08-15",
    "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-05",
    "2026-10-09", "2026-12-25",
    "2027-01-01", "2027-02-06", "2027-02-07", "2027-02-08", "2027-02-09", "2027-03-01",
    "2027-05-05", "2027-05-13", "2027-06-06", "2027-06-07", "2027-08-15", "2027-08-16",
    "2027-09-14", "2027-09-15", "2027-09-16", "2027-10-03", "2027-10-04", "2027-10-09",
    "2027-10-11", "2027-12-25",
}
HOLIDAYS = set(DEFAULT_HOLIDAYS)
W = "월화수목금토일"
ALL_MONTHS = list(range(1, 13))


def set_holidays(extra):
    HOLIDAYS.clear()
    HOLIDAYS.update(DEFAULT_HOLIDAYS)
    HOLIDAYS.update(extra or [])


def is_business_day(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def next_business_day(d, forward=True):
    step = 1 if forward else -1
    cur = d
    for _ in range(30):
        if is_business_day(cur):
            return cur
        cur += timedelta(days=step)
    return d


def _span_days(d0, d1):
    out, d = [], d0
    while d <= d1:
        out.append(d)
        d += timedelta(days=1)
    return out


def _shift(d, mode):
    if mode == "none" or is_business_day(d):
        return d
    return next_business_day(d, forward=(mode == "next"))


# ---------- 예전 규칙 형식 → 현재 형식 ----------
def normalize(rule):
    r = dict(rule or {})
    if "period" not in r:
        k = r.pop("kind", "daily")
        if k == "daily":
            r["period"] = "day"
        elif k == "weekly":
            r["period"] = "week"
        elif k == "yearly":
            r.update(period="month", basis="day", n=r.get("day", 1),
                     months=[int(r.get("month", 1))])
        elif k == "quarterly_day":
            r.update(period="month", basis="day", n=r.get("day", 1),
                     months=[int(x) for x in r.get("months", [3, 6, 9, 12])])
        else:
            r["period"] = "month"
            r["basis"] = {"monthly_day": "day",
                          "monthly_business_day": "business_day",
                          "monthly_weekday": "weekday",
                          "before_month_end": "before_end",
                          "before_month_end_bd": "before_end_bd"}.get(k, "day")
            if r["basis"] == "day":
                r["n"] = r.get("day", 1)
    r.setdefault("holiday_shift", "prev")
    if r.get("period") == "day":
        r.setdefault("business_only", True)
    return r


# ---------- 기준 계산 ----------
def _by_basis(r, d0, d1):
    """주기 구간 [d0, d1] 안에서 기준에 맞는 날짜 하나."""
    basis = r.get("basis", "day")
    days = _span_days(d0, d1)
    bd = [d for d in days if is_business_day(d)]

    if basis == "day":
        n = int(r.get("n", 1))
        idx = n - 1 if n > 0 else len(days) + n
        return days[idx] if 0 <= idx < len(days) else None

    if basis == "business_day":
        n = int(r.get("n", 1))
        idx = n - 1 if n > 0 else len(bd) + n
        return bd[idx] if 0 <= idx < len(bd) else None

    if basis == "weekday":
        n = int(r.get("n", 1))
        wd = int(r.get("weekday", 0))
        hit = [d for d in days if d.weekday() == wd]
        idx = n - 1 if n > 0 else len(hit) + n
        return hit[idx] if 0 <= idx < len(hit) else None

    if basis == "before_end":
        k = int(r.get("k", 0))
        idx = len(days) - 1 - k
        return days[idx] if 0 <= idx < len(days) else None

    if basis == "before_end_bd":
        k = int(r.get("k", 0))
        idx = len(bd) - 1 - k
        return bd[idx] if 0 <= idx < len(bd) else None

    return None


def _month_span(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _quarter_span(y, q):     # q = 0..3  →  1·4·7·10월 시작
    sm = q * 3 + 1
    em = sm + 2
    return date(y, sm, 1), date(y, em, calendar.monthrange(y, em)[1])


# ---------- 날짜 생성 ----------
def occurrences(rule, start, end):
    r = normalize(rule)
    period = r.get("period", "day")
    shift = r.get("holiday_shift", "prev")
    out = []

    if period == "day":
        for d in _span_days(start, end):
            if not r.get("business_only", True) or is_business_day(d):
                out.append(d)
        return out

    if period == "week":
        wd = set(r.get("weekdays") or [])
        every = max(1, int(r.get("interval", 1)))
        anchor = date.fromisoformat(r["anchor"]) if r.get("anchor") else start
        a_mon = anchor - timedelta(days=anchor.weekday())
        for d in _span_days(start, end):
            if d.weekday() in wd:
                weeks = ((d - timedelta(days=d.weekday())) - a_mon).days // 7
                if every == 1 or weeks % every == 0:
                    out.append(_shift(d, shift))
        return sorted(set(out))

    if period == "quarter":
        y = start.year
        while date(y, 1, 1) <= end + timedelta(days=370):
            for q in range(4):
                d0, d1 = _quarter_span(y, q)
                if d1 < start or d0 > end + timedelta(days=95):
                    continue
                d = _by_basis(r, d0, d1)
                if d:
                    d = _shift(d, shift)
                    if start <= d <= end:
                        out.append(d)
            y += 1
        return sorted(set(out))

    # month
    months = set(int(x) for x in (r.get("months") or ALL_MONTHS))
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        if m in months:
            d = _by_basis(r, *_month_span(y, m))
            if d:
                d = _shift(d, shift)
                if start <= d <= end:
                    out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return sorted(set(out))


# ---------- 설명 문구 ----------
def _basis_text(r, q=False):
    """q=True 면 분기 주기용 문구."""
    basis = r.get("basis", "day")
    n = int(r.get("n", 1))
    k = int(r.get("k", 0))
    if basis == "day":
        if n == -1:
            return "마지막 날" if q else "말일"
        return f"{n}일째" if q else f"{n}일"
    if basis == "business_day":
        return "마지막 영업일" if n == -1 else f"{n}번째 영업일"
    if basis == "weekday":
        wd = W[int(r.get("weekday", 0))]
        return f"마지막 {wd}요일" if n == -1 else f"{n}번째 {wd}요일"
    if basis == "before_end":
        if k == 0:
            return "마지막 날" if q else "말일"
        return f"말 {k}일 전"
    if basis == "before_end_bd":
        if k == 0:
            return "마지막 영업일"
        return f"말 {k}영업일 전"
    return ""


def describe(rule):
    if not rule:
        return "반복"
    r = normalize(rule)
    p = r.get("period", "day")

    if p == "day":
        return "매 영업일" if r.get("business_only", True) else "매일"

    if p == "week":
        ds = "·".join(W[i] for i in sorted(r.get("weekdays") or []))
        iv = int(r.get("interval", 1))
        head = {1: "매주", 2: "격주", 3: "3주마다", 4: "4주마다"}.get(iv, f"{iv}주마다")
        return f"{head} {ds}요일"

    if p == "quarter":
        return "매 분기 " + _basis_text(r, q=True)

    months = sorted(set(int(x) for x in (r.get("months") or ALL_MONTHS)))
    body = _basis_text(r)
    if len(months) == 12:
        return "매월 " + body
    if len(months) == 1:
        return f"매년 {months[0]}월 " + body
    return "·".join(str(x) for x in months) + "월 " + body
