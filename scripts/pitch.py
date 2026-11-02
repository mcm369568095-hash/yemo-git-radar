# -*- coding: utf-8 -*-
"""三行落地：改哪一处 → 卖给谁 → 怎么交付。

这一步是雷达和"榜单"的分界线。
榜单告诉你"这个项目有 8000 星"，这三行告诉你"今晚该动哪一处、明天找谁收钱"。

纯规则生成，不依赖大模型，所以能无人值守跑。
Agent 在场时可以用 LLM 覆写 pitch 字段（见 SKILL.md 第二步），规则版是兜底。
"""
import re

# ---------------------------------------------------------------- 卖给谁

# 先认行业，再认形态。具体行业永远比"AI 工具"这种大词值钱——
# 因为"卖给做玄学号的人"你能直接搜到人，"卖给想用 AI 的人"你搜不到。
INDUSTRY = [
    (r"(紫微|八字|命理|斗数|塔罗|风水|占卜|ziwei|bazi|tarot|astrology|horoscope)", "做玄学/命理内容的号主", "玄学"),
    (r"(养生|中医|健康|体检|食谱|减肥|健身|nutrition|fitness|health)", "做健康养生的内容号", "健康"),
    (r"(教育|课程|题库|考试|刷题|单词|网课|教学|\bedu\b|\bquiz|learn(ing)?\s*(platform|app)|students?)", "做课和卖资料的老师", "教育"),
    (r"(电商|商城|店铺|下单|购物车|带货|shopify|ecommerce|woocommerce)", "开网店的小老板", "电商"),
    (r"(视频|字幕|配音|剪辑|短视频|tts|subtitle|video|audio|speech)", "做短视频的剪辑号", "视频"),
    (r"(设计|海报|配图|figma|图片|image|design|photoshop|midjourney)", "接单的设计师和电商美工", "设计"),
    (r"(写作|文案|公众号|小红书|自媒体|排版|copywriting|newsletter|wechat)", "做自媒体的人", "内容"),
    (r"(客服|私域|自动回复|机器人|telegram|whatsapp|chatbot|customer)", "要自动回消息的商家", "客服"),
    (r"(数据|报表|采集|爬虫|excel|表格|抓取|scrape|crawler|analytics|dashboard)", "要做数据但不会写代码的人", "数据"),
    (r"(文档|pdf|markdown|笔记|知识库|wiki|ocr|document)", "要整理归档资料的人", "文档"),
    (r"(合同|法律|发票|财税|记账|报税|invoice|legal|tax|accounting)", "小微企业老板和会计", "财税"),
    (r"(求职|简历|招聘|面试|resume|hiring|recruit)", "找工作和招人的双方", "求职"),
    (r"(宠物|母婴|装修|家居|房产|旅游|餐饮|门店|本地)", "本地小店的店主", "本地生意"),
]

# 形态兜底：认不出行业时，按"谁会用这类工具"给买家
FORM_BUYER = {
    "web应用": "想有个自己工具但不会写代码的人",
    "引擎库": "要用这套能力但搞不定环境的人",
    "命令行": "需要这套能力但装不上的人",
    "Agent技能": "天天用 AI 干活、但不知道装什么的人",
    "模板主题": "想快速上线一个小产品的人",
    "模型数据": "要跑模型但搞不定环境和参数的人",
}


def audience_of(repo, readme="", form=""):
    """返回 (买家, 标签)。行业命中次数最多的胜出。"""
    blob = f"{repo.get('name','')} {repo.get('desc','')} {' '.join(repo.get('topics') or [])}".lower()
    hits = {}
    for pat, who, tag in INDUSTRY:
        c = len(re.findall(pat, blob))
        if c:
            hits[tag] = (c, who, tag)
    if hits:
        best = max(hits.values(), key=lambda x: x[0])
        return best[1], best[2]
    return FORM_BUYER.get(form, "想用这套东西但自己装不上的人"), "通用"


# ---------------------------------------------------------------- 改哪一处

# 每个形态对应一组"下一个动作"。动作必须具体到今晚就能做，
# 不能出现"优化体验""提升品质"这种说了等于没说的话。
ACTIONS = {
    "web应用": [
        ("没有中文界面", "把界面文案和按钮全翻成中文，再截一套中文版演示图当商品图"),
        ("没有在线演示", "部署一个公开 demo，让人先玩再决定买不买"),
        ("没有行业预设", "做 10 个行业预设（餐饮/教培/门店），一键套用"),
    ],
    "引擎库": [
        ("只有代码没有界面", "包一层网页界面，让不会写代码的人点两下就能用"),
        ("没有中文上手文档", "把 README 翻成中文，配一张「三步跑通」流程图"),
        ("没有现成案例", "补 3 个真实场景示例，每个都能直接跑出结果"),
    ],
    "命令行": [
        ("要敲一长串参数", "封装成双击就能跑的脚本，把参数做成填空"),
        ("没有中文说明", "写一份「从装到出结果」的图文，每步配截图"),
        ("没有成品输出", "把输出直接做成能交出去的东西（图/表/PDF）"),
    ],
    "Agent技能": [
        ("只有英文指令", "改写成中文指令版，加 3 个真实场景的开场白"),
        ("没有打包成技能", "整理成可直接安装的技能包，附使用截图"),
        ("没有效果对比", "做前后对比案例，让人一眼看出差别"),
    ],
    "模板主题": [
        ("只是通用模板", "换成本地行业案例（餐饮/教培/门店），改文案和配色"),
        ("没有安装说明", "写一份「十分钟上线」步骤，配截图"),
        ("没有配套素材", "补一套同风格图片和字体，一起打包卖"),
    ],
    "模型数据": [
        ("部署门槛太高", "做成一键安装包，环境和参数全预设好"),
        ("没有中文说明", "写中文说明书 + 现成调用脚本"),
        ("没有使用场景", "补三个「拿来就能用」的场景脚本"),
    ],
}
DEFAULT_ACTION = ("没有中文文档", "翻译并重写成中文教程，配一套可复制的步骤")

# ---------------------------------------------------------------- 怎么交付

DELIVERY = {
    "web应用": ("打包部署到客户自己的服务器/域名，收一次部署费", "做成在线服务，按月收使用费"),
    "引擎库": ("做成带界面的成品，按份卖（发网盘，附中文说明）", "接单代跑：客户给需求，你出结果"),
    "命令行": ("做成图文教程 + 现成脚本包，一次付费长期用", "接单代跑，按次收费"),
    "Agent技能": ("打包成技能文件，配使用教程一起卖", "做成付费专栏的一章，当引流钩子"),
    "模板主题": ("换 logo 配色文案，出一套同名 zip 直接卖", "做成「开箱即用版」发网盘，附中文说明"),
    "模型数据": ("做成一键安装包 + 中文说明书", "按调用次数做代跑服务"),
}

# 语言 → 上手小时数。给"今晚能不能动手"一个实数，别让人凭感觉估。
TIME_COST = {
    "Python": 2, "JavaScript": 2, "TypeScript": 3, "HTML": 1, "Shell": 1,
    "Go": 3, "Java": 5, "Kotlin": 6, "Swift": 6, "Dart": 4, "C#": 4,
    "PHP": 2, "Ruby": 2, "Vue": 2, "Svelte": 2, "Jupyter Notebook": 2,
    "Rust": 8, "C": 8, "C++": 9, "Zig": 8, "CUDA": 6,
}


def est_hours(repo):
    base = TIME_COST.get(repo.get("lang") or "", 4)
    kb = repo.get("size_kb", 0)
    if kb > 150_000:
        base += 4
    elif kb > 50_000:
        base += 2
    if repo.get("has_discussions"):
        base -= 1
    return max(1, base)


def build_pitch(repo, form, gaps, readme=""):
    """返回 {change, buyer, deliver, hours, gap_key_word}"""
    acts = ACTIONS.get(form, [DEFAULT_ACTION])
    gap_keys = {g[0] for g in gaps}
    pick = None
    for name, act in acts:
        if name in gap_keys:
            pick = (name, act)
            break
    if not pick:
        pick = acts[0]
    name, action = pick
    who, tag = audience_of(repo, readme, form)
    deliver, deliver_alt = DELIVERY.get(form, DELIVERY["命令行"])
    return {
        "gap_key": name,
        "change": action,
        "buyer": who,
        "buyer_tag": tag,
        "deliver": deliver,
        "deliver_alt": deliver_alt,
        "hours": est_hours(repo),
        "gap_key_word": name,
    }


# ---------------------------------------------------------------- 说明与风险

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF]+")


def plain_what(repo):
    """一句话说清这东西干啥。英文原文照搬，不硬翻——翻错比不翻更误导。"""
    d = _EMOJI.sub("", (repo.get("desc") or "")).strip(" -—·:")
    if not d:
        return "作者没写简介，得打开仓库才知道是什么"
    return d


RISK = {
    "GPL-3.0": "GPL：改了必须开源，卖闭源产品有法律风险",
    "GPL-2.0": "GPL：改了必须开源",
    "AGPL-3.0": "AGPL：连做成网络服务都算分发，必须开源，商用最麻烦",
    "NOASSERTION": "许可证不明，动手前去 README 确认一遍",
    "": "没有 LICENSE 文件，严格说不能商用",
}


def risk_note(repo):
    lic = repo.get("license") or ""
    if lic in RISK:
        return RISK[lic]
    if repo.get("owner_type") == "Organization" and (repo.get("stars") or 0) > 20000:
        return "大厂项目，路线不由你定，只能做外围（部署/中文化/模板）"
    if (repo.get("stars") or 0) > 30000:
        return "体量太大，改源码成本高，建议只做外围服务"
    return ""
