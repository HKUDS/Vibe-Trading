#!/usr/bin/env python3
"""
股票查询模块
负责股票代码查询和股票信息获取
"""

import re
from typing import Dict, Optional, List


class StockSearchService:
    """股票查询服务"""
    
    # 常见股票代码映射表（示例数据，实际应用中可以从API或数据库获取）
    STOCK_DATABASE = {
        # 腾讯
        "腾讯": {"code": "00700", "name": "腾讯控股", "market": "hk"},
        "腾讯控股": {"code": "00700", "name": "腾讯控股", "market": "hk"},
        
        # 阿里巴巴
        "阿里": {"code": "09988", "name": "阿里巴巴-SW", "market": "hk"},
        "阿里巴巴": {"code": "09988", "name": "阿里巴巴-SW", "market": "hk"},
        
        # 平安
        "平安": {"code": "02318", "name": "平安保险", "market": "hk"},
        "平安保险": {"code": "02318", "name": "平安保险", "market": "hk"},
        
        # 茅台
        "茅台": {"code": "600519", "name": "贵州茅台", "market": "sh"},
        "贵州茅台": {"code": "600519", "name": "贵州茅台", "market": "sh"},
        
        # 工商银行
        "工行": {"code": "601398", "name": "工商银行", "market": "sh"},
        "工商银行": {"code": "601398", "name": "工商银行", "market": "sh"},
        
        # 中国石油
        "中石油": {"code": "601857", "name": "中国石油", "market": "sh"},
        "中国石油": {"code": "601857", "name": "中国石油", "market": "sh"},
        
        # 招商银行
        "招行": {"code": "600036", "name": "招商银行", "market": "sh"},
        "招商银行": {"code": "600036", "name": "招商银行", "market": "sh"},
        
        # 中国人寿
        "中国人寿": {"code": "601628", "name": "中国人寿", "market": "sh"},
        
        # 中国银行
        "中国银行": {"code": "601988", "name": "中国银行", "market": "sh"},
        
        # 农业银行
        "农行": {"code": "601288", "name": "农业银行", "market": "sh"},
        "农业银行": {"code": "601288", "name": "农业银行", "market": "sh"},
        
        # 建设银行
        "建行": {"code": "601939", "name": "建设银行", "market": "sh"},
        "建设银行": {"code": "601939", "name": "建设银行", "market": "sh"},
        
        # 五粮液
        "五粮液": {"code": "000858", "name": "五粮液", "market": "sz"},
        
        # 比亚迪
        "比亚迪": {"code": "002594", "name": "比亚迪", "market": "sz"},
        
        # 宁德时代
        "宁德时代": {"code": "300750", "name": "宁德时代", "market": "sz"},
        
        # 中国平安
        "中国平安": {"code": "000001", "name": "平安银行", "market": "sz"},
        
        # 万科
        "万科": {"code": "000002", "name": "万科A", "market": "sz"},
        "万科A": {"code": "000002", "name": "万科A", "market": "sz"},
        
        # 格力电器
        "格力": {"code": "000651", "name": "格力电器", "market": "sz"},
        "格力电器": {"code": "000651", "name": "格力电器", "market": "sz"},
        
        # 美的集团
        "美的": {"code": "000333", "name": "美的集团", "market": "sz"},
        "美的集团": {"code": "000333", "name": "美的集团", "market": "sz"},
        
        # 海康威视
        "海康威视": {"code": "002415", "name": "海康威视", "market": "sz"},
        
        # 浦发银行
        "浦发银行": {"code": "600000", "name": "浦发银行", "market": "sh"},
        
        # 首创环保
        "首创环保": {"code": "600008", "name": "首创环保", "market": "sh"},
        
        # 华联股份
        "华联股份": {"code": "000882", "name": "华联股份", "market": "sz"},
        
        # 京东方A
        "京东方": {"code": "000725", "name": "京东方A", "market": "sz"},
        "京东方A": {"code": "000725", "name": "京东方A", "market": "sz"},
        
        # 中信证券
        "中信证券": {"code": "600030", "name": "中信证券", "market": "sh"},
        
        # 海通证券
        "海通证券": {"code": "600837", "name": "海通证券", "market": "sh"},
        
        # 中芯国际
        "中芯国际": {"code": "688981", "name": "中芯国际", "market": "sh"},
        
        # 京东集团
        "京东": {"code": "09618", "name": "京东集团-SW", "market": "hk"},
        "京东集团": {"code": "09618", "name": "京东集团-SW", "market": "hk"},
        
        # 美团
        "美团": {"code": "03690", "name": "美团-W", "market": "hk"},
        
        # 小米集团
        "小米": {"code": "01810", "name": "小米集团-W", "market": "hk"},
        "小米集团": {"code": "01810", "name": "小米集团-W", "market": "hk"},
    }
    
    def __init__(self):
        """初始化股票查询服务"""
        pass
    
    def search_stock_code(self, keyword: str) -> Optional[Dict]:
        """
        根据股票名称或代码查询股票信息
        
        Args:
            keyword: 股票名称或代码
            
        Returns:
            股票信息字典，包含code、name、market等字段
            如果未找到返回None
        """
        if not keyword:
            return None
        
        keyword = keyword.strip()
        
        # 1. 直接匹配代码
        if self._is_stock_code(keyword):
            return self._search_by_code(keyword)
        
        # 2. 模糊匹配名称
        return self._search_by_name(keyword)
    
    def _is_stock_code(self, code: str) -> bool:
        """
        判断是否为股票代码
        
        Args:
            code: 待判断的字符串
            
        Returns:
            如果是股票代码返回True，否则返回False
        """
        # A股代码：6位数字
        if re.match(r'^\d{6}$', code):
            return True
        
        # 港股代码：4-5位数字
        if re.match(r'^\d{4,5}$', code):
            return True
        
        return False
    
    def _search_by_code(self, code: str) -> Optional[Dict]:
        """
        根据代码搜索股票
        
        Args:
            code: 股票代码
            
        Returns:
            股票信息字典
        """
        # 去掉前导零
        code = code.lstrip('0') or '0'
        
        for stock in self.STOCK_DATABASE.values():
            stock_code = stock['code'].lstrip('0') or '0'
            if stock_code == code:
                return stock
        
        # 如果未找到，返回一个基本的股票信息对象
        return {
            "code": code.zfill(6),
            "name": "未知股票",
            "market": "unknown"
        }
    
    def _search_by_name(self, name: str) -> Optional[Dict]:
        """
        根据名称搜索股票
        
        Args:
            name: 股票名称
            
        Returns:
            股票信息字典
        """
        # 1. 完全匹配
        if name in self.STOCK_DATABASE:
            return self.STOCK_DATABASE[name]
        
        # 2. 包含匹配
        matches = []
        for stock_name, stock_info in self.STOCK_DATABASE.items():
            if name in stock_name or stock_name in name:
                matches.append((stock_name, stock_info))
        
        if len(matches) == 1:
            return matches[0][1]
        elif len(matches) > 1:
            # 返回第一个匹配的股票
            return matches[0][1]
        
        # 未找到
        return None
    
    def get_market_code(self, stock_code: str) -> Optional[str]:
        """
        获取股票的市场代码
        
        Args:
            stock_code: 股票代码
            
        Returns:
            市场代码（1：深圳；2：上海）
            如果无法确定返回None
        """
        stock_info = self.search_stock_code(stock_code)
        if not stock_info:
            return None
        
        market = stock_info.get("market")
        
        # 映射市场到代码
        market_mapping = {
            "sz": "1",  # 深圳
            "sh": "2",  # 上海
            "hk": None  # 港股不在A股系统
        }
        
        return market_mapping.get(market)
    
    def format_stock_info(self, stock_info: Dict) -> str:
        """
        格式化股票信息为可读字符串
        
        Args:
            stock_info: 股票信息字典
            
        Returns:
            格式化后的字符串
        """
        code = stock_info.get("code", "未知")
        name = stock_info.get("name", "未知")
        market = stock_info.get("market", "未知")
        
        market_names = {
            "sz": "深圳",
            "sh": "上海",
            "hk": "香港",
            "unknown": "未知"
        }
        
        market_name = market_names.get(market, "未知")
        
        return f"{name}（{code}，{market_name}交易所）"


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="股票查询工具")
    parser.add_argument("--keyword", type=str, help="股票名称或代码")
    parser.add_argument("--action", type=str, choices=["search", "market"], default="search", help="操作类型")
    
    args = parser.parse_args()
    
    service = StockSearchService()
    
    if args.action == "search":
        result = service.search_stock_code(args.keyword)
        if result:
            print(service.format_stock_info(result))
        else:
            print("未找到股票信息")
    elif args.action == "market":
        market_code = service.get_market_code(args.keyword)
        if market_code:
            print(f"市场代码: {market_code}")
        else:
            print("无法确定市场代码")


if __name__ == "__main__":
    main()
