# -*- coding: utf-8 -*-
"""跑之前先摸清这台机器有什么。

要回答的三个问题：
  1. 有没有 git？          —— 没有不影响跑，只是少一条找 token 的路
  2. 要不要登录？          —— 不要。登录只是为了跑得快，不是跑得起来的前提
  3. 网络通不通？          —— 通不了就直说，别让人等三分钟再报个莫名其妙的错

判定三档：
  FULL     有可用 token。API 详情 + 页面兜底，最快，字段最全。
  LITE     没 token，但网页能访问。走 github.com 页面 + raw 静态文件，
           不消耗任何 API 额度，照样出完整报告，只是慢一点。
  OFFLINE  连 github.com 都打不开。直接告诉用户去检查网络/代理。
"""
import shutil
import sys
import time


def _ver_tuple(s):
    out = []
    for p in (s or "").split(".")[:3]:
        try:
            out.append(int("".join(c for c in p if c.isdigit()) or 0))
        except Exception:
            out.append(0)
    return tuple(out + [0] * (3 - len(out)))


def probe(check_token=True, timeout=15):
    """全量体检。任何一项失败都不抛异常，只记录状态。"""
    info = {
        "python": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 8),
        "requests": None,
        "git": shutil.which("git"),
        "gh_cli": shutil.which("gh"),
        "token": "",
        "token_source": "",
        "token_ok": None,
        "rate": {},
        "trending_ok": None,
        "api_ok": None,
        "mode": "OFFLINE",
        "notes": [],
    }

    try:
        import requests
        info["requests"] = requests.__version__
    except Exception:
        info["notes"].append("没装 requests，先跑 pip install requests")
        info["mode"] = "BROKEN"
        return info

    import gh_client

    info["token"] = gh_client.get_token()
    info["token_source"] = gh_client.token_source()

    # --- 网页通路：这条通不通，决定能不能出报告
    try:
        import requests
        t0 = time.time()
        r = requests.get("https://github.com/trending?since=daily",
                         headers={"User-Agent": gh_client.PAGE_UA}, timeout=timeout)
        info["trending_ok"] = (r.status_code == 200 and "Box-row" in r.text)
        info["trending_ms"] = int((time.time() - t0) * 1000)
    except Exception as e:
        info["trending_ok"] = False
        info["notes"].append(f"打不开 github.com/trending（{type(e).__name__}）")

    # --- API 通路
    try:
        info["rate"] = gh_client.rate_limit(info["token"] or None)
        info["api_ok"] = bool(info["rate"])
    except Exception:
        info["api_ok"] = False

    # --- token 到底能不能用
    if info["token"] and check_token:
        try:
            import requests
            r = requests.get("https://api.github.com/user",
                             headers={"Authorization": "Bearer " + info["token"],
                                      "User-Agent": gh_client.UA}, timeout=timeout)
            info["token_ok"] = (r.status_code == 200)
            if r.status_code == 401:
                info["notes"].append("token 无效或已过期（401）")
            elif r.status_code == 403:
                info["notes"].append("token 被限流或权限不足（403）")
        except Exception:
            info["token_ok"] = None
    elif not info["token"]:
        info["token_ok"] = False

    # --- 定档
    if info["trending_ok"]:
        info["mode"] = "FULL" if info.get("token_ok") else "LITE"
    elif info["api_ok"]:
        info["mode"] = "LITE"          # 网页挂了但 API 还活着，也能跑
    else:
        info["mode"] = "OFFLINE"

    return info


MODE_TEXT = {
    "FULL": ("完整模式", "有可用 token。API 拿详情，页面补 README，最快也最全。"),
    "LITE": ("轻量模式", "没 token 也能跑。改走网页和静态文件，不消耗 API 额度，预计慢 1-2 分钟。"),
    "OFFLINE": ("离线/不可达", "github.com 打不开，出不了报告。"),
    "BROKEN": ("环境不全", "缺依赖，跑不起来。"),
}


def advice(info):
    """把「怎么办」说成人话。检测的价值全在这一段。"""
    tips = []
    mode = info["mode"]

    if mode == "BROKEN":
        return ["pip install requests  然后重新跑一次"]

    if mode == "OFFLINE":
        tips.append("先确认能打开 https://github.com —— 浏览器能开、脚本开不了，多半是代理没给命令行用。")
        tips.append("挂了代理的话，试：export HTTPS_PROXY=http://127.0.0.1:7890（端口按你自己的改）")
        return tips

    if mode == "LITE":
        if not info["git"]:
            tips.append("这台机器没装 git —— 不影响出报告，只是少一条自动找 token 的路。"
                        "想装的话：https://git-scm.com/downloads")
        tips.append("现在没 token，一小时只能发 60 次 API 请求。报告照样出，但会慢 1-2 分钟。")
        tips.append("想要快：去 https://github.com/settings/tokens 建一个 classic token（勾 public_repo 就够），"
                    "填进本技能目录的 config.json 的 gh_token 字段。不填也能用。")
        if info["token"] and info.get("token_ok") is False:
            tips.append("⚠ 检测到一个 token 但用不了，已忽略。检查是否过期。")
        return tips

    # FULL
    core = info["rate"].get("core_left")
    if core is not None and core < 200:
        tips.append(f"API 剩余额度只有 {core} 次，今天可能不够补全部详情。额度每小时重置。")
    if not info["git"]:
        tips.append("没装 git —— 无影响：token 是从别处拿到的。")
    if not tips:
        tips.append("一切正常，直接跑。")
    return tips


def render_text(info, with_advice=True):
    """给人看的体检报告。"""
    def mark(ok):
        return "OK " if ok else "!! "

    title, desc = MODE_TEXT.get(info["mode"], ("未知", ""))
    lines = [
        "夜秣git副业雷达 · 环境自检",
        "=" * 46,
        f"{mark(info['python_ok'])} Python {info['python']}"
        + ("" if info["python_ok"] else "  （需要 3.8+）"),
        f"{mark(bool(info['requests']))} requests "
        + (info["requests"] or "未安装"),
        f"{mark(bool(info['git']))} git "
        + (info["git"] or "未安装（不影响使用）"),
        f"{mark(bool(info['gh_cli']))} gh CLI "
        + (info["gh_cli"] or "未安装（可选，装了就多条找 token 的路）"),
    ]

    if info["token"]:
        ok = info.get("token_ok")
        state = "有效" if ok else ("无效" if ok is False else "未验证")
        lines.append(f"OK  token 已找到 —— 来源：{info['token_source']}，状态：{state}")
    else:
        lines.append("!!  token 未配置 —— 走匿名，照样能出报告")

    if info["rate"]:
        r = info["rate"]
        lines.append(f"OK  API 额度  核心 {r.get('core_left')}/{r.get('core_limit')}，"
                     f"搜索 {r.get('search_left')}/{r.get('search_limit')}")
    else:
        lines.append("!!  查不到 API 额度（可能是网络问题）")

    t = info.get("trending_ok")
    if t:
        lines.append(f"OK  github.com 可达（{info.get('trending_ms', '?')} ms）")
    else:
        lines.append("!!  github.com/trending 打不开")

    lines.append("-" * 46)
    lines.append(f"运行模式：{title}")
    lines.append(f"        {desc}")

    if with_advice:
        tips = advice(info)
        if tips:
            lines.append("")
            lines.append("接下来怎么做：")
            for i, t2 in enumerate(tips, 1):
                lines.append(f"  {i}. {t2}")
    return "\n".join(lines)


def quick_mode():
    """只判模式，不做完整体检（跑 run 之前调用，省时间）。"""
    import gh_client
    token = gh_client.get_token()
    if token:
        # 有 token 就当 FULL，真失效会在请求时暴露，再降级
        return "FULL", token
    return "LITE", ""
