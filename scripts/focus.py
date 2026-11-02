# -*- coding: utf-8 -*-
"""方向库：用户说「我想找虚拟产品方向的项目」，这里负责把它翻译成能搜出东西的查询。

2026-11-02 实测结论（决定了这里的写法）：
  · `topic:presentation stars:>200`  → 107 条，全是真项目（ppt-master 7.2万星、slidev、reveal.js）
  · `ppt in:name stars:>200`         → 95 条，干净
  · `notion template in:name,description` → **1 条**，多词短语几乎搜不到
  · `topic:a OR topic:b`             → Validation Failed，topic 不支持 OR

所以：**topic 为主，in:name 为辅，别写多词短语。**
topic 查不到（0 条）时自动退回 in:name，保证任何方向都搜得出东西。
"""
import re

# 每个方向：
#   topics    GitHub 真实 topic（优先用，精准）
#   name_kw   仓库名关键词（topic 不够时补）
#   buyer     这个方向的买家是谁（覆盖 pitch 里的通用买家）
#   deliver   这个方向通常怎么交付
#   words     判断「这条结果属不属于本方向」的本地校验词
FOCUS = {
    "虚拟产品": {
        "desc": "能把成果打包成文件卖的：模板、资料包、知识库、课件、简历",
        "topics": ["presentation", "slides", "powerpoint", "notion"],
        "name_kw": ["ppt", "slides", "resume", "worksheet", "notion"],
        "buyer": "卖电子资料 / 做知识付费的号主",
        "deliver": "打包成模板包或资料包，按份卖，发网盘+中文说明",
        "core": ["ppt", "slide", "presentation", "powerpoint", "notion", "resume",
                 "worksheet", "deck", "演示", "模板", "课件"],
    },
    "AI 工具": {
        "desc": "Agent、提示词、知识库问答、MCP 这类能直接套壳卖的工具",
        "topics": ["llm", "ai-agents", "chatbot", "rag"],
        "name_kw": ["agent", "llm", "prompt", "mcp", "rag"],
        "buyer": "想给客户做 AI 落地的接单者",
        "deliver": "部署到客户自己的服务器/账号，按项目收费",
        "core": ["agent", "llm", "gpt", "prompt", "rag", "chat", "mcp", "chatbot"],
    },
    "内容创作": {
        "desc": "视频剪辑、字幕、配音、封面、文案，做内容的人天天要用",
        "topics": ["video", "subtitle", "text-to-speech", "image-generation"],
        "name_kw": ["video", "subtitle", "tts", "cover", "editor", "writer"],
        "buyer": "做短视频 / 写公众号的内容创作者",
        "deliver": "做成开箱即用的工具包，附操作录屏，一次性卖断",
        "core": ["video", "subtitle", "tts", "voice", "caption", "transcri",
                 "视频", "字幕", "配音", "剪辑"],
    },
    "数据效率": {
        "desc": "爬虫、自动化、表格处理、PDF/OCR，替人省时间的活",
        "topics": ["automation", "scraper", "workflow", "ocr"],
        "name_kw": ["scraper", "automation", "excel", "pdf", "ocr", "crawler"],
        "buyer": "被重复劳动卡住的运营 / 小公司老板",
        "deliver": "按需求定制脚本，部署好交付，按次或包月收费",
        "core": ["scrap", "crawl", "automat", "excel", "pdf", "ocr", "spreadsheet",
                 "爬虫", "自动化"],
    },
    "自媒体运营": {
        "desc": "SEO、数据分析、多平台发布、选题工具",
        "topics": ["seo", "analytics", "social-media"],
        "name_kw": ["seo", "wechat", "xiaohongshu", "analytics", "publish"],
        "buyer": "做矩阵号 / 帮人代运营的团队",
        "deliver": "部署成网页工具，按月收服务费或一次性卖授权",
        "core": ["seo", "analytic", "social-media", "wechat", "xiaohongshu", "publish",
                 "公众号", "小红书", "运营"],
    },
    "电商": {
        "desc": "选品、比价、订单、商品图，做店的人愿意为省事付钱",
        "topics": ["ecommerce", "shopify", "price-tracker"],
        "name_kw": ["shopify", "product", "price", "order", "ecommerce"],
        "buyer": "开跨境店 / 做无货源的中小卖家",
        "deliver": "做成带界面的小工具，按店铺数收年费",
        "core": ["shopify", "ecommerce", "price-track", "order", "store", "amazon",
                 "选品", "电商"],
    },
    "教育教学": {
        "desc": "课件、题库、学习工具，家长和老师都在找",
        "topics": ["education", "elearning", "course"],
        "name_kw": ["course", "quiz", "learning", "teach", "kids", "edu"],
        "buyer": "做教辅资料 / 给机构做课件的老师",
        "deliver": "按课时打包成课件包，发网盘，附逐字稿",
        "core": ["educat", "course", "quiz", "teach", "elearn", "教学", "课件", "题库"],
    },
    "设计素材": {
        "desc": "图标、字体、主题、UI 套件，设计和小程序都用得上",
        "topics": ["icons", "fonts", "design-system", "ui-kit"],
        "name_kw": ["icon", "font", "logo", "theme", "ui-kit", "design"],
        "buyer": "要做视觉但请不起设计师的小团队",
        "deliver": "整理成素材包，按套卖，可授权商用",
        "core": ["icon", "font", "logo", "design-system", "ui-kit", "theme",
                 "图标", "字体", "配色"],
    },
}

# 别名 → 标准方向名。用户可能说英文、说简称、说具体东西。
ALIAS = {
    "虚拟产品": "虚拟产品", "虚拟": "虚拟产品", "资料": "虚拟产品", "模板": "虚拟产品",
    "ppt": "虚拟产品", "知识库": "虚拟产品", "课件": "虚拟产品", "文档": "虚拟产品",
    "virtual": "虚拟产品", "template": "虚拟产品", "digital-product": "虚拟产品",
    "ai": "AI 工具", "ai工具": "AI 工具", "agent": "AI 工具", "提示词": "AI 工具",
    "大模型": "AI 工具", "llm": "AI 工具", "工具": "AI 工具",
    "内容": "内容创作", "内容创作": "内容创作", "视频": "内容创作", "配音": "内容创作",
    "字幕": "内容创作", "写作": "内容创作", "video": "内容创作", "content": "内容创作",
    "数据": "数据效率", "效率": "数据效率", "爬虫": "数据效率", "自动化": "数据效率",
    "excel": "数据效率", "ocr": "数据效率", "data": "数据效率",
    "自媒体": "自媒体运营", "运营": "自媒体运营", "seo": "自媒体运营",
    "小红书": "自媒体运营", "公众号": "自媒体运营", "social": "自媒体运营",
    "电商": "电商", "跨境": "电商", "选品": "电商", "shopify": "电商", "ecommerce": "电商",
    "教育": "教育教学", "教学": "教育教学", "学习": "教育教学", "题库": "教育教学",
    "education": "教育教学", "kids": "教育教学",
    "设计": "设计素材", "图标": "设计素材", "字体": "设计素材", "logo": "设计素材",
    "design": "设计素材", "icon": "设计素材",
}


def match(name):
    """把用户随口说的方向对上号。对不上返回 None。"""
    if not name:
        return None
    s = name.strip().lower()
    if s in ALIAS:
        return ALIAS[s]
    if name.strip() in FOCUS:
        return name.strip()
    # 部分匹配：用户说"我想找虚拟产品这种"也要能认
    for k in FOCUS:
        if k.lower() in s or k.replace(" ", "") in s.replace(" ", ""):
            return k
    for a, v in ALIAS.items():
        if a in s:
            return v
    return None


def list_all():
    return [(k, v["desc"]) for k, v in FOCUS.items()]


def queries(focus_key, min_stars=400):
    """把一个方向变成若干条查询。topic 在前（精准），in:name 兜底。"""
    f = FOCUS.get(focus_key)
    if not f:
        return []
    out = []
    for t in f["topics"]:
        out.append((f"topic:{t}", f"stars:>{min_stars} topic:{t}"))
    if f["name_kw"]:
        kws = " OR ".join(f'"{k}"' if " " in k else k for k in f["name_kw"])
        out.append((f"名字含 {'/'.join(f['name_kw'][:3])}",
                    f"stars:>{min_stars} ({kws}) in:name"))
    return out


# 开发者脚手架：星再多也不是"能打包卖的资料"，一律排掉。
# 实测 topic:template 会拉进 sveltejs/svelte（8.8 万星前端框架）和一堆 starter kit。
DEV_SCAFFOLD = ("starter kit", "starter-kit", "starter template", "boilerplate",
                "scaffold", "coding challenge", "interview question", "leetcode",
                "curated list", "awesome list")


def belongs(repo, focus_key):
    """本地校验：这条结果真的属于这个方向吗？

    GitHub 的 topic 谁都能打，in:name 也会误中，所以必须二次确认：
      1. 先排掉开发者脚手架（starter kit / boilerplate 这类，星再多也不该卖）
      2. 再要求命中至少一个方向核心词
    """
    f = FOCUS.get(focus_key)
    if not f:
        return True
    blob = " ".join([
        (repo.get("name") or ""),
        (repo.get("desc") or ""),
        " ".join(repo.get("topics") or []),
    ]).lower()
    if any(x in blob for x in DEV_SCAFFOLD):
        return False
    return any(w in blob for w in f.get("core", []))


def buyer_for(focus_key):
    f = FOCUS.get(focus_key) or {}
    return f.get("buyer", ""), f.get("deliver", "")
