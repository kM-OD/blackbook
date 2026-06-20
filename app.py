# -*- coding: utf-8 -*-
"""
黑皮书选股系统 v5.2 - 修复 form 导致勾选失效的问题
核心修复：
  1. st.data_editor 不放在 form 里，直接从 st.session_state[key] 读取勾选结果
  2. 加自选/删除后删除对应的 session_state key，让 data_editor 重置
  3. 刷新登录用 URL token 恢复（Streamlit 同一 WebSocket 会话本身保持 session_state）
"""
import os
import sys
import time
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="黑皮书选股 v5.2",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===== 把 Streamlit Secrets 写入环境变量（让 cloud_storage.py 一定能读到）=====
try:
    import os
    os.environ["GITHUB_PAT"] = st.secrets["GITHUB_PAT"]
    os.environ["GITHUB_USER"] = st.secrets.get("GITHUB_USER", "kM-OD")
except Exception:
    pass

from data_fetcher import (
    fetch_lhb_one_day, get_market_env_by_index,
    fetch_multi_day_review_batch, fill_lhb_with_realtime,
    guess_industry_by_name,
    fetch_post_returns, fetch_realtime_quotes, fetch_stock_news,
)
from selector import evaluate_stock
from rules_config import load_config
from auth import (
    login, register, validate_session, logout,
    load_user_watchlist, save_user_watchlist,
)

# ===== CSS =====
st.markdown("""<style>
.login-box{max-width:420px;margin:60px auto;padding:40px 36px;
background:#fff;border-radius:18px;box-shadow:0 4px 24px rgba(60,60,120,0.13);text-align:center}
.login-title{font-size:2em;font-weight:700;color:#1a1a2e;margin-bottom:6px}
.login-sub{color:#888;font-size:1em;margin-bottom:24px}
.stTabs [data-baseweb="tab"]{font-size:1.1rem;font-weight:600}
div[data-testid="stDataFrame"]{border-radius:12px}
</style>""", unsafe_allow_html=True)

# ===== 初始化 session_state =====
_DEFAULTS = {
    "logged_in": False,
    "username": "",
    "sel_cache": None,
    "add_result": "",
    "del_result": "",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ===== 持久登录逻辑 =====
# 优先级: session_state > URL token > 未登录
# 每次页面加载都尝试从 URL 恢复（处理刷新/新标签页场景）
if not st.session_state["logged_in"]:
    # 方法1: 从 URL 读取 token
    try:
        url_token = st.query_params.get("token", "")
    except Exception:
        url_token = ""
    # 方法2: 从 session_state 读取之前存的 token（同一标签页刷新时用）
    if not url_token:
        url_token = st.session_state.get("_token", "")
    if url_token:
        un = validate_session(url_token)
        if un:
            st.session_state["logged_in"] = True
            st.session_state["username"] = un
            st.session_state["_token"] = url_token  # 备份到 session_state

# ===== 未登录 → 登录页 =====
if not st.session_state["logged_in"]:
    st.markdown('<div class="login-box">', unsafe_allow_html=True)
    st.markdown('<div class="login-title">📊 黑皮书选股系统</div>', unsafe_allow_html=True)
    st.markdown('<div class="login-sub">A股龙虎榜智能筛选 · v5.2</div>', unsafe_allow_html=True)

    t1, t2 = st.tabs(["🔑 登录", "📝 注册"])

    with t1:
        with st.form("f_login"):
            u = st.text_input("用户名", key="lu")
            p = st.text_input("密码", type="password", key="lp")
            if st.form_submit_button("🚀 登录", use_container_width=True):
                res = login(u, p)
                if res["success"]:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = u
                    st.session_state["_token"] = res["token"]  # 备份到 session_state
                    try:
                        st.query_params["token"] = res["token"]  # 写入 URL
                    except Exception:
                        pass
                    st.rerun()
                else:
                    st.error("❌ " + res["msg"])

    with t2:
        with st.form("f_reg"):
            ru = st.text_input("用户名(2-20字符)", key="ru")
            rp = st.text_input("密码(至少4位)", type="password", key="rp")
            ri = st.text_input("邀请码", key="ri")
            if st.form_submit_button("📋 注册", use_container_width=True):
                res = register(ru, rp, ri)
                if res["success"]:
                    st.success("✅ 注册成功！切换到登录页")
                else:
                    st.error("❌ " + res["msg"])

    st.caption("*仅供娱乐学习，不构成投资建议*")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ==================== 已登录主界面 ====================
uname = st.session_state["username"]

with st.sidebar:
    st.markdown(f"### 👤 {uname}")
    st.caption("黑皮书 v5.2")
    st.divider()
    if st.button("🚪 退出登录", use_container_width=True, key="btn_logout"):
        try:
            tk = st.query_params.get("token", "")
            logout(tk)
        except Exception:
            pass
        for _k in list(st.session_state.keys()):
            del st.session_state[_k]
        try:
            del st.query_params["token"]
        except Exception:
            pass
        st.rerun()
    st.divider()
    st.caption("数据: 新浪/东方财富")

st.title("📊 黑皮书选股系统")
tab_overview, tab_select, tab_watch = st.tabs(["📈 总览", "🔍 选股", "⭐ 自选"])

# ==================== TAB 1: 总览 ====================
with tab_overview:
    st.header("📈 使用指南")
    c1, c2 = st.columns(2)
    with c1:
        st.info("**快速开始**\n\n①「选股」tab选日期→联网分析\n②勾选股票→点加自选\n③「自选」tab跟踪盈亏")
    with c2:
        st.warning("**策略说明**\n\n- 规则体系: 黑皮书 v1.3.1\n- ⭐⭐⭐黄金 / ⭐⭐高优 / ⭐标准 / ⚠️观察\n- 数据源: 公开免费接口")

    st.divider()
    st.subheader("市场环境判定")
    st.dataframe(
        pd.DataFrame({
            "环境": ["强市 🟢", "中性 🟡", "弱市 🔴"],
            "条件": ["上证>+1% AND 深证>+0.5%", "不满足强/弱市", "上证<-1.5% AND 深证<-1.0%"],
            "建议": ["积极追板", "精选龙头", "空仓观望"],
        }),
        use_container_width=True, hide_index=True,
    )

# ==================== TAB 2: 今日选股 ====================
with tab_select:
    st.subheader("🔍 联网选股")

    # 显示上次操作结果
    ar = st.session_state.get("add_result", "")
    if ar:
        st.success(ar)
        # 只显示一次，清空
        st.session_state["add_result"] = ""

    today_s = datetime.now().strftime("%Y-%m-%d")
    col_d, col_b = st.columns([2, 1])
    with col_d:
        pick_dt = st.date_input("分析日期", value=datetime.now(),
            min_value=datetime(2024, 1, 1), max_value=datetime.now(),
            format="YYYY-MM-DD", key="pd")
    with col_b:
        st.write(""); st.write("")
        btn_go = st.button("🌐 联网选股", use_container_width=True, type="primary", key="btn_go")

    cache = st.session_state.get("sel_cache")
    if cache and str(cache.get("date", "")) == str(pick_dt) and not btn_go:
        st.info(f"📦 已缓存 {cache['date']} 结果 ({len(cache.get('selected', []))}只通过)")
        if st.button("🔄 重跑", key="btn_rerun"):
            btn_go = True

    if btn_go:
        with st.spinner("正在拉取龙虎榜、大盘指数、K线数据..."):
            ds = pick_dt.strftime("%Y-%m-%d")
            lhb = fetch_lhb_one_day(ds)
            if not lhb:
                st.error(f"{ds} 无数据(非交易日或接口异常)")
                st.stop()
            seen, uniq = set(), []
            for s in lhb:
                c = s.get("code", "")
                if c not in seen:
                    seen.add(c)
                    uniq.append(s)
            uniq.sort(key=lambda x: x.get("close", 0), reverse=True)
            lhb = fill_lhb_with_realtime(uniq, ds)
            env = get_market_env_by_index(ds)
            codes = [s.get("code", "") for s in lhb]
            revs = fetch_multi_day_review_batch(codes, ds, days=5)
            ind = {s["code"]: guess_industry_by_name(s.get("name", "")) for s in lhb}
            rules, _ = load_config()
            results = []
            for s in lhb:
                r = evaluate_stock(s, env, rules, revs.get(s.get("code", ""), {}))
                r["板块"] = ind.get(s.get("code", ""), "?")
                results.append(r)
            sel = [r for r in results if r.get("通过")]
            rej = [r for r in results if not r.get("通过")]
            sel.sort(key=lambda x: (x.get("星级", {}).get("star", 0), x.get("评分", 0)), reverse=True)
            st.session_state["sel_cache"] = {
                "date": ds, "env": env,
                "selected": sel, "rejected": rej,
                "total": len(lhb), "reviews": revs,
            }
        st.rerun()

    cache = st.session_state.get("sel_cache")
    if not cache:
        st.info("👆 选日期→点「联网选股」")
        st.stop()

    sel = cache["selected"]
    rej = cache["rejected"]
    env = cache["env"]
    total = cache["total"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("龙虎榜总数", f"{total}只")
    m2.metric("通过筛选", f"{len(sel)}只")
    m3.metric("淘汰", f"{len(rej)}只")
    m4.markdown(f"**环境:** {env}")

    if not sel:
        st.warning("无股票通过筛选")
        st.stop()

    # 构建表格（✅ 默认 False，用户自己勾选）
    wl = load_user_watchlist(uname)
    wl_codes = {w.get("code", "") for w in wl}
    rows = []
    for r in sel:
        si = r.get("星级", {})
        code = r.get("代码", r.get("code", "?"))
        name = r.get("名称", r.get("name", "?"))
        rat = r.get("占比", "")
        if isinstance(rat, dict):
            rat_s = f"机:{rat.get('机构', 0)}% 游:{rat.get('游资', 0)}%"
        else:
            rat_s = str(rat)
        rows.append({
            "✅": False,
            "代码": code,
            "名称": name,
            "收盘价": round(r.get("收盘价", 0), 2),
            "涨幅%": round(r.get("涨幅%", 0), 2),
            "评分": r.get("评分", 0),
            "星级": f"{si.get('icon', '')} {si.get('label', '')}",
            "主力": r.get("主力类型", ""),
            "占比": rat_s,
            "板块": r.get("板块", ""),
        })

    df = pd.DataFrame(rows)
    # 显示只读表格
    st.dataframe(
        df[["代码", "名称", "收盘价", "涨幅%", "评分", "星级", "主力"]],
        use_container_width=True,
        hide_index=True,
        height=min(max(len(rows) * 32 + 30, 200), 500),
    )

    # ===== 用 multiselect 选择，简单可靠 =====
    stock_options = [f"{r['代码']} {r['名称']}" for r in rows]
    selected = st.multiselect(
        "👇 勾选要添加的股票（可多选）",
        options=stock_options,
        default=[],
        key="ms_add",
        placeholder="点击下拉框选择...",
    )

    if st.button("➕ 加自选（选中）", type="primary", key="btn_add_wl"):
        if not selected:
            st.warning("请先在上方下拉框中选择股票")
        else:
            added = 0
            wl = load_user_watchlist(uname)
            wl_codes = {w.get("code", "") for w in wl}
            added_codes = []
            for item in selected:
                code = str(item.split()[0])  # 取代码部分
                if code in wl_codes:
                    continue
                rf = next((r for r in sel if str(r.get("代码", r.get("code", ""))) == code), None)
                if rf:
                    wl.append({
                        "code": code,
                        "name": " ".join(item.split()[1:]),
                        "date_added": cache.get("date", today_s),
                        "price_at_add": float(rf.get("收盘价", 0)),
                        "score": int(rf.get("评分", 0)),
                        "star_label": str(rf.get("星级", {}).get("label", "")),
                        "industry": str(rf.get("板块", "")),
                    })
                    wl_codes.add(code)
                    added_codes.append(code)
                    added += 1
            save_user_watchlist(uname, wl)
            verify = load_user_watchlist(uname)
            st.session_state["add_result"] = f"✅ 成功添加 {added} 只到自选！（验证：当前自选共 {len(verify)} 只）去「⭐ 自选」查看"

    if rej:
        with st.expander(f"淘汰明细 ({len(rej)}只)", expanded=False):
            rd = [{
                "代码": r.get("代码", ""),
                "名称": r.get("名称", ""),
                "原因": r.get("淘汰原因", ""),
                "红线": str(r.get("触发红线", "")),
            } for r in rej[:20]]
            st.dataframe(pd.DataFrame(rd), use_container_width=True, hide_index=True)

# ==================== TAB 3: 自选跟踪 ====================
with tab_watch:
    st.header("⭐ 我的自选跟踪")
    wl = load_user_watchlist(uname)

    dr = st.session_state.get("del_result", "")
    if dr:
        if dr.startswith("✅"):
            st.success(dr)
        else:
            st.warning(dr)
        st.session_state["del_result"] = ""

    if not wl:
        st.info("暂无自选。在「选股」页勾选股票添加。")
    else:
        codes = [w.get("code", "") for w in wl]

        # 行情缓存：5分钟内不重复请求
        @st.cache_data(ttl=300, show_spinner=False)
        def _cached_quotes(cds):
            return fetch_realtime_quotes(list(cds)) if cds else {}

        quotes = _cached_quotes(tuple(codes))
        ts = datetime.now().strftime("%Y-%m-%d")
        rows_wl = []
        for w in wl:
            c = w.get("code", "")
            q = quotes.get(c, {})
            cp = q.get("price", 0)
            bp = w.get("price_at_add", 0)
            chg = q.get("change_pct", 0)
            pnl = round((cp - bp) / bp * 100, 2) if bp > 0 else 0
            ad = w.get("date_added", "")
            pr = fetch_post_returns(c, ad, 3) if ad < ts else []
            t1 = f"+{pr[0]['return_pct']}%" if len(pr) > 0 else "-"
            t2 = f"+{pr[1]['return_pct']}%" if len(pr) > 1 else "-"
            t3 = f"+{pr[2]['return_pct']}%" if len(pr) > 2 else "-"
            rows_wl.append({
                "🗑️": False,
                "代码": c,
                "名称": w.get("name", ""),
                "入选日": ad,
                "入选价": bp,
                "当前价": cp,
                "涨跌%": chg,
                "盈亏%": pnl,
                "T+1": t1,
                "T+2": t2,
                "T+3": t3,
                "评分": w.get("score", 0),
                "星级": w.get("star_label", ""),
                "板块": w.get("industry", ""),
            })

        dw = pd.DataFrame(rows_wl)
        valid_pnl = [p for p in dw["盈亏%"] if isinstance(p, (int, float))]
        wr = sum(1 for p in valid_pnl if p > 0) / max(len(valid_pnl), 1) * 100
        pc = sum(1 for p in valid_pnl if p > 0)
        nc = len(valid_pnl) - pc

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("自选", f"{len(wl)}只")
        s2.metric("均盈亏", f"{dw['盈亏%'].mean():+.2f}%" if valid_pnl else "N/A")
        s3.metric("胜率", f"{wr:.0f}%")
        s4.metric("盈亏比", f"{pc}/{nc}")

        st.write("**选择要删除的股票 → 点按钮确认**")

        # ===== 用 multiselect 选择，简单可靠 =====
        wl_options = [f"{w.get('code','?')} {w.get('name','?')}" for w in wl]
        del_selected = st.multiselect(
            "👇 勾选要删除的股票（可多选）",
            options=wl_options,
            default=[],
            key="ms_del",
            placeholder="点击下拉框选择...",
        )

        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("🗑️ 删除选中", key="btn_del_sel"):
                if not del_selected:
                    st.session_state["del_result"] = "⚠️ 请先在上方下拉框中选择要删除的股票"
                else:
                    del_codes = {item.split()[0] for item in del_selected}
                    new_wl = [w for w in wl if w.get("code", "") not in del_codes]
                    save_user_watchlist(uname, new_wl)
                    verify = load_user_watchlist(uname)
                    st.session_state["del_result"] = f"✅ 已删除 {len(del_codes)} 只（验证：当前自选共 {len(verify)} 只）"
                    _cached_quotes.clear()
        with dc2:
            if st.button("🗑️ 清空全部", key="btn_del_all"):
                save_user_watchlist(uname, [])
                st.session_state["del_result"] = "✅ 已清空全部自选"
                _cached_quotes.clear()

        # 新闻：默认折叠
        st.divider()
        with st.expander("📰 最新动态（点击展开）", expanded=False):
            ncols = st.columns(min(len(wl), 3))
            for i, w in enumerate(wl):
                with ncols[i % min(len(wl), 3)]:
                    nm = w.get("name", "")
                    if nm != "未知":
                        nw = fetch_stock_news(nm, 2)
                        if nw:
                            for n in nw:
                                st.caption(f"[{n['date']}] **{nm}** | {n['media']}: {n['title'][:30]}")
                        else:
                            st.caption(f"*{nm}* 暂无新闻")
