# -*- coding: utf-8 -*-
"""推荐位（"口子"）控制 + 署名。

两条规矩，作者本人定的：
  · 第一次出报告，把「夜秣git副业雷达」完整亮一次 —— 让人知道有这么个东西、怎么装；
  · 第二次往后不再重复整卡，但**署名永远在** —— 每天推同一张卡是骚扰，
    把自己的名字藏起来是没礼貌。两者不一样。

所以这里做两件事：记住推过几次；第一次给整卡，之后给一行脚注。
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
STATE = DATA / "state.json"

DEFAULT = {
    "runs": 0,
    "promo_shown": 0,
    "first_run_at": "",
    "last_run_at": "",
    "autosched_asked": 0,
}

# ── 作者信息：改这四处就改完全站署名 ──────────────────────
SKILL_NAME = "夜秣git副业雷达"
SKILL_SLUG = "yemo-git-radar"
SKILL_ALIAS = "夜秣git副业雷达 / yemo-git-radar"
AUTHOR = "夜秣"
WECHAT = "夜秣AI搞钱"
SKILLHUB = "夜秣"


def load():
    DATA.mkdir(parents=True, exist_ok=True)
    if not STATE.exists():
        return dict(DEFAULT)
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        return {**DEFAULT, **d}
    except Exception:
        return dict(DEFAULT)


def save(d):
    DATA.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def tick(now_iso="", day=""):
    """每次出报告调一次。返回本次该不该出完整推荐卡。

    🔴 「第几期」按**天数**算，不按渲染次数算。
    同一天调三次 render/analyze/deep，期号不该从第 1 期跳到第 4 期 ——
    那不叫期号，那叫渲染次数，读者会以为漏看了两期。
    """
    d = load()
    if day:
        if day != d.get("last_date"):
            d["runs"] = int(d.get("runs", 0)) + 1
            d["last_date"] = day
    else:
        d["runs"] = int(d.get("runs", 0)) + 1
    if not d.get("first_run_at"):
        d["first_run_at"] = now_iso
    d["last_run_at"] = now_iso
    first = int(d.get("promo_shown", 0)) < 1
    if first:
        d["promo_shown"] = int(d.get("promo_shown", 0)) + 1
    save(d)
    return first, d


def need_ask_sched():
    """要不要提示「配成每天 8 点自动出报告」。

    只问一次。用户答过（同意或拒绝）就置 1，之后不再烦他。
    重装/清空 data 会再问一次，这正是想要的 —— 新机器上本来就该问。
    """
    d = load()
    return not int(d.get("autosched_asked", 0)) and int(d.get("runs", 0)) >= 1


def mark_sched_asked():
    d = load()
    d["autosched_asked"] = 1
    save(d)


FULL = """
<section class="promo">
  <span class="tag">这份报告是怎么来的</span>
  <h3>这玩意儿叫「{name}」<br>它每天替你在 GitHub 上翻一遍垃圾</h3>
  <p>GitHub 每天新增几千个仓库。真正能变成钱的，一天可能就三五个。你自己翻，翻到第十个就烦了。</p>
  <p>这个技能干的事很窄：每天扫涨星最快的和新冒头的，按<b>能不能变成钱</b>打分，然后给每个项目写三行——改哪一处、卖给谁、怎么交付。不出报告的时候它什么都不干，不占你时间。</p>
  <p>它不保证你能赚到钱。它只保证你不用再花两小时翻 trending，翻完还不知道该干嘛。</p>
  <div class="how">
    <b>怎么装</b>：在你的 Agent 里搜「{alias}」，装完说一句"跑一下今天的副业雷达"就行。<br>
    <b>想每天自动</b>：让它建一个每天早上的定时任务，报告会自己躺到你的目录里。<br>
    <b>找我</b>：公众号「{wechat}」 · SkillHub 搜「{skillhub}」 · 作者 {author}
  </div>
</section>
"""

MINI = """
<div class="signature">
  <p>「{name}」生成 · 作者 <b>{author}</b> · 公众号 <b>{wechat}</b> · SkillHub <b>{skillhub}</b></p>
</div>
"""


def render(is_first):
    if is_first:
        return FULL.format(name=SKILL_NAME, alias=SKILL_ALIAS, author=AUTHOR,
                           wechat=WECHAT, skillhub=SKILLHUB)
    return MINI.format(name=SKILL_NAME, author=AUTHOR, wechat=WECHAT, skillhub=SKILLHUB)
