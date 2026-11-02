# -*- coding: utf-8 -*-
"""HTML 报告渲染。所有视觉都在 templates/report.html 里，这里只管填数据。"""
import html
import re
from datetime import datetime
from pathlib import Path

import analy

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
    a = r.get("analy") or {}
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
    chips = []
    st = r.get("seen_times") or 0
    if st > 1:
        # 老面孔要明说。读者第二次看到同一个项目，不解释一句会以为雷达没更新
        chips.append(f'<span class="chip">第 {st} 次上榜 · 上次 {esc(r.get("seen_last",""))}</span>')
    chips += [f'<span class="chip">{esc(g2)}</span>' for g2 in r.get("gaps_short", [])]
    chips.append(f'<span class="chip">预计 {p.get("hours","?")} 小时跑起来</span>')
    chips.append(f'<span class="chip">{esc(r.get("form",""))}</span>')
    if r.get("risk"):
        chips.append(f'<span class="chip warn">{esc(r["risk"])}</span>')
    if r.get("suspect"):
        chips.append(f'<span class="chip warn">{esc(r["suspect"])}</span>')
    if g in ("S", "A"):
        chips.append('<span class="chip ok">可商用</span>')
    # 翻译质量分档。这不是装饰 —— 用户要拿这份报告发给客户，
    # 「AI 精译」和「机器直译」差的是一个能不能直接用的判断。
    state = analy.zh_state(a)
    if state == "llm":
        chips.append('<span class="chip ok">AI 精译</span>')
    elif state == "rule":
        chips.append('<span class="chip auto">机器直译 · 建议让 Agent 过一遍</span>')
    else:
        chips.append('<span class="chip warn">作者没写简介 · 建议手动补一句</span>')

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
  <div class="nums">{''.join(nums)}</div>
{layers_html(r, a)}
{usage_html(a)}
{how_html(a)}
{gap_html(a, p)}
{buyer_html(a, p)}
{duo_html(a)}
  <div class="foot">{''.join(chips)}</div>
</article>"""


# ---------------------------------------------------------------- 四层说明

def layers_html(r, a):
    # 保底顺序：精修 → 规则版 → 清洗过的简介（r['plain'] 已是清过的原文）
    en = a.get("en") or r.get("plain") or r.get("desc") or "（作者没写简介）"
    zh = a.get("zh") or "（没有译文）"
    plain = a.get("plain") or ""
    out = f"""
  <div class="layers">
    <div class="ly en"><span class="lb">原文</span><span class="tx">{esc(en)}</span></div>
    <div class="ly zh"><span class="lb">直译</span><span class="tx">{esc(zh)}</span></div>"""
    if plain:
        out += f"""
    <div class="ly plain"><span class="lb">说人话</span><span class="tx">{esc(plain)}</span></div>"""
    return out + "\n  </div>"


def _ul(items, ordered=False):
    if not items:
        return ""
    tag = "ol" if ordered else "ul"
    return f'<{tag}>' + "".join(f"<li>{esc(x)}</li>" for x in items) + f"</{tag}>"


def usage_html(a):
    if not a.get("usage"):
        return ""
    return f"""
  <div class="blk"><p class="blk-h">能干什么<span class="sub">拿去用在什么地方</span></p>
    {_ul(a["usage"])}
  </div>"""


def how_html(a):
    if not a.get("how"):
        return ""
    return f"""
  <div class="blk"><p class="blk-h">怎么用起来<span class="sub">从零到出结果</span></p>
    {_ul(a["how"], ordered=True)}
  </div>"""


def gap_html(a, p):
    gap = a.get("gap") or p.get("change")
    if not gap:
        return ""
    return f"""
  <div class="blk"><p class="blk-h">差哪一步<span class="sub">这就是你要补的活，也就是能卖钱的地方</span></p>
    <div class="gap-box"><p>{esc(gap)}</p></div>
  </div>"""


def buyer_html(a, p):
    buyer = a.get("buyer") or p.get("buyer")
    why = a.get("why")
    if not buyer:
        return ""
    why_html = f'<p style="margin-top:6px;color:var(--ink-2);font-size:14.8px">{esc(why)}</p>' if why else ""
    return f"""
  <div class="blk"><p class="blk-h">卖给谁<span class="sub">谁是这套东西的适用者</span></p>
    <div class="buyer-line">适用者：<b>{esc(buyer)}</b></div>{why_html}
  </div>"""


def duo_html(a):
    self_use = a.get("self")
    pack = a.get("pack")
    if not (self_use or pack):
        return ""
    cells = []
    if self_use:
        cells.append(f'<div><p class="blk-h">自用 · 你自己怎么用它</p><p>{esc(self_use)}</p></div>')
    if pack:
        cells.append(f'<div><p class="blk-h">打包出售 · 怎么变成商品</p><p>{esc(pack)}</p></div>')
    return f'<div class="duo">{"".join(cells)}</div>'


def build_brief(picks, dropped, stats):
    """三句话：第一句说今晚干什么，第二句说今天盘子什么样，第三句说排掉了什么。

    这三句是整份报告唯一"人在说话"的地方，不能写成统计播报。
    """
    lines = []

    def cl(s):
        # 动作文案自己可能带句号（精修版常带），拼进句子里会变成「。。」
        return esc(str(s or "").rstrip("。.;； "))

    s = [r for r in picks if r.get("grade") == "S"]
    a = [r for r in picks if r.get("grade") == "A"]

    if s:
        top = s[0]
        lines.append(
            f"今天只有 <strong>{len(s)} 个</strong>够 S 级。排第一的是 "
            f"<strong>{esc(top['full_name'])}</strong>：{esc(top['pitch']['buyer'])}会买，"
            f"今晚的活是{cl(top['pitch']['change'])}。"
        )
    elif a:
        top = a[0]
        lines.append(
            f"今天<strong>没有 S 级</strong>，最好的是 <strong>{esc(top['full_name'])}</strong>"
            f"（{top.get('score')} 分）。能做，但得先补一步才交得出去——{cl(top['pitch']['change'])}。"
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
    a = len([r for r in picks if r.get("grade") == "A"])
    multi = len([r for r in picks if r.get("license") in
                 ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "0BSD", "Unlicense", "CC0-1.0")])
    # 第三格跟着标题走：没有 S 级时写「8 个 A 级」，别让标题说「能卖」、数字说「0」
    if s:
        third = (str(s), "S 级可动手")
    elif a:
        third = (str(a), "A 级可改")
    else:
        third = ("0", "今晚没得动")
    items = [
        (str(scanned), "扫描仓库"),
        (str(len(picks)), "进入候选"),
        third,
        (str(multi), "许可证干净"),
    ]
    return "".join(
        f'<div class="stat"><div class="n">{n}</div><div class="l">{l}</div></div>'
        for n, l in items
    )


def sec_head(no, title, hint):
    return (f'<div class="sec"><span class="no">{no}</span><h2>{esc(title)}</h2>'
            f'<span class="hint">{esc(hint)}</span></div>')


BUCKETS = [
    ("new", "今日新上榜", "三个月内新建、已经起量的，还没被做烂"),
    ("hot", "涨星中", "今天或本周还在涨，说明需求正被验证"),
    ("veteran", "既往高星", "星多、今天没动 —— 沉淀下来的老底，做二创最省事"),
]


def build_pick_section(picks):
    """每日重点：全品类，不按方向分区。

    这个 tab 回答的是「今天全网在冒什么」，跟用户选了虚拟产品还是电商无关 ——
    想看自己那个方向，去右边「单独重点」。混在一起的结果是两边都看不清。
    """
    if not picks:
        return ('<div class="empty"><p>今天没有项目过线。</p>'
                '<p>这本身也是结论：要么全网在放假，要么涨的都是不能变现的。</p></div>', 2)
    head = sec_head("01", "今天能动手的", f"{len(picks)} 个，按能不能变成钱排，不是按星数")
    return head + "".join(card(i + 1, r) for i, r in enumerate(picks)), 2


FOCUS_EMPTY = """
<div class="empty">
  <p>这个 tab 放的是<b>你自己选的方向</b>，不是今天的全站榜单。</p>
  <p>说一句「我想找虚拟产品的项目」，或者跑<br>
  <code>python scripts/radar.py run --focus 虚拟产品</code></p>
  <p style="font-size:13px;margin-top:10px">说过一次就记住了，之后每天这部分自动按这个方向抓 ——
  今日新上榜、正在涨星的、攒下来的老底，分三块摆给你。</p>
</div>"""


def build_focus_panel(focus_tab, deep=None, kb=None):
    """单独重点：用户那个方向的专题，三块分开摆。

    为什么不混着按分数排：用户要的三样东西价值不一样。
    今天刚冒头的新项目可能分数低（star 少、issue 少），但它还没被做烂；
    老牌三万星的项目分数高，可你去做二创根本抢不过。混排的结果永远是老项目挤掉新面孔。
    """
    out = []
    if focus_tab:
        key = focus_tab.get("key") or ""
        total = sum(len(v or []) for v in (focus_tab.get("buckets") or {}).values())
        out.append(sec_head("01", f"方向专题 · {key}",
                            f"只在这个方向里挑，共 {total} 个，分三块看"))
        n = 0
        for bid, name, hint in BUCKETS:
            lst = (focus_tab.get("buckets") or {}).get(bid) or []
            if not lst:
                if bid == "hot":
                    # 头两天这栏必然空：涨星要靠跨天快照算差额，第一天没有"上次"
                    out.append('<p class="fn">「涨星中」今天空着 —— 这个方向今天没有项目在涨，'
                               '或者刚装上还没攒够跨天快照（涨星要靠前后两天对比才算得准）。</p>')
                continue
            out.append(f'<div class="subsec"><h3>{esc(name)}</h3>'
                       f'<span>{esc(hint)}</span></div>')
            for r in lst:
                n += 1
                out.append(card(n, r))
    elif not deep:
        return FOCUS_EMPTY
    else:
        # 有深挖但还没定方向：先把引导摆上，别让人以为这 tab 只有深挖
        out.append(FOCUS_EMPTY)

    if deep:
        out.append(sec_head("02" if focus_tab else "01",
                            "深挖档案", "点名要看的，拆到能动手为止"))
        out += [deep_card(r, i + 1) for i, r in enumerate(deep)]

    if not out:
        return FOCUS_EMPTY

    if kb and kb.get("days"):
        out.append(
            f'<div class="kbn"><p><b>已经攒了 {kb["days"]} 天、{kb["projects"]} 个项目。</b>'
            f'每天这批都会自动建档，想找以前看过的，问一句「雷达里搜 X」就行 —— '
            f'这就是你自己的选品库，不依赖任何平台。</p></div>')
    return "".join(out)


def build_extra(dropped, no=2):
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
<div class="sec"><span class="no">{no:02d}</span><h2>今天排掉了什么</h2>
<span class="hint">不用看，理由在这</span></div>
<article class="card">
  <p class="what" style="margin-bottom:6px">雷达的价值一半在"选进来"，另一半在"挡出去"。以下项目星数够，但一个人接不了手，或者接手了也卖不出去：</p>
  {rows}
</article>"""


# ---------------------------------------------------------------- 单独重点（深挖）

DEEP_EMPTY = """
<div class="empty">
  <p>这个 tab 是给<b>点名要看的项目</b>留的。</p>
  <p>跟 Agent 说一句「深挖 owner/repo」，或者命令行跑<br>
  <code>python scripts/radar.py deep owner/repo</code><br>
  它会把这一个项目从"能干嘛"到"怎么打包成商品"全拆一遍，放在这里。</p>
  <p style="font-size:13px;margin-top:10px">没有指定项目时，这里就是空的 —— 每日榜单在左边那个 tab。</p>
</div>"""


def deep_card(r, i=None):
    a = r.get("analy") or {}
    p = r.get("pitch", {})
    g = r.get("grade", "C")
    name = r.get("full_name", "")
    nums = [
        f"<span>{fmt(r.get('stars',0))} 总星</span>",
        f"<span>{fmt(r.get('forks',0))} fork</span>",
        f"<span>{esc(r.get('lang') or '未知语言')}</span>",
        f"<span>{esc(r.get('license') or '无许可证')}</span>",
        f"<span>{esc(r.get('form',''))}</span>",
        f"<span>综合 {r.get('score',0)}/100 · {g} 级</span>",
    ]
    say = a.get("plain") or "（还没有说明）"
    hero = f"""
<section class="deep-hero">
  <p class="k">单独重点 · 深挖</p>
  <h2><a href="{esc(r.get('url'))}" target="_blank" rel="noopener" style="color:#fff">{esc(name)}</a></h2>
  <p class="sub">作者 @{esc(r.get('owner'))} · {esc(r.get('grade_word',''))}</p>
  <p class="say">{esc(say)}</p>
  <div class="deep-nums">{''.join(nums)}</div>
</section>"""

    body = [hero]
    body.append(f"""
<div class="blk"><p class="blk-h">原文 <span class="sub">作者自己怎么说的</span></p>
  <p style="color:var(--ink-3);font-size:14px">{esc(a.get('en') or r.get('desc') or '（没写简介）')}</p>
  <p style="margin-top:6px">{esc(a.get('zh') or '')}</p>
</div>""")
    body.append(usage_html(a))
    body.append(how_html(a))
    body.append(gap_html(a, p))
    body.append(buyer_html(a, p))
    body.append(duo_html(a))

    if a.get("moat"):
        body.append(f"""
  <div class="blk"><p class="blk-h">门槛与风险<span class="sub">动手前得知道的</span></p>
    <p>{esc(a["moat"])}</p>
  </div>""")
    risks = [x for x in (r.get("risk"), r.get("suspect")) if x]
    if risks:
        body.append('<div class="blk"><p class="blk-h">另外两条<span class="sub">许可证 / 热度</span></p>'
                    + "".join(f'<p style="margin-bottom:5px">· {esc(x)}</p>' for x in risks) + "</div>")

    chips = [f'<span class="chip">{esc(x)}</span>' for x in (r.get("gaps_short") or [])]
    chips.append(f'<span class="chip">预计 {p.get("hours","?")} 小时跑起来</span>')
    state = analy.zh_state(a)
    chips.append('<span class="chip ok">AI 精译</span>' if state == "llm"
                 else '<span class="chip auto">机器直译</span>')
    return f'<article class="card {g.lower()}" style="margin-top:18px">{"".join(body)}<div class="foot">{"".join(chips)}</div></article>'


def deep_html(deep):
    if not deep:
        return DEEP_EMPTY
    head = sec_head("00", "点名深挖的这一个", "不是榜单，是把它拆开看")
    return head + "".join(deep_card(r, i + 1) for i, r in enumerate(deep))


MODE_HTML = {    "FULL": '<span class="pill">API 直取</span>',
    "LITE": '<span class="pill lite" title="没有配置 token，改从网页抓取，不消耗 API 额度">'
            '轻量通路 · 未用 API</span>',
}


THEMES = ("green", "day", "dark")


def render(date_str, picks, dropped, scanned, promo_html, issue=1, out_dir=None,
           mode="FULL", degraded=False, focus_tab=None, deep=None,
           history=None, kb=None, theme=""):
    tpl = TPL.read_text(encoding="utf-8")
    s_cnt = len([r for r in picks if r.get("grade") == "S"])
    a_cnt = len([r for r in picks if r.get("grade") == "A"])
    # 「没有 S 级」不等于「没有能动手的」—— A 级也是改一改就能卖。
    # 原来一律写「今天没有能动手的」，读者扫一眼标题就走了，8 张卡白给。
    if s_cnt:
        h1 = f'今天有 <em>{s_cnt} 个</em>能直接动手'
    elif a_cnt:
        h1 = f'今天有 <em>{a_cnt} 个</em>改一改能卖'
    else:
        h1 = "今天没有能动手的"

    pill = MODE_HTML.get(mode, MODE_HTML["FULL"])
    if degraded:
        pill = ('<span class="pill lite" title="跑到中途 API 额度用完了，自动切到网页通路">'
                '中途降级 · 部分字段为估算</span>')
    fk = (focus_tab or {}).get("key")
    if fk:
        pill += f'<span class="pill focus">盯着 · {esc(fk)}</span>'
    reused = len([r for r in picks
                  if (r.get("seen_times") or 0) > 0 and r.get("seen_last") != date_str])
    if reused:
        # 新料不够时的回看必须明说。不说的话读者会发现"怎么又是这几个"，
        # 然后怀疑雷达没在工作 —— 其实恰恰是查重在起作用。
        pill += (f'<span class="pill lite" title="今天新项目不够填满名额，'
                 f'这几个是之前推过、冷却期被放宽的">{reused} 个回看</span>')

    note = ""
    if mode == "LITE" or degraded:
        # 这段落在深色 .brief 区块里，必须用浅色，否则对比度不够看不清
        note = (
            '<p style="font-size:13.5px;line-height:1.7;'
            'color:rgba(242,239,232,.62);border-top:1px solid rgba(242,239,232,.16);'
            'padding-top:12px;margin:16px 0 0">'
            '这一期没走 API（没配 token 或额度用尽），许可证和 README 是从仓库网页读的，'
            '体积、issue 数、创建时间拿不到真实值 —— 相应维度按保守值给分并整体折了 6%，'
            '所以分数偏低，不会虚高。</p>'
        )

    # 默认摸鱼绿 —— 马总点名的配色。另外两套随时可点。
    th = (theme or "green").strip().lower()
    if th not in THEMES:
        th = "green"
    th_attr = {t: ("checked" if t == th else "") for t in THEMES}

    pick_html, next_no = build_pick_section(picks)
    focus_html = build_focus_panel(focus_tab, deep, kb)

    out = (tpl
           .replace("{{TITLE}}", esc(f"Git 副业雷达 · {date_str}"))
           .replace("{{H1}}", h1)
           .replace("{{DATE}}", esc(date_str))
           .replace("{{SCANNED}}", str(scanned))
           .replace("{{PICKED}}", str(len(picks)))
           .replace("{{ISSUE}}", str(issue))
           .replace("{{MODE}}", pill)
           .replace("{{TH_GREEN}}", th_attr["green"])
           .replace("{{TH_DAY}}", th_attr["day"])
           .replace("{{TH_DARK}}", th_attr["dark"])
           .replace("{{BRIEF}}", build_brief(picks, dropped, None) + note)
           .replace("{{STATS}}", build_stats(picks, scanned, dropped))
           .replace("{{PICK_SECTION}}", pick_html)
           .replace("{{EXTRA}}", build_extra(dropped, no=next_no))
           .replace("{{FOCUS_PANEL}}", focus_html)
           .replace("{{PROMO}}", promo_html or "")
           .replace("{{GENERATED_AT}}", datetime.now().strftime("%Y-%m-%d %H:%M")))
    if out_dir:
        p = Path(out_dir) / f"Git副业雷达_{date_str}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out, encoding="utf-8")
        return p
    return out
