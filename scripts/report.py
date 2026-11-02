# -*- coding: utf-8 -*-
"""HTML 报告渲染。所有视觉都在 templates/report.html 里，这里只管填数据。"""
import html
import re
from datetime import datetime
from pathlib import Path

TPL = Path(__file__).resolve().parent.parent / "templates" / "report.html"


def esc(s):
    return html.escape(str(s or ""), quote=True)


def fmt(n):
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def card(i, r):
    g = r.get("grade", "C")
    lic = r.get("license") or "无"
    nums = [
        f'<span class="num"><b>{fmt(r.get("stars",0))}</b> 总星</span>',
        f'<span class="num"><b>{fmt(r.get("forks",0))}</b> fork</span>',
        f'<span class="num">{esc(r.get("lang") or "未知语言")}</span>',
        f'<span class="num">{esc(lic)}</span>',
    ]
    if r.get("gained"):
        label = {"daily": "今日", "weekly": "本周", "monthly": "本月"}.get(r.get("since", ""), "近期")
        nums.insert(0, f'<span class="num hot">🔥 <b>+{fmt(r["gained"])}</b> {label}</span>')
    elif r.get("velocity"):
        nums.insert(0, f'<span class="num hot">🔥 约 <b>+{fmt(round(r["velocity"]))}</b> 星/天</span>')

    p = r.get("pitch", {})
    chips = [f'<span class="chip">{esc(g2)}</span>' for g2 in r.get("gaps_short", [])]
    chips.append(f'<span class="chip">预计 {p.get("hours","?")} 小时跑起来</span>')
    chips.append(f'<span class="chip">{esc(r.get("form",""))}</span>')
    if r.get("risk"):
        chips.append(f'<span class="chip warn">{esc(r["risk"])}</span>')
    if g in ("S", "A"):
        chips.append('<span class="chip ok">可商用</span>')

    return f"""
<article class="card {g.lower()}">
  <div class="card-top">
    <div class="rank">{i:02d}</div>
    <div class="ttl">
      <div class="name"><a href="{esc(r.get('url'))}" target="_blank" rel="noopener">{esc(r.get('full_name'))}</a></div>
      <div class="by">作者 <a href="https://github.com/{esc(r.get('owner'))}" target="_blank" rel="noopener">@{esc(r.get('owner'))}</a>
        · 综合 {r.get('score',0)}/100</div>
    </div>
    <span class="badge {g}">{g} · {esc(r.get('grade_word',''))}</span>
  </div>
  <p class="what">{esc(r.get('plain',''))}</p>
  <div class="nums">{''.join(nums)}</div>
  <div class="pitch">
    <p class="pitch-h">三行落地</p>
    <div class="row"><span class="k">改哪一处</span><span class="v">{esc(p.get('change',''))}</span></div>
    <div class="row"><span class="k">卖给谁</span><span class="v"><b>{esc(p.get('buyer',''))}</b></span></div>
    <div class="row"><span class="k">怎么交付</span><span class="v">{esc(p.get('deliver',''))}</span></div>
  </div>
  <div class="foot">{''.join(chips)}</div>
</article>"""


def build_brief(picks, dropped, stats):
    """三句话：第一句说今晚干什么，第二句说今天盘子什么样，第三句说排掉了什么。

    这三句是整份报告唯一"人在说话"的地方，不能写成统计播报。
    """
    lines = []
    s = [r for r in picks if r.get("grade") == "S"]
    a = [r for r in picks if r.get("grade") == "A"]

    if s:
        top = s[0]
        lines.append(
            f"今天只有 <strong>{len(s)} 个</strong>够 S 级。排第一的是 "
            f"<strong>{esc(top['full_name'])}</strong>：{esc(top['pitch']['buyer'])}会买，"
            f"今晚的活是{esc(top['pitch']['change'])}。"
        )
    elif a:
        top = a[0]
        lines.append(
            f"今天<strong>没有 S 级</strong>，最好的是 <strong>{esc(top['full_name'])}</strong>"
            f"（{top.get('score')} 分）。能做，但得先补一步才交得出去——{esc(top['pitch']['change'])}。"
        )
    else:
        lines.append(
            "今天<strong>全军覆没</strong>。涨得最猛的那批，许可证或形态都不适合一个人接手。"
            "这种日子不出手，比乱出手强。"
        )

    # 第二句：今天盘子长什么样。这是"分析"和"播报"的分界。
    if picks:
        ai = len([r for r in picks if re.search(
            r"(ai|llm|gpt|agent|model|claude|gemini|prompt)", 
            f"{r.get('name','')} {r.get('desc','')}".lower())])
        ind = len([r for r in picks if r["pitch"].get("buyer_tag") not in ("通用", None)])
        avg = round(sum(r.get("score", 0) for r in picks) / len(picks))
        if ai >= len(picks) * 0.7:
            lines.append(
                f"再说今天的盘子：{len(picks)} 个候选里 <strong>{ai} 个是 AI 相关</strong>，"
                f"平均 {avg} 分。榜已经被 AI 包场了，这意味着两件事——机会多，但同质化也重，"
                f"你能想到的二创别人也想得到。真正稀缺的不是项目，是<strong>找到具体买家</strong>。"
            )
        elif ind >= len(picks) * 0.6:
            lines.append(
                f"今天的盘子不错：{len(picks)} 个里有 <strong>{ind} 个能对上具体行业</strong>，"
                f"平均 {avg} 分。这种日子适合动手，因为买家是现成的，不用教育市场。"
            )
        else:
            lines.append(
                f"今天的盘面很杂：{len(picks)} 个候选平均 {avg} 分，"
                f"能对上具体行业的只有 {ind} 个。剩下的得靠你自己想场景，成本会高不少。"
            )

    # 第三句：排掉的东西，按真实原因归类说
    if dropped:
        reasons = {}
        for d in dropped:
            r = d["reason"]
            if "清单" in r:
                reasons["清单合集"] = reasons.get("清单合集", 0) + 1
            elif "绕过" in r or "破解" in r:
                reasons["合规红线"] = reasons.get("合规红线", 0) + 1
            elif "之外" in r:
                reasons["分数不够"] = reasons.get("分数不够", 0) + 1
            else:
                reasons["其它"] = reasons.get("其它", 0) + 1
        parts = "、".join(f"{k} {v} 个" for k, v in sorted(reasons.items(), key=lambda x: -x[1]))
        lines.append(
            f"排掉 <strong>{len(dropped)} 个</strong>：{parts}。"
            f"清单流看着最可惜——几十万星，但你交不出东西。"
        )
    return "\n".join(f"<p>{x}</p>" for x in lines)


def build_stats(picks, scanned, dropped):
    s = len([r for r in picks if r.get("grade") == "S"])
    multi = len([r for r in picks if r.get("license") in
                 ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "0BSD", "Unlicense", "CC0-1.0")])
    items = [
        (str(scanned), "扫描仓库"),
        (str(len(picks)), "进入候选"),
        (str(s), "S 级可动手"),
        (str(multi), "许可证干净"),
    ]
    return "".join(
        f'<div class="stat"><div class="n">{n}</div><div class="l">{l}</div></div>'
        for n, l in items
    )


def build_extra(dropped):
    if not dropped:
        return ""
    rows = "".join(
        f'<div style="display:flex;gap:14px;padding:8px 0;border-top:1px solid #F0ECE2">'
        f'<span style="flex:0 0 178px;font-size:13.5px;color:var(--ink);word-break:break-all;line-height:1.6">{esc(d["full_name"])}</span>'
        f'<span style="flex:1;font-size:13px;color:var(--ink-3);line-height:1.6">{esc(d["reason"])}</span>'
        f'</div>'
        for d in dropped[:12]
    )
    return f"""
<div class="sec"><span class="no">02</span><h2>今天排掉了什么</h2>
<span class="hint">不用看，理由在这</span></div>
<article class="card">
  <p class="what" style="margin-bottom:6px">雷达的价值一半在"选进来"，另一半在"挡出去"。以下项目星数够，但一个人接不了手，或者接手了也卖不出去：</p>
  {rows}
</article>"""


def render(date_str, picks, dropped, scanned, promo_html, issue=1, out_dir=None):
    tpl = TPL.read_text(encoding="utf-8")
    s_cnt = len([r for r in picks if r.get("grade") == "S"])
    h1 = (f'今天有 <em>{s_cnt} 个</em>能动手' if s_cnt
          else "今天没有能动手的")
    out = (tpl
           .replace("{{TITLE}}", esc(f"Git 副业雷达 · {date_str}"))
           .replace("{{H1}}", h1)
           .replace("{{DATE}}", esc(date_str))
           .replace("{{SCANNED}}", str(scanned))
           .replace("{{PICKED}}", str(len(picks)))
           .replace("{{ISSUE}}", str(issue))
           .replace("{{BRIEF}}", build_brief(picks, dropped, None))
           .replace("{{STATS}}", build_stats(picks, scanned, dropped))
           .replace("{{CARDS}}", "".join(card(i + 1, r) for i, r in enumerate(picks)))
           .replace("{{EXTRA}}", build_extra(dropped))
           .replace("{{PROMO}}", promo_html or "")
           .replace("{{GENERATED_AT}}", datetime.now().strftime("%Y-%m-%d %H:%M")))
    if out_dir:
        p = Path(out_dir) / f"Git副业雷达_{date_str}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out, encoding="utf-8")
        return p
    return out
