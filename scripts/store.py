# -*- coding: utf-8 -*-
"""存档 + 查重账本。

马总 2026-11-02 定的规矩：
  · 每天抓的东西单独建档，一天一份 —— 攒着就是一套项目知识库
  · 推过的要记账，第二天不许原样再推一遍
  · 账本要看得见「这个第几次上、第一次是哪天」，否则读者以为雷达坏了

三层数据：
  data/seen.json               跨天账本：谁推过、几次、哪几天、在哪个 tab
  data/archive/YYYY-MM-DD.json  每日全档：当天扫到的全量 + 入选 + 排掉 + 方向分区
  data/archive/index.json       索引：日期 / 方向 / 数量 / 名字表，给检索用

为什么要记全量而不只记入选的：
  今天没进前 8 的项目，二十天后可能就是那个方向里最值得做的。
  只留入选的那 8 个，第二天查重是够了，但攒不成知识库。
"""
import json
import re
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SEEN = DATA / "seen.json"
ARC = DATA / "archive"
INDEX = ARC / "index.json"

# 每日重点：7 天内不重推。全站池子大，7 天足够换一批新的。
# 单独重点：14 天。方向内池子小，重复更没意义 —— 用户是在攒知识库，不是看热搜。
COOLDOWN = {"daily": 7, "focus": 14}
# 实在没得推的时候逐级放宽，绝不出「今天空白」这种结果。
# 最后一档是 None = 不限冷却，无条件全收 —— 否则池子小的时候会算出「0 个候选」。
RELAX_STEPS = (7, 14, 30, 60, None)


# ---------------------------------------------------------------- 小工具

def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _gap_days(a, b):
    """a 到 b 相差多少天。认不出日期就当没隔开（返回大数，等于不拦）。"""
    try:
        da = datetime.strptime(a, "%Y-%m-%d")
        db = datetime.strptime(b, "%Y-%m-%d")
        return (db - da).days
    except Exception:
        return 9999


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 账本

def account():
    """读账本。结构不对就当新的，别让一个坏文件把整条流程拦住。"""
    d = _read(SEEN, {})
    if not isinstance(d, dict) or not isinstance(d.get("repos"), dict):
        return {"repos": {}, "updated_at": ""}
    return d


def info(full_name, acc=None):
    """这个项目的历史：推过几次、上次哪天、第一次哪天。"""
    a = acc if acc is not None else account()
    e = a["repos"].get(full_name) or {}
    return {
        "times": e.get("times", 0),
        "first": e.get("first", ""),
        "last": e.get("last", ""),
        "dates": e.get("dates") or [],
        "tabs": e.get("tabs") or [],
    }


def known(full_name):
    return info(full_name)["times"] > 0


def annotate(r, acc=None):
    """把历史贴到项目上，报告里就能写「第 2 次上榜 · 上次 11-02」。"""
    h = info(r.get("full_name", ""), acc)
    r["seen_times"] = h["times"]
    r["seen_first"] = h["first"]
    r["seen_last"] = h["last"]
    return r


def note(repos, date="", tab="daily"):
    """记账：这几条今天推了。

    同一天重复跑不重复计数 —— 否则一天调三次 render，账本上就成了「推了三遍」，
    第二天查重会因为这个假记录把项目挡掉。
    """
    date = date or _today_str()
    acc = account()
    for r in repos:
        fn = (r or {}).get("full_name") or ""
        if not fn:
            continue
        e = acc["repos"].setdefault(fn, {})
        if not e.get("first"):
            e["first"] = date
        dates = e.get("dates") or []
        if date not in dates:
            dates.append(date)
        e["dates"] = dates[-180:]
        e["times"] = len(dates)
        e["last"] = date
        tabs = e.get("tabs") or []
        if tab and tab not in tabs:
            tabs.append(tab)
        e["tabs"] = tabs
        e["stars"] = r.get("stars") or e.get("stars") or 0
        e["focus"] = r.get("_focus") or e.get("focus") or ""
    acc["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write(SEEN, acc)
    return acc


def marked_seen(r, acc=None):
    """这条最近推过吗？返回 (推过没, 隔了几天, 上次日期)。

    🔴 今天推过的一律不算「历史重复」。
    查重是为了「别天天推同一个」，不是为了「同一天上午推过下午就不许再出现」——
    用户早上生成一次、中午调了参数再生成，如果第二份把早上的全换掉，
    他会以为雷达在乱跳。同一天重跑应该稳定收敛到同一批。
    """
    h = info(r.get("full_name", ""), acc)
    if not h["last"]:
        return False, 9999, ""
    gap = _gap_days(h["last"], _today_str())
    if gap <= 0:
        return False, 9999, h["last"]
    return True, gap, h["last"]


# ---------------------------------------------------------------- 冷却期选取

def cooldown_pick(picks, need, tab="daily", why_out=None, meta=None):
    """从排好序的候选里挑 need 个，最近推过的先跳过；不够就逐级放宽。

    返回 (选中, [], 实际冷却天数)。被挡下的写进 why_out。

    🔴 放宽必须**累加**，不能每档重头全收。
    踩过的坑：8 个老项目 + 3 个新项目要选 8 个，7 天冷却第一轮只收到 3 个新的，
    一路放宽到「不限」之后重头遍历一次，前 8 个全是老项目 —— 3 个新项目被丢了，
    等于冷却期一放宽，当天所有新料全部作废。正确做法是先收能收的，再用放宽的档补位。
    """
    acc = account()
    picks = list(picks)
    base = COOLDOWN.get(tab, 7)
    steps = [s for s in RELAX_STEPS if s is None or s >= base] or [base]

    chosen, taken, used, reused = [], set(), base, 0
    for days in steps:
        if len(chosen) >= need:
            break
        used = days
        pool = picks
        if days is None:
            # 完全放开时改成「最久没推的优先」。
            # 不然分数最高的那几个会永远霸榜：第 3 天推 p00，第 4 天还是 p00，
            # 用户看到的是一份三天前就该换掉的榜单。
            pool = sorted(picks, key=lambda r: (
                info(r.get("full_name", ""), acc).get("last") or "0000-00-00"))
        for r in pool:
            if len(chosen) >= need:
                break
            fn = r.get("full_name") or ""
            if fn in taken:
                continue
            seen, gap, last = marked_seen(r, acc)
            annotate(r, acc)
            if days is None or not seen or gap >= days:
                chosen.append(r)
                taken.add(fn)
                # 只有「在基础冷却期内推过、靠放宽才进来」的才算回看；
                # 隔了 30 天自然过了 7 天冷却的，是正常轮换，不叫回看。
                if seen and gap < base:
                    reused += 1
        if len(chosen) >= need:
            break

    for r in picks:
        if (r.get("full_name") or "") in taken:
            continue
        seen, gap, last = marked_seen(r, acc)
        annotate(r, acc)
        if why_out is not None:
            if seen:
                why_out.append({
                    "full_name": r.get("full_name", ""),
                    "stars": r.get("stars", 0),
                    "reason": f"{gap} 天前（{last}）推过，冷却 {base} 天内不重推",
                })
            else:
                why_out.append({
                    "full_name": r.get("full_name", ""),
                    "stars": r.get("stars", 0),
                    "reason": f"综合 {r.get('score', 0)} 分（{r.get('grade', '')} 级），名额满了",
                })

    if meta is not None:
        meta["days"] = used
        meta["relaxed"] = used is None or used > base
        meta["reused"] = reused
    return chosen, [], used


# ---------------------------------------------------------------- 归档

def archive(date, payload):
    """当天一档。重跑同一天就覆盖（是最新事实），不生成第二份。"""
    ARC.mkdir(parents=True, exist_ok=True)
    p = ARC / f"{date}.json"
    payload = dict(payload)
    payload["date"] = date
    payload["archived_at"] = datetime.now().isoformat(timespec="seconds")
    _write(p, payload)
    _update_index(date, payload)
    return p


def _update_index(date, payload):
    idx = _read(INDEX, {"items": []})
    if not isinstance(idx, dict):
        idx = {"items": []}
    items = [x for x in idx.get("items", []) if x.get("date") != date]
    daily = ((payload.get("daily") or {}).get("picks") or [])
    ft = payload.get("focus_tab") or {}
    ft_names = []
    for b in (ft.get("buckets") or {}).values():
        ft_names += [r.get("full_name", "") for r in (b or [])]
    names = [r.get("full_name", "") for r in daily] + ft_names
    items.append({
        "date": date,
        "mode": payload.get("mode", ""),
        "focus": ft.get("key") or payload.get("focus") or "",
        "scanned": payload.get("scanned", 0),
        "daily": len(daily),
        "focus_n": len(ft_names),
        "deep": len(payload.get("deep") or []),
        "names": [n for n in names if n],
    })
    items.sort(key=lambda x: x.get("date", ""))
    idx["items"] = items[-400:]
    idx["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write(INDEX, idx)
    return idx


def list_archive(limit=60):
    idx = _read(INDEX, {"items": []})
    items = idx.get("items") or []
    return items[-limit:][::-1]


def load_archive(date):
    return _read(ARC / f"{date}.json", None)


def kb_search(keyword, limit=40):
    """在历史档案里找项目。攒了几个月，这就是自己的选品库。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return []
    hits = []
    for f in sorted(ARC.glob("2*.json"), reverse=True):
        d = _read(f, None)
        if not isinstance(d, dict):
            continue
        date = d.get("date") or f.stem

        def scan(lst, where):
            for r in lst or []:
                blob = " ".join([
                    r.get("full_name", ""), r.get("desc", ""),
                    " ".join(r.get("topics") or []), r.get("form", ""),
                ]).lower()
                if kw in blob:
                    hits.append({
                        "date": date, "where": where,
                        "full_name": r.get("full_name", ""),
                        "stars": r.get("stars", 0),
                        "score": r.get("score", 0),
                        "grade": r.get("grade", ""),
                        "desc": r.get("desc", ""),
                    })

        scan((d.get("daily") or {}).get("picks"), "每日重点")
        ft = d.get("focus_tab") or {}
        for k, v in (ft.get("buckets") or {}).items():
            scan(v, f"单独重点·{k}")
        scan(d.get("deep"), "深挖")
        if len(hits) >= limit * 3:
            break
    seen, out = set(), []
    for h in hits:
        if h["full_name"] in seen:
            continue
        seen.add(h["full_name"])
        out.append(h)
        if len(out) >= limit:
            break
    return out


def catalog(limit=12):
    """档案目录：哪天扫了多少、推了哪些。给报告/命令行看进度用。"""
    return list_archive(limit)


def count():
    idx = _read(INDEX, {"items": []})
    items = idx.get("items") or []
    total = len({n for x in items for n in (x.get("names") or [])})
    return {"days": len(items), "projects": total}
