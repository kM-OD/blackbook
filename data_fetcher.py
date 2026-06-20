"""
数据获取层 - 联网拉数据
- 龙虎榜: 新浪源(akshare stock_lhb_detail_daily_sina)
- 实时行情: 新浪hq.sinajs.cn(批量快)
- 历史K线: 新浪ak.stock_zh_a_daily
- 大盘指数: 新浪ak.stock_zh_index_daily
- 多日回顾: fetch_multi_day_review() 自动拉近5日K线做资金接力分析
"""
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import requests
import akshare as ak

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}


def _normalize_code(code: str) -> str:
    """6位代码 → sh600000 / sz000001"""
    code = str(code).strip().zfill(6)
    if code.startswith(("6", "9", "5")):
        return f"sh{code}"
    return f"sz{code}"


def _ma(closes: List[float], n: int) -> Optional[float]:
    """计算N日均线"""
    if len(closes) < n:
        return None
    return round(sum(closes[-n:]) / n, 2)


# ===================== 龙虎榜 =====================
def fetch_lhb_one_day(date: str) -> List[dict]:
    """
    拉某日龙虎榜(新浪源,99只/天)
    date: '2026-06-17'
    """
    try:
        date_compact = date.replace("-", "")
        df = ak.stock_lhb_detail_daily_sina(date_compact)
        if df is None or len(df) == 0:
            return []
        records = []
        for _, row in df.iterrows():
            change_pct = float(row.get("对应值", 0))
            records.append({
                "code": str(row.get("股票代码", "")).zfill(6),
                "name": str(row.get("股票名称", "")),
                "date": date,
                "close": float(row.get("收盘价", 0)),
                "change_pct": change_pct,
                "turnover": 0,
                "net_buy": 0,
                "buy_amt": 0,
                "sell_amt": 0,
                "reason": str(row.get("指标", "")),
                "上榜类型": _classify_reason(str(row.get("指标", ""))),
            })
        return records
    except Exception as e:
        print(f"龙虎榜 {date} 拉取失败: {e}")
        return []


def _classify_reason(reason: str) -> str:
    """上榜原因分类"""
    if "涨幅" in reason and "7%" in reason:
        return "涨幅偏离7%"
    if "跌幅" in reason and "7%" in reason:
        return "跌幅偏离7%"
    if "涨停" in reason:
        return "涨停"
    if "跌停" in reason:
        return "跌停"
    if "换手率" in reason and "20%" in reason:
        return "换手率20%"
    if "连续" in reason:
        return "连续三日"
    return "其他"


# ===================== 实时行情 =====================
def fetch_realtime_quotes(codes: List[str]) -> Dict[str, dict]:
    """批量拉实时行情(新浪)"""
    if not codes:
        return {}
    result = {}
    batch_size = 100
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        symbols = ",".join(_normalize_code(c) for c in batch)
        url = f"https://hq.sinajs.cn/list={symbols}"
        try:
            r = requests.get(url, headers=COMMON_HEADERS, timeout=10)
            for line in r.text.strip().split("\n"):
                if "=" not in line or '""' in line:
                    continue
                prefix, rest = line.split("=", 1)
                code = prefix.split("_")[-1]
                pure_code = code[2:]
                data = rest.strip('";\n ')
                if not data:
                    continue
                fields = data.split(",")
                if len(fields) < 32:
                    continue
                try:
                    result[pure_code] = {
                        "name": fields[0],
                        "open": float(fields[1]) if fields[1] else 0,
                        "prev_close": float(fields[2]) if fields[2] else 0,
                        "price": float(fields[3]) if fields[3] else 0,
                        "high": float(fields[4]) if fields[4] else 0,
                        "low": float(fields[5]) if fields[5] else 0,
                        "volume": int(float(fields[8])) if fields[8] else 0,
                        "amount": float(fields[9]) if fields[9] else 0,
                        "date": fields[30] if len(fields) > 30 else "",
                    }
                    if result[pure_code]["prev_close"] > 0:
                        result[pure_code]["change_pct"] = round(
                            (result[pure_code]["price"] - result[pure_code]["prev_close"])
                            / result[pure_code]["prev_close"] * 100, 2
                        )
                    else:
                        result[pure_code]["change_pct"] = 0
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"实时行情第 {i//batch_size+1} 批失败: {e}")
        time.sleep(0.3)
    return result


# ===================== 大盘指数 =====================
def fetch_index_daily(code: str, start_date: str, end_date: str) -> List[dict]:
    """
    拉大盘指数日K线
    code: 'sh000001'(上证) / 'sz399001'(深成) / 'sz399006'(创业板)
    返回: [{date, close, change_pct, ...}, ...]
    涨跌幅基于前一交易日收盘计算
    """
    try:
        df = ak.stock_zh_index_daily(symbol=code)
        if df is None or len(df) == 0:
            return []
        df = df.copy()
        df["date_str"] = df["date"].astype(str)
        s = start_date.replace("-", "")
        e = end_date.replace("-", "")
        s_norm = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        e_norm = f"{e[:4]}-{e[4:6]}-{e[6:8]}"
        df_range = df[df["date_str"] <= e_norm].tail(10).sort_values("date_str").reset_index(drop=True)
        if len(df_range) == 0:
            return []
        results = []
        prev_close = None
        for _, row in df_range.iterrows():
            close = float(row.get("close", 0))
            change_pct = 0
            if prev_close and prev_close > 0:
                change_pct = round((close - prev_close) / prev_close * 100, 2)
            results.append({
                "date": row["date_str"],
                "open": float(row.get("open", 0)),
                "close": close,
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "volume": float(row.get("volume", 0)),
                "change_pct": change_pct,
            })
            prev_close = close
        return [r for r in results if s_norm <= r["date"] <= e_norm]
    except Exception as e:
        print(f"指数 {code} 拉取失败: {e}")
        return []


# ===================== 单只K线 =====================
def fetch_kline_one(code: str, start_date: str, end_date: str) -> List[dict]:
    """拉单只股票K线(北交所/失败返回空)"""
    pure = _normalize_code(code)
    try:
        df = ak.stock_zh_a_daily(symbol=pure, start_date=start_date.replace("-", ""),
                                  end_date=end_date.replace("-", ""), adjust="qfq")
        if df is None or len(df) == 0:
            return []
        results = []
        for _, row in df.iterrows():
            # 北交所或异常接口可能没date列
            if "date" not in row.index:
                return []
            results.append({
                "date": str(row.get("date", ""))[:10],
                "open": float(row.get("open", 0)),
                "close": float(row.get("close", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "volume": float(row.get("volume", 0)),
                "turnover": float(row.get("turnover", 0)),
            })
        return results
    except Exception:
        return []


# ===================== 多日回顾(核心新增) =====================
def fetch_multi_day_review(code: str, end_date: str, days: int = 5) -> Dict:
    """
    拉近N日K线 + 自动计算多日回顾指标(用于判断资金接力)
    返回: {
        "klines": [...],           # 近N日K线
        "N日内涨跌幅%": 5.2,
        "是否突破MA60": True,      # 当前价在MA60上方
        "MA60": 32.5,
        "MA20": 33.1,
        "量比": 1.3,               # 今日量/5日均量
        "换手率5日均": 4.2,
        "资金净流入推算_亿": 0.8,  # 启发式: (今日量 - 5日均量) * 均价 → 主力净流入
        "主力连续净流入天数": 2,    # 启发式: 连续N日价涨量增
    }
    """
    try:
        # 多取60日为了算MA60
        start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=80)).strftime("%Y-%m-%d")
        klines = fetch_kline_one(code, start, end_date)
        if not klines or len(klines) < 5:
            return {"klines": [], "valid": False}

        closes = [k["close"] for k in klines]
        volumes = [k["volume"] for k in klines]
        turnovers = [k.get("turnover", 0) for k in klines]

        # 取近N日
        recent = klines[-days:]
        recent_closes = [k["close"] for k in recent]
        recent_vols = [k["volume"] for k in recent]
        recent_turns = [k.get("turnover", 0) for k in recent]

        # N日涨跌幅
        n_chg = round((recent_closes[-1] - recent_closes[0]) / recent_closes[0] * 100, 2) if recent_closes[0] > 0 else 0

        # MA60
        ma60 = _ma(closes, 60)
        ma20 = _ma(closes, 20)
        ma5 = _ma(closes, 5)
        above_ma60 = ma60 is not None and recent_closes[-1] > ma60

        # 量比(今日量/5日均量)
        avg_vol_5 = sum(recent_vols) / len(recent_vols) if recent_vols else 0
        vol_ratio = round(recent_vols[-1] / avg_vol_5, 2) if avg_vol_5 > 0 else 0

        # 换手率5日均
        avg_turn_5 = round(sum(recent_turns) / len(recent_turns), 2) if recent_turns else 0

        # 启发式: 资金净流入推算
        # 逻辑: (今日成交额 - 5日均成交额) → 多出来的成交额视作"主力净流入"(以万为单位)
        today_amount = recent_vols[-1] * recent_closes[-1]  # 成交额(元)
        avg_amount_5 = sum(recent_vols[i] * recent_closes[i] for i in range(len(recent))) / len(recent)
        flow_yi = round((today_amount - avg_amount_5) / 1e8, 2)  # 亿

        # 主力连续净流入天数(启发式: 连续N日"价涨+量增")
        up_days = 0
        for i in range(1, len(recent)):
            if recent_closes[i] > recent_closes[i-1] and recent_vols[i] > recent_vols[i-1]:
                up_days += 1
            else:
                up_days = 0  # 连续中断

        return {
            "valid": True,
            "klines": recent,
            "N日内涨跌幅%": n_chg,
            "MA60": ma60,
            "MA20": ma20,
            "MA5": ma5,
            "是否在MA60上方": above_ma60,
            "量比": vol_ratio,
            "换手率5日均": avg_turn_5,
            "资金净流入推算_亿": flow_yi,
            "主力连续净流入天数": up_days,
        }
    except Exception as e:
        print(f"{code} 多日回顾失败: {e}")
        return {"valid": False, "klines": []}


def fetch_multi_day_review_batch(codes: List[str], end_date: str, days: int = 5) -> Dict[str, Dict]:
    """批量拉多日回顾(单线程,避免被封)"""
    results = {}
    for i, code in enumerate(codes):
        results[code] = fetch_multi_day_review(code, end_date, days)
        if (i + 1) % 5 == 0:
            time.sleep(0.2)  # 歇一下
    return results


# ===================== 交易日判定 =====================
def _is_trading_day(date: str) -> bool:
    """
    检查某日是否为A股交易日
    逻辑: 能拉到该日的大盘K线即为交易日
    """
    try:
        klines = fetch_index_daily("sh000001", date, date)
        if not klines:
            return False
        return any(k.get("date", "") == date for k in klines)
    except Exception:
        return False


# ===================== 市场环境 =====================
def get_market_env_by_index(date: str) -> str:
    """
    双指数综合判定(强/中/弱)
    - 上证<-1.5% AND 深证<-1.0% → 弱市
    - 上证>+1.0% AND 深证>+0.5% → 强市
    - 否则中性
    """
    try:
        sh = fetch_index_daily("sh000001", date, date)
        sz = fetch_index_daily("sz399001", date, date)
        if not sh or not sz:
            return "中性"
        sh_chg = sh[-1].get("change_pct", 0)
        sz_chg = sz[-1].get("change_pct", 0)
        if sh_chg <= -1.5 and sz_chg <= -1.0:
            return "弱市"
        if sh_chg >= 1.0 and sz_chg >= 0.5:
            return "强市"
        return "中性"
    except Exception as e:
        print(f"市场环境判定失败: {e}")
        return "中性"


# ===================== 补充实时 =====================
def fill_lhb_with_realtime(lhb_list: List[dict], date: str) -> List[dict]:
    """用实时行情补充龙虎榜"""
    if not lhb_list:
        return lhb_list
    today = datetime.now().strftime("%Y-%m-%d")
    if date != today:
        return lhb_list

    codes = [r["code"] for r in lhb_list]
    quotes = fetch_realtime_quotes(codes)

    for r in lhb_list:
        c = r["code"]
        if c in quotes:
            q = quotes[c]
            r["close"] = q["price"]
            r["change_pct"] = q["change_pct"]
            r["volume"] = q["volume"]
            r["amount"] = q["amount"]
            r["turnover"] = 0
    return lhb_list


# ===================== 板块/行业查询 =====================
def fetch_stock_industry_batch(codes: List[str]) -> Dict[str, str]:
    """
    批量查询股票所属行业(板块)
    返回: {code: "行业名称"}
    优先用东财个股信息接口,失败则用名称启发式匹配
    """
    result = {}
    for code in codes:
        result[code] = _query_industry(code)
    return result


# 行业关键词映射 (用于启发式 fallback)
_INDUSTRY_KEYWORDS = {
    "半导体": ["芯片", "集成电路", "半导体", "存储", "晶圆", "封装", "光刻", "射频", "模拟芯片"],
    "电力": ["电力", "电网", "水电", "火电", "核电", "风电", "光伏发电", "热电", "新能源运营"],
    "房地产": ["地产", "房产", "置业", "城建", "城投", "开发", "建筑"],
    "银行": ["银行", "农商行", "农信社"],
    "白酒": ["白酒", "酿酒", "茅台", "五粮液", "汾酒", "酒"],
    "医药": ["医药", "生物制药", "中药", "化学药", "疫苗", "医疗器械", "诊断"],
    "新能源车": ["电池", "锂电", "正极", "负极", "电解液", "隔膜", "整车", "汽车", "汽配", "新能源车", "比亚迪", "宁德"],
    "人工智能": ["AI", "人工智能", "大模型", "算力", "服务器", "云计算", "数据中心", "软件", "计算机", "威视", "信息", "通讯", "中兴", "网络", "安防"],
    "消费电子": ["电子", "显示", "面板", "光学", "摄像头", "耳机", "手机", "智能终端", "立讯", "歌尔"],
    "化工": ["化学", "化工", "材料", "塑料", "橡胶", "涂料", "化纤"],
    "机械": ["机械", "机床", "重工", "设备", "电梯", "工程机械"],
    "军工": ["军工", "航空", "航天", "船舶", "兵器", "国防"],
    "通信": ["通信", "5G", "光纤", "光缆", "基站", "天线", "运营商"],
    "家电": ["家电", "空调", "冰箱", "洗衣机", "厨电", "小家电"],
    "食品": ["食品", "饮料", "乳品", "调味", "预制菜", "农牧"],
    "有色": ["铜", "铝", "锌", "稀土", "黄金", "锂矿", "金属", "矿产"],
    "煤炭": ["煤炭", "焦煤", "焦炭", "能源开采"],
    "钢铁": ["钢铁", "特钢", "钢材"],
    "传媒": ["传媒", "影视", "游戏", "广告", "出版", "教育"],
    "交通运输": ["航运", "港口", "机场", "高速", "物流", "快递", "铁路"],
}


def _query_industry(code: str) -> str:
    """查单只股票的行业,先尝试API再fallback"""
    # 方案1: 东财个股信息
    try:
        df = ak.stock_individual_info_em(symbol=_normalize_code_for_em(code))
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                val = str(row.get("item", "") or "")
                if "行业" in val or "所属" in val:
                    industry = str(row.get("value", "") or "").strip()
                    if industry and len(industry) < 20:
                        return industry
    except Exception:
        pass

    # 方案2: 名称启发式 (需要name参数,这里返回未知,由调用方补)
    return "未知"


def guess_industry_by_name(name: str) -> str:
    """根据股票名称猜测板块"""
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return industry
    return "其他"


def _normalize_code_for_em(code: str) -> str:
    """东财EM格式: 600519 / 000001"""
    return str(code).strip().zfill(6)


# ===================== 后续N日涨幅 =====================
def fetch_post_returns(code: str, base_date: str, days: int = 3) -> List[dict]:
    """
    查询某股在 base_date 之后 N 个交易日的实际涨幅
    用于历史日期选股的"验证"功能
    返回: [{"date": "2026-06-18", "close": 12.34, "return_pct": 1.23}, ...]
    注意: 如果base_date是未来或当天,返回空列表
    """
    from datetime import datetime as dt
    try:
        base_dt = dt.strptime(base_date, "%Y-%m-%d")
        today_dt = dt.now().date()
        # 如果基准日是今天或未来,不查
        if base_dt.date() >= today_dt:
            return []

        end_dt = base_dt + timedelta(days=15)  # 留够余地跳过非交易日
        klines = fetch_kline_one(code, base_date, end_dt.strftime("%Y-%m-%d"))

        results = []
        base_close = None
        found_base = False
        for k in klines:
            kd = k.get("date", "")[:10]
            if kd == base_date:
                base_close = k["close"]
                found_base = True
                continue
            if found_base and base_close and len(results) < days:
                ret = round((k["close"] - base_close) / base_close * 100, 2)
                results.append({
                    "date": kd,
                    "close": k["close"],
                    "return_pct": ret,
                })
        return results
    except Exception as e:
        print(f"{code} 后续涨幅查询失败: {e}")
        return []


# ===================== 个股新闻 =====================
def fetch_stock_news(stock_name: str, count: int = 5) -> list:
    """
    搜索个股相关新闻(东方财富搜索API)
    返回: [{"title": "...", "date": "...", "media": "...", "url": "..."}, ...]
    """
    if not stock_name or stock_name == "未知":
        return []
    try:
        import json as _json
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        params = {
            "cb": "jQuery",
            "param": _json.dumps({
                "uid": "", "keyword": stock_name,
                "type": ["cmsArticleWebOld"],
                "client": "web", "clientType": "web", "clientVersion": "curr",
                "param": {
                    "cmsArticleWebOld": {
                        "searchScope": "default", "sort": "default",
                        "pageIndex": 1, "pageSize": count,
                        "preTag": "", "postTag": ""
                    }
                }
            }, ensure_ascii=False),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://so.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=10)
        # 去掉jsonp回调: 找第一个{和最后一个}之间的内容作为JSON
        text = r.text.strip()
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            json_str = text[first_brace:last_brace + 1]
            data = _json.loads(json_str)
        articles = data.get("result", {}).get("cmsArticleWebOld", [])
        return [{
            "title": a.get("title", ""),
            "date": a.get("date", "")[:10],
            "media": a.get("mediaName", a.get("media", "")),
            "url": a.get("url", ""),
            "content": (a.get("content", "") or "")[:100],
        } for a in articles]
    except Exception as e:
        print(f"新闻搜索失败({stock_name}): {e}")
        return []


# ====== 测试 ======
if __name__ == "__main__":
    print("=" * 60)
    print("测试1: 拉6/17龙虎榜")
    lhb = fetch_lhb_one_day("2026-06-17")
    print(f"  拉到 {len(lhb)} 条")
    if lhb:
        print(f"  首条: {lhb[0]}")

    print()
    print("测试2: 多日回顾 600519")
    review = fetch_multi_day_review("600519", "2026-06-17", days=5)
    if review.get("valid"):
        print(f"  5日涨跌: {review['N日内涨跌幅%']}%")
        print(f"  MA60: {review['MA60']}, MA20: {review['MA20']}")
        print(f"  在MA60上方: {review['是否在MA60上方']}")
        print(f"  量比: {review['量比']}")
        print(f"  资金净流入推算: {review['资金净流入推算_亿']}亿")
        print(f"  主力连续净流入: {review['主力连续净流入天数']}天")
