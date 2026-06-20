"""
黑皮书规则配置 v1.3.1
所有可调参数集中在这里，改这里就等于改规则
"""
import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config_user.json"

# ========== v1.3.1 默认规则 ==========
DEFAULT_RULES = {
    "version": "v1.3.1",

    # ---- 机构(主力) 规则 ----
    "机构淘汰线_股价": 15,           # 机构龙虎榜股价低于此淘汰
    "机构黄金区间_下": 30,           # 机构龙虎榜股价黄金区间下限
    "机构黄金区间_上": 50,           # 机构龙虎榜股价黄金区间上限
    "机构评分_价格权重": 0.30,       # 5维评分: 价格权重
    "机构评分_金额权重": 0.25,       # 5维评分: 金额权重
    "机构评分_数量权重": 0.20,       # 5维评分: 数量权重
    "机构评分_板块权重": 0.15,       # 5维评分: 板块权重
    "机构评分_均线权重": 0.10,       # 5维评分: 均线权重
    "机构评分_及格线": 60,           # 评分低于此淘汰

    # ---- 游资(营业部) 规则 ----
    "游资淘汰线_股价": 10,           # 游资龙虎榜股价低于此淘汰
    "游资参与线_股价": 40,           # 游资龙虎榜股价>=此可参与

    # ---- 红线（4条+1条） ----
    "红线_换手率": 20,               # 换手率>=此淘汰
    "红线_上榜次数": 5,              # 5+次上榜淘汰
    "红线_弱市机构": True,           # 弱市出现机构→淘汰(v1.3.1改回淘汰)
    "红线_涨幅偏离7机构": True,      # 涨幅>=7%且是机构→正式规则(加分→必选)
    "红线_综合评分": 60,             # 评分<60 淘汰

    # ---- 市场环境判定 ----
    "弱市_指数跌幅阈值": -1.5,       # 上证单日跌幅<此=弱市
    "中性市_指数涨跌幅上限": 1.5,    # -1.5%~1.5% = 中性
    "强市_指数涨幅阈值": 1.5,        # 上证单日涨幅>=此=强市

    # ---- 止盈止损 (策略B) ----
    "止损线": -7,                    # -7%止损
    "止盈线": 10,                    # +10%止盈
    "持有天数上限": 5,               # 持有T+1~T+5
}

DEFAULT_PATHS = {
    "龙虎榜数据": "../2026-06-20-12-44-00/lhb_expanded_40days.json",
    "K线缓存":   "../2026-06-20-12-44-00/kline_cache_2026.json",
    "回测结果":   "./backtest_results.json",
    "选股输出":   "./selected_stocks.json",
}


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        # 合并: 默认值+用户保存值
        merged = {**DEFAULT_RULES, **saved.get("rules", {})}
        merged_paths = {**DEFAULT_PATHS, **saved.get("paths", {})}
        return merged, merged_paths
    return DEFAULT_RULES.copy(), DEFAULT_PATHS.copy()


def save_config(rules: dict, paths: dict = None):
    out = {
        "rules": rules,
        "paths": paths or DEFAULT_PATHS,
        "saved_at": __import__("datetime").datetime.now().isoformat()
    }
    # Windows 上偶尔 open(w) 会因权限/文件锁失败,改成先写临时再覆盖
    import os, tempfile
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    # 强制替换(Windows 上需要先删除)
    if os.path.exists(CONFIG_FILE):
        try:
            os.remove(CONFIG_FILE)
        except OSError:
            pass
    os.rename(tmp, CONFIG_FILE)
    return CONFIG_FILE


if __name__ == "__main__":
    rules, paths = load_config()
    print(f"当前规则版本: {rules['version']}")
    print(f"机构淘汰线: 股价<{rules['机构淘汰线_股价']}元")
    print(f"游资参与线: 股价>={rules['游资参与线_股价']}元")
    print(f"止损/止盈: {rules['止损线']}% / +{rules['止盈线']}%")
    print(f"配置已加载，{len(rules)}条规则")
