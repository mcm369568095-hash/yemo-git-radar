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

# 形态兜底：认不出行业时，按"谁会用这类工具"给买家。
# 每个形态给三个备选，是为了在同一份报告里换着说 ——
# 连着三张卡都写"天天用 AI 干活的人"，读者立刻看出这是模板。
FORM_BUYER = {
    "web应用": ["想有个自己工具但不会写代码的人", "要上线个小站但没预算请开发的人", "手上有客户、缺一个能演示的东西的人"],
    "引擎库": ["要用这套能力但搞不定环境的人", "接外包时缺一个现成轮子的人", "团队里没人会配环境的项目负责人"],
    "命令行": ["需要这套能力但装不上的人", "天天手工做重复活的人", "不想学编程但要用工具的人"],
    "Agent技能": ["天天用 AI 干活、但不知道装什么的人", "买了 AI 会员却只用来聊天的人", "想用 AI 但每次都从零写提示词的人"],
    "模板主题": ["想快速上线一个小产品的人", "接单缺模板所以要现成素材的人", "自己开店想换套门面的人"],
    "模型数据": ["要跑模型但搞不定环境和参数的人", "有数据但没有技术团队的人", "想试 AI 但显卡一般的人"],
}
GENERIC_BUYER = "想用这套东西但自己装不上的人"


def audience_of(repo, readme="", form="", avoid=None):
    """返回 (买家, 标签)。行业命中次数最多的胜出。

    avoid: 同一份报告里已经出现过的买家。整份报告八个卡全写"接单的设计师"，
    读者会觉得这是模板不是分析 —— 所以命中次数第二的行业顶上来。
    """
    avoid = avoid or set()
    blob = f"{repo.get('name','')} {repo.get('desc','')} {' '.join(repo.get('topics') or [])}".lower()
    hits = {}
    for pat, who, tag in INDUSTRY:
        c = len(re.findall(pat, blob))
        if c:
            hits[tag] = (c, who, tag)
    if hits:
        ranked = sorted(hits.values(), key=lambda x: -x[0])
        for _, who, tag in ranked:
            if who not in avoid:
                return who, tag
        # 认出的行业全被用过了：宁可重复，也不退回到"想用这套东西的人"——
        # 「卖给开网店的小老板」重复三次，仍然比八张卡全是泛泛买家有用。
        return ranked[0][1], ranked[0][2]
    alts = FORM_BUYER.get(form)
    if alts:
        for who in alts:
            if who not in avoid:
                return who, "通用"
        return alts[0], "通用"
    return GENERIC_BUYER, "通用"


# ---------------------------------------------------------------- 改哪一处

# 每个形态对应一组"下一个动作"。动作必须具体到今晚就能做，
# 不能出现"优化体验""提升品质"这种说了等于没说的话。
# 每种形态至少 5 条：报告里同形态项目常常占三四个，只有 3 条就必然复读。
ACTIONS = {
    "web应用": [
        ("没有中文界面", "把界面文案和按钮全翻成中文，再截一套中文版演示图当商品图"),
        ("没有在线演示", "部署一个公开 demo，让人先玩再决定买不买"),
        ("没有行业预设", "做 10 个行业预设（餐饮/教培/门店），一键套用"),
        ("出东西了带不走", "加一个一键导出（图/PDF/Excel），让人能直接拿去用"),
        ("第一次配置劝退", "内置 3 套成品模板，省掉从空白开始那一步"),
        ("没有上手视频", "录一条 3 分钟上手视频，替掉所有文字说明"),
    ],
    "引擎库": [
        ("只有代码没有界面", "包一层网页界面，让不会写代码的人点两下就能用"),
        ("没有中文上手文档", "把 README 翻成中文，配一张「三步跑通」流程图"),
        ("没有现成案例", "补 3 个真实场景示例，每个都能直接跑出结果"),
        ("环境装不上", "打包成 Docker 镜像或一键脚本，把依赖全封死"),
        ("没有效果对比", "做一组前后对比图，让人一眼看出值不值"),
        ("接口太难调", "写一层傻瓜封装，两行代码出结果"),
    ],
    "命令行": [
        ("要敲一长串参数", "封装成双击就能跑的脚本，把参数做成填空"),
        ("没有中文说明", "写一份「从装到出结果」的图文，每步配截图"),
        ("没有成品输出", "把输出直接做成能交出去的东西（图/表/PDF）"),
        ("批量处理要自己写", "加一个「选文件夹→出结果」的批量模式"),
        ("报错看不懂", "把常见报错做成中文对照表，每条附一句怎么办"),
    ],
    "Agent技能": [
        ("只有英文指令", "改写成中文指令版，加 3 个真实场景的开场白"),
        ("没有打包成技能", "整理成可直接安装的技能包，附使用截图"),
        ("没有效果对比", "做前后对比案例，让人一眼看出差别"),
        ("场景全是国外的", "把示例换成国内的活（公众号/小红书/电商），别用国外 demo"),
        ("不知道装到哪", "写一份「三步装完」图文，截一张装成功的界面"),
        ("指令太长记不住", "改成一话口语版，用户只要说需求就能触发"),
    ],
    "模板主题": [
        ("只是通用模板", "换成本地行业案例（餐饮/教培/门店），改文案和配色"),
        ("没有安装说明", "写一份「十分钟上线」步骤，配截图"),
        ("没有配套素材", "补一套同风格图片和字体，一起打包卖"),
        ("配色不合国内审美", "换一套国内审美的配色，出 3 个版本让人挑"),
        ("只有截图没有演示", "搭一个能点开看的演示站，比截图有说服力"),
    ],
    "模型数据": [
        ("部署门槛太高", "做成一键安装包，环境和参数全预设好"),
        ("没有中文说明", "写中文说明书 + 现成调用脚本"),
        ("没有使用场景", "补三个「拿来就能用」的场景脚本"),
        ("普通显卡跑不动", "换小模型 + 量化版，让人用自己电脑就能跑"),
        ("出结果还得调参", "给一套默认参数，打开就出可用结果"),
    ],
}
DEFAULT_ACTION = ("没有中文文档", "翻译并重写成中文教程，配一套可复制的步骤")

# ---------------------------------------------------------------- 怎么交付

# 每个形态三条交付路径。第一条最稳，后面的更适合有存量客户的人。
DELIVERY = {
    "web应用": (
        "打包部署到客户自己的服务器/域名，收一次部署费",
        "做成在线服务，按月收使用费",
        "连部署带教一次，做成「一天陪跑」按次收",
        "换成客户自己的数据跑一遍，按场景收定制费",
    ),
    "引擎库": (
        "做成带界面的成品，按份卖（发网盘，附中文说明）",
        "接单代跑：客户给需求，你出结果",
        "做成中文教程 + 成品包，走知识付费",
        "封装成 API 出租，按调用量收费",
    ),
    "命令行": (
        "做成图文教程 + 现成脚本包，一次付费长期用",
        "接单代跑，按次收费",
        "改成一键工具卖，附中文说明书",
        "做成月度订阅：脚本持续更新，老客户按月付",
    ),
    "Agent技能": (
        "打包成技能文件，配使用教程一起卖",
        "做成付费专栏的一章，当引流钩子",
        "接企业内训，教团队把这套装上",
        "做成定制版：按客户业务流程改一遍，单独报价",
    ),
    "模板主题": (
        "换 logo 配色文案，出一套同名 zip 直接卖",
        "做成「开箱即用版」发网盘，附中文说明",
        "按行业拆成多套，一套一个价",
        "接定制：照客户品牌重做一套，收设计费",
    ),
    "模型数据": (
        "做成一键安装包 + 中文说明书",
        "按调用次数做代跑服务",
        "装到客户机器上一次收清，再收维护费",
        "做成托管版：客户不装，直接用你的接口",
    ),
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


def build_pitch(repo, form, gaps, readme="", used=None, used_buyers=None, used_deliver=None):
    """返回 {change, buyer, deliver, hours, gap_key_word}

    used / used_buyers / used_deliver: 同一份报告里已经用过的动作、买家、交付方式。
    传进来就会优先挑没重复的 —— 不然八个卡全写"把界面翻成中文"、"打包部署收部署费"，
    报告看起来像复读机，读者翻两页就不看了。
    """
    used = used if used is not None else set()
    used_buyers = used_buyers if used_buyers is not None else set()
    used_deliver = used_deliver if used_deliver is not None else set()
    acts = ACTIONS.get(form, [DEFAULT_ACTION])
    gap_keys = {g[0] for g in gaps}

    pick = None
    # 第一优先：对上缺口 + 没被用过
    for name, act in acts:
        if name in gap_keys and act not in used:
            pick = (name, act)
            break
    # 第二优先：没被用过就行
    if not pick:
        for name, act in acts:
            if act not in used:
                pick = (name, act)
                break
    # 第三优先：动作都对得上缺口，哪怕重复也用（对得上比不重复重要）
    if not pick:
        for name, act in acts:
            if name in gap_keys:
                pick = (name, act)
                break
    # 实在全都用过了，才允许重复
    if not pick:
        pick = acts[0]
    name, action = pick
    who, tag = audience_of(repo, readme, form, avoid=used_buyers)
    alts = DELIVERY.get(form, DELIVERY["命令行"])
    deliver = next((x for x in alts if x not in used_deliver), alts[0])
    deliver_alt = next((x for x in alts if x not in used_deliver and x != deliver), alts[-1])
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
# GitHub 的 emoji 短码：`:black_heart:` `:rocket:` 这类不是 Unicode 字符，
# 上面那条正则清不掉，会原样出现在报告里。单独清一遍。
_SHORTCODE = re.compile(r":[a-z0-9_+\-]{2,32}:")


def plain_what(repo):
    """一句话说清这东西干啥。英文原文照搬，不硬翻——翻错比不翻更误导。"""
    d = (repo.get("desc") or "")
    d = _SHORTCODE.sub("", d)
    d = _EMOJI.sub("", d).strip(" -—·:,")
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
