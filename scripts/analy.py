# -*- coding: utf-8 -*-
"""四层说明：原文 → 中文直译 → 说人话 → 能干什么/怎么用。

为什么要有这一层：
GitHub 的简介是写给工程师看的英文短句。"Create and share beautiful images of
your source code" 这句话，工程师一眼懂，但一个想在 Git 上找副业的人看完什么也没得到
——他不知道这东西**长什么样、能干嘛、自己能不能用**。

所以每个项目要给四层：
  1. 原文        照抄，不删。有人要核对自己去看
  2. 中文直译    一字一句译准，不做演绎
  3. 说人话      打个比方，让完全不懂技术的人知道这等于什么
  4. 能干什么    3 条具体场景 + 怎么用起来

🔴 铁律：**永远不许交白卷**。
旧版遇到规则吃不透的句子会降级成「跟「代码、图片」有关（作者原话没译全）」，
这份报告发出去等于自曝其短 —— 用户看到的是"你爬了 130 个仓库，结果什么都没译"。
现在分三档，每一档都必须是能读的中文：
    llm   Agent 读过上下文写的（最好）
    rule  规则直译：词汇级准确，句式可能生硬，但**完整、无空白**
    raw   原文照录 + 一句形态判断（只在作者真的什么都没写时出现）

规则层的定位不是"能替代模型"，而是"模型不在场时也不丢人"。
真正好用的报告，靠的是 `translate` 流程（见文件末尾 CLI）：把待译清单交给模型，
一次译完写回，比在词表上堆一百个词管用。
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
LAST = DATA / "last_picks.json"
TODO = DATA / "todo_translate.json"
TRANS = DATA / "translate.json"

# ---------------------------------------------------------------- 清洗

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u2190-\u21FF]+")
_SHORTCODE = re.compile(r":[a-z0-9_+\-]{2,32}:")
_MDLINK = re.compile(r"!?\[[^\]]*\]\([^)]*\)")          # markdown 图片/链接
_MDBADGE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)")
_HTMLTAG = re.compile(r"<[^>]{1,200}>")
_URL = re.compile(r"https?://\S+")


def clean_desc(s):
    s = _SHORTCODE.sub("", s or "")
    s = _EMOJI.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" -—·:,")
    return s


# ---------------------------------------------------------------- 术语词典
#
# 规则：**长的、专的放前面**。"source code" 必须比 "code" 先命中，
# "large language model" 必须比 "model" 先命中。手工维护顺序太容易错，
# 所以下面按 pattern 的有效长度自动倒序，新增词随便往组里塞就行。

_RAW_PHRASES = [
    # ── 形态与领域 ──────────────────────────────
    (r"curated list of", "精选的"), (r"awesome list", "精品清单"),
    (r"cheat ?sheet", "速查表"), (r"road ?map", "路线图"),
    (r"best practices", "最佳实践"), (r"getting started", "上手引导"),
    (r"quick ?start", "快速上手"), (r"how ?to", "怎么做"),
    (r"end[- ]to[- ]end", "端到端"), (r"all[- ]in[- ]one", "一站式"),
    (r"out of the box", "开箱即用"), (r"batteries included", "开箱即用"),
    (r"from scratch", "从零开始"), (r"one[- ]click", "一键"), (r"one click", "一键"),
    (r"drag and drop", "拖拽"), (r"no[- ]code", "零代码"), (r"low[- ]code", "低代码"),
    (r"no[- ]code", "零代码"), (r"self[- ]hosted", "可自建"), (r"self hosted", "可自建"),
    (r"open[- ]source", "开源"), (r"open source", "开源"),
    (r"cross[- ]platform", "跨平台"), (r"command[- ]line", "命令行"),
    (r"real[- ]time", "实时"), (r"real time", "实时"),

    # ── AI / 模型 ──────────────────────────────
    (r"large language models?", "大语言模型"), (r"language models?", "大模型"),
    (r"machine learning", "机器学习"), (r"deep learning", "深度学习"),
    (r"neural networks?", "神经网络"), (r"prompt engineering", "提示词工程"),
    (r"prompts?", "提示词"), (r"chat ?bots?", "聊天机器人"),
    (r"ai agents?", "AI 智能体"), (r"agents?", "智能体"),
    (r"fine[- ]tun(e|ing)", "微调"), (r"embeddings?", "向量"),
    (r"inference", "推理"), (r"training", "训练"), (r"datasets?", "数据集"),
    (r"model context protocol", "模型上下文协议"), (r"\bmcp\b", "MCP"),

    # ── 前后端 ────────────────────────────────
    (r"full[- ]?stack", "全栈"), (r"front[- ]?end", "前端"), (r"back[- ]?end", "后端"),
    (r"user interface", "界面"), (r"data ?bases?", "数据库"), (r"spread ?sheets?", "表格"),
    (r"content management", "内容管理"), (r"static (site|page)s?", "静态站点"),
    (r"landing pages?", "落地页"), (r"search engines?", "搜索引擎"),
    (r"alternatives?", "替代品"), (r"local[- ]first", "本地优先"),
    (r"\bbots?\b", "机器人"), (r"\bweb\b", "网页"),
    (r"\brecord(s|ing|ed)?\b", "录制"), (r"\bedit(s|ing|ed)?\b", "编辑"),
    (r"desktop", "桌面"), (r"mobile", "手机"),
    (r"\bno\b", "无"), (r"cookies?", "Cookie"),
    (r"offline[- ]first", "离线优先"), (r"mobile[- ]first", "移动优先"),
    (r"web ?sites?", "网站"), (r"web ?apps?", "网页应用"), (r"web ?pages?", "网页"),
    (r"app(lication)?s?", "应用"), (r"platforms?", "平台"), (r"services?", "服务"),
    (r"systems?", "系统"), (r"engines?", "引擎"), (r"frameworks?", "框架"),
    (r"librar(y|ies)", "库"), (r"toolkits?", "工具包"), (r"tool ?s?", "工具"),
    (r"boilerplates?", "脚手架"), (r"templates?", "模板"), (r"plugins?", "插件"),
    (r"extensions?", "扩展"), (r"modules?", "模块"), (r"packages?", "包"),
    (r"components?", "组件"), (r"servers?", "服务器"), (r"clients?", "客户端"),
    (r"prox(y|ies)", "代理"), (r"gateways?", "网关"), (r"middlewares?", "中间件"),
    (r"dashboards?", "看板"), (r"admin panels?", "后台"), (r"widgets?", "小组件"),
    (r"\bapis?\b", "接口"), (r"\bsdks?\b", "开发包"), (r"\bcli\b", "命令行工具"),
    (r"\bui\b", "界面"), (r"\bux\b", "体验"), (r"\bcss\b", "CSS"), (r"\bhtml\b", "HTML"),
    (r"\bjson\b", "JSON"), (r"\brest\b", "REST"), (r"\bgraph ?ql\b", "GraphQL"),
    (r"\bwebassembly\b", "WebAssembly"), (r"\bwasm\b", "WASM"),

    # ── 动作 ──────────────────────────────────
    # 🔴 派生词必须排在词根前面："generator" 有 genera+t+or 三种切法，
    # 正则先匹配到 generate 就只剩一个裸 "or"，报告里会出现「站点生成or」。
    (r"generators?", "生成器"), (r"compressor", "压缩器"),
    (r"generat(e|es|ing|ion)", "生成"), (r"creat(e|es|ing|ion)", "创建"),
    (r"build(ing|s)?", "搭建"), (r"mak(e|es|ing)", "制作"),
    (r"turn(s|ing)?", "把"), (r"convert(s|ing)?", "转换"),
    (r"extract(s|ing|ion)?", "提取"), (r"pars(e|es|ing)", "解析"),
    (r"scrap(e|es|ing|er)", "抓取"), (r"crawl(er|ing)?", "爬取"),
    (r"analy[sz](e|es|ing|er)", "分析"), (r"visuali[sz](e|es|ing|ation)", "可视化"),
    (r"compress(ion|ed|es|ing)?", "压缩"),
    (r"render(s|ing)?", "渲染"), (r"format(s|ting)?", "排版"),
    (r"manag(e|es|ing|ement)", "管理"), (r"organi[sz](e|es|ing)", "整理"),
    (r"editors?", "编辑器"), (r"writ(e|es|ing|er)", "写作"),
    (r"shar(e|es|ing)", "分享"), (r"publish(es|ing)?", "发布"),
    (r"export(s|ing)?", "导出"), (r"import(s|ing)?", "导入"),
    (r"upload(s|ing)?", "上传"), (r"download(s|ing)?", "下载"),
    (r"sync(s|ing|hroniz\w*)?", "同步"), (r"backup(s|ping)?", "备份"),
    (r"migrat(e|es|ing|ion)", "迁移"), (r"deploy(s|ing|ment)?", "部署"),
    (r"monitor(s|ing)?", "监控"), (r"track(s|ing)?", "追踪"),
    (r"auto-?mat(e|es|ing|ion)", "自动化"), (r"optimi[sz](e|es|ing)", "优化"),
    (r"search(es|ing)?", "搜索"), (r"filter(s|ing)?", "筛选"),
    (r"sort(s|ing)?", "排序"), (r"integrat(e|es|ing|ion)", "集成"),
    (r"embed(s|ded|ding)?", "嵌入"), (r"host(s|ing|ed)?", "托管"),
    (r"serve(d|ing)?\b", "服务"), (r"run(s|ning)?", "运行"),
    (r"install(s|ing)?", "安装"), (r"setup|set up", "配置"),
    (r"learn(s|ing)?", "学习"), (r"teach(es|ing)?", "教"),
    (r"play(s|ing|er)?", "播放"), (r"record(s|ing)?", "录制"),
    (r"translat(e|es|ing|ion)", "翻译"), (r"summari[sz](e|es|ing)", "总结"),
    (r"transcri(be|pt|ption)", "转写"), (r"caption(s|ing)?", "字幕"),

    # ── 名词 ──────────────────────────────────
    (r"source code", "源代码"), (r"code ?bases?", "代码库"),
    (r"snippets?", "代码片段"), (r"codes?", "代码"),
    (r"images?", "图片"), (r"photos?", "照片"), (r"videos?", "视频"),
    (r"audios?", "音频"), (r"music", "音乐"), (r"voice", "语音"),
    (r"speech", "语音"), (r"sounds?", "声音"), (r"gifs?", "GIF"),
    (r"animation(s)?", "动画"), (r"animations?", "动画"),
    (r"documents?", "文档"), (r"\bpdfs?\b", "PDF"), (r"mark ?down", "Markdown"),
    (r"presentations?", "演示文稿"), (r"slides?", "幻灯片"),
    (r"slides?", "幻灯片"), (r"resumes?|cvs?", "简历"),
    (r"cover letters?", "求职信"), (r"job descriptions?", "职位描述"),
    (r"jobs?", "工作"), (r"careers?", "职业"),
    (r"notes?", "笔记"), (r"note[- ]taking", "记笔记"),
    (r"knowledge base", "知识库"), (r"wikis?", "百科"),
    (r"blogs?", "博客"), (r"newsletters?", "邮件通讯"), (r"podcasts?", "播客"),
    (r"e-?books?", "电子书"), (r"books?", "书"), (r"novels?", "小说"),
    (r"stor(y|ies)", "故事"), (r"games?", "游戏"),
    (r"charts?", "图表"), (r"graphs?", "图形"), (r"diagrams?", "图表"),
    (r"icons?", "图标"), (r"fonts?", "字体"), (r"colors?", "颜色"),
    (r"themes?", "主题"), (r"styles?", "样式"), (r"designs?", "设计"),
    (r"workflows?", "工作流"), (r"pipelines?", "流水线"),
    (r"schedulers?", "调度器"), (r"queues?", "队列"),
    (r"analytics", "数据分析"), (r"metrics", "指标"),
    (r"logs?(ging)?", "日志"), (r"tests?(ing)?", "测试"),
    (r"secur(e|ity)", "安全"), (r"auth(entication|orization)?", "认证"),
    (r"logins?", "登录"), (r"passwords?", "密码"),
    (r"encrypt(ion)?", "加密"), (r"privac(y|ies)", "隐私"),
    (r"anonymous", "匿名"), (r"cach(e|es|ing)", "缓存"),
    (r"performance", "性能"), (r"speed", "速度"),
    (r"e-?commerce", "电商"), (r"payments?", "支付"),
    (r"invoices?", "发票"), (r"subscriptions?", "订阅"),
    (r"crypto(currenc(y|ies))?", "加密货币"), (r"blockchain", "区块链"),
    (r"trading", "交易"), (r"finance", "财务"), (r"accounting", "记账"),
    (r"budget(s|ing)?", "预算"), (r"expenses?", "开销"),
    (r"3d", "3D"), (r"vr", "VR"), (r"ar\b", "AR"),
    (r"map(s|ping)?", "地图"), (r"gps", "定位"), (r"location(s)?", "位置"),
    (r"weather", "天气"), (r"calendar(s)?", "日历"), (r"tasks?", "任务"),
    (r"todo", "待办"), (r"kanban", "看板"), (r"projects?", "项目"),
    (r"files?", "文件"), (r"folders?", "文件夹"),
    (r"storage", "存储"), (r"cloud", "云端"),
    (r"extensions?", "扩展"), (r"skills?", "技能"),
    (r"assistants?", "助手"), (r"models?", "模型"),
    (r"clients?", "客户端"), (r"devices?", "设备"),
    (r"\bwindow\b", "窗口"), (r"screens?", "屏幕"), (r"displays?", "显示"),

    # ── 形容 / 修饰 ────────────────────────────
    (r"lightweight", "轻量"), (r"blazing(ly)? fast", "极快"),
    (r"fast(est)?", "快速"), (r"powerful", "强大"), (r"simple", "简单"),
    (r"minimal(ist)?", "极简"), (r"modern", "现代"), (r"beautiful", "精美的"),
    (r"pretty", "精致的"), (r"elegant", "优雅"), (r"clean", "干净"),
    (r"neat", "整洁"), (r"responsive", "自适应"),
    (r"customi[sz]able", "可自定义"), (r"extensible", "可扩展"),
    (r"modular", "模块化"), (r"scalable", "可扩展"),
    (r"robust", "稳健"), (r"reliable", "可靠"), (r"stable", "稳定"),
    (r"tiny", "极小"), (r"small", "小巧"), (r"huge", "大型"),
    (r"free", "免费"), (r"paid", "付费"), (r"premium", "高级"),
    (r"official", "官方"), (r"curated", "精选"),
    (r"collection(s)?", "合集"), (r"awesome", "精品"),
    (r"local(ly)?", "本地"), (r"offline", "离线"), (r"online", "在线"),
    (r"instant", "即时"), (r"batch", "批量"), (r"async(hronous)?", "异步"),
    (r"portable", "便携"), (r"private", "私密"), (r"public", "公开"),
    (r"instant", "即时"), (r"zero[- ]config", "零配置"),
    (r"native", "原生"), (r"based", "基于"), (r"powered", "驱动"),
    (r"focused", "专注"), (r"designed", "为…设计"), (r"built", "构建"),
    (r"written", "编写"), (r"made", "制作"), (r"created", "创建"),

    # ── 虚词 / 连接 ────────────────────────────
    (r"personal", "个人"), (r"\btextu?s?\b", "文本"),
    (r"developers?", "开发者"), (r"\bideas?\b", "创意"),
    (r"\bwrite\b", "写"), (r"\bwrite\b", "写"),
    (r"digital", "数字"), (r"assets?", "资产"), (r"media", "媒体"),
    (r"contents?", "内容"), (r"\bdata\b", "数据"), (r"management", "管理"),
    (r"\bcan\b", "能"), (r"\buse[sd]?\b", "使用"),
    (r"\bcustom(izable)?\b", "自定义"), (r"\bfirst\b", "先"),
    (r"\bfor your\b", "给你的"), (r"\bwithout\b", "不需要"),
    (r"\bwith\b", "带"), (r"\bfor\b", "面向"), (r"\bof\b", "的"),
    (r"\busing\b", "用"), (r"\bbased on\b", "基于"), (r"\binto\b", "变成"),
    (r"\bfrom\b", "从"), (r"\bby\b", "由"), (r"\bto\b", "到"),
    (r"\bin\b", "在"), (r"\bon\b", "在"), (r"\byour\b", "你的"),
    (r"\byou\b", "你"), (r"\band\b", "与"), (r"\bor\b", "或"),
    (r"\ball\b", "全部"), (r"\bany\b", "任何"), (r"\bevery\b", "每个"),
    (r"\bmore\b", "更多"), (r"\bmost\b", "最"), (r"\bbest\b", "最好的"),
    (r"\bthe\b", ""), (r"\ba\b", ""), (r"\ban\b", ""), (r"\bis\b", "是"),
    (r"\bare\b", "是"), (r"\bit\b", "它"), (r"\bthat\b", ""),
    (r"\bwhich\b", ""), (r"\bthis\b", "这个"), (r"\busing\b", "用"),
    (r"&", "和"),
]


def _pat_len(p):
    """pattern 的实际匹配长度，用来排序（去掉正则符号后的大致长度）。"""
    return len(re.sub(r"\\.|\\b|[\^$.|?*+()\[\]{}]", "", p))


# 🔴 派生词必须排在最前面，不参与长度排序。
# 正则从左往右贪婪匹配词根，会把 "recorder" 切成 "record"+"er"、
# "generator" 切成 "generate"+"or" —— 中文里就凭空多出一个裸字母，
# 报告上出现「屏幕录制 er」这种，比不译还难看。
_PRIORITY = [
    (r"recorders?", "录制器"), (r"generators?", "生成器"),
    (r"editors?", "编辑器"), (r"compressors?", "压缩器"),
    (r"managers?", "管理器"), (r"scrapers?", "爬虫"),
    (r"players?", "播放器"), (r"containers?", "容器"),
    (r"servers?", "服务器"), (r"helpers?", "助手"),
]

PHRASES = _PRIORITY + sorted(_RAW_PHRASES, key=lambda x: -_pat_len(x[0]))

# 句式优先于词替换：整句结构对了，剩下的词乱一点也不影响意思。
# 顺序 = 从具体到宽泛，前面命中了就不再往下试。
_SENT = [
    # an X alternative to Y —— 中文说「Y 的 X 替代品」，直译成「面向 Y 的 X」就废了。
    # 必须排在最前：下面的 "a X for/to Y" 会把 to 抢走。
    (r"^(?:a |an )?(.{2,}?) alternative to (.+)$",
     lambda m: f"{_phrase_tr(m.group(2))}的{_tr(m.group(1))}替代品"),
    # 清单类
    (r"^(?:a |an )?(?:curated |awesome )?list of (.+)$",
     lambda m: f"{_phrase_tr(m.group(1))}清单"),
    (r"^(?:a |an )?collection of (.+)$",
     lambda m: f"{_phrase_tr(m.group(1))}合集"),
    # X is a Y
    (r"^(.{3,}?) is (?:a |an )(.+)$",
     lambda m: f"{_tr(m.group(1))}是一个{_tr(m.group(2))}"),
    # a X for Y  /  a X to Y
    (r"^(?:a |an )(.{2,}?) (?:for|to) (.+)$",
     lambda m: f"面向{_tr(m.group(2))}的{_tr(m.group(1))}"),
    # a X that Y
    (r"^(?:a |an )(.{2,}?) (?:that|which) (.+)$",
     lambda m: f"{_tr(m.group(1))}，它可以{_tr(m.group(2))}"),
    # X built with Y
    (r"^(.{2,}?) (?:built|written|made|powered) (?:with|by|in|using) (.+)$",
     lambda m: f"用{_tr(m.group(2))}做的{_tr(m.group(1))}"),
    # turn X into Y
    (r"^turn (.{2,}?) into (.+)$",
     lambda m: f"把{_phrase_tr(m.group(1))}变成{_phrase_tr(m.group(2))}"),
    # create and share ...（两个并列动词，逐段译）
    (r"^(?:create|generate|build|make|write) (?:and|&) (\w+)\s+(.+)$",
     lambda m: f"{_tr(m.group(0).split()[0])}并{_tr(m.group(1))}"
               + _of_flip(m.group(2))),
    # X in one click —— 中文把「一键」放前面
    (r"^(.{2,}?) in (?:one|a single) click$",
     lambda m: f"一键{_phrase_tr(m.group(1))}"),
    # X from Y using Z
    (r"^(.{2,}?) from (.{2,}?) using (.+)$",
     lambda m: f"用{_tr(m.group(3))}从{_tr(m.group(2))}{_tr(m.group(1))}"),
    # 破折号分句：X — Y
    (r"^(.{3,}?)\s*[—–]\s*(.+)$",
     lambda m: f"{_tr(m.group(1))}——{_tr(m.group(2))}"),
    # 逗号 + a/an：X, a Y
    (r"^(.{3,}?), (?:a |an )(.+)$",
     lambda m: f"{_tr(m.group(1))}，一个{_tr(m.group(2))}"),
    # 祈使句开头
    (r"^(?:create|generate|build|make|turn) (.+)$",
     lambda m: f"生成{_of_flip(m.group(1))}"),
    (r"^built for (.+)$",
     lambda m: f"为{_tr(m.group(1))}打造"),
    (r"^(?:write|draft) (.+)$",
     lambda m: f"写{_tr(m.group(1))}"),
    # X for Y（通用）
    (r"^(.{2,}?) for (.+)$",
     lambda m: f"面向{_tr(m.group(2))}的{_of_flip(m.group(1))}"),
    # X with Y
    (r"^(.{2,}?) with (.+)$",
     lambda m: f"{_of_flip(m.group(1))}，{_with_tail(m.group(2))}"),
    # X without Y
    (r"^(.{2,}?) without (.+)$",
     lambda m: f"不需要{_tr(m.group(2))}的{_of_flip(m.group(1))}"),
    # X on top of Y
    (r"^(.{2,}?) (?:on top of|based on) (.+)$",
     lambda m: f"基于{_tr(m.group(2))}的{_tr(m.group(1))}"),
]


def _with_tail(s):
    """`with no cookies` 是「不带 Cookie」，译成「带无 Cookie」中文不通。"""
    m = re.match(r"^(?:no|zero|without) (.+)$", (s or "").strip(), flags=re.I)
    if m:
        return f"不带{_tr(m.group(1))}"
    return f"带{_tr(s)}"


_SUB_SENT = [
    (r"^(.{2,}?) in (?:one|a single) click$", lambda m: f"一键{_phrase_tr(m.group(1))}"),
    (r"^(.{2,}?) for (.+)$", lambda m: f"面向{_tr(m.group(2))}的{_of_flip(m.group(1))}"),
    (r"^(.{2,}?) with (.+)$", lambda m: f"{_of_flip(m.group(1))}，{_with_tail(m.group(2))}"),
    (r"^(.{2,}?) (?:built|written|made|powered) (?:with|by|in) (.+)$",
     lambda m: f"用{_tr(m.group(2))}做的{_tr(m.group(1))}"),
]


def _phrase_tr(s):
    """子短语翻译。

    清单类句子（Collection of X for Y）的尾巴不能直接喂给 _tr ——
    _tr 只会逐词换，"icons for web design" 会变成「图标面向网页设计」。
    这里先试着按 for/with 结构切一刀，切不动再退回 _of_flip。
    """
    s = (s or "").strip()
    for pat, fn in _SUB_SENT:
        m = re.match(pat, s, flags=re.I)
        if m:
            try:
                out = fn(m)
                if out and len(_CJK.findall(out)) >= 2:
                    return out
            except Exception:
                pass
    return _of_flip(s)


def _of_flip(s):
    """`beautiful images of your source code` → `你源代码的精美图片`。

    英文的 of 是后置修饰，中文必须倒过来。词表把 of 直接换成「的」，
    出来就是「好看图片的你的源代码」——每个词都对，语序全错，读起来像机翻。
    这个函数在短语级做一次倒装，是规则翻译里性价比最高的一步。
    """
    s = (s or "").strip()
    m = re.match(r"^(.{2,}?) of (.+)$", s, flags=re.I)
    if not m:
        return _tr(s)
    head, tail = _tr(m.group(1)), _tr(m.group(2))
    if not head or not tail:
        return _tr(s)
    return f"{tail}的{head}"


# ---------------------------------------------------------------- 词替换核心

_TRIM_HEAD = re.compile(r"^(?:的|了|面向|用于|用|把|给|与|和|在|到|由|变成|是)+")
_TRIM_TAIL = re.compile(r"(?:的|了|面向|用于|与|和|在|到|把|给|由|或|是)+$")
_DUP = re.compile(r"(.)\1{1,}")


def _tidy(s):
    """把词替换留下的碎片收拾干净。

    "面向的图片生成工具" → "图片生成工具"
    "生成的源代码的好看图片" → 尽量留能读的部分
    这一步不做的话，译文会像机翻 —— 不是词不对，是接缝处堵着。
    """
    s = re.sub(r"\s+", " ", s or "")
    s = re.sub(r"(的){2,}", "的", s)
    s = re.sub(r"(，){2,}", "，", s)
    s = _TRIM_HEAD.sub("", s.strip())
    s = _TRIM_TAIL.sub("", s.strip())
    s = re.sub(r"^\s*[，,、]\s*", "", s)
    s = re.sub(r"\s+([，,、。])", r"\1", s)
    # 中英混排：中文和英文单词之间补一个空格。
    # 不补的话「面向Notion的」会粘成一坨，中文读者看着像乱码。
    s = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=[\u4e00-\u9fff])", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" ，,、。.-—")


def _tr(s):
    s = (s or "").strip(" .。,")
    out = s
    for pat, cn in PHRASES:
        out = re.sub(pat, cn, out, flags=re.I)
    # 复数残留："image" 吃掉 "images" 后留下一个 s → "图片s"
    out = re.sub(r"([\u4e00-\u9fff])(?:s|es)\b", r"\1", out)
    # 中文之间的空格全部去掉，中英之间留一个
    out = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    return _tidy(out)


_EN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")
_CJK = re.compile(r"[\u4e00-\u9fff]")

# 这些是"本来就该保留英文"的名字，不算没译。
_KEEP_EN = {
    "api", "pdf", "seo", "ai", "llm", "saas", "ide", "css", "html", "json",
    "sdk", "cli", "ui", "ux", "rest", "graphql", "wasm", "mcp", "gpt", "oss",
    "yaml", "toml", "sql", "url", "uri", "http", "https", "git", "github",
    "docker", "kubernetes", "linux", "macos", "windows", "ios", "android",
    "react", "vue", "next", "nextjs", "node", "python", "rust", "golang",
    "typescript", "javascript", "java", "kotlin", "swift", "php", "ruby",
    "obsidian", "notion", "figma", "chrome", "firefox", "vscode", "wordpress",
    "aws", "azure", "gcp", "vercel", "supabase", "firebase", "openai",
    "claude", "gemini", "llama", "stable", "diffusion", "whisper",
    "markdown", "latex", "gif", "png", "jpg", "svg", "mp4", "webp",
}


def _left_en(out):
    """译完后还剩几个"不像专名"的英文词。0-1 个 = 通顺，越多越生硬。"""
    words = [w for w in _EN_WORD.findall(out or "")]
    return [w for w in words if w.lower() not in _KEEP_EN]


def _too_english(out):
    return len(_left_en(out)) >= 2


def to_zh(desc, fallback=""):
    """英文简介 → 中文直译。

    🔴 这个函数**永远不返回空、永远不返回"没译全"**。
    规则吃不透的句子，宁可保留英文原词（那本来就是专名），
    也绝不交出一句"跟 XX 有关（作者原话没译全）"——那句话比不译更气人。
    """
    d = clean_desc(desc) or clean_desc(fallback)
    if not d:
        return ""
    if _CJK.search(d):
        return d                      # 本来就是中文，不动
    # 三段口号（"Write HTML. Render video. Built for agents."）必须先切后译。
    # 整句套模板一定失败，逐词替换又变成一锅粥 —— 切成短句各译各的才读得通。
    parts = [x for x in re.split(r"(?<=[A-Za-z0-9\)])\.\s+", d) if x.strip()]
    if 2 <= len(parts) <= 4 and all(len(x) >= 6 for x in parts):
        outs = [to_zh(x) for x in parts]
        if all(len(_CJK.findall(o)) >= 2 for o in outs):
            return "。".join(o.rstrip("。") for o in outs) + "。"

    # 句式不一定第一次就中。全试一遍，取"残留英文最少"的那版 ——
    # 结构对的句子哪怕剩两个专名，也比退回逐词替换好读得多。
    best, best_left = "", 99
    for pat, fn in _SENT:
        m = re.match(pat, d, flags=re.I)
        if not m:
            continue
        try:
            out = fn(m)
        except Exception:
            continue
        if not out or len(_CJK.findall(out)) < 2:
            continue
        left = len(_left_en(out))
        if left < best_left:
            best, best_left = out, left
        if not _too_english(out):
            return out
    if best_left <= 2:
        return best
    # 所有句式都不干净 → 逐词替换 + of 倒装，保留原词兜底
    out = _of_flip(d)
    if len(_CJK.findall(out)) >= 2 and len(_left_en(out)) <= best_left:
        return out
    return best or out or d


# ---------------------------------------------------------------- README 摘要
#
# 一半的"作者没写简介"其实是 GitHub 的 About 空着，但 README 第一段写得清清楚楚。
# 放着不用，白白浪费一次翻译机会。

_SKIP_LINE = re.compile(
    r"^\s*(?:[#>*\-=|]{1,4}\s*)?(?:!\[|<img|<a |<p |<div|\[!\[|badge|table of contents|"
    r"contents|installation|install|usage|license|contributing|acknowledg|"
    r"目录|安装|使用|许可|贡献)", re.I)


def readme_lede(readme, limit=320):
    """从 README 里摘第一段像"简介"的话。

    跳过标题、徽章、图片、目录、安装说明 —— 这些占了 README 前 30 行，
    但一句人话都没有。真正说明"这是什么"的通常是第一个长段落。
    """
    if not readme:
        return ""
    txt = _MDLINK.sub("", readme)
    txt = _HTMLTAG.sub("", txt)
    txt = _URL.sub("", txt)
    buf = []
    for raw in txt.splitlines():
        line = raw.strip()
        if not line:
            if len(" ".join(buf)) > 40:
                break
            buf = []
            continue
        if line.startswith(("#", "|", "```", "---", "===")):
            continue
        if _SKIP_LINE.match(line):
            continue
        if len(line) < 12:
            continue
        buf.append(line)
        if len(" ".join(buf)) > limit:
            break
    out = re.sub(r"\s+", " ", " ".join(buf)).strip()
    out = re.sub(r"^[\s\-—:.,，、]+", "", out)
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0] + "…"
    return out


# ---------------------------------------------------------------- 说人话

# 形态 → 这东西"等于"什么。用类比，不用术语 ——
# 用户听懂"等于什么"，比听懂"是什么技术"有用得多。
FORM_PLAIN = {
    "web应用": "一个打开网页就能用的在线小工具，不用装任何东西",
    "引擎库": "一堆已经写好的能力，但没有界面，得有人包一层壳才能给普通人用",
    "命令行": "一个要在黑框里敲命令才动起来的工具，功能硬，但上手要人带",
    "Agent技能": "一份写给 AI 的操作手册，装进 AI 工具后它就知道按你的规矩干活",
    "模版主题": "一套现成的模板，把内容换掉就能发布",
    "模板主题": "一套现成的模板，把内容换掉就能发布",
    "模型数据": "一个能跑 AI 的模型或数据集，得自己配环境才能动",
    "素材资源": "一堆现成能用的素材，拿来直接放进自己的东西里",
}


def to_plain(zh, form, desc=""):
    like = FORM_PLAIN.get(form, "一个现成的工具")
    if not zh:
        return f"作者没写简介。从形态看，这是{like}。"
    return f"说白了，这是{like}。它干的事是：{zh}"


# ---------------------------------------------------------------- 能干什么

FORM_USAGE = {
    "web应用": ["直接打开当工具用，省掉装软件那一步", "部署到自己的域名，做成一个能对外收钱的服务", "挂在自己号里当「免费小工具」，用来引流"],
    "引擎库": ["接到同类需求时拿它当底子，省掉搭骨架的两三天", "包一层网页界面，做成给非技术人用的成品", "集成进自己的项目，跳过从零写这一段"],
    "命令行": ["把每天重复的那串命令固化成脚本，一条命令出结果", "批量处理文件/图片/文档，一次跑完一整个文件夹", "接单代跑：客户给素材，你出结果"],
    "Agent技能": ["装进常用的 AI 工具，让它按行规干活，不用每次重写要求", "改造成中文版，卖给不会写提示词的人", "当课程或付费专栏的核心案例，边讲边演示"],
    "模板主题": ["换成自己的内容直接发布，不用等设计", "按行业改造成多套，一套一个价", "当引流钩子：免费给一套，私信换全套"],
    "模型数据": ["在自己机器上跑起来，做批量处理", "做成在线服务，按次或按月收费", "先跑通效果，写成测评内容赚流量"],
    "素材资源": ["直接当素材库用，省掉找图找模板的时间", "挑一部分重组成自己的合集卖", "当赠品挂在商品页，提高转化"],
}


def usage_of(repo, form, pitch):
    base = list(FORM_USAGE.get(form, ["当作一个现成能力，接到自己的活里"]))
    tag = (pitch or {}).get("buyer_tag") or ""
    # 有具体行业时，第一条换成这个行业的活 —— 比通用场景有用得多
    ind = {
        "设计": "接单时用它出初稿，客户改的是稿子不是空白页",
        "视频": "批量出素材/封面/字幕，一个晚上干完一周的量",
        "教育": "做成课件和练习材料，按课时拆开卖",
        "玄学": "批量出内容配图，维持日更不断",
        "电商": "批量做商品图/详情页，一次上新几十个 SKU",
        "内容": "日常更新时用它顶掉最耗时的那一步",
        "文档": "把散落的资料整理成结构化文档",
        "数据": "把手工统计的活换成一次配置、长期自动跑",
        "财税": "把重复的票据/报表处理变成一键",
        "求职": "批量改简历、按岗位定制，一次投几十家",
    }.get(tag)
    if ind:
        base.insert(0, ind)
    return base[:3]


# ---------------------------------------------------------------- 怎么用

FORM_HOW = {
    "web应用": ["打开作者给的网址（或自己部署一份）", "按界面提示把内容填进去", "选样式/导出，拿到成品"],
    "引擎库": ["按 README 装依赖（这一步最容易卡住）", "跑一个作者给的示例，确认能出结果", "把自己的数据/需求换成示例里的输入"],
    "命令行": ["装好运行环境", "复制作者给的命令跑一遍", "把参数换成自己的文件路径"],
    "Agent技能": ["把技能文件放进 AI 工具的技能目录", "在对话里说一句触发词", "按它给的步骤走，不满意就补一句要求"],
    "模板主题": ["下载模板", "把文字和图片换成自己的", "按平台要求的尺寸导出"],
    "模型数据": ["准备显卡和环境", "下载权重/数据", "按示例脚本跑第一次推理"],
    "素材资源": ["下载整包", "按自己的用途筛一遍，挑出能用的", "替换/重组成自己的成品"],
}


def how_to(form):
    return list(FORM_HOW.get(form, ["看 README 跑通示例", "换成自己的输入", "拿到结果"]))


# ---------------------------------------------------------------- 卖给谁 & 卖点

def why_of(pitch, form):
    buyer = (pitch or {}).get("buyer") or "这类人"
    change = (pitch or {}).get("change") or ""
    if not change:
        return f"{buyer}不缺想法，缺的是一个能直接用的一步。"
    return (f"{buyer}不是不会做，是懒得为这一步花两三天试错。"
            f"你把「{change}」替他们做完，他们花的钱远少于自己折腾的时间。")


# ---------------------------------------------------------------- 自用

FORM_SELF = {
    "web应用": "自己干活时当外挂：重复的排版、出图、整理交给它，一次省十几分钟。用熟之后你会清楚自己哪一步最该自动化——这个认知比工具本身值钱。",
    "引擎库": "接到类似需求直接拿它当底子，省掉搭骨架的两三天；顺手把它当成自己的技术储备，下次报价敢往上抬。",
    "命令行": "把每天要重复敲的东西固化成脚本，以后一条命令出结果；攒下来的脚本就是你自己的工具库。",
    "Agent技能": "装进自己常用的 AI 工具里，写东西、做分析时不用每次从头描述要求，输出的东西还稳定。",
    "模板主题": "自己发内容不用等设计，改改就发；一套模板能反复用几十次。",
    "模型数据": "先在自己机器上跑通，摸清效果边界，再拿这个能力去接单——试错成本全在自己电脑上，不花钱。",
    "素材资源": "做图做视频时不用再东拼西凑素材，一个包解决风格统一问题，出片速度直接翻倍。",
}


def self_of(form):
    return FORM_SELF.get(form, "自己先用一遍，摸清它能干什么、卡在哪，这段经验本身就是内容素材。")


# ---------------------------------------------------------------- 打包出售

FORM_PACK = {
    "web应用": "汉化 + 一套中文模板 + 部署教程，打包成 zip 发网盘；主图用「改前 vs 改后」对比，标题写用户能搜的词。",
    "引擎库": "包一层网页界面，录一段 3 分钟演示，按份卖；买家买的不是代码，是「不用装环境」。",
    "命令行": "做成「双击就能跑」的包 + 图文教程，一次付费长期用；再开一个代跑通道接零散单。",
    "Agent技能": "整理成可直接安装的技能包 + 使用截图，配一节教程一起卖；也可以做成付费专栏的一章当引流钩子。",
    "模板主题": "换 logo 配色文案，出一套同名 zip，按行业拆成多套分别定价。",
    "模型数据": "做成一键安装包 + 中文说明书；再开代跑服务，按调用次数收。",
    "素材资源": "挑出最好的 50 个重新分类打包，配一份「怎么用」的图文，按 9.9 引流价卖，赚的是后面的私信。",
}


def pack_of(form, pitch):
    base = FORM_PACK.get(form, "改造成中文可用版，配教程打包出售。")
    deliver = (pitch or {}).get("deliver")
    if deliver:
        base = f"{base}落地上就按这条走：{deliver}。"
    return base


# ---------------------------------------------------------------- 组装

def build(repo, gaps, pitch, readme=""):
    """规则版四层说明。返回的 dict 带 `_auto: True` / `_src: "rule"`，Agent 精修后会被覆盖。"""
    form = repo.get("form") or ""
    en = clean_desc(repo.get("desc"))
    src_note = ""
    if not en:
        # About 空着但 README 有话 —— 摘一段当原文，总比「作者没写简介」强
        lede = readme_lede(readme)
        if lede:
            en, src_note = lede, "（取自 README 首段）"
    zh = to_zh(en)
    return {
        "en": en or "（作者没写简介，README 也没找到可用段落）",
        "zh": (zh + src_note) if zh else "",
        "plain": to_plain(zh, form, en),
        "usage": usage_of(repo, form, pitch),
        "how": how_to(form),
        "gap": (pitch or {}).get("change") or "",
        "buyer": (pitch or {}).get("buyer") or "",
        "why": why_of(pitch, form),
        "self": self_of(form),
        "pack": pack_of(form, pitch),
        "_auto": True,
        "_src": "rule",
    }


# ---------------------------------------------------------------- 合并精修

FIELDS = ("en", "zh", "plain", "usage", "how", "gap", "buyer", "why", "self", "pack")
LIST_FIELDS = ("usage", "how")


def merge(picks, analysis):
    """把 Agent 写的分析合进 picks。analysis 可以是 list（按 full_name 匹配）或 dict。

    只覆盖给出的字段，没给的保留规则兜底 —— 这样 Agent 可以只修最难看的那几句。
    返回 (合并了几个, 缺了哪几个)。
    """
    if isinstance(analysis, dict):
        analysis = analysis.get("items") or analysis.get("picks") or list(analysis.values())
    by_name = {}
    for a in analysis or []:
        if isinstance(a, dict) and a.get("full_name"):
            by_name[a["full_name"]] = a

    hit, miss = 0, []
    for r in picks:
        a = by_name.get(r.get("full_name"))
        if not a:
            miss.append(r.get("full_name"))
            continue
        cur = dict(r.get("analy") or {})
        for k in FIELDS:
            v = a.get(k)
            if v is None or v == "" or v == []:
                continue
            if k in LIST_FIELDS and isinstance(v, str):
                v = [x.strip() for x in re.split(r"[;；\n]+", v) if x.strip()]
            cur[k] = v
        cur["_auto"] = False
        cur["_src"] = "llm"
        r["analy"] = cur
        # 卖给谁/差哪一步 跟 pitch 是同一件事，精修后回写，别让两处说法打架
        if cur.get("buyer"):
            r.setdefault("pitch", {})["buyer"] = cur["buyer"]
        if cur.get("gap"):
            r["pitch"]["change"] = cur["gap"]
        hit += 1
    return hit, miss


def completeness(a):
    """0-1，用来在报告里标「已精修 / 机翻兜底」。"""
    if not a:
        return 0.0
    ok = sum(1 for k in FIELDS if a.get(k))
    return round(ok / len(FIELDS), 2)


# ---------------------------------------------------------------- 翻译质量分档

def zh_state(a):
    """这条说明的翻译处在哪一档：llm / rule / raw。

    报告上就靠这个决定要不要提示"可以再润色一下"。
    """
    a = a or {}
    zh = (a.get("zh") or "").strip()
    if a.get("_src") == "llm" or a.get("_auto") is False:
        return "llm"
    if not zh or "没写简介" in zh or zh == "（没有译文）":
        return "raw"
    if _too_english(zh) and len(_CJK.findall(zh)) < 6:
        return "raw"
    return "rule"


def needs_translate(r):
    """这条该不该进待译清单。

    判据不是"有没有中文"，而是"一个不懂英文的人看完，能不能知道这东西干嘛"。
    所以：中文太少、或还剩一串没译的英文词 → 都算待译。
    """
    a = r.get("analy") or {}
    if zh_state(a) == "llm":
        return False
    zh = (a.get("zh") or "").strip()
    if not zh or "没写简介" in zh:
        return True
    if len(_CJK.findall(zh)) < 8:
        return True
    # 阈值放到 1：剩一个 "Developers" 没译，读者就得自己猜。
    # 宁可在待译清单里多一条，也别让报告里挂着一句不中不洋的话。
    return len(_left_en(zh)) >= 1


# ---------------------------------------------------------------- CLI：翻译流水线
#
# 规则层是"不丢人"，模型层才是"好用"。这一步把两个接起来：
#   todo   扫出待译清单 → 交给模型（Agent 自己就能译）
#   apply  把译好的中文写回 last_picks.json
#   check  体检：还有几条没过关
#
# 为什么不让脚本自己去调 API：token 是用户的，key 是用户的，
# 脚本替用户花钱的事一次都不做。Agent 在场时它就等于免费翻译器。

def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _all_picks(d):
    """last_picks.json 里所有需要说明的项目：每日 + 单独重点三桶 + 深挖。"""
    out = list(d.get("picks") or [])
    for bucket in ((d.get("focus_tab") or {}).get("buckets") or {}).values():
        out += bucket
    return out


def cmd_todo(args):
    d = _load(LAST)
    if not d:
        print(f"读不到 {LAST}，先跑 fetch / run")
        return 1
    seen, rows = set(), []
    for r in _all_picks(d):
        fn = r.get("full_name")
        if not fn or fn in seen or not needs_translate(r):
            continue
        seen.add(fn)
        a = r.get("analy") or {}
        rows.append({
            "full_name": fn,
            "form": r.get("form", ""),
            "en": a.get("en") or r.get("desc") or "",
            "zh_now": a.get("zh") or "",
            "readme_hint": readme_lede(r.get("readme", ""), 260),
            # 只让模型填 zh / plain 两个字段：其余（能干什么/卖给谁）规则版已经够用，
            # 全塞给模型会把 token 花在已经不错的地方。
            "fill": {"zh": "", "plain": ""},
        })
    TODO.parent.mkdir(parents=True, exist_ok=True)
    TODO.write_text(json.dumps({
        "_说明": "把每条的 fill.zh（中文直译）和 fill.plain（说人话）补上，"
                 "然后 python scripts/radar.py translate --apply",
        "count": len(rows), "items": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"[*] 待译 {len(rows)} 条 -> {TODO}")
    print("    下一步：让 Agent 填 fill.zh / fill.plain，再 --apply")
    return 0


def cmd_apply(args):
    src = Path(getattr(args, "file", "") or TRANS)
    t = _load(src)
    if not t:
        print(f"读不到 {src}（先 --todo，再照着填）")
        return 1
    items = t.get("items") if isinstance(t, dict) else t
    by = {}
    for it in items or []:
        if not isinstance(it, dict):
            continue
        fn = it.get("full_name")
        if not fn:
            continue
        fill = it.get("fill") or {}
        by[fn] = {
            "zh": (fill.get("zh") or it.get("zh") or "").strip(),
            "plain": (fill.get("plain") or it.get("plain") or "").strip(),
        }
    d = _load(LAST)
    if not d:
        print(f"读不到 {LAST}")
        return 1
    hit = 0
    for r in _all_picks(d):
        v = by.get(r.get("full_name"))
        if not v or not v["zh"]:
            continue
        a = dict(r.get("analy") or {})
        a["zh"] = v["zh"]
        if v["plain"]:
            a["plain"] = v["plain"]
        else:
            a["plain"] = to_plain(v["zh"], r.get("form", ""))
        a["_auto"] = False
        a["_src"] = "llm"
        r["analy"] = a
        hit += 1
    LAST.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    left = len([r for r in _all_picks(d) if needs_translate(r)])
    print(f"[*] 写回 {hit} 条，还剩 {left} 条待译")
    if left:
        print("    继续跑 --todo 补剩下的，或者就这么出报告（会有「机器直译」标记）")
    return 0


def cmd_check(args):
    d = _load(LAST)
    if not d:
        print(f"读不到 {LAST}")
        return 1
    picks = _all_picks(d)
    stat = {"llm": 0, "rule": 0, "raw": 0}
    bad = []
    for r in picks:
        s = zh_state(r.get("analy") or {})
        stat[s] = stat.get(s, 0) + 1
        if s != "llm":
            bad.append(r.get("full_name"))
    n = len(picks) or 1
    print(f"翻译体检：共 {len(picks)} 个")
    print(f"  已精修 {stat['llm']}  ·  机器直译 {stat['rule']}  ·  原文照录 {stat['raw']}")
    print(f"  覆盖率 {stat['llm'] * 100 // n}%")
    if bad:
        print(f"  待译 {len(bad)} 个：{', '.join(bad[:8])}" + ("…" if len(bad) > 8 else ""))
        print("  补译：python scripts/radar.py translate --todo")
    else:
        print("  全部过关，这份报告可以直接发出去。")
    return 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="四层说明 / 翻译流水线")
    ap.add_argument("cmd", nargs="?", default="check",
                    choices=["todo", "apply", "check", "test"])
    ap.add_argument("--file", default="", help="apply 用：译好的 json 路径")
    ap.add_argument("text", nargs="*", help="test 用：直接译一句话看看")
    a = ap.parse_args(argv)
    if a.cmd == "todo":
        return cmd_todo(a)
    if a.cmd == "apply":
        return cmd_apply(a)
    if a.cmd == "test":
        s = " ".join(a.text) or "Create and share beautiful images of your source code"
        print("原文：", s)
        print("直译：", to_zh(s))
        return 0
    return cmd_check(a)


if __name__ == "__main__":
    raise SystemExit(main())
