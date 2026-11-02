# -*- coding: utf-8 -*-
"""夜秣git副业雷达 · 主引擎

一条命令干完全部：
    python radar.py run                  # 抓 + 打分 + 出 HTML
    python radar.py fetch --days 30      # 只抓，存 json（给 Agent 精修用）
    python radar.py render               # 拿上一步的 json 出 HTML

设计取向：宁可少而准，不要多而杂。
一天真正能动手的项目不会超过五个，凑到二十个的唯一后果是你一个都不看。
"""
import argparse
import json
import math
import re
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gh_client
import envcheck
import analy as analy_mod
import focus as focus_mod
import pitch as pitch_mod
import promo
import report
import scorer
import store

DATA = HERE.parent / "data"
HIST = DATA / "history"
REPORTS = DATA / "reports"
LAST = DATA / "last_picks.json"
PROFILE = DATA / "profile.json"
DEEP = DATA / "deep.json"          # 单独重点（深挖）的项目
ANALYSIS = DATA / "analysis.json"  # Agent 写的精修分析
FOCUS_TAB = DATA / "focus_tab.json"  # 单独重点：方向专题（按天）

CLEAN_LICENSES = ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause",
                  "ISC", "0BSD", "Unlicense", "CC0-1.0")


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 历史快照

def load_prev():
    """找上一次的快照，用来算真实涨星。"""
    HIST.mkdir(parents=True, exist_ok=True)
    files = sorted(HIST.glob("*.json"))
    if not files:
        return {}, None
    try:
        d = json.loads(files[-1].read_text(encoding="utf-8"))
        return d.get("stars", {}), files[-1].stem
    except Exception:
        return {}, None


def save_snap(repos, date_str):
    HIST.mkdir(parents=True, exist_ok=True)
    stars = {r["full_name"]: r.get("stars", 0) for r in repos if r.get("stars")}
    (HIST / f"{date_str}.json").write_text(
        json.dumps({"date": date_str, "stars": stars}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    # 只留最近 60 天，别把磁盘塞满
    for f in sorted(HIST.glob("*.json"))[:-60]:
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------- 抓

def collect_daily(args, token):
    """每日重点的池子：全站清单，不掺方向。

    两个来源：trending（今天在涨的）+ 近 N 天新建的高星（新冒头的）。
    就这两样，不再加"存量按星排前 100"—— 那样每天推的都是同样几个大项目，
    报告第二天就变成复读机（这个坑 2026-11-02 踩过）。
    """
    pool = {}
    if not args.no_trending:
        for since in ("daily", "weekly"):
            try:
                t = gh_client.fetch_trending(since=since)
                log(f"[*] trending/{since}: {len(t)} 个")
                for r in t:
                    # daily 优先：同一天两个榜都出现，保留 daily 的涨星数
                    if r["full_name"] in pool and since != "daily":
                        continue
                    pool[r["full_name"]] = r
            except Exception as e:
                log(f"[!] trending/{since} 失败: {e}")

    try:
        s = gh_client.search_new(days=args.days, min_stars=args.min_stars,
                                 per_page=40, token=token)
        log(f"[*] 近 {args.days} 天新建高星: {len(s)} 个")
        for r in s:
            pool.setdefault(r["full_name"], r)
    except Exception as e:
        log(f"[!] search_new 失败: {e}")

    log(f"[*] 每日池子去重后 {len(pool)} 个")
    return pool


def collect_focus(fk, args, token, daily_pool):
    """单独重点的池子：只装这个方向里的项目。

    三个来源，对应马总要的「今日高星、涨星、既往高星」：
      1. 今日全站池里属于本方向的  → 今天在涨的（涨星 / 今日高星）
      2. 方向定向搜索（按星排）     → 存量高星，星多但今天没动
      3. 存量近期活跃（pushed）     → 老树发新芽，更新了但没上榜

    每个项目只进一个桶，桶的判定在 _bucket_of()，互斥，不会同一张卡出现两次。
    """
    pool = {}

    for fn, r in (daily_pool or {}).items():
        if focus_mod.belongs(r, fk):
            rr = dict(r)
            rr["_focus"] = fk
            rr["_src"] = "today"
            rr["_priority"] = True     # 今天全站榜里就属于这个方向的，优先补详情
            pool[fn] = rr
    n_today = len(pool)

    qs = focus_mod.queries(fk, min_stars=max(150, args.min_stars))
    log(f"[*] 方向定向「{fk}」：{len(qs)} 条查询")
    for label, q in qs:
        try:
            got = gh_client.search_query(q, sort="stars", per_page=15, token=token)
            keep = [r for r in got if focus_mod.belongs(r, fk)]
            for r in keep:
                k = r["full_name"]
                if k in pool:
                    continue
                rr = dict(r)
                rr["_focus"] = fk
                rr["_src"] = "search"
                pool[k] = rr
            log(f"    {label}: 拉到 {len(got)}，命中方向 {len(keep)}")
            time.sleep(2.0)       # search 接口限速，别打太快
        except gh_client.RateLimited:
            log(f"    {label}: 搜索额度用完，跳过剩余方向查询")
            RT["degraded"] = True
            break
        except Exception as e:
            log(f"    {label} 失败: {e}")

    # 「既往高星」由上面 sort=stars 的查询已经覆盖。
    # 2026-11-02 实测：给 search_pushed 加方向校验命中 0 个 —— 它不带 topic，
    # 拉回来的是全球按星排的大项目，白烧一次请求，删掉。
    log(f"[*] 方向「{fk}」池子 {len(pool)} 个（今日全站命中 {n_today} 个）")
    return pool


def _bucket_of(r):
    """单独重点里的分桶。三桶互斥，用户一眼能分开看。

    new     三个月内新建的 —— 今天的高星，还没被做烂
    hot     今天/本周在涨星的 —— 正在被验证的需求
    veteran 老项目、星多、今天没动 —— 沉淀下来的，做二创最省事

    🔴 created_at 缺失时不能直接判 age=9999 → veteran：
    LITE 通路下 trending 项目常常拿不到创建时间，那样「今日新上榜」永远是空的。
    今天全站榜里命中的，就按新的算 —— 它今天在榜上，这本身就是最强的「新」证据。
    """
    if r.get("created_at"):
        if scorer.days_since(r.get("created_at")) < 90:
            return "new"
    elif r.get("_src") == "today":
        return "new"
    if (r.get("gained") or 0) > 0:
        return "hot"
    return "veteran"


RT = {"mode": "FULL", "degraded": False}


# ---------------------------------------------------------------- 方向偏好

def load_profile():
    """记住用户上一次选的方向。下次不用再说一遍。"""
    if PROFILE.exists():
        try:
            return json.loads(PROFILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_profile(focus_key):
    p = load_profile()
    p["focus"] = focus_key
    p["updated_at"] = datetime.now().isoformat(timespec="seconds")
    hist = p.get("history") or []
    if not hist or hist[-1].get("focus") != focus_key:
        hist.append({"focus": focus_key, "at": p["updated_at"]})
    p["history"] = hist[-30:]
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


def _lite_enrich(repo):
    """不碰 API 的通路：仓库页面一次拿 license + README，缺字段给保守默认值。

    拿不到的东西会显式标进 _missing，报告里能看出来哪些是估的。
    """
    d = dict(repo)
    missing = []
    page = gh_client.fetch_repo_page(repo["full_name"])
    if page:
        if not d.get("license"):
            d["license"] = page.get("license") or ""
        d["readme"] = page.get("readme") or ""
    else:
        d["readme"] = ""

    if not d.get("license"):
        d["license"] = gh_client.raw_license(repo["full_name"])
    if not d.get("readme"):
        d["readme"] = gh_client.raw_readme(repo["full_name"])
    if not d.get("license"):
        missing.append("license")

    # 下面三项 API 才有。拿不到就留 None，让 scorer 用替代证据算，别硬填假值。
    if d.get("size_kb") is None:
        d["size_kb"] = 20000        # 中等体积假设 → 交付维度 7 分
        missing.append("体积")
    if d.get("created_at") is None:
        missing.append("创建时间")
    if d.get("open_issues") is None:
        missing.append("issue数")

    d["_partial"] = True
    d["_missing"] = missing
    return d


def enrich(repo, token, mode=None):
    """补详情 + README。失败就返回 None，不拖垮整批。

    mode=FULL 走 API；mode=LITE 走网页。API 额度耗尽会往上抛 RateLimited，
    由 process 捕获后整体切到 LITE，不再一个个撞墙。
    """
    mode = mode or RT["mode"]
    if mode == "LITE":
        d = _lite_enrich(repo)
    else:
        d = gh_client.repo_detail(repo["full_name"], token)
        if not d:
            d = _lite_enrich(repo)          # API 404/451，页面还有机会
        else:
            d["readme"] = gh_client.readme_head(repo["full_name"], 4000, token)

    # trending 源有 gained，别被详情覆盖掉
    d["gained"] = repo.get("gained", 0) or d.get("gained", 0)
    d["since"] = repo.get("since", "")
    d["source"] = repo.get("source", "")
    # 🔴 repo_detail 返回的是全新 dict，方向标记不会自动带过来。
    # 漏了这行，报告里「本期重点」一段永远是空的。
    if repo.get("_focus"):
        d["_focus"] = repo["_focus"]
    d.setdefault("readme", "")
    return d


# ---------------------------------------------------------------- 打分

def _repitch(head, state=None):
    """按最终报告顺序重写三行落地，保证同一份报告里不出现重复句。

    state 可以跨两次调用传下去 —— 每日重点和单独重点在同一份报告里，
    两个 tab 出现同一句"把界面翻成中文"，读者照样觉得是模板。
    """
    used, buyers, delivers = state if state else (set(), Counter(), set())
    for r in head:
        gaps = r.get("_gaps") or [(w, w, "") for w in (r.get("gaps_short") or [])] \
            or [("没有中文文档", "没有中文文档", "")]
        p = pitch_mod.build_pitch(
            r, r.get("form", ""), gaps, r.get("readme", ""),
            used=used,
            used_buyers={b for b, c in buyers.items() if c >= 2},
            used_deliver=delivers)
        p["gap_key_word"] = next(
            (g[1] for g in gaps if g[0] == p["gap_key"]), gaps[0][1]
        ).replace("没有", "缺")
        r["pitch"] = p
        if (r.get("analy") or {}).get("_auto"):
            # 说明层跟 pitch 是同一套结论，pitch 换了说明也得跟着换
            r["analy"] = analy_mod.build(r, gaps, p, r.get("readme", ""))
        used.add(p["change"])
        buyers[p["buyer"]] += 1
        delivers.add(p["deliver"])
    return (used, buyers, delivers)


def process(repos, token, prev, args, prev_date=None, detail_limit=None, cache=None):
    """一条管线：粗排 → 补详情 → 打分。返回打过分、可排序的候选池。

    不做截断、不做查重 —— 那是 _pick_daily / _pick_focus 的事，因为两条管线的
    「给几个」「冷却期多长」「怎么分桶」都不一样，混在一起写迟早打结。
    """
    picks, dropped = [], []
    used_actions = set()      # 同一份报告里不重复同一个改造动作
    buyer_seen = Counter()    # 买家：同一个最多出现两次，第三次起换人
    used_deliver = set()      # 交付路径：同一条只用一次
    cache = cache if cache is not None else {}
    acc = store.account()

    # 粗排：涨星多的、星多的先补详情，省 API 调用。
    # 最近推过的降到 0.35 倍 —— 不是排除，是让新项目先拿到详情名额。
    def rough(r):
        base = (r.get("gained") or 0) * 3 + r.get("stars", 0) ** 0.6
        seen, gap, _ = store.marked_seen(r, acc)
        if seen and gap < 7:
            base *= 0.35
        return base

    ordered = sorted(repos, key=rough, reverse=True)
    limit = detail_limit or args.max_detail

    # 🔴 优先项目必须有保底名额。
    # 方向池里 62 个项目，绝大多数是几万星的存量老项目，粗排永远排在前面；
    # 今天刚上榜的新项目星少、涨星 0，按 rough 排根本进不了前 24 ——
    # 结果「今日新上榜」那桶永远是空的，用户看不到他最想要的那一类。
    pri = [r for r in ordered if r.get("_priority")]
    rest = [r for r in ordered if not r.get("_priority")]
    head_pri = pri[:12]
    todo = (head_pri + rest[:max(0, limit - len(head_pri))])[:limit]
    if head_pri:
        log(f"[*] 补详情 {len(todo)} 个（其中今日新冒头 {len(head_pri)} 个）")
    else:
        log(f"[*] 补详情 {len(todo)} 个（池子 {len(ordered)} 个）")

    for i, r in enumerate(todo, 1):
        fn = r["full_name"]
        if fn in cache:
            d = cache[fn]
        else:
            try:
                d = enrich(r, token)
            except gh_client.RateLimited:
                # 额度没了不是致命错误 —— 换条路继续，别让用户白等一场
                if RT["mode"] == "FULL":
                    log("[!] API 额度用完，自动切到网页通路（不消耗额度），继续跑")
                    RT["mode"] = "LITE"
                    RT["degraded"] = True
                    try:
                        d = enrich(r, token, mode="LITE")
                    except Exception as e:
                        log(f"[!] {fn} 切网页后仍失败: {e}")
                        continue
                else:
                    log(f"[!] {fn} 网页抓取失败，跳过")
                    continue
            except Exception as e:
                log(f"[!] {fn} 详情失败: {e}")
                continue
            if d:
                cache[fn] = d
        if not d:
            continue
        if i % 8 == 0:
            log(f"    ...已处理 {i}/{len(todo)}")

        reason = scorer.reject_reason(d)
        if reason:
            dropped.append({"full_name": d["full_name"], "reason": reason, "stars": d["stars"]})
            continue

        # 真实涨星：本地历史优先，其次 trending，最后按新建推算
        today = datetime.now().strftime("%Y-%m-%d")
        if d["full_name"] in prev and prev_date and prev_date != today:
            delta = d["stars"] - prev[d["full_name"]]
            if delta > (d.get("gained") or 0):
                d["gained"] = delta
                d["since"] = "since_last"
        total, detail = scorer.score(d, d.get("readme", ""))
        d["score"] = total
        d["detail"] = detail
        d["grade"], d["grade_word"] = scorer.grade(total)
        d["form"] = scorer.classify_form(d, d.get("readme", ""))
        d["velocity"] = scorer.velocity(d, 1 if d.get("since") == "daily" else
                                        7 if d.get("since") == "weekly" else None)
        gaps = scorer.find_gaps(d, d.get("readme", ""))
        d["_gaps"] = gaps
        d["gaps_short"] = [g[1] for g in gaps]
        d["risk"] = pitch_mod.risk_note(d)
        d["suspect"] = scorer.star_suspect(d)
        # 买家允许重复两次：第一次命中通常是最准的行业，不该为了去重牺牲准确度；
        # 但连着三个卡都写"接单的设计师"，读者就知道这是模板了。
        p = pitch_mod.build_pitch(d, d["form"], gaps, d.get("readme", ""),
                                  used=used_actions,
                                  used_buyers={b for b, c in buyer_seen.items() if c >= 2},
                                  used_deliver=used_deliver)
        used_actions.add(p["change"])
        buyer_seen[p["buyer"]] += 1
        used_deliver.add(p["deliver"])
        # 概要里那句「因为缺 XX」要和实际给的动作对得上，不能固定用 gaps[0]
        p["gap_key_word"] = next(
            (g[1] for g in gaps if g[0] == p["gap_key"]), gaps[0][1]
        ).replace("没有", "缺")
        d["pitch"] = p
        d["plain"] = pitch_mod.plain_what(d)
        # 四层说明（原文/直译/说人话/能干什么）—— 规则兜底，Agent 可用 analyze 覆盖
        d["analy"] = analy_mod.build(d, gaps, p, d.get("readme", ""))
        d["url"] = f"https://github.com/{d['full_name']}"
        d["_bucket"] = _bucket_of(d) if d.get("_focus") else ""
        picks.append(d)
        time.sleep(0.4)  # 别打爆 API

    return picks, dropped, todo, cache


ORDER = {"S": 0, "A": 1, "B": 2, "C": 3}
SORT_KEY = lambda x: (ORDER[x["grade"]], -x["score"], -(x.get("gained") or 0))


def _pick_daily(cands, args, dropped):
    """每日重点：全品类，按等级/分数排，查重后取 top N。"""
    cands.sort(key=SORT_KEY)
    why, meta = [], {}
    head, _, _days = store.cooldown_pick(cands, args.top, "daily", why, meta)
    dropped.extend(why)
    if meta.get("relaxed"):
        log(f"[!] 新项目不够，每日重点的冷却放宽到 "
            f"{meta['days'] if meta.get('days') else '不限'}（其中 {meta.get('reused',0)} 个回看）")
    # 选取时新项目优先（否则老项目凭分数永远挤掉新料），
    # 但报告里仍按「能不能变成钱」排 —— 章节标题是这么承诺的，排序不能自己打脸。
    head.sort(key=SORT_KEY)
    return head[:args.top], meta


def _pick_focus(cands, fk, args, dropped):
    """单独重点：三个桶各取几个。

    桶不是装饰 —— 用户要的三样东西（今天的高星 / 正在涨的 / 攒下来的老底）
    价值不一样，混在一起按分数排，老牌大项目永远挤掉今天刚冒头的新面孔。
    """
    each = max(1, int(getattr(args, "focus_each", 3)))
    total_cap = max(each, int(getattr(args, "focus_top", 9)))
    names = {"new": "今日新上榜", "hot": "涨星中", "veteran": "既往高星"}
    buckets = {k: [] for k in names}
    for r in cands:
        buckets.setdefault(r.get("_bucket") or _bucket_of(r), []).append(r)

    why, out, meta_all = [], [], {"reused": 0, "relaxed": False, "days": {}}
    for k in ("new", "hot", "veteran"):
        lst = sorted(buckets.get(k) or [], key=SORT_KEY)
        if not lst:
            continue
        meta = {}
        take, _, days = store.cooldown_pick(lst, each, "focus", why, meta)
        out.extend(take[:each])
        meta_all["reused"] += meta.get("reused", 0)
        meta_all["relaxed"] = meta_all["relaxed"] or meta.get("relaxed", False)
        meta_all["days"][k] = days

    if len(out) < total_cap:
        have = {r["full_name"] for r in out}
        rest = sorted([r for r in cands if r["full_name"] not in have], key=SORT_KEY)
        more, _, _ = store.cooldown_pick(rest, total_cap - len(out), "focus", why)
        out.extend(more[:total_cap - len(out)])

    out.sort(key=lambda x: ("new", "hot", "veteran").index(x.get("_bucket") or "veteran"))
    dropped.extend(why)
    log("[*] 方向分桶：" + "、".join(
        f"{names[k]} {len([r for r in out if (r.get('_bucket') or 'veteran') == k])} 个"
        for k in names)
        + (f"（回看 {meta_all['reused']} 个）" if meta_all["reused"] else ""))
    return out[:total_cap], meta_all


def _finish(daily, focus_tab, dropped, cands):
    """两个 tab 一起收尾：动作去重 + 给没选上的写理由。

    去重状态跨两个 tab 传递。每日重点先挑，单独重点用剩下的说法 ——
    否则同一份报告里两个 tab 各写一句"把界面翻成中文"，模板感就出来了。
    """
    st = _repitch(daily)
    focus_all = []
    if focus_tab:
        for b in (focus_tab.get("buckets") or {}).values():
            focus_all += b
        _repitch(focus_all, st)

    chosen = {r["full_name"] for r in daily} | {r["full_name"] for r in focus_all}
    for r in cands:
        if r["full_name"] in chosen:
            continue
        why = f"综合 {r['score']} 分（{r['grade']} 级），名额有限，这一期没进"
        dropped.append({"full_name": r["full_name"], "stars": r["stars"],
                        "reason": why, "score": r["score"]})
    dropped.sort(key=lambda x: -x.get("stars", 0))
    return daily, focus_all


# ---------------------------------------------------------------- 主流程

def prepare(args):
    """开跑前定档：有没有 token、有没有 git，都不该拦住出报告。

    三档：
      FULL  有可用 token → API 拿详情，最快最全
      LITE  没 token      → 走 github.com 网页 + raw 静态文件，零额度消耗
    没装 git 也一样能跑 —— git 只是「自动找 token」的其中一条路，不是前提。
    """
    token = args.token or gh_client.get_token()
    src = gh_client.token_source()
    mode = "FULL" if token else "LITE"
    if getattr(args, "lite", False):
        mode = "LITE"
        if token:
            log("[*] --lite：补详情改走网页通路，token 只留给搜索接口")

    if not token:
        cfg = gh_client.ensure_config_hint()
        log("[!] 没找到 GitHub token —— 走轻量模式")
        log("    改从 github.com 网页抓 license 和 README，不消耗 API 额度，照样出完整报告，慢 1-2 分钟。")
        log(f"    想要快：在 {cfg} 的 gh_token 填一个 token")
        log("            申请地址 https://github.com/settings/tokens  （勾 public_repo 就够，免费）")
    else:
        log(f"[*] token 来源：{src or '指定参数'}")

    RT["mode"] = mode

    # --- 方向：命令行优先，其次沿用上次记住的
    raw = (getattr(args, "focus", "") or "").strip()
    prof = load_profile()

    if raw.lower() in ("list", "列表", "?", "有哪些"):
        log("\n可选方向（用 --focus 方向名 指定）：")
        for k, d in focus_mod.list_all():
            log(f"  {k:<6} {d}")
        log("\n不指定就按全站榜推；指定一次之后会记住，下次不用再说。")
        raise SystemExit(0)

    fk = None
    if raw.lower() in ("none", "off", "不限", "全部", "关闭"):
        if prof.get("focus"):
            save_profile(None)
        log("[*] 已关闭方向 —— 单独重点那个 tab 会空着，每日重点照常出")
    elif raw:
        fk = focus_mod.match(raw)
        if fk:
            log(f"[*] 单独重点盯着：{fk} —— 每天额外按这个方向挖一遍，"
                f"分「今日新上榜 / 涨星中 / 既往高星」三块摆")
        else:
            log(f"[!] 没认出方向「{raw}」，这一期只有每日重点。可选：")
            for k, d in focus_mod.list_all():
                log(f"      {k:<6} {d}")
    else:
        fk = prof.get("focus")
        if fk:
            log(f"[*] 沿用上次的方向：{fk}（想换加 --focus 其它方向，想关加 --focus none）")

    if fk:
        save_profile(fk)
    args.focus_key = fk

    return token, mode


def _load_deep():
    """读单独重点。文件坏了就当没有，不能让一个坏 JSON 拦住建报告。"""
    try:
        d = json.loads(DEEP.read_text(encoding="utf-8"))
        items = d.get("items") if isinstance(d, dict) else d
        return [x for x in (items or []) if isinstance(x, dict)]
    except Exception:
        return []


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _sync_pitch_from_analy(r):
    """把精修过的说法同步回 pitch。

    🔴 概要那三句读的是 `pitch.change`，卡片读的是 `analy.gap`。
    不同步就会出现「概要说翻 README，卡片说做中文模板」——同一份报告两个说法。
    """
    a = r.get("analy") or {}
    p = r.setdefault("pitch", {})
    if a.get("gap"):
        p["change"] = a["gap"]
    if a.get("buyer"):
        p["buyer"] = a["buyer"]
    return r


def _ensure_analy(r):
    """补齐四层说明。

    🔴 分两种：Agent 精修过的（`_auto is False`）只补空字段，一个字都不动；
    机翻兜底的整套重算 —— 不然改了翻译规则、改了比喻模板，老数据永远不生效，
    用户会看到「说人话」那句还是三天前那个半通不通的版本。
    """
    gaps = r.get("_gaps") or [(w, w, "") for w in (r.get("gaps_short") or [])]
    base = analy_mod.build(r, gaps, r.get("pitch") or {}, r.get("readme", ""))
    cur = dict(r.get("analy") or {})
    if cur.get("_auto") is False:
        for k, v in base.items():
            # 🔴 跳过标记字段。`_auto` 的值本身就是 False，
            # `if not cur.get(k)` 对它永远成立 —— 会把「已精修」翻回「机器直译」，
            # 于是每次重出一遍报告，AI 译过的东西就被悄悄降级了。
            if k in ("_auto", "_src"):
                continue
            if not cur.get(k):
                cur[k] = v
    else:
        cur = base
    r["analy"] = cur
    _sync_pitch_from_analy(r)
    return cur


def cmd_doctor(args):
    """体检：这台机器到底能不能跑、缺什么、要不要登录。"""
    log("[*] 正在体检（会发几个请求，约 5 秒）...")
    info = envcheck.probe()
    print()
    print(envcheck.render_text(info))
    print()
    if info["mode"] in ("FULL", "LITE"):
        log("结论：能跑。")
    else:
        log("结论：现在跑不了，按上面第 1 条处理。")
    return info


def _slim(r):
    """归档时把 readme 去掉 —— 只留结论，一天几十个仓库全文能把档案撑到几兆。"""
    d = {k: v for k, v in r.items() if k not in ("readme", "detail")}
    d.pop("analy", None)
    d["analy"] = {k: v for k, v in (r.get("analy") or {}).items()
                  if k in ("zh", "plain", "gap", "buyer", "_auto", "_src")}
    return d


def _run_pipelines(args, token):
    """跑完两条独立管线，返回一份待渲染/待存档的数据。

    这两条管线是**分开**的，不是一份榜单切两半：
      每日重点  全站扫，跟用户选了什么都无关 —— 今天全网在冒什么
      单独重点  只看用户那个方向 —— 今天这个方向有什么值得盯
    之前混在一起（用 _focus 标记在同一份榜单里分区）是错的：
    用户选了虚拟产品，每日那份就被挤成"方向内 + 剩饭"，等于没有日报了。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    prev, prev_date = load_prev()
    fk = getattr(args, "focus_key", None)
    dropped, cache = [], {}

    # ---- 管线 A：每日重点（全站，不看方向）
    pool_d = collect_daily(args, token)
    cands_d, drop_d, enr_d, cache = process(
        pool_d.values(), token, prev, args, prev_date, cache=cache)
    head_d, cool_meta = _pick_daily(cands_d, args, drop_d)
    dropped += drop_d
    log(f"[*] 每日重点：池子 {len(pool_d)} → 入选 {len(head_d)} 个")

    # ---- 管线 B：单独重点（只看方向）
    focus_tab, cands_f, pool_f = None, [], {}
    if fk:
        log("")
        pool_f = collect_focus(fk, args, token, pool_d)
        cands_f, drop_f, _enr_f, cache = process(
            pool_f.values(), token, prev, args, prev_date,
            detail_limit=getattr(args, "focus_detail", 24), cache=cache)
        head_f, fmeta = _pick_focus(cands_f, fk, args, drop_f)
        buckets = {}
        for r in head_f:
            buckets.setdefault(r.get("_bucket") or "veteran", []).append(r)
        focus_tab = {"key": fk, "buckets": buckets, "pool": len(pool_f),
                     "picked": len(head_f),
                     "reused": fmeta.get("reused", 0),
                     "relaxed": fmeta.get("relaxed", False)}
        dropped += drop_f
        log(f"[*] 单独重点：方向池子 {len(pool_f)} → 入选 {len(head_f)} 个")
    else:
        log("[*] 没设方向，单独重点空着（说一句「我想找虚拟产品的项目」就有了）")

    _finish(head_d, focus_tab, dropped, cands_d + cands_f)
    enr = enr_d + [r for r in cache.values() if r not in enr_d]
    return {
        "date": today,
        "daily": {"picks": head_d, "dropped": [d for d in drop_d]},
        "focus_tab": focus_tab,
        "dropped": dropped,
        "scanned": len(set(pool_d) | set(pool_f)),
        "pools": {"daily": len(pool_d), "focus": len(pool_f)},
        "mode": RT["mode"], "degraded": RT["degraded"],
        "focus": fk,
        "cooldown": cool_meta,
        "_enriched": enr,
    }


def _reuse_analysis(picks, old):
    """同一天重跑，别把已经精修过的说明冲掉 —— 精修是花了模型时间的，不是缓存。"""
    if not old:
        return 0
    keep = {}
    for r in (old.get("picks") or []):
        if (r.get("analy") or {}).get("_auto") is False:
            keep[r["full_name"]] = r["analy"]
    for b in ((old.get("focus_tab") or {}).get("buckets") or {}).values():
        for r in b or []:
            if (r.get("analy") or {}).get("_auto") is False:
                keep[r["full_name"]] = r["analy"]
    n = 0
    for r in picks:
        if keep.get(r["full_name"]):
            r["analy"] = keep[r["full_name"]]
            _sync_pitch_from_analy(r)
            n += 1
    return n


def _commit(data, args, render_now=True):
    """写 last_picks.json（+ 记账 + 建档 + 渲染）。

    记账放在这里，不放 fetch ——「推过」的标准是**报告真的出去了**，
    抓了没出报告不该占冷却期，否则用户试跑两次就被自己挡住三天。
    """
    daily = data["daily"]["picks"]
    ft = data.get("focus_tab") or {}
    focus_all = [r for b in (ft.get("buckets") or {}).values() for r in b]

    payload = {
        "date": data["date"],
        "picks": daily,
        "dropped": data.get("dropped", []),
        "scanned": data.get("scanned", 0),
        "mode": data.get("mode", ""),
        "degraded": data.get("degraded", False),
        "focus": data.get("focus"),
        "focus_tab": ft or None,
        "pools": data.get("pools", {}),
        "cooldown": data.get("cooldown", {}),
    }
    LAST.parent.mkdir(parents=True, exist_ok=True)
    LAST.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    if not render_now:
        # fetch 只抓不出报告，不记账也不建档 —— 抓了没推不该占冷却期
        return None
    _archive(payload)   # 建档放渲染前：报告里「已经攒了 N 天」要算上今天
    first, state = promo.tick(datetime.now().isoformat(timespec="seconds"), data["date"])
    out_dir = Path(args.out) if getattr(args, "out", "") else REPORTS
    p = report.render(
        data["date"], daily, data.get("dropped", []), data.get("scanned", 0),
        promo.render(first), issue=state.get("runs", 1), out_dir=out_dir,
        mode=data.get("mode", "FULL"), degraded=data.get("degraded", False),
        focus_tab=ft or None,
        deep=_sync_deep(data.get("deep") or _load_deep(), daily),
        history=store.catalog(8), kb=store.count(),
        theme=getattr(args, "theme", "") or "")
    # 🔴 记账放在渲染**成功之后**。
    # 放在前面的话，渲染一崩（比如模板变量没对上），这 17 个项目已经被记成"推过"，
    # 第二天全被冷却挡掉 —— 用户什么都没看到，却被告知"这些昨天推过了"。
    _note(payload)
    log(f"[OK] 报告 -> {p}")
    return p


def cmd_run(args):
    token, mode = prepare(args)
    data = _run_pipelines(args, token)
    n_d = len(data["daily"]["picks"])
    n_f = (data.get("focus_tab") or {}).get("picked", 0)
    if not n_d and not n_f:
        log("[!] 今天没有任何项目过线，仍然出报告（说明原因也是一种结论）")

    save_snap(data["_enriched"], data["date"])

    old = _load_json(LAST) if LAST.exists() else None
    n = _reuse_analysis(data["daily"]["picks"]
                        + [r for b in ((data.get("focus_tab") or {}).get("buckets") or {}).values()
                           for r in b], old)
    if n:
        log(f"[*] 沿用了上次的精修说明 {n} 个")

    if RT["degraded"]:
        log("[!] 本期中途额度耗尽，已自动降级为轻量通路，报告标注了这一点")

    p = _commit(data, args, render_now=True)
    _nudge_translate(data)
    _nudge_sched()
    if args.open:
        import webbrowser
        webbrowser.open(p.resolve().as_uri())
    return p


def _nudge_sched():
    """第一次出完报告，提示 Agent 问一句「要不要设成每天 8 点自动跑」。

    🔴 为什么由脚本喊、而不是只写在文档里：
    文档是「想读的时候才读」，这条提示是「跑完就撞到脸上」。
    技能分发出去，Agent 换了一个，没人会回去翻第七章 —— 但这行日志它会看见。

    只问一次。答过（同意或拒绝都算）就置位，之后每天跑都静默。
    """
    if not promo.need_ask_sched():
        return
    log("")
    log("┌" + "─" * 58)
    log("│ 第一次出报告。回话之前，先问用户这一句：")
    log("│")
    log("│   要不要把它设成每天早上 8 点自动出报告？")
    log("│     ① 要         → 建一个每日 08:00 的定时任务，" )
    log("│                    命令：python scripts/radar.py run")
    log("│     ② 换个时间   → 按用户说的时间建，命令同上")
    log("│     ③ 先不用     → 什么都不用建")
    log("│")
    log("│ 不管用户答哪一个，问完都要执行下面这条收尾")
    log("│ （否则明天还会再问一遍）：")
    log("│     python scripts/radar.py sched --done")
    log("└" + "─" * 58)


def cmd_sched(args):
    """标记「已问过用户要不要定时」。"""
    if getattr(args, "done", False):
        promo.mark_sched_asked()
        log("[OK] 已记录：定时任务这件事问过了，之后不再提。")
        return
    need = promo.need_ask_sched()
    log(f"[*] 待问：{'是' if need else '否（已经问过或还没出过报告）'}")


def _nudge_translate(data):
    """报告出完了，还差最重要的一步：翻译。

    🔴 规则翻译只保证「不是空白」，不保证「能发出去」。
    不在这里把话说明白，用户就会拿着一份半成品去发，然后问
    「我爬下来这么多，怎么一句人话都没有」。
    """
    every = list(data["daily"]["picks"])
    for b in ((data.get("focus_tab") or {}).get("buckets") or {}).values():
        every += b or []
    left = [r for r in every if analy_mod.needs_translate(r)]
    if not left:
        log("[OK] 翻译全部过关，这份报告可以直接发。")
        return
    log("")
    log(f"[!] 还有 {len(left)} 个项目的简介是机器直译 —— 能读，但发出去不够。")
    log("    补译（Agent 自己就能译，不用额外花钱）：")
    log("      python scripts/radar.py translate --todo    # 出待译清单")
    log("      （填 fill.zh / fill.plain）")
    log("      python scripts/radar.py translate --apply   # 写回并重出报告")


def cmd_fetch(args):
    """只抓不渲染，把候选写到 last_picks.json 供 Agent 精修。

    注意这里**不记账**：抓了但没出报告，不该占冷却期。
    """
    token, mode = prepare(args)
    data = _run_pipelines(args, token)
    save_snap(data["_enriched"], data["date"])
    _commit(data, args, render_now=False)
    daily = data["daily"]["picks"]
    ft = data.get("focus_tab") or {}
    log(f"[OK] 已写入 {LAST}（每日 {len(daily)} 个"
        + (f"，单独重点 {ft.get('picked',0)} 个）" if ft else "）"))
    for i, r in enumerate(daily, 1):
        tag = f"第{r.get('seen_times',0)}次" if r.get("seen_times", 0) > 1 else ""
        log(f"  日 {i:02d} [{r['grade']}] {r['full_name']:<40} {r['score']:>3}分 "
            f"+{r.get('gained',0)} {tag}")
    for k, lst in (ft.get("buckets") or {}).items():
        for r in lst:
            log(f"  向 {k:<8} [{r['grade']}] {r['full_name']:<40} {r['score']:>3}分")
    return LAST


def cmd_analyze(args):
    """把 Agent 写的精修分析（analysis.json）合并进候选，然后出报告。

    Agent 的价值就在这一步：规则版只能把英文词换成中文词，
    真正"这东西等于什么、谁会买、为什么买"只有读得懂上下文的人（模型）写得出来。
    """
    path = Path(getattr(args, "file", "") or ANALYSIS)
    data = _load_json(path)
    if data is None:
        raise SystemExit(f"读不到 {path}（JSON 格式或路径不对）")
    if not LAST.exists():
        raise SystemExit("还没有 last_picks.json，先跑 fetch")
    d = json.loads(LAST.read_text(encoding="utf-8"))
    picks = d.get("picks", [])
    # 先把规则版垫底，再拿精修覆盖 —— 否则 analysis.json 没写的字段（比如原文 en）
    # 会留成空洞，报告里就直接空着。
    for r in picks:
        _ensure_analy(r)
    hit, miss = analy_mod.merge(picks, data)
    for r in picks:
        r.setdefault("plain", "")
    LAST.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[*] 精修合并：{hit} 个，未覆盖 {len(miss)} 个"
        + (f"（{', '.join(miss[:3])}…）" if miss else ""))

    # 单独重点里的项目也要能精修：同一份 analysis.json 一起喂
    deep = _load_deep()
    if deep:
        dh, _ = analy_mod.merge(deep, data)
        by_name = {a.get("full_name"): a for a in (data.get("items") or [])
                   if isinstance(a, dict)} if isinstance(data, dict) else {}
        for r in deep:
            extra = (by_name.get(r.get("full_name")) or {}).get("deep") or {}
            for k in ("moat",):
                if extra.get(k):
                    r.setdefault("analy", {})[k] = extra[k]
        if dh:
            DEEP.write_text(json.dumps({"items": deep}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
            log(f"[*] 单独重点也合并了 {dh} 个")
    return _render_from(d, args)


def _sync_deep(deep, picks):
    """深挖页和每日卡说同一个项目时，数字必须一致。

    深挖时如果没接 trending，涨星是缺的，同一个仓库会出现
    「每日重点 69 分 A 级 / 单独重点 54 分 B 级」这种自相矛盾。
    以榜单那份为准，深挖只负责多讲内容。
    """
    by_name = {r.get("full_name"): r for r in (picks or [])}
    for r in deep:
        src = by_name.get(r.get("full_name"))
        if not src:
            continue
        for k in ("score", "grade", "grade_word", "stars", "forks", "lang",
                  "license", "gained", "since", "velocity", "form",
                  "gaps_short", "risk", "suspect", "desc", "topics"):
            if src.get(k) not in (None, "", []):
                r[k] = src[k]
    return deep


def _record(d):
    """记账 + 建档。同一天重复调用不会重复计数 —— render/analyze/deep 都会走到这里。"""
    _archive(d)
    _note(d)


def _note(d):
    """记账：这几条今天推了。"""
    picks = d.get("picks") or []
    ft = d.get("focus_tab") or {}
    focus_all = [r for b in (ft.get("buckets") or {}).values() for r in b]
    if picks:
        store.note(picks, d.get("date", ""), "daily")
    if focus_all:
        store.note(focus_all, d.get("date", ""), "focus")


def _archive(d):
    """建档：当天一份。渲染前就要写，报告里那行「已经攒了 N 天」要算上今天。"""
    picks = d.get("picks") or []
    ft = d.get("focus_tab") or {}
    store.archive(d.get("date", ""), {
        "mode": d.get("mode", ""),
        "degraded": d.get("degraded", False),
        "focus": ft.get("key") or d.get("focus"),
        "scanned": d.get("scanned", 0),
        "pools": d.get("pools", {}),
        "daily": {"picks": [_slim(r) for r in picks],
                  "dropped": (d.get("dropped") or [])[:40]},
        "focus_tab": {
            "key": ft.get("key"),
            "pool": ft.get("pool", 0),
            "buckets": {k: [_slim(r) for r in v]
                        for k, v in (ft.get("buckets") or {}).items()},
        },
        "deep": _load_deep(),
    })


def _render_from(d, args):
    """拿一份 last_picks 出报告。analyze / render / deep 都走这里。"""
    _record(d)
    first, state = promo.tick(datetime.now().isoformat(timespec="seconds"), d.get("date", ""))
    out_dir = Path(args.out) if getattr(args, "out", "") else REPORTS
    deep = _sync_deep(_load_deep(), d.get("picks", []))
    p = report.render(d["date"], d.get("picks", []), d.get("dropped", []),
                      d.get("scanned", 0), promo.render(first),
                      issue=state.get("runs", 1), out_dir=out_dir,
                      mode=d.get("mode", "FULL"), degraded=d.get("degraded", False),
                      focus_tab=d.get("focus_tab") or None, deep=deep,
                      history=store.catalog(8), kb=store.count(),
                      theme=getattr(args, "theme", "") or "")
    log(f"[OK] 报告 -> {p}")
    _nudge_sched()
    return p


def cmd_deep(args):
    """深挖一个指定仓库，塞进报告的「单独重点」tab。

    和每日榜单的区别：榜单是"今天有一批，你挑一个"，
    深挖是"我就要看这个，把它能不能变现给我拆到底"。
    """
    target = (getattr(args, "target", "") or "").strip()
    if not target:
        raise SystemExit("用法：python scripts/radar.py deep owner/repo")
    target = re.sub(r"^(https?://)?(www\.)?github\.com/", "", target).strip("/")

    token = args.token or gh_client.get_token()
    mode = "LITE" if (getattr(args, "lite", False) or not token) else "FULL"
    log(f"[*] 深挖 {target}（{'API' if mode == 'FULL' else '网页通路'}）")

    d = None
    if mode == "FULL":
        d = gh_client.repo_detail(target, token)
        if d:
            d["readme"] = gh_client.readme_head(target, 8000, token)
    if not d:
        d = _lite_enrich({"full_name": target})
    if not d:
        raise SystemExit(f"拿不到 {target} 的信息（仓库不存在 / 私有 / 网络不通）")

    d.setdefault("gained", 0)
    d["score_detail"] = scorer.score(d, d.get("readme", ""))[1]
    total = scorer.score(d, d.get("readme", ""))[0]
    d["score"] = total
    d["grade"], d["grade_word"] = scorer.grade(total)
    d["form"] = scorer.classify_form(d, d.get("readme", ""))
    d["velocity"] = scorer.velocity(d)
    gaps = scorer.find_gaps(d, d.get("readme", ""))
    d["gaps_short"] = [g[1] for g in gaps]
    d["risk"] = pitch_mod.risk_note(d)
    d["suspect"] = scorer.star_suspect(d)
    p = pitch_mod.build_pitch(d, d["form"], gaps, d.get("readme", ""))
    d["pitch"] = p
    d["analy"] = analy_mod.build(d, gaps, p, d.get("readme", ""))
    d["url"] = f"https://github.com/{d['full_name']}"
    d["readme"] = ""      # README 原文体积大，不往 deep.json 里塞

    items = [x for x in _load_deep() if x.get("full_name") != d["full_name"]]
    items.insert(0, d)
    items = items[:5]
    DEEP.parent.mkdir(parents=True, exist_ok=True)
    DEEP.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    log(f"[*] 已加入「单独重点」：{d['full_name']}（{d['grade']} 级 {total} 分）")
    log(f"    要更细的分析：改 {DEEP} 里这个对象的 analy 字段，或写 analysis.json 再跑 analyze")

    # 顺手重出报告，让 tab 里立刻有东西
    if LAST.exists():
        d0 = json.loads(LAST.read_text(encoding="utf-8"))
        return _render_from(d0, args)
    return None


def cmd_render(args):
    """拿 last_picks.json 出报告（可先用 Agent 覆写 pitch 字段再跑这一步）。"""
    if not LAST.exists():
        raise SystemExit("还没有 last_picks.json，先跑 fetch")
    d = json.loads(LAST.read_text(encoding="utf-8"))
    # 简介一律在出报告时重算：fetch 存的可能是旧版本清洗逻辑的结果，
    # 改了清洗规则（比如 GitHub emoji 短码 :black_heart:）不该逼用户重抓一遍。
    every = list(d.get("picks", []))
    for b in ((d.get("focus_tab") or {}).get("buckets") or {}).values():
        every += b or []
    for r in every:
        r["plain"] = pitch_mod.plain_what(r)
        _ensure_analy(r)   # 老数据没有四层说明，出报告时补上，别逼用户重抓
    return _render_from(d, args)


def cmd_translate(args):
    """翻译流水线：把待译清单交给模型，译完写回。

    规则翻译保底能用，但真正的"能发出去"要靠模型。
    这一步就是两者之间的桥：
      1. --todo   扫出还差哪几条，写成一份带空位的 json
      2. （Agent 填 fill.zh / fill.plain）
      3. --apply  写回 last_picks.json，标成 AI 精译
    不自动调 API：token 是用户的，脚本不替用户花钱。
    """
    step = "check"
    if getattr(args, "todo", False):
        step = "todo"
    elif getattr(args, "apply", False):
        step = "apply"
    # 🔴 先按当前规则把四层说明重算一遍再体检。
    # 不重算的话，translate 读的是几天前落盘的旧文案（比如早期版本写死的
    # "跟XX有关（作者原话没译全）"），判据全乱：明明一句人话都没有，却显示已通过。
    if LAST.exists():
        try:
            d = json.loads(LAST.read_text(encoding="utf-8"))
            for r in _all_rows(d):
                r["plain"] = pitch_mod.plain_what(r)
                _ensure_analy(r)
            LAST.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            log(f"[!] 重算四层说明失败（不影响继续）：{e}")
    argv = [step]
    if getattr(args, "file", ""):
        argv += ["--file", args.file]
    return analy_mod.main(argv)


def _all_rows(d):
    """last_picks 里所有带说明的项目：每日 + 单独重点三桶。"""
    rows = list(d.get("picks") or [])
    for b in ((d.get("focus_tab") or {}).get("buckets") or {}).values():
        rows += b or []
    return rows


def cmd_archive(args):
    """查历史档案。攒了几个月，这就是自己的选品库。"""
    kw = (getattr(args, "grep", "") or args.target or "").strip()
    if kw:
        hits = store.kb_search(kw, limit=30)
        if not hits:
            log(f"[!] 档案里没搜到「{kw}」。档案目录：{store.ARC}")
            return []
        log(f"[*] 「{kw}」命中 {len(hits)} 个（同项目只列最早一次）：\n")
        for h in hits:
            log(f"  {h['date']}  {h['full_name']:<42} {h['stars']:>7} 星 "
                f"{h['score']:>3} 分 {h['grade']} 级  [{h['where']}]")
            if h.get("desc"):
                log(f"            {h['desc'][:80]}")
        return hits

    items = store.list_archive(int(getattr(args, "days", 0) or 20))
    if not items:
        log(f"[!] 还没有任何档案。跑一次 run 就会自动建：{store.ARC}")
        return []
    c = store.count()
    log(f"[*] 档案 {c['days']} 天 / {c['projects']} 个项目（同日重跑覆盖，不重复计数）\n")
    for it in items:
        log(f"  {it['date']}  扫 {it['scanned']:>4}  每日 {it['daily']:>2}  "
            f"单独 {it['focus_n']:>2}  深挖 {it['deep']}  "
            f"{('· ' + it['focus']) if it.get('focus') else ''}")
    log(f"\n  想找项目：python scripts/radar.py archive --grep ppt")
    return items


def main():
    ap = argparse.ArgumentParser(description="夜秣git副业雷达")
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "fetch", "render", "doctor", "analyze",
                             "deep", "archive", "translate", "sched"])
    ap.add_argument("target", nargs="?", default="",
                    help="deep 用：owner/repo；archive 用：搜索关键词")
    ap.add_argument("--days", type=int, default=30, help="新建项目回溯天数")
    ap.add_argument("--min-stars", type=int, default=200, dest="min_stars")
    ap.add_argument("--top", type=int, default=8, help="每日重点放几个")
    ap.add_argument("--max-detail", type=int, default=34, dest="max_detail",
                    help="每日重点最多给多少个项目补详情（控制 API 调用）")
    ap.add_argument("--out", default="", help="报告输出目录")
    ap.add_argument("--no-trending", action="store_true", dest="no_trending")
    ap.add_argument("--token", default="")
    ap.add_argument("--focus", default="",
                    help="单独重点的方向（虚拟产品/AI 工具/内容创作/数据效率/"
                         "自媒体运营/电商/教育教学/设计素材），传 list 看全部，传 none 关闭")
    ap.add_argument("--focus-top", type=int, default=9, dest="focus_top",
                    help="单独重点最多放几个（默认 9）")
    ap.add_argument("--focus-each", type=int, default=3, dest="focus_each",
                    help="单独重点每一块（新上榜/涨星/老底）各放几个（默认 3）")
    ap.add_argument("--focus-detail", type=int, default=24, dest="focus_detail",
                    help="方向池最多给多少个补详情（默认 24）")
    ap.add_argument("--grep", default="", help="archive 用：在历史档案里搜关键词")
    ap.add_argument("--lite", action="store_true",
                    help="强制走网页通路，不消耗 API 额度（没 token 时自动开）")
    ap.add_argument("--open", action="store_true", help="出完自动打开")
    ap.add_argument("--file", default="",
                    help="analyze 用：Agent 写的 analysis.json 路径")
    ap.add_argument("--theme", default="",
                    help="报告主题：green（摸鱼绿，默认）/ day（白天）/ dark（深色）")
    ap.add_argument("--todo", action="store_true",
                    help="translate 用：生成待译清单 data/todo_translate.json")
    ap.add_argument("--apply", action="store_true",
                    help="translate 用：把译好的 data/translate.json 写回")
    ap.add_argument("--done", action="store_true",
                    help="sched 用：标记「已问过用户要不要每日定时」")
    args = ap.parse_args()

    try:
        if args.cmd == "run":
            cmd_run(args)
        elif args.cmd == "fetch":
            cmd_fetch(args)
        elif args.cmd == "doctor":
            cmd_doctor(args)
        elif args.cmd == "analyze":
            cmd_analyze(args)
        elif args.cmd == "deep":
            cmd_deep(args)
        elif args.cmd == "archive":
            cmd_archive(args)
        elif args.cmd == "translate":
            cmd_translate(args)
        elif args.cmd == "sched":
            cmd_sched(args)
        else:
            cmd_render(args)
    except KeyboardInterrupt:
        log("\n[!] 手动中断")
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
