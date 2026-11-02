# -*- coding: utf-8 -*-
"""变现可行性评分。

设计原则：**不按"多火"排序，按"多好卖"排序。**
一个 8000 星但 AGPL + 纯 C++ + 无文档的项目，对想赚点钱的人来说价值低于
一个 900 星 MIT + Python + 一键 docker 的项目。

六维打分（满分 100）+ 一道硬淘汰。
所有阈值都写在这里，改一行就能调，不要散落到别处。
"""
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------- 常量表

# 可商用度：能不能改完就卖，是变现的第一道门
LICENSE_SCORE = {
    "MIT": 25, "Apache-2.0": 25, "BSD-2-Clause": 25, "BSD-3-Clause": 25,
    "ISC": 25, "0BSD": 25, "Unlicense": 25, "CC0-1.0": 25,
    "MPL-2.0": 15, "LGPL-3.0": 15, "LGPL-2.1": 15,
    "GPL-3.0": 5, "GPL-2.0": 5, "AGPL-3.0": 5,
    "NOASSERTION": 8, "": 8,
}
LICENSE_RISK = {
    "GPL-3.0": "GPL：你改完的代码必须开源，卖闭源产品有法律风险",
    "GPL-2.0": "GPL：同上，改动必须开源",
    "AGPL-3.0": "AGPL：连「部署成网络服务」都算分发，必须开源，最不适合商用",
    "NOASSERTION": "许可证不明，用之前必须去 README 确认，否则可能踩坑",
    "": "没有许可证文件。默认视为「保留所有权利」，严格说不能商用",
}

# 上手成本：自己都跑不起来，就别谈卖了
LANG_SCORE = {
    "Python": 20, "JavaScript": 20, "TypeScript": 20, "Go": 20,
    "HTML": 20, "Shell": 18, "Vue": 18, "Svelte": 18,
    "Java": 16, "Kotlin": 16, "Swift": 16, "Dart": 16, "C#": 16,
    "PHP": 16, "Ruby": 16, "Jupyter Notebook": 17,
    "Rust": 12, "C": 10, "C++": 10, "Zig": 10, "CUDA": 8,
}


# ---------------------------------------------------------------- 工具

def _parse_dt(s):
    """认 GitHub 的 ISO 时间。Z 结尾、+00:00 结尾、带微秒、只有日期，都要能吃。

    只认一种格式是个隐患：轻量通路是从网页/静态文件里抠字段的，
    格式和 API 不完全一样，认不出来就静默返回 9999 天，
    后面所有日期判断（时效红利、一年多没提交、星速）全部失效。
    """
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                d = datetime.strptime(s.split("+")[0].split(".")[0], fmt)
                break
            except Exception:
                d = None
        if d is None:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def days_since(s):
    d = _parse_dt(s)
    if not d:
        return 9999
    return max(0, (datetime.now(timezone.utc) - d).days)


def cjk_ratio(text):
    if not text:
        return 0.0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return cjk / max(1, len(text))


# ---------------------------------------------------------------- 硬淘汰

# 合规红线：这些东西技术上能跑，但拿去卖会给买家招来麻烦（甚至法律责任）。
# 雷达宁可漏掉机会，也不能把人往坑里带。
COMPLIANCE_RISK = re.compile(
    r"(jailbreak|破甲|越狱|解除限制|绕过(审核|风控|付费|限制)|"
    r"破解|爆破|crack|keygen|bypass\s*(paywall|filter|policy|limit)|"
    r"薅羊毛|白嫖|盗版|piracy|外挂|cheat\s*engine|"
    r"爬虫.*(付费墙|登录墙)|scrape.*(paywall|behind\s*login))",
    re.I,
)


def reject_reason(r):
    """返回淘汰原因，None 表示通过。"""
    if r.get("archived"):
        return "项目已归档"
    if r.get("stars", 0) < 50:
        return "星数太少，需求没被验证"
    # 拿不到提交时间（轻量通路）时不要当"年久失修"——缺数据不等于项目死了。
    # 能上 trending 本身就说明刚有人在动它。
    pushed = r.get("pushed_at")
    if pushed and days_since(pushed) > 365:
        return "一年多没提交，代码可能已经跑不动"

    name = (r.get("name") or "").lower()
    desc = (r.get("desc") or "")
    topics = " ".join(r.get("topics") or [])

    # 纯合集/清单：不能跑、不能交付，只能当读物
    blob_desc = f"{name} {desc}".lower()
    if name.startswith("awesome") or re.search(
            r"(a\s+list\s+of|list\s+of|collection\s+of|collective\s+list|curated\s+list|awesome[\s-]list)",
            blob_desc):
        return "纯清单/合集，没有可运行的代码，不能交付"
    if "awesome-list" in topics.lower():
        return "纯清单/合集，没有可运行的代码，不能交付"

    # 合规红线
    if COMPLIANCE_RISK.search(f"{name} {desc} {topics}"):
        return "涉及绕过平台限制或破解，能跑但不能拿去做商品，跳过"
    return None



# ---------------------------------------------------------------- 六维打分

def score(r, readme=""):
    """r: repo 详情 dict；readme: README 前段文本。返回 (总分, 明细dict)"""
    detail = {}
    topics = " ".join(r.get("topics") or [])
    blob = f"{r.get('desc','')} {topics} {readme}".lower()

    # 1 可商用 25
    lic = r.get("license") or ""
    s1 = LICENSE_SCORE.get(lic, 8)
    detail["lic"] = s1

    # 2 上手 20
    s2 = LANG_SCORE.get(r.get("lang") or "", 14)
    if re.search(r"docker|compose", blob):
        s2 = min(20, s2 + 3)
    if r.get("homepage"):
        s2 = min(20, s2 + 2)
    detail["easy"] = s2

    # 3 中文友好 15
    s3 = 0
    if cjk_ratio(r.get("desc") or "") > 0.15:
        s3 += 8
    if cjk_ratio(readme[:2000]) > 0.08:
        s3 += 7
    if re.search(r"chinese|中文", topics, re.I):
        s3 += 3
    s3 = min(15, s3)
    detail["zh"] = s3

    # 4 需求真实 20 —— 用 issue/star 比当"有人在真用"的代理指标
    stars = max(1, r.get("stars", 1))
    oi = r.get("open_issues")
    if oi is None:
        # 轻量通路拿不到 issue 数。缺数据不等于没人用：
        # 一天涨几十上百星，本身就是"一堆人在关注"的证据。
        g = r.get("gained") or 0
        s4 = 15 if g >= 100 else 13 if g >= 30 else 10
    else:
        ratio = oi / stars
        if ratio >= 0.02:
            s4 = 20
        elif ratio >= 0.005:
            s4 = 16
        else:
            s4 = 10
    if r.get("has_discussions"):
        s4 += 2
    if days_since(r.get("pushed_at")) <= 7:
        s4 += 2
    s4 = min(20, s4)
    detail["demand"] = s4

    # 5 交付轻 10 —— 仓库越小越好打包，太大意味着依赖地狱
    kb = r.get("size_kb", 0)
    if kb < 5_000:
        s5 = 10
    elif kb < 30_000:
        s5 = 7
    elif kb < 100_000:
        s5 = 4
    else:
        s5 = 2
    detail["deliver"] = s5

    # 6 时效红利 10 —— 越新越少人做，越容易吃到第一波
    created = r.get("created_at")
    if created:
        age = days_since(created)
        if age <= 30:
            s6 = 10
        elif age <= 60:
            s6 = 7
        elif age <= 90:
            s6 = 5
        elif age <= 180:
            s6 = 3
        else:
            s6 = 1
    else:
        # 轻量通路拿不到创建时间，用"今天涨了多少星"当新鲜度的替身
        g = r.get("gained") or 0
        s6 = 7 if g >= 100 else 5 if g >= 30 else 3 if g >= 10 else 2
    detail["fresh"] = s6

    total = sum(detail.values())

    # 7 个人可接手度（±）—— 这一条是雷达的良心。
    # 光看"能不能商用/好不好装"不够，还得问：这活儿一个人接得住吗？
    # 一个要八卡 GPU 的推理框架，许可证再干净也不是副业。
    adj = 0
    infra = re.search(r"\b(cuda|gpu|distributed|multi-node|cluster|tensorrt|vllm|"
                      r"inference\s*(framework|engine)|training\s*framework|kernel)\b",
                      f"{r.get('desc','')} {' '.join(r.get('topics') or [])} {readme[:1200]}".lower())
    if infra:
        adj -= 12
    if re.search(r"\b(framework|sdk|infrastructure|runtime|compiler|protocol)\b",
                 f"{r.get('desc','')} {' '.join(r.get('topics') or [])}".lower()):
        adj -= 6
    if r.get("owner_type") == "Organization" and (r.get("stars") or 0) > 20000:
        adj -= 8
    # 反过来，能对上具体行业的，价值要高得多——因为买家能直接找到
    try:
        from pitch import INDUSTRY
        for pat, _, _ in INDUSTRY:
            if re.search(pat, f"{r.get('desc','')} {' '.join(r.get('topics') or [])}".lower()):
                adj += 8
                break
    except Exception:
        pass
    detail["adj"] = adj

    # 轻量通路有三项是估的，整体再折 6%。
    # 不折的话会出现"字段缺得越多分越高"——替代证据比真实数据还宽松，那就本末倒置了。
    if r.get("_partial"):
        total = int(total * 0.94)

    total = max(0, min(100, total + adj))
    return total, detail


def grade(total):
    if total >= 80:
        return "S", "今晚就能动手"
    if total >= 65:
        return "A", "改一改能卖"
    if total >= 50:
        return "B", "值得研究"
    return "C", "只看不碰"


# ---------------------------------------------------------------- 形态与缺口

# 形态决定"怎么交付"，比行业更能左右打法：
# 同样是 5000 星，一个 web 应用能卖部署费，一个纯库只能卖教程。
FORM_ORDER = [
    ("Agent技能", r"(agent\s*skill|claude\s*skill|\bskills?\b|提示词|prompt\s*(pack|template|library))"),
    ("模板主题", r"(boilerplate|starter|template|scaffold|theme|ui\s*kit|模板|脚手架)"),
    ("模型数据", r"(model\s*weights|checkpoint|gguf|safetensors|dataset|foundation\s*model|推理框架|模型权重)"),
    ("web应用", r"(dashboard|platform|\bsaas\b|\bcms\b|\bstudio\b|editor|website|web\s*app|管理后台|在线工具|"
                r"\bbot\b|assistant|coworker|浏览器|界面)"),
    ("命令行", r"(\bcli\b|command-line|terminal|\bshell\b|命令行|脚本工具)"),
]

# 前端技术栈出现，基本可以断定是个能跑起来的网页应用
WEB_STACK = re.compile(r"(npm\s+(run|install)|pnpm|yarn|next\.js|nuxt|react|vue|svelte|tailwind|"
                       r"vite|webpack|localhost:\d{4}|http://localhost)",
                       re.I)


def classify_form(r, readme=""):
    blob = f"{r.get('name','')} {r.get('desc','')} {' '.join(r.get('topics') or [])}".lower()
    for label, pat in FORM_ORDER:
        if re.search(pat, blob):
            return label
    # 兜底：README 里出现 npm run dev / react / localhost:3000 这类，基本就是网页应用
    if WEB_STACK.search(readme or ""):
        return "web应用"
    return "引擎库"


def find_gaps(r, readme):
    """找出这个项目"缺什么"。缺什么，就是你能改什么、就能卖什么。

    ★ 中文判断必须直接看 README 里的汉字比例，不能搜"中文"这个词。
      早期版本搜关键词，结果全中文的项目被判成"没有中文本地化"，闹了笑话。
    """
    gaps = []
    zh_ok = cjk_ratio(readme[:2000]) > 0.05
    if not zh_ok:
        gaps.append(("没有中文上手文档", "没有中文上手文档", "把 README 翻成中文，配一张三步跑通图"))

    is_web = bool(re.search(r"(dashboard|platform|studio|editor|web|admin|界面|后台)",
                            f"{r.get('desc','')} {' '.join(r.get('topics') or [])}".lower()))
    if is_web and not re.search(r"(i18n|locale|多语言|中文)", f"{r.get('desc','')} {readme[:1500]}".lower()):
        gaps.append(("没有中文界面", "没有中文界面", "把界面文案和按钮全翻成中文，截一套中文版演示图"))

    if not re.search(r"(docker|compose)", f"{r.get('desc','')} {readme}".lower()):
        gaps.append(("没有一键部署", "没有一键部署", "补一个 Dockerfile + compose，别人一条命令跑起来"))

    if not r.get("homepage") and not re.search(r"(demo|live|online|preview|在线|演示)",
                                               f"{r.get('desc','')} {readme[:1500]}".lower()):
        gaps.append(("没有在线演示", "没有在线演示", "部署一个公开 demo 站，让人先玩再买单"))

    if not gaps:
        gaps.append(("已经比较齐整", "文档和部署都齐了", "往垂直场景做深：换皮、加行业模板、做托管服务"))
    return gaps[:3]


def velocity(r, span_days=None):
    """星速 = 单位时间涨的星。trending 源直接有 gained，新建项目用 age 推算。"""
    g = r.get("gained") or 0
    if span_days:
        return g / max(1, span_days)
    age = max(1, days_since(r.get("created_at")))
    return (r.get("stars") or 0) / age if age < 400 else 0


# ---------------------------------------------------------------- 星速可疑

# 一个仓库短期内暴涨到离谱的量级，通常三种情况：真被大 V 转了一次、
# 刷星买榜、或者数据本身就是营销出来的。三种情况下都不该让人今晚就动手——
# 刷出来的热度没有真实用户，你做出的二创也没人接。
SUSPECT_PER_DAY = 700      # 平均每天涨 700 星以上，值得看一眼
SUSPECT_WINDOW = 180       # 只看建号 180 天内的；老仓库总量大很正常


def star_suspect(r):
    """返回一句警示，没问题返回空串。"""
    created = r.get("created_at")
    if not created:
        return ""
    age = days_since(created)
    if age >= SUSPECT_WINDOW:
        return ""
    stars = r.get("stars") or 0
    per_day = stars / max(1, age)
    if per_day < SUSPECT_PER_DAY:
        return ""
    return (f"星速可疑：{age} 天涨到 {stars:,} 星（日均 {int(per_day):,}），"
            f"先观察一周看有没有真实用户再动手")

