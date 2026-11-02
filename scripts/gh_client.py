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

# ---------------------------------------------------------------- token

def get_token():
    """优先级：环境变量 GH_TOKEN / GITHUB_TOKEN → git credential 兜底。"""
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT"):
        v = os.environ.get(k)
        if v and v.strip():
            return v.strip()
    try:
        import subprocess
        out = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=12,
        ).stdout
        m = re.search(r"^password=(.+)$", out, re.M)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return ""


def _headers(token=None):
    h = {"Accept": "application/vnd.github+json", "User-Agent": UA,
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url, token=None, params=None, timeout=30, retries=3):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=_headers(token), params=params, timeout=timeout)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                time.sleep(8 * (i + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
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
    out = []
    for it in data.get("items", []):
        out.append({
            "full_name": it["full_name"],
            "owner": it["owner"]["login"],
            "name": it["name"],
            "desc": it.get("description") or "",
            "lang": it.get("language") or "",
            "stars": it.get("stargazers_count", 0),
            "forks": it.get("forks_count", 0),
            "gained": 0,          # 由 repo_detail / 历史 diff 补
            "since": f"created<{days}d",
            "source": "search_new",
            "created_at": it.get("created_at"),
            "topics": it.get("topics") or [],
            "archived": it.get("archived", False),
            "pushed_at": it.get("pushed_at"),
            "license": ((it.get("license") or {}).get("spdx_id") or ""),
        })
    return out


def search_pushed(days=7, min_stars=500, per_page=30, token=None):
    """存量里近期仍在活跃、星数够大的项目（用来抓"老树发新芽"）。"""
    from datetime import datetime, timedelta, timezone
    d = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = f"pushed:>{d} stars:>={min_stars}"
    r = _get(f"{API}/search/repositories", token, params={
        "q": q, "sort": "updated", "order": "desc", "per_page": per_page,
    })
    data = r.json()
    out = []
    for it in data.get("items", []):
        out.append({
            "full_name": it["full_name"],
            "owner": it["owner"]["login"],
            "name": it["name"],
            "desc": it.get("description") or "",
            "lang": it.get("language") or "",
            "stars": it.get("stargazers_count", 0),
            "forks": it.get("forks_count", 0),
            "gained": 0,
            "since": f"pushed<{days}d",
            "source": "search_pushed",
            "created_at": it.get("created_at"),
            "topics": it.get("topics") or [],
            "archived": it.get("archived", False),
            "pushed_at": it.get("pushed_at"),
            "license": ((it.get("license") or {}).get("spdx_id") or ""),
        })
    return out


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
