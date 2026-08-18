#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线形态分析计算器
功能：根据OHLC数据计算K线实体特征、识别基础形态、计算形态强度
"""

import json
from typing import List, Dict


class Kline:
    """单根K线数据类"""
    def __init__(self, date: str, open_p: float, high: float, low: float, close: float, volume: float = 0):
        self.date = date
        self.open = open_p
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
    
    @property
    def is_yang(self) -> bool:
        """是否阳线"""
        return self.close > self.open
    
    @property
    def is_yin(self) -> bool:
        """是否阴线"""
        return self.close < self.open
    
    @property
    def is_doji(self) -> bool:
        """是否十字星（实体小于振幅的10%）"""
        body = abs(self.close - self.open)
        amplitude = self.high - self.low
        if amplitude == 0:
            return True
        return body / amplitude < 0.1
    
    @property
    def body_size(self) -> float:
        """实体大小"""
        return abs(self.close - self.open)
    
    @property
    def upper_shadow(self) -> float:
        """上影线长度"""
        return self.high - max(self.open, self.close)
    
    @property
    def lower_shadow(self) -> float:
        """下影线长度"""
        return min(self.open, self.close) - self.low
    
    @property
    def amplitude(self) -> float:
        """振幅"""
        return self.high - self.low
    
    @property
    def change_pct(self) -> float:
        """涨跌幅"""
        return (self.close - self.open) / self.open * 100


def identify_single_pattern(kline: Kline, prev_klines: List[Kline] = None) -> List[Dict]:
    """识别单根K线形态"""
    patterns = []
    body_ratio = kline.body_size / kline.amplitude if kline.amplitude > 0 else 0
    upper_ratio = kline.upper_shadow / kline.amplitude if kline.amplitude > 0 else 0
    lower_ratio = kline.lower_shadow / kline.amplitude if kline.amplitude > 0 else 0
    
    # 大阳线
    if kline.is_yang and kline.change_pct > 3 and body_ratio > 0.7:
        patterns.append({
            "name": "大阳线",
            "type": "看涨",
            "strength": 3,
            "description": "多头强势，上涨动能充足"
        })
    
    # 大阴线
    if kline.is_yin and abs(kline.change_pct) > 3 and body_ratio > 0.7:
        patterns.append({
            "name": "大阴线",
            "type": "看跌",
            "strength": 3,
            "description": "空头强势，下跌动能充足"
        })
    
    # 十字星
    if kline.is_doji:
        patterns.append({
            "name": "十字星",
            "type": "变盘",
            "strength": 4,
            "description": "多空博弈激烈，可能出现变盘"
        })
    
    # 锤头线（下影线长，实体小，在上方）
    if lower_ratio > 0.6 and body_ratio < 0.3 and upper_ratio < 0.2:
        if prev_klines and len(prev_klines) >= 3:
            recent_trend = prev_klines[-1].close - prev_klines[-3].close
            if recent_trend < 0:
                patterns.append({
                    "name": "锤头线",
                    "type": "看涨反转",
                    "strength": 4,
                    "description": "下跌后出现的底部反转信号"
                })
    
    # 射击之星（上影线长，实体小，在下方）
    if upper_ratio > 0.6 and body_ratio < 0.3 and lower_ratio < 0.2:
        if prev_klines and len(prev_klines) >= 3:
            recent_trend = prev_klines[-1].close - prev_klines[-3].close
            if recent_trend > 0:
                patterns.append({
                    "name": "射击之星",
                    "type": "看跌反转",
                    "strength": 4,
                    "description": "上涨后出现的顶部反转信号"
                })
    
    # 吊颈线
    if lower_ratio > 0.6 and body_ratio < 0.3 and upper_ratio < 0.2:
        if prev_klines and len(prev_klines) >= 3:
            recent_trend = prev_klines[-1].close - prev_klines[-3].close
            if recent_trend > 0:
                patterns.append({
                    "name": "吊颈线",
                    "type": "看跌反转",
                    "strength": 4,
                    "description": "上涨后出现的顶部警示信号"
                })
    
    return patterns


def identify_combo_patterns(klines: List[Kline]) -> List[Dict]:
    """识别组合K线形态"""
    patterns = []
    
    if len(klines) < 2:
        return patterns
    
    last = klines[-1]
    prev = klines[-2]
    
    # 看涨吞没
    if (last.is_yang and prev.is_yin and
        last.open < prev.close and last.close > prev.open):
        body_prev = prev.body_size
        body_last = last.body_size
        if body_last > body_prev * 1.2:
            patterns.append({
                "name": "看涨吞没",
                "type": "看涨反转",
                "strength": 5,
                "description": "底部反转信号，阳线完全包裹前阴线实体"
            })
    
    # 看跌吞没
    if (last.is_yin and prev.is_yang and
        last.open > prev.close and last.close < prev.open):
        body_prev = prev.body_size
        body_last = last.body_size
        if body_last > body_prev * 1.2:
            patterns.append({
                "name": "看跌吞没",
                "type": "看跌反转",
                "strength": 5,
                "description": "顶部反转信号，阴线完全包裹前阳线实体"
            })
    
    # 孕线
    if (last.body_size < prev.body_size * 0.6 and
        min(last.open, last.close) > min(prev.open, prev.close) and
        max(last.open, last.close) < max(prev.open, prev.close)):
        patterns.append({
            "name": "孕线",
            "type": "变盘",
            "strength": 3,
            "description": "趋势酝酿变盘，波动率收缩"
        })
    
    # 早晨之星（三根K线）
    if len(klines) >= 3:
        k3 = klines[-3]
        k2 = klines[-2]
        k1 = klines[-1]
        if (k3.is_yin and k3.change_pct < -2 and
            k2.is_doji and
            k1.is_yang and k1.change_pct > 2 and
            k1.close > (k3.open + k3.close) / 2):
            patterns.append({
                "name": "早晨之星",
                "type": "看涨反转",
                "strength": 5,
                "description": "经典底部反转形态，下跌-十字星-上涨"
            })
        
        # 黄昏之星
        if (k3.is_yang and k3.change_pct > 2 and
            k2.is_doji and
            k1.is_yin and abs(k1.change_pct) > 2 and
            k1.close < (k3.open + k3.close) / 2):
            patterns.append({
                "name": "黄昏之星",
                "type": "看跌反转",
                "strength": 5,
                "description": "经典顶部反转形态，上涨-十字星-下跌"
            })
        
        # 红三兵
        if (all(k.is_yang for k in [k3, k2, k1]) and
            k1.close > k2.close > k3.close and
            k1.body_size > k2.body_size * 0.8 and
            k2.body_size > k3.body_size * 0.8):
            patterns.append({
                "name": "红三兵",
                "type": "看涨持续",
                "strength": 4,
                "description": "连续三根阳线，上涨趋势确认"
            })
        
        # 黑三鸦
        if (all(k.is_yin for k in [k3, k2, k1]) and
            k1.close < k2.close < k3.close and
            abs(k1.change_pct) > 1 and abs(k2.change_pct) > 1 and abs(k3.change_pct) > 1):
            patterns.append({
                "name": "黑三鸦",
                "type": "看跌持续",
                "strength": 4,
                "description": "连续三根阴线，下跌趋势确认"
            })
    
    return patterns


def analyze_klines(klines_data: List[Dict]) -> Dict:
    """
    分析K线数据，识别形态
    
    Args:
        klines_data: K线数据列表，每项包含date/open/high/low/close/volume
    
    Returns:
        分析结果字典
    """
    klines = []
    for k in klines_data:
        klines.append(Kline(
            date=k.get("date", ""),
            open_p=float(k["open"]),
            high=float(k["high"]),
            low=float(k["low"]),
            close=float(k["close"]),
            volume=float(k.get("volume", 0))
        ))
    
    all_patterns = []
    
    # 识别单根K线形态
    for i, kline in enumerate(klines):
        prev_klines = klines[:i]
        single_patterns = identify_single_pattern(kline, prev_klines)
        for p in single_patterns:
            p["position"] = i + 1
            p["date"] = kline.date
            all_patterns.append(p)
    
    # 识别组合形态
    combo_patterns = identify_combo_patterns(klines)
    for p in combo_patterns:
        p["position"] = len(klines)
        p["date"] = klines[-1].date if klines else ""
        all_patterns.append(p)
    
    # 按强度排序
    all_patterns.sort(key=lambda x: x["strength"], reverse=True)
    
    # 综合研判
    bullish = sum(p["strength"] for p in all_patterns if "看涨" in p["type"])
    bearish = sum(p["strength"] for p in all_patterns if "看跌" in p["type"])
    
    if bullish > bearish * 1.5:
        direction = "偏多"
    elif bearish > bullish * 1.5:
        direction = "偏空"
    else:
        direction = "震荡"
    
    return {
        "total_klines": len(klines),
        "pattern_count": len(all_patterns),
        "patterns": all_patterns,
        "bullish_strength": bullish,
        "bearish_strength": bearish,
        "direction": direction,
        "latest_close": klines[-1].close if klines else 0
    }


def double_top_analysis(first_peak: float, second_peak: float, neckline: float, current_price: float) -> Dict:
    """
    双顶形态分析与目标位测算
    
    Args:
        first_peak: 第一个高点价格
        second_peak: 第二个高点价格
        neckline: 颈线位价格
        current_price: 当前价格
    
    Returns:
        分析结果
    """
    top_height = first_peak - neckline
    target_price = neckline - top_height
    peak_diff_pct = abs(first_peak - second_peak) / first_peak * 100
    
    if peak_diff_pct < 3:
        form_level = "标准双顶"
        form_score = 5
    elif peak_diff_pct < 5:
        form_level = "近似双顶"
        form_score = 4
    else:
        form_level = "双顶形态不标准"
        form_score = 2
    
    break_neck = current_price < neckline
    
    return {
        "form_level": form_level,
        "form_score": form_score,
        "top_height": round(top_height, 2),
        "target_price": round(target_price, 2),
        "neckline_break": break_neck,
        "peak_diff_pct": round(peak_diff_pct, 2),
        "suggestion": "已确认跌破颈线，看跌目标位{}".format(round(target_price, 2)) if break_neck else "尚未跌破颈线，关注颈线位支撑"
    }


def calculate_support_resistance(klines_data: List[Dict]) -> Dict:
    """
    计算支撑位和压力位
    
    Args:
        klines_data: K线数据列表
    
    Returns:
        支撑压力位分析
    """
    lows = [float(k["low"]) for k in klines_data]
    highs = [float(k["high"]) for k in klines_data]
    closes = [float(k["close"]) for k in klines_data]
    
    # 简单的支撑压力计算
    recent_low = min(lows[-10:]) if len(lows) >= 10 else min(lows)
    recent_high = max(highs[-10:]) if len(highs) >= 10 else max(highs)
    current_price = closes[-1]
    
    return {
        "current_price": current_price,
        "support_1": round(recent_low, 2),
        "resistance_1": round(recent_high, 2),
        "support_2": round(recent_low * 0.97, 2),
        "resistance_2": round(recent_high * 1.03, 2),
        "position_in_range": round((current_price - recent_low) / (recent_high - recent_low) * 100, 1) if recent_high != recent_low else 50
    }


# ===== 示例运行 =====
if __name__ == "__main__":
    # 测试数据：早晨之星形态
    test_data = [
        {"date": "2026-07-01", "open": 20.50, "high": 20.80, "low": 19.80, "close": 19.90, "volume": 100000},
        {"date": "2026-07-02", "open": 19.90, "high": 20.10, "low": 19.20, "close": 19.30, "volume": 120000},
        {"date": "2026-07-03", "open": 19.30, "high": 19.50, "low": 18.80, "close": 18.90, "volume": 150000},
        {"date": "2026-07-04", "open": 18.90, "high": 19.00, "low": 18.50, "close": 18.80, "volume": 130000},
        {"date": "2026-07-07", "open": 18.80, "high": 19.20, "low": 18.60, "close": 19.10, "volume": 110000},
        {"date": "2026-07-08", "open": 19.10, "high": 19.30, "low": 18.70, "close": 19.00, "volume": 95000},
        {"date": "2026-07-09", "open": 19.00, "high": 19.50, "low": 18.20, "close": 18.30, "volume": 180000},
        {"date": "2026-07-10", "open": 18.30, "high": 18.50, "low": 18.20, "close": 18.40, "volume": 80000},
        {"date": "2026-07-11", "open": 18.40, "high": 19.80, "low": 18.30, "close": 19.60, "volume": 220000},
    ]
    
    print("=" * 50)
    print("K线形态分析结果")
    print("=" * 50)
    result = analyze_klines(test_data)
    print(f"分析K线数: {result['total_klines']}")
    print(f"识别形态数: {result['pattern_count']}")
    print(f"多头力量: {result['bullish_strength']}")
    print(f"空头力量: {result['bearish_strength']}")
    print(f"综合方向: {result['direction']}")
    print(f"最新收盘价: {result['latest_close']}")
    print()
    print("识别到的形态：")
    for p in result["patterns"]:
        stars = "★" * p["strength"] + "☆" * (5 - p["strength"])
        print(f"  - {p['name']} [{p['type']}] {stars}")
        print(f"    {p['description']}")
    
    # 测试双顶分析
    print()
    print("=" * 50)
    print("双顶形态测算示例")
    print("=" * 50)
    dt_result = double_top_analysis(15.0, 14.8, 12.0, 11.5)
    print(json.dumps(dt_result, ensure_ascii=False, indent=2))
    
    # 测试支撑压力位
    print()
    print("=" * 50)
    print("支撑压力位计算示例")
    print("=" * 50)
    sr_result = calculate_support_resistance(test_data)
    print(json.dumps(sr_result, ensure_ascii=False, indent=2))
