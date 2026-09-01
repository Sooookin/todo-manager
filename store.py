# -*- coding: utf-8 -*-
"""데이터 저장 + 일정 인스턴스 계산."""
import json, os, threading, uuid
from datetime import date, datetime, timedelta

import paths
import recur

paths.migrate_legacy()
DATA = paths.DATA_FILE
LOCK = threading.RLock()

_DEFAULT = {"tasks": [], "fired": [], "holidays": [], "settings": {"notify_min": 30, "brief_time": "08:30", "business_only": True}}


def _read():
    if not os.path.exists(DATA):
        return json.loads(json.dumps(_DEFAULT))
    try:
        with open(DATA, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return json.loads(json.dumps(_DEFAULT))
    for k, v in _DEFAULT.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    return d


def _write(d):
    paths.ensure_data_dir()
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA)


def load():
    with LOCK:
        d = _read()
        recur.set_holidays(d.get("holidays"))
        return d


def save(d):
    with LOCK:
        _write(d)


def tasks():
    return load()["tasks"]


def add(t):
    with LOCK:
        d = _read()
        t.setdefault("id", uuid.uuid4().hex[:12])
        t.setdefault("created", datetime.now().isoformat(timespec="seconds"))
        t.setdefault("done", False)
        t.setdefault("done_dates", [])
        t.setdefault("note", "")
        t.setdefault("pinned", False)
        # 격주 이상 반복은 기준 주가 고정돼야 하므로 등록 시점을 anchor 로 박아둔다
        r = t.get("rule")
        if r and r.get("kind") == "weekly":
            r.setdefault("anchor", t["created"][:10])
        d["tasks"].append(t)
        _write(d)
        return t


def update(tid, patch):
    with LOCK:
        d = _read()
        for t in d["tasks"]:
            if t["id"] == tid:
                r = patch.get("rule")
                if r and r.get("kind") == "weekly" and "anchor" not in r:
                    old_r = t.get("rule") or {}
                    r["anchor"] = old_r.get("anchor") or (t.get("created") or "")[:10] or date.today().isoformat()
                t.update(patch)
                _write(d)
                return t
        return None


def remove(tid):
    with LOCK:
        d = _read()
        d["tasks"] = [t for t in d["tasks"] if t["id"] != tid]
        _write(d)


def toggle_done(tid, day=None):
    """일반 할 일은 done 토글, 반복 일정은 해당 날짜만 완료 처리."""
    with LOCK:
        d = _read()
        for t in d["tasks"]:
            if t["id"] != tid:
                continue
            if t.get("kind") == "routine":
                day = day or date.today().isoformat()
                dd = set(t.get("done_dates") or [])
                dd.symmetric_difference_update({day})
                t["done_dates"] = sorted(dd)
            else:
                t["done"] = not t.get("done")
                t["done_at"] = datetime.now().isoformat(timespec="seconds") if t["done"] else None
            _write(d)
            return t
        return None


def skip(tid, day=None):
    """반복 일정의 이번 회차만 건너뛴다."""
    with LOCK:
        d = _read()
        for t in d["tasks"]:
            if t["id"] == tid:
                day = day or date.today().isoformat()
                sk = set(t.get("skip_dates") or [])
                sk.add(day)
                t["skip_dates"] = sorted(sk)
                _write(d)
                return t
        return None


# ---------- 인스턴스 계산 ----------

def _dt(day, hhmm):
    h, m = (hhmm or "23:59").split(":")
    return datetime.combine(day, datetime.min.time()).replace(hour=int(h), minute=int(m))


def instances(back=14, ahead=45, data=None):
    """화면/알림이 공통으로 쓰는 평면화된 일정 목록."""
    d = data or load()
    today = date.today()
    lo, hi = today - timedelta(days=back), today + timedelta(days=ahead)
    out = []
    for t in d["tasks"]:
        if t.get("archived"):
            continue
        kind = t.get("kind", "deadline")
        if kind == "floating":
            out.append(_inst(t, None))
        elif kind == "routine":
            # 등록 이전 날짜는 밀린 일로 잡지 않는다
            born = (t.get("created") or "")[:10]
            start = max(lo, date.fromisoformat(born)) if born else lo
            skips = set(t.get("skip_dates") or [])
            for day in recur.occurrences(t.get("rule") or {}, start, hi):
                if day.isoformat() not in skips:
                    out.append(_inst(t, day))
        else:
            if not t.get("due_date"):
                out.append(_inst(t, None))
            else:
                out.append(_inst(t, date.fromisoformat(t["due_date"])))
    return out


def _inst(t, day):
    done = (day.isoformat() in (t.get("done_dates") or [])) if (t.get("kind") == "routine" and day) else bool(t.get("done"))
    due_dt = _dt(day, t.get("due_time")) if day else None
    return {
        "id": t["id"],
        "title": t.get("title", ""),
        "note": t.get("note", ""),
        "kind": t.get("kind", "deadline"),
        "tag": t.get("tag", ""),
        "pinned": bool(t.get("pinned")),
        "date": day.isoformat() if day else None,
        "time": t.get("due_time") or "",
        "due": due_dt.isoformat(timespec="minutes") if due_dt else None,
        "rule": t.get("rule") or None,
        "rule_n": recur.normalize(t["rule"]) if (t.get("kind") == "routine" and t.get("rule")) else None,
        "period": recur.normalize(t["rule"]).get("period") if (t.get("kind") == "routine" and t.get("rule")) else None,
        "rule_text": recur.describe(t.get("rule")) if t.get("kind") == "routine" else "",
        "muted": bool(t.get("muted")),
        "notify_min": t.get("notify_min", None),
        "done": done,
    }


def overview():
    """한 화면 개요. 마감 있는 일을 앞세우고, 반복 업무는 따로 묶는다."""
    d = load()
    today = date.today()
    now = datetime.now()
    ti = today.isoformat()
    ins = instances(back=10, ahead=75, data=d)

    # 마감 우선 → 날짜 → 시각
    def key(i):
        return (i["kind"] != "deadline", i["date"] or "9999", i["time"] or "99:99")

    # ── 밀린 것 ─────────────────────────────────────────────
    past = [i for i in ins if i["date"] and i["date"] < ti and not i["done"]]
    overdue = [i for i in past if i["kind"] == "deadline"]
    # 반복 업무는 "가장 최근에 놓친 1건"만, 최근 7일 안쪽만.
    # 매 영업일 반복은 지난 회차를 따라갈 의미가 없어 제외한다.
    limit = (today - timedelta(days=7)).isoformat()
    seen = set()
    for i in sorted([x for x in past if x["kind"] == "routine"],
                    key=lambda x: x["date"], reverse=True):
        if i["period"] == "day" or i["id"] in seen or i["date"] < limit:
            continue
        seen.add(i["id"])
        overdue.append(i)
    overdue.sort(key=key)

    # ── 오늘 ────────────────────────────────────────────────
    todays = sorted([i for i in ins if i["date"] == ti], key=lambda i: (i["done"],) + key(i))

    # ── 다가오는 마감 (반복 제외) ────────────────────────────
    wk = (today + timedelta(days=7)).isoformat()
    upcoming = sorted([i for i in ins if i["kind"] == "deadline" and i["date"]
                       and ti < i["date"] <= wk and not i["done"]], key=key)
    later = sorted([i for i in ins if i["kind"] == "deadline" and i["date"]
                    and i["date"] > wk and not i["done"]], key=key)

    # ── 반복 업무: 항목당 "다음 예정일" 한 줄 ────────────────
    nxt = {}
    for i in ins:
        if i["kind"] != "routine" or not i["date"] or i["date"] < ti:
            continue
        cur = nxt.get(i["id"])
        if cur is None or i["date"] < cur["date"]:
            nxt[i["id"]] = i
    routines = []
    for t in d["tasks"]:
        if t.get("kind") != "routine" or t.get("archived"):
            continue
        row = nxt.get(t["id"])
        if row is None:
            row = _inst(t, None)
        routines.append(dict(row, next_date=row.get("date")))
    routines.sort(key=lambda r: (r["next_date"] or "9999", r["time"] or "99:99"))

    floating = [i for i in ins if i["kind"] == "floating" and not i["done"]]
    floating.sort(key=lambda i: (not i["pinned"],))
    donetoday = [i for i in todays if i["done"]]

    return {
        "today": ti,
        "now": now.strftime("%H:%M"),
        "is_business_day": recur.is_business_day(today),
        "holidays": sorted(recur.HOLIDAYS),
        "overdue": overdue,
        "todays": todays,
        "upcoming": upcoming,
        "later": later[:40],
        "routines": routines,
        "floating": floating,
        "stats": {
            "left": len([i for i in todays if not i["done"]]) + len(overdue),
            "done": len(donetoday),
            "total": len(todays),
        },
        "tasks": [t for t in d["tasks"] if not t.get("archived")],
        "settings": d.get("settings", {}),
    }
