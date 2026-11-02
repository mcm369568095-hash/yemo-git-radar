# -*- coding: utf-8 -*-
"""GitHub 数据抓取层。

三个数据源，互为补充：
  A. github.com/trending  官方涨星口径（今日/本周各涨多少星，直接给数）
  B. Search API           created:>N天 按星排序 —— 新项目爆发榜
  C. 本地快照 delta       自己存的历史，跑得越久越准

只用标准库 + requests，不引第三方解析器。
"""
import json
import os
import re
import time
import urllib.parse

import requests

UA = "yemo-git-radar/1.0 (+https://github.com/yemomcm)"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"


class RateLimited(Exception):
    """API 额度用完。上层捕获后应切到 raw 通路，而不是继续硬撞。"""


# ---------------------------------------------------------------- token

# 技能目录下的 config.json，给不会设环境变量的人用
CONFIG = __import__("pathlib").Path(__file__).resolve().parent.parent / "config.json"

_TOKEN_SOURCE = ""      # 记录 token 从哪来的，给 doctor 用


def token_source():
    return _TOKEN_SOURCE


def get_token():
    """按「越省事越靠前」的顺序找 token。

    1. 环境变量 GH_TOKEN / GITHUB_TOKEN / GITHUB_PAT
    2. 技能目录 config.json 的 gh_token   ← 不会配环境变量的人走这条
    3. gh CLI 已登录（gh auth token）
    4. 本机 git 已缓存 GitHub 凭据（git credential fill）← 没装 git 就跳过
    全都没有就返回空串，走匿名 —— 不会报错，不会崩。
    """
    global _TOKEN_SOURCE

    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT"):
        v = (os.environ.get(k) or "").strip()
        if v:
            _TOKEN_SOURCE = f"环境变量 {k}"
            return v

    try:
        if CONFIG.exists():
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
            v = (cfg.get("gh_token") or "").strip()
            if v:
                _TOKEN_SOURCE = "config.json"
                return v
    except Exception:
        pass

    # 3. gh CLI：只读它的配置文件，不执行 `gh auth token`
    #    🔴 踩过坑：没登录时 `gh auth token` 会挂起等输入，整个脚本卡死（实测卡 25 秒以上还没回）。
    #    读文件零开销、零风险，效果一样。
    try:
        import pathlib
        cands = [
            pathlib.Path.home() / ".config" / "gh" / "hosts.yml",
            pathlib.Path(os.environ.get("APPDATA", "")) / "GitHub CLI" / "hosts.yml",
        ]
        for f in cands:
            if f.exists():
                txt = f.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r"oauth_token:\s*(\S+)", txt)
                if m and m.group(1).startswith(("gho_", "ghp_", "github_pat_")):
                    _TOKEN_SOURCE = "gh CLI 配置"
                    return m.group(1).strip()
    except Exception:
        pass

    # 4. 本机 git 凭据 —— 默认不碰，必须显式开。
    #
    #    🔴 实测两次卡死：`git credential fill` 在没有缓存凭据时，Git Credential Manager
    #    会起界面等用户操作，subprocess 的 timeout 杀不干净（子进程还握着管道，
    #    communicate 会继续阻塞）。表现是整个脚本挂死，用户以为坏了。
    #    分发场景绝不能默认走这条路 —— 要用就设 YEMO_USE_GIT_CRED=1。
    if os.environ.get("YEMO_USE_GIT_CRED") == "1":
        try:
            import shutil
            import subprocess
            if shutil.which("git"):
                out = subprocess.run(
                    ["git", "credential", "fill"],
                    input="protocol=https\nhost=github.com\n\n",
                    capture_output=True, text=True, timeout=8,
                ).stdout
                m = re.search(r"^password=(.+)$", out, re.M)
                if m:
                    _TOKEN_SOURCE = "本机 git 凭据"
                    return m.group(1).strip()
        except Exception:
            pass

    _TOKEN_SOURCE = ""
    return ""


def ensure_config_hint():
    """第一次跑又没有 token 时，落一个带注释的模板，省得用户猜字段名。"""
    if CONFIG.exists():
        return CONFIG
    try:
        CONFIG.write_text(json.dumps({
            "_说明": "把下面 gh_token 换成你自己的 GitHub token（免费，30 秒）。不填也能跑，只是走匿名、慢一些。",
            "_在哪申请": "https://github.com/settings/tokens  →  Generate new token (classic)  →  勾 public_repo 即可",
            "gh_token": ""
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return CONFIG


def rate_limit(token=None):
    """查当前额度。匿名也能查，本身不消耗额度。"""
    try:
        r = requests.get(f"{API}/rate_limit", headers=_headers(token), timeout=15)
        d = r.json().get("resources", {})
        core = d.get("core", {})
        search = d.get("search", {})
        return {
            "core_left": core.get("remaining"),
            "core_limit": core.get("limit"),
            "search_left": search.get("remaining"),
            "search_limit": search.get("limit"),
        }
    except Exception:
        return {}


def _headers(token=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": UA,
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url, token=None, params=None, timeout=30, retries=3):
    """普通请求。额度耗尽会抛 RateLimited 而不是傻等到超时 —— 让上层去降级。"""
    last = None
    hit_limit = False
    for i in range(retries):
        try:
            r = requests.get(url, headers=_headers(token), params=params, timeout=timeout)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                hit_limit = True
                time.sleep(2 if i == 0 else 5)
                continue
            if r.status_code in (404, 451):
                return None
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    if hit_limit:
        raise RateLimited(f"{url} 额度已用完")
    raise RuntimeError(f"GET {url} 失败: {last}")


# ---------------------------------------------------------------- A. trending

_NUM = re.compile(r"([\d,]+)")


def _num(s):
    if not s:
        return 0
    return int(re.sub(r"[^\d]", "", s) or 0)


def fetch_trending(since="daily", lang=""):
    """解析 github.com/trending 的 HTML。

    注意：GitHub 把 href 挪到了 data-hydro-click 后面，所以不能用
    `<a href="/...">` 这种老写法，必须按块提取。这段代码对结构变化很脆，
    一旦返回 0 条就是 GitHub 又改版了，先打印一个 article 看结构。
    """
    url = "https://github.com/trending"
    if lang:
        url += "/" + urllib.parse.quote(lang)
    url += f"?since={since}"
    r = _get(url)
    html = r.text
    out = []
    for art in re.findall(r'<article class="Box-row">(.*?)</article>', html, re.S):
        # 仓库名：只在 h2 里找，避开赞助商 / 登录 / star 按钮那些链接
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", art, re.S)
        if not h2:
            continue
        hm = re.search(r'href="/([^"/]+)/([^"/]+)"', h2.group(1))
        if not hm:
            continue
        owner, name = hm.group(1), hm.group(2)
        if owner in ("sponsors", "login", "orgs", "topics"):
            continue

        dm = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', art, re.S)
        desc = re.sub(r"<[^>]+>", "", dm.group(1)).strip() if dm else ""
        lm = re.search(r'itemprop="programmingLanguage">([^<]+)<', art)
        lang_name = lm.group(1).strip() if lm else ""

        def count_of(kind):
            m = re.search(rf'/{kind}"[^>]*>(.*?)</a>', art, re.S)
            if not m:
                return 0
            return _num(re.sub(r"<[^>]+>", "", m.group(1)).strip())

        gm = re.search(r"([\d,]+)\s+stars\s+(today|this week|this month)", art)
        out.append({
            "full_name": f"{owner}/{name}",
            "owner": owner,
            "name": name,
            "desc": desc,
            "lang": lang_name,
            "stars": count_of("stargazers"),
            "forks": count_of("forks"),
            "gained": _num(gm.group(1)) if gm else 0,
            "since": since,
            "source": "trending",
        })
    return out


# ---------------------------------------------------------------- B. search

def _map_item(it, source, since=""):
    """Search API 的 item → 内部统一结构。三个 search 函数共用。"""
    return {
        "full_name": it["full_name"],
        "owner": it["owner"]["login"],
        "name": it["name"],
        "desc": it.get("description") or "",
        "lang": it.get("language") or "",
        "stars": it.get("stargazers_count", 0),
        "forks": it.get("forks_count", 0),
        "gained": 0,          # 由 repo_detail / 历史 diff 补
        "since": since,
        "source": source,
        "created_at": it.get("created_at"),
        "pushed_at": it.get("pushed_at"),
        "topics": it.get("topics") or [],
        "archived": it.get("archived", False),
        "license": ((it.get("license") or {}).get("spdx_id") or ""),
        "open_issues": it.get("open_issues_count"),
        "size_kb": it.get("size"),
        "homepage": it.get("homepage") or "",
    }


def search_query(q, sort="stars", per_page=20, token=None):
    """通用搜索入口。q 直接写 GitHub 搜索语法。

    方向定向搜索走这里。sort 默认按星排，会带进超大无关项目，
    所以调用方拿到结果后必须再过一遍 focus.belongs() 做本地校验。
    """
    try:
        r = _get(f"{API}/search/repositories", token, params={
            "q": q, "sort": sort, "order": "desc", "per_page": per_page,
        })
    except RateLimited:
        raise
    if r is None:
        return []
    data = r.json()
    return [_map_item(it, "focus", "focus") for it in data.get("items", [])]


def search_new(days=30, min_stars=200, per_page=30, page=1, token=None):
    """近 N 天新建、已有一定星的项目（新项目的高星必然集中在最近，等于增量）。"""
    from datetime import datetime, timedelta, timezone
    d = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = f"created:>{d} stars:>={min_stars}"
    url = f"{API}/search/repositories"
    r = _get(url, token, params={
        "q": q, "sort": "stars", "order": "desc",
        "per_page": per_page, "page": page,
    })
    data = r.json()
    return [_map_item(it, "search_new", f"created<{days}d") for it in data.get("items", [])]


def search_pushed(days=7, min_stars=500, per_page=30, token=None):
    """存量里近期仍在活跃、星数够大的项目（用来抓"老树发新芽"）。"""
    from datetime import datetime, timedelta, timezone
    d = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = f"pushed:>{d} stars:>={min_stars}"
    r = _get(f"{API}/search/repositories", token, params={
        "q": q, "sort": "updated", "order": "desc", "per_page": per_page,
    })
    data = r.json()
    return [_map_item(it, "search_pushed", f"pushed<{days}d") for it in data.get("items", [])]


# ---------------------------------------------------------------- repo 详情

def repo_detail(full_name, token=None):
    """补齐评分要用的字段：license / issue / 更新时间 / topics / size / homepage。"""
    r = _get(f"{API}/repos/{full_name}", token)
    if r is None:
        return None
    d = r.json()
    return {
        "full_name": d["full_name"],
        "owner": d["owner"]["login"],
        "owner_type": d["owner"]["type"],
        "name": d["name"],
        "desc": d.get("description") or "",
        "lang": d.get("language") or "",
        "stars": d.get("stargazers_count", 0),
        "forks": d.get("forks_count", 0),
        "watchers": d.get("subscribers_count", 0),
        "open_issues": d.get("open_issues_count", 0),
        "license": ((d.get("license") or {}).get("spdx_id") or ""),
        "license_name": ((d.get("license") or {}).get("name") or ""),
        "topics": d.get("topics") or [],
        "created_at": d.get("created_at"),
        "pushed_at": d.get("pushed_at"),
        "updated_at": d.get("updated_at"),
        "size_kb": d.get("size", 0),
        "archived": d.get("archived", False),
        "has_discussions": d.get("has_discussions", False),
        "has_wiki": d.get("has_wiki", False),
        "homepage": d.get("homepage") or "",
        "url": d.get("html_url"),
        "default_branch": d.get("default_branch", "main"),
    }


def readme_head(full_name, max_chars=4000, token=None):
    """拿 README 前段，用来判中文友好 / 有无部署说明 / 有无 demo。"""
    r = _get(f"{API}/repos/{full_name}/readme", token)
    if r is None:
        return ""
    d = r.json()
    import base64
    try:
        txt = base64.b64decode(d.get("content", "")).decode("utf-8", "ignore")
    except Exception:
        return ""
    return txt[:max_chars]


def latest_release(full_name, token=None):
    r = _get(f"{API}/repos/{full_name}/releases/latest", token)
    if r is None:
        return ""
    try:
        return r.json().get("tag_name", "") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------- C. 无额度通路
#
# 没有 token、或者额度跑光了，API 就废了。但有两样东西不消耗额度：
#   1. github.com/<owner>/<repo> 网页 —— license 和 README 都在里面
#   2. raw.githubusercontent.com —— 纯静态，随便读
# 有了这两条，匿名也能出完整报告，只是慢一些。

PAGE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_LIC_PATTERNS = [
    (r"\bAGPL[- ]?3", "AGPL-3.0"),
    (r"\bLGPL[- ]?3", "LGPL-3.0"),
    (r"\bGPL[- ]?3", "GPL-3.0"),
    (r"\bGPL[- ]?2", "GPL-2.0"),
    (r"Apache[- ]?(License)?[, ]*2", "Apache-2.0"),
    (r"\bMPL[- ]?2", "MPL-2.0"),
    (r"\bBSD[- ]?3", "BSD-3-Clause"),
    (r"\bBSD[- ]?2", "BSD-2-Clause"),
    (r"\bISC\b", "ISC"),
    (r"\bUnlicense\b", "Unlicense"),
    (r"\bMIT\b", "MIT"),
]


def _norm_license(text):
    """把网页上那句人话（'MIT license' / 'Apache-2.0 license'）翻成 SPDX。"""
    for pat, spdx in _LIC_PATTERNS:
        if re.search(pat, text, re.I):
            return spdx
    return ""


def fetch_repo_page(full_name, max_readme=4000):
    """一次请求拿 license + README。不消耗 API 额度。

    返回 dict；彻底拿不到就返回 None（调用方继续用原始数据跑）。
    """
    try:
        r = requests.get(f"https://github.com/{full_name}",
                         headers={"User-Agent": PAGE_UA, "Accept": "text/html"},
                         timeout=30)
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:
        return None

    out = {"full_name": full_name}

    # 许可证：页面上会有 `Apache-2.0 license` 这样的锚文本
    m = re.search(r">\s*([A-Za-z0-9.\-+]{2,30})\s+license\s*<", html, re.I)
    lic = _norm_license(m.group(1)) if m else ""
    if not lic:
        # 页头有时只写 "MIT" 不带 license 字样
        m2 = re.search(r'octicon-law[^>]*>.{0,400}?>\s*([A-Za-z0-9.\-+]{2,30})\s*<', html, re.S)
        if m2:
            lic = _norm_license(m2.group(1))
    out["license"] = lic

    # README：markdown-body 里那段
    a = re.search(r'<article[^>]*class="[^"]*markdown-body[^"]*"[^>]*>(.*?)</article>',
                  html, re.S)
    if a:
        txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", a.group(1), flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
        txt = re.sub(r"&nbsp;?", " ", txt)
        txt = re.sub(r"&amp;", "&", txt)
        txt = re.sub(r"&lt;", "<", txt)
        txt = re.sub(r"&gt;", ">", txt)
        txt = re.sub(r"[ \t]+", " ", txt)
        out["readme"] = txt.strip()[:max_readme]
    else:
        out["readme"] = ""

    return out


def raw_readme(full_name, max_chars=4000):
    """页面解析失败时的兜底：直接读原始文件。HEAD 是 GitHub 的默认分支别名。"""
    for fn in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        try:
            r = requests.get(f"{RAW}/{full_name}/HEAD/{fn}",
                             headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 200 and r.text.strip():
                return r.text[:max_chars]
        except Exception:
            continue
    return ""


def raw_license(full_name):
    """最后兜底：读 LICENSE 文件正文，按特征词判 SPDX。"""
    for fn in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENSE-MIT"):
        try:
            r = requests.get(f"{RAW}/{full_name}/HEAD/{fn}",
                             headers={"User-Agent": UA}, timeout=20)
            if r.status_code != 200:
                continue
            head = r.text[:3000]
            if "GNU AFFERO GENERAL PUBLIC LICENSE" in head.upper():
                return "AGPL-3.0"
            if "GNU LESSER GENERAL PUBLIC LICENSE" in head.upper():
                return "LGPL-3.0"
            if "GNU GENERAL PUBLIC LICENSE" in head.upper():
                return "GPL-3.0" if "Version 3" in head else "GPL-2.0"
            if "Apache License" in head and "Version 2.0" in head:
                return "Apache-2.0"
            if "Mozilla Public License" in head:
                return "MPL-2.0"
            if "Permission is hereby granted, free of charge" in head:
                return "MIT"
            if "Redistribution and use in source and binary forms" in head:
                return "BSD-3-Clause" if "Neither the name" in head else "BSD-2-Clause"
            if "This is free and unencumbered software released into the public domain" in head:
                return "Unlicense"
        except Exception:
            continue
    return ""
