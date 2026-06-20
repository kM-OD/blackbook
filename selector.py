"""
黑皮书选股引擎 v1.3.2 - 适配真实数据 + 多日回顾 + 打星评级

v1.3.2 升级:
1. 新增多日回顾维度(5日资金净流入/主力连续天数/MA60位置/量比)
2. 打星评级: ⭐⭐⭐黄金 / ⭐⭐高优 / ⭐标准 / ⚠️观察 / ❌淘汰
3. 资金接力比例明确化: 机构占比% / 游资占比% / 散户占比%
   - 不再笼统说"混合",而是"机构70%+游资30%接,散户洗出"
"""
from typing import Dict, List, Optional


def calc_market_env(index_change_pct: float, rules: dict) -> str:
    """判定市场环境: 强/中/弱"""
    weak_th = rules["弱市_指数跌幅阈值"]
    strong_th = rules["强市_指数涨幅阈值"]
    if index_change_pct <= weak_th:
        return "弱市"
    elif index_change_pct >= strong_th:
        return "强市"
    return "中性"


def infer_capital_breakdown(stock: dict, review: dict) -> Dict:
    """
    资金接力比例分析(明确化谁多谁少)

    优先级:
    1) 当日龙虎榜上榜原因 + 涨幅 → 主力类型判定
    2) 多日回顾数据 → 资金净流入方向 + 主力连续天数
    3) 启发式推算机构vs游资vs散户占比

    返回: {
        "主力类型": "机构" | "游资" | "混合" | "散户",
        "占比": {"机构": 65, "游资": 25, "散户": 10},  # %
        "可信度": "高"|"中"|"低",
        "依据": ["涨幅偏离7%上榜(机构特征)", "5日资金净流入+1.2亿"],
    }
    """
    evidence = []
    change_pct = stock.get("change_pct", 0)
    close = stock.get("close", 0)
    reason = stock.get("reason", "") or stock.get("上榜类型", "")
    turnover = stock.get("turnover", 0)
    is_zt = "涨幅" in reason and "7%" in reason
    is_zt_full = change_pct >= 9.5
    is_huan_20 = "换手率" in reason and "20%" in reason

    flow_yi = review.get("资金净流入推算_亿", 0) if review else 0
    up_days = review.get("主力连续净流入天数", 0) if review else 0
    vol_ratio = review.get("量比", 1) if review else 1

    # 启发式占比初始值
    jg_pct, yz_pct, sh_pct = 33, 33, 34

    # ===== 1) 龙虎榜特征判定主力类型 =====
    if is_zt or is_zt_full:
        # 涨停上榜,大资金博弈
        if close >= 30 and close <= 50:
            # 黄金区间 + 涨停 → 机构概率高
            jg_pct, yz_pct, sh_pct = 60, 30, 10
            evidence.append(f"涨停+股价{close}元在黄金区间(机构主导)")
        elif close >= 40:
            # 高价 + 涨停 → 游资概率高
            jg_pct, yz_pct, sh_pct = 25, 60, 15
            evidence.append(f"涨停+股价{close}元(游资主导)")
        else:
            jg_pct, yz_pct, sh_pct = 40, 40, 20
            evidence.append("涨停上榜,资金结构待定")
    elif is_huan_20:
        # 高换手上榜
        yz_pct, jg_pct, sh_pct = 55, 25, 20
        evidence.append("高换手20%上榜(游资活跃)")
    elif change_pct >= 5 and change_pct < 9:
        # 中等涨幅,温和上涨
        if vol_ratio > 1.5:
            jg_pct, yz_pct, sh_pct = 55, 30, 15
            evidence.append(f"温和上涨+量比{vol_ratio}(机构稳步建仓)")
        else:
            jg_pct, yz_pct, sh_pct = 50, 20, 30
            evidence.append("温和上涨+量能温和(机构+散户)")
    elif change_pct < 0:
        # 下跌上榜(危险)
        yz_pct, jg_pct, sh_pct = 20, 20, 60
        evidence.append("下跌上榜(散户抄底嫌疑)")

    # ===== 2) 多日资金流修正 =====
    if review and review.get("valid"):
        if flow_yi > 0.5 and up_days >= 2:
            # 主力资金持续净流入
            jg_pct = min(80, jg_pct + 10)
            sh_pct = max(5, sh_pct - 10)
            evidence.append(f"5日资金净流入+{flow_yi}亿+连续{up_days}日(主力建仓)")
        elif flow_yi < -0.5:
            # 资金净流出
            sh_pct = min(60, sh_pct + 15)
            jg_pct = max(5, jg_pct - 10)
            evidence.append(f"5日资金净流出{flow_yi}亿(主力离场)")

        if vol_ratio > 2.0:
            yz_pct = min(70, yz_pct + 10)
            evidence.append(f"量比{vol_ratio}(异常放量,游资嫌疑)")

    # 归一化
    total = jg_pct + yz_pct + sh_pct
    jg_pct, yz_pct, sh_pct = round(jg_pct/total*100), round(yz_pct/total*100), round(sh_pct/total*100)
    # 修正四舍五入
    diff = 100 - (jg_pct + yz_pct + sh_pct)
    jg_pct += diff

    # 主力类型
    if jg_pct >= 50:
        capital_type = "机构"
    elif yz_pct >= 50:
        capital_type = "游资"
    elif jg_pct + yz_pct >= 70 and sh_pct <= 25:
        capital_type = "机构+游资"  # 良性接力
    else:
        capital_type = "混合"

    # 可信度
    confidence = "高" if (is_zt or is_zt_full) and review and review.get("valid") else "中"
    if not review or not review.get("valid"):
        confidence = "低"

    return {
        "主力类型": capital_type,
        "占比": {"机构": jg_pct, "游资": yz_pct, "散户": sh_pct},
        "可信度": confidence,
        "依据": evidence,
    }


def calc_score(stock: dict, review: dict, rules: dict) -> float:
    """
    5维评分(0-100):
    - 价格(30) + 资金净流入(25) + 量能(15) + 涨幅(15) + 多日趋势(15)
    """
    score = 0
    price = stock.get("close", 25)
    change_pct = stock.get("change_pct", 0)
    flow_yi = review.get("资金净流入推算_亿", 0) if review and review.get("valid") else 0
    vol_ratio = review.get("量比", 1) if review and review.get("valid") else 1
    above_ma60 = review.get("是否在MA60上方", False) if review and review.get("valid") else False
    up_days = review.get("主力连续净流入天数", 0) if review and review.get("valid") else 0
    n_chg = review.get("N日内涨跌幅%", 0) if review and review.get("valid") else 0

    # 1) 价格(0-30)
    lo, hi = rules["机构黄金区间_下"], rules["机构黄金区间_上"]
    if lo <= price <= hi:
        score += 30
    elif 15 <= price < lo:
        score += 20
    elif price > hi:
        score += 15
    elif 10 <= price < 15:
        score += 10
    else:
        score += 0

    # 2) 资金净流入(0-25)
    if flow_yi >= 2:
        score += 25
    elif flow_yi >= 1:
        score += 18
    elif flow_yi >= 0.3:
        score += 10
    elif flow_yi >= 0:
        score += 5
    else:
        score += 0

    # 3) 量能(0-15)
    if 1.2 <= vol_ratio <= 2.5:
        score += 15
    elif 0.8 <= vol_ratio < 1.2:
        score += 10
    elif vol_ratio > 2.5:
        score += 8
    else:
        score += 3

    # 4) 涨幅(0-15)
    if 0 < change_pct < 5:
        score += 15
    elif 5 <= change_pct < 7:
        score += 13
    elif 7 <= change_pct < 10:
        score += 10
    elif change_pct >= 10:
        score += 8
    elif change_pct >= -3:
        score += 5
    else:
        score += 0

    # 5) 多日趋势(0-15)
    trend_score = 0
    if above_ma60:
        trend_score += 5
    if up_days >= 2:
        trend_score += 5
    if 0 < n_chg <= 10:
        trend_score += 5
    elif n_chg > 10:
        trend_score += 3  # 涨太多反而要小心
    score += trend_score

    return min(100, round(score, 1))


def calc_star_rating(stock: dict, review: dict, capital: Dict, score: float, market_env: str, rules: dict) -> Dict:
    """
    打星评级(基于黑皮书v1.3.1+真实数据)

    ⭐⭐⭐ 黄金信号: 涨停+机构接力(20≤股价<50)+资金净流入>0
    ⭐⭐   高优先级: 涨幅7%+机构 + 评分≥70 + 资金净流入
    ⭐    标准推荐: 评分≥60 + 资金结构健康(机构≥40%且散户≤30%)
    ⚠️   观察名单: 评分50-60,结构待定
    ❌   淘汰: 触发红线/评分<50
    """
    price = stock.get("close", 0)
    change_pct = stock.get("change_pct", 0)
    is_zt = change_pct >= 9.5
    is_7pct = change_pct >= 7
    is_jg = capital["主力类型"] == "机构"
    jg_pct = capital["占比"]["机构"]
    sh_pct = capital["占比"]["散户"]
    flow_yi = review.get("资金净流入推算_亿", 0) if review and review.get("valid") else 0

    # 黄金信号
    if is_zt and 20 <= price < 50 and is_jg and flow_yi > 0:
        return {
            "star": 3, "icon": "⭐⭐⭐", "label": "黄金信号",
            "操作": "✅ 最高优先级,仓位可按上限执行",
            "color": "#FFD700"
        }
    if is_zt and 20 <= price < 50 and capital["主力类型"] == "机构+游资" and flow_yi > 0:
        return {
            "star": 3, "icon": "⭐⭐⭐", "label": "黄金信号",
            "操作": "✅ 最高优先级,机构+游资良性接力",
            "color": "#FFD700"
        }

    # 高优先级
    if is_7pct and is_jg and score >= 70 and flow_yi > 0:
        return {
            "star": 2, "icon": "⭐⭐", "label": "高优先级",
            "操作": "✅ 强烈推荐,正常仓位",
            "color": "#FF6B6B"
        }
    if is_zt and is_jg and score >= 65:
        return {
            "star": 2, "icon": "⭐⭐", "label": "高优先级",
            "操作": "✅ 涨停+机构,数据支撑",
            "color": "#FF6B6B"
        }

    # 标准
    if score >= rules["机构评分_及格线"] and jg_pct >= 40 and sh_pct <= 30:
        return {
            "star": 1, "icon": "⭐", "label": "标准推荐",
            "操作": "✅ 可参与,关注止盈止损",
            "color": "#4CAF50"
        }

    # 观察
    if 50 <= score < rules["机构评分_及格线"]:
        return {
            "star": 0.5, "icon": "⚠️", "label": "观察名单",
            "操作": "🔍 结构待定,等接力信号明确",
            "color": "#FFA726"
        }

    # 淘汰
    return {
        "star": 0, "icon": "❌", "label": "淘汰",
        "操作": "🚫 评分不足或结构不健康",
        "color": "#9E9E9E"
    }


def check_red_lines(stock: dict, market_env: str, capital: Dict, rules: dict) -> List[str]:
    """红线检查"""
    flags = []
    turnover = stock.get("turnover", 5)
    change_pct = stock.get("change_pct", 0)
    reason = stock.get("reason", "") or stock.get("上榜类型", "")
    is_jg = capital["主力类型"] in ("机构", "机构+游资")
    is_yz = capital["主力类型"] == "游资"
    price = stock.get("close", 0)

    # 红线1: 换手率过高
    if turnover >= rules["红线_换手率"]:
        flags.append(f"🔴换手率{turnover}%≥{rules['红线_换手率']}%")

    # 红线2: 弱市+机构
    if rules["红线_弱市机构"] and market_env == "弱市" and is_jg:
        flags.append("🔴弱市机构(淘汰)")

    # 红线3: 跌幅偏离/跌停上榜
    if "跌幅" in reason or "跌停" in reason:
        flags.append("🔴跌幅偏离/跌停上榜(高危)")

    # 红线4: 游资+股价<10
    if is_yz and price < 10:
        flags.append("🔴游资+股价<10元(必淘汰)")

    # 红线5: 游资+涨幅>=7
    if is_yz and change_pct >= 7:
        flags.append("🔴游资+涨幅7%+(高风险)")

    # 加分项
    if rules["红线_涨幅偏离7机构"] and change_pct >= 7 and is_jg:
        flags.append("✅涨幅7%+机构(必选)")

    return flags


def check_hard_reject(stock: dict, market_env: str, capital: Dict, rules: dict) -> Optional[str]:
    """硬性淘汰"""
    price = stock.get("close", 0)
    is_jg = capital["主力类型"] in ("机构", "机构+游资")
    is_yz = capital["主力类型"] == "游资"
    score = stock.get("_score", 70)
    change_pct = stock.get("change_pct", 0)
    reason = stock.get("reason", "") or stock.get("上榜类型", "")

    # 1) 跌幅偏离/跌停上榜 → 必淘汰
    if "跌幅" in reason or "跌停" in reason:
        return f"跌幅偏离/跌停上榜(高危淘汰)"

    # 2) 机构+股价<15
    if is_jg and price < rules["机构淘汰线_股价"]:
        return f"机构+股价{price}元<{rules['机构淘汰线_股价']}元"

    # 3) 游资+股价<10
    if is_yz and price < rules["游资淘汰线_股价"]:
        return f"游资+股价{price}元<{rules['游资淘汰线_股价']}元"

    # 4) 换手率过高
    turnover = stock.get("turnover", 0)
    if turnover >= rules["红线_换手率"]:
        return f"换手率{turnover}%≥{rules['红线_换手率']}%"

    # 5) 游资+涨幅>=7
    if is_yz and change_pct >= 7:
        return f"游资+涨幅{change_pct}%(高风险)"

    return None


def evaluate_stock(stock: dict, market_env: str, rules: dict, review: dict = None) -> Dict:
    """
    单只股票评估(v1.3.2)
    输入: stock(龙虎榜单条) + market_env + rules + review(多日回顾,可选)
    输出: {通过, 评分, 星级, 资金结构(含占比), 触发规则, 淘汰原因, 接力状态}
    """
    capital = infer_capital_breakdown(stock, review or {})
    score = calc_score(stock, review or {}, rules)
    stock["_score"] = score
    stock["主力类型"] = capital["主力类型"]

    rating = calc_star_rating(stock, review or {}, capital, score, market_env, rules)
    red_flags = check_red_lines(stock, market_env, capital, rules)
    reject_reason = check_hard_reject(stock, market_env, capital, rules)

    passed = reject_reason is None

    # 接力状态综合判断
    jg_pct = capital["占比"]["机构"]
    yz_pct = capital["占比"]["游资"]
    sh_pct = capital["占比"]["散户"]
    if jg_pct >= 50 and sh_pct <= 25 and yz_pct < 50:
        relay_state = "🟢 健康接力:机构主导,散户洗出"
    elif yz_pct >= 50 and jg_pct <= 30:
        relay_state = "🟡 游资接力:谨慎参与"
    elif jg_pct + yz_pct >= 70 and sh_pct <= 30:
        relay_state = "🟢 良性接力:机构+游资合力"
    elif sh_pct >= 50:
        relay_state = "🔴 散户主导:警惕接盘"
    else:
        relay_state = "⚪ 结构模糊"

    return {
        "代码": stock.get("code"),
        "名称": stock.get("name"),
        "收盘价": stock.get("close"),
        "涨幅%": stock.get("change_pct"),
        "通过": passed,
        "评分": score,
        "星级": rating,
        "资金结构": capital,
        "主力类型": capital["主力类型"],
        "占比": capital["占比"],
        "可信度": capital["可信度"],
        "依据": capital["依据"],
        "触发规则": red_flags,
        "淘汰原因": reject_reason,
        "接力状态": relay_state,
        "多日回顾": review or {},
    }


if __name__ == "__main__":
    from rules_config import load_config
    rules, _ = load_config()
    test_stock = {
        "code": "600000", "name": "测试股",
        "close": 32.5, "change_pct": 3.2, "turnover": 5.0,
        "net_buy": 1.2e8, "buy_amt": 1.5e8, "sell_amt": 3e7,
        "date": "2026-06-17", "reason": "涨幅偏离值达7%",
    }
    test_review = {
        "valid": True, "N日内涨跌幅%": 5.2, "MA60": 30, "MA20": 32,
        "是否在MA60上方": True, "量比": 1.3, "换手率5日均": 4.2,
        "资金净流入推算_亿": 1.2, "主力连续净流入天数": 2,
    }
    result = evaluate_stock(test_stock, "中性", rules, test_review)
    print(f"通过: {result['通过']}")
    print(f"评分: {result['评分']}")
    print(f"星级: {result['星级']['icon']} {result['星级']['label']}")
    print(f"主力: {result['主力类型']}")
    print(f"占比: {result['占比']}")
    print(f"依据: {result['依据']}")
    print(f"接力: {result['接力状态']}")
    print(f"淘汰: {result['淘汰原因']}")
