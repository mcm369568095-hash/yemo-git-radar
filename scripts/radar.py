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
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import gh_client
import pitch as pitch_mod
import promo
import report
import scorer

DATA = HERE.parent / "data"
HIST = DATA / "history"
REPORTS = DATA / "reports"
LAST = DATA / "last_picks.json"

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

def collect(args, token):
    pool = {}
    scanned = 0

    if not args.no_trending:
        for since in ("daily", "weekly"):
            try:
                t = gh_client.fetch_trending(since=since)
                log(f"[*] trending/{since}: {len(t)} 个")
                scanned += len(t)
                for r in t:
                    # daily 优先：同一天两个榜都出现，保留 daily 的涨星数
                    if r["full_name"] in pool and since != "daily":
                        continue
                    pool[r["full_name"]] = r
            except Exception as e:
                log(f"[!] trending/{since} 失败: {e}")

    try:
        s = gh_client.search_new(days=args.days, min_stars=args.min_stars, per_page=40, token=token)
        log(f"[*] 近 {args.days} 天新建高星: {len(s)} 个")
        scanned += len(s)
        for r in s:
            pool.setdefault(r["full_name"], r)
    except Exception as e:
        log(f"[!] search_new 失败: {e}")

    scanned = len(pool)
    log(f"[*] 去重后池子 {len(pool)} 个")

    prev, prev_date = load_prev()
    if prev:
        log(f"[*] 载入历史快照 {prev_date}（{len(prev)} 条），可算真实涨星")
    else:
        log("[*] 首次运行，没有历史快照，涨星只能用 trending 口径 / 新建推算")

    return list(pool.values()), scanned, prev, prev_date


def enrich(repo, token):
    """补详情 + README。失败就返回 None，不拖垮整批。"""
    d = gh_client.repo_detail(repo["full_name"], token)
    if not d:
        return None
    # trending 源有 gained，别被详情覆盖掉
    d["gained"] = repo.get("gained", 0)
    d["since"] = repo.get("since", "")
    d["source"] = repo.get("source", "")
    try:
        d["readme"] = gh_client.readme_head(repo["full_name"], 4000, token)
    except Exception:
        d["readme"] = ""
    return d


# ---------------------------------------------------------------- 打分

def process(repos, token, prev, args, prev_date=None):
    picks, dropped = [], []
    # 粗排：涨星多的、星多的先补详情，省 API 调用
    def rough(r):
        return (r.get("gained") or 0) * 3 + r.get("stars", 0) ** 0.6
    repos = sorted(repos, key=rough, reverse=True)[:args.max_detail]

    for i, r in enumerate(repos, 1):
        try:
            d = enrich(r, token)
        except Exception as e:
            log(f"[!] {r['full_name']} 详情失败: {e}")
            continue
        if not d:
            continue
        if i % 8 == 0:
            log(f"    ...已处理 {i}/{len(repos)}")

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
        d["gaps_short"] = [g[1] for g in gaps]
        d["risk"] = pitch_mod.risk_note(d)
        p = pitch_mod.build_pitch(d, d["form"], gaps, d.get("readme", ""))
        p["gap_key_word"] = gaps[0][1].replace("没有", "缺")
        d["pitch"] = p
        d["plain"] = pitch_mod.plain_what(d)
        d["url"] = f"https://github.com/{d['full_name']}"
        picks.append(d)
        time.sleep(0.4)  # 别打爆 API

    # 排序：等级 > 分数 > 涨星
    order = {"S": 0, "A": 1, "B": 2, "C": 3}
    picks.sort(key=lambda x: (order[x["grade"]], -x["score"], -(x.get("gained") or 0)))

    # 没进前 N 的也要留个说法——"这轮为什么没选它"本身就是结论
    head, tail = picks[:args.top], picks[args.top:]
    for r in tail:
        dropped.append({
            "full_name": r["full_name"],
            "stars": r["stars"],
            "reason": f"综合 {r['score']} 分（{r['grade']} 级），排在前 {args.top} 之外",
        })
    dropped.sort(key=lambda x: -x["stars"])
    return head, dropped, repos


# ---------------------------------------------------------------- 主流程

def cmd_run(args):
    token = args.token or gh_client.get_token()
    if not token:
        log("[!] 没拿到 GitHub token，走匿名请求（每小时 60 次，会很慢）")
    today = datetime.now().strftime("%Y-%m-%d")

    pool, scanned, prev, prev_date = collect(args, token)
    picks, dropped, enriched = process(pool, token, prev, args, prev_date)
    log(f"[*] 候选 {len(picks)} 个 / 排掉 {len(dropped)} 个")

    if not picks:
        log("[!] 今天没有任何项目过线，仍然出报告（说明原因也是一种结论）")

    save_snap(enriched, today)

    first, state = promo.tick(datetime.now().isoformat(timespec="seconds"))
    promo_html = promo.render(first)

    out_dir = Path(args.out) if args.out else REPORTS
    p = report.render(today, picks, dropped, scanned, promo_html,
                      issue=state.get("runs", 1), out_dir=out_dir)

    LAST.parent.mkdir(parents=True, exist_ok=True)
    LAST.write_text(json.dumps(
        {"date": today, "picks": picks, "dropped": dropped, "scanned": scanned},
        ensure_ascii=False, indent=1), encoding="utf-8")

    log(f"[OK] 报告 -> {p}")
    if first:
        log("[*] 本期带了完整推荐卡（首次），后续不再重复")
    if args.open:
        import webbrowser
        webbrowser.open(p.resolve().as_uri())
    return p


def cmd_fetch(args):
    """只抓不渲染，把候选写到 last_picks.json 供 Agent 精修。"""
    token = args.token or gh_client.get_token()
    today = datetime.now().strftime("%Y-%m-%d")
    pool, scanned, prev, prev_date = collect(args, token)
    picks, dropped, enriched = process(pool, token, prev, args, prev_date)
    save_snap(enriched, today)
    LAST.parent.mkdir(parents=True, exist_ok=True)
    LAST.write_text(json.dumps(
        {"date": today, "picks": picks, "dropped": dropped, "scanned": scanned},
        ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[OK] 候选已写入 {LAST}（{len(picks)} 个）")
    for i, r in enumerate(picks, 1):
        log(f"  {i:02d} [{r['grade']}] {r['full_name']:<42} {r['score']:>3}分  +{r.get('gained',0)}")
    return LAST


def cmd_render(args):
    """拿 last_picks.json 出报告（可先用 Agent 覆写 pitch 字段再跑这一步）。"""
    if not LAST.exists():
        raise SystemExit("还没有 last_picks.json，先跑 fetch")
    d = json.loads(LAST.read_text(encoding="utf-8"))
    first, state = promo.tick(datetime.now().isoformat(timespec="seconds"))
    out_dir = Path(args.out) if args.out else REPORTS
    p = report.render(d["date"], d["picks"], d["dropped"], d.get("scanned", 0),
                      promo.render(first), issue=state.get("runs", 1), out_dir=out_dir)
    log(f"[OK] 报告 -> {p}")
    return p


def main():
    ap = argparse.ArgumentParser(description="夜秣git副业雷达")
    ap.add_argument("cmd", nargs="?", default="run",
                    choices=["run", "fetch", "render"])
    ap.add_argument("--days", type=int, default=30, help="新建项目回溯天数")
    ap.add_argument("--min-stars", type=int, default=200, dest="min_stars")
    ap.add_argument("--top", type=int, default=8, help="报告里放几个")
    ap.add_argument("--max-detail", type=int, default=34, dest="max_detail",
                    help="最多给多少个项目补详情（控制 API 调用）")
    ap.add_argument("--out", default="", help="报告输出目录")
    ap.add_argument("--no-trending", action="store_true", dest="no_trending")
    ap.add_argument("--token", default="")
    ap.add_argument("--open", action="store_true", help="出完自动打开")
    args = ap.parse_args()

    try:
        if args.cmd == "run":
            cmd_run(args)
        elif args.cmd == "fetch":
            cmd_fetch(args)
        else:
            cmd_render(args)
    except KeyboardInterrupt:
        log("\n[!] 手动中断")
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
