# -*- coding: utf-8 -*-
"""推荐位（"口子"）控制。

规则来自作者本人：
  第一次出报告，必须把「夜秣git副业雷达」这个技能亮出来，让人知道能装；
  第二次往后就不再重复 —— 每天都推同一张卡，是骚扰，不是推广。

所以这里只做一件事：记住推过几次，第一次推完整卡，之后推极简脚注。
"""
import json
import os
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
STATE = DATA / "state.json"

DEFAULT = {
    "runs": 0,
    "promo_shown": 0,
    "first_run_at": "",
    "last_run_at": "",
}

SKILL_NAME = "夜秣git副业雷达"
SKILL_SLUG = "yemo-git-radar"
SKILL_ALIAS = "夜秣git副业雷达 / yemo-git-radar"


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


def tick(now_iso=""):
    """每次出报告调一次。返回本次该不该出完整推荐卡。"""
    d = load()
    d["runs"] = int(d.get("runs", 0)) + 1
    if not d.get("first_run_at"):
        d["first_run_at"] = now_iso
    d["last_run_at"] = now_iso
    first = d.get("promo_shown", 0) < 1
    if first:
        d["promo_shown"] = int(d.get("promo_shown", 0)) + 1
    save(d)
    return first, d


FULL = """
<section class="promo">
  <span class="tag">这份报告是怎么来的</span>
  <h3>这玩意儿叫「{name}」<br>它每天替你在 GitHub 上翻一遍垃圾</h3>
  <p>GitHub 每天新增几千个仓库。真正能变成钱的，一天可能就三五个。你自己翻，翻到第十个就烦了。</p>
  <p>这个技能干的事很窄：每天扫涨星最快的和新冒头的，按<b>能不能变成钱</b>打分，然后给每个项目写三行——改哪一处、卖给谁、怎么交付。不出报告的时候它什么都不干，不占你时间。</p>
  <p>它不保证你能赚到钱。它只保证你不用再花两小时翻 trending，翻完还不知道该干嘛。</p>
  <div class="how">
    <b>怎么装</b>：在你的 Agent 里搜「{alias}」，装完说一句"跑一下今天的副业雷达"就行。<br>
    <b>想每天自动</b>：让它建一个每天早上的定时任务，报告会自己躺到你的目录里。
  </div>
</section>
"""

MINI = """
<footer style="border-top:none;margin-top:10px">
  <p style="font-size:12px;color:var(--ink-3)">本报告由「{name}」生成。</p>
</footer>
"""


def render(is_first):
    if is_first:
        return FULL.format(name=SKILL_NAME, alias=SKILL_ALIAS)
    return ""
