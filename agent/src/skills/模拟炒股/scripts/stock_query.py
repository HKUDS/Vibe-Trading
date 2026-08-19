#!/usr/bin/env python3
"""
查询模块
负责各种查询功能：持仓、盈利、资金、成交记录等
"""

import requests
from typing import Dict, Optional, List


class StockQueryService:
    """股票查询服务"""
    
    # API基础URL
    BASE_URL = "http://trade.10jqka.com.cn:8088"
    
    # 浏览器User-Agent
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    def __init__(self, timeout: int = 30):
        """
        初始化查询服务
        
        Args:
            timeout: 请求超时时间（秒）
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": self.USER_AGENT
        }
    
    def query_positions(self, usrid: str, yybid: str = "997376") -> Dict:
        """
        查询持仓
        
        Args:
            usrid: 资金账号
            yybid: 营业部ID（默认997376）
            
        Returns:
            持仓信息字典
            
        Raises:
            Exception: 查询失败时抛出异常
        """
        # 构建URL参数
        params = {
            "name": usrid,
            "yybid": yybid,
            "type": "1",  # 1表示资金账号
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_web_qry_stock"
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # 检查HTTP状态码
            if response.status_code >= 400:
                raise Exception(f"HTTP请求失败: 状态码 {response.status_code}, 响应内容: {response.text}")
            
            data = response.json()
            
            # 检查业务状态码
            errorcode = data.get("errorcode", -1)
            if errorcode != 0:
                errormsg = data.get("errormsg", "未知错误")
                raise Exception(f"查询持仓失败: {errormsg}")
            
            # 提取持仓数据
            positions = data.get("result", []) or data.get("list", [])
            
            return {
                "positions": positions,
                "total_count": len(positions)
            }
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询持仓请求失败: {str(e)}")
    
    def query_profit_info(self, username: str, yybid: str = "997376") -> Dict:
        """
        查询个人盈利情况
        
        Args:
            username: 用户名
            yybid: 营业部ID（默认997376）
            
        Returns:
            盈利情况字典
            
        Raises:
            Exception: 查询失败时抛出异常
        """
        # 构建URL参数
        params = {
            "usrname": username,
            "yybid": yybid,
            "type": "",
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_qry_userinfo_v1"
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # 检查HTTP状态码
            if response.status_code >= 400:
                raise Exception(f"HTTP请求失败: 状态码 {response.status_code}, 响应内容: {response.text}")
            
            data = response.json()
            
            # 检查业务状态码
            errorcode = data.get("errorcode", -1)
            if errorcode != 0:
                errormsg = data.get("errormsg", "未知错误")
                raise Exception(f"查询盈利情况失败: {errormsg}")
            
            # 提取盈利数据
            profit_list = data.get("list", [])
            if not profit_list:
                raise Exception("未查询到盈利数据")
            
            profit_info = profit_list[0]
            
            return profit_info
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询盈利情况请求失败: {str(e)}")
    
    def query_fund(self, usrid: str) -> Dict:
        """
        查询用户资金
        
        Args:
            usrid: 资金账号
            
        Returns:
            资金信息字典
            
        Raises:
            Exception: 查询失败时抛出异常
        """
        # 构建URL参数 - 使用 usrid 字段（资金账号）
        params = {
            "usrid": usrid,
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_qry_fund_t"
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # 检查HTTP状态码
            if response.status_code >= 400:
                raise Exception(f"HTTP请求失败: 状态码 {response.status_code}, 响应内容: {response.text}")
            
            data = response.json()
            
            # 检查业务状态码
            errorcode = data.get("errorcode", -1)
            if errorcode != 0:
                errormsg = data.get("errormsg", "未知错误")
                raise Exception(f"查询资金失败: {errormsg}")
            
            # 提取资金数据 - 数据在 list 字段中
            fund_list = data.get("list", [])
            
            if not fund_list:
                raise Exception("未查询到资金数据")
            
            fund_info = fund_list[0]
            
            return fund_info
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询资金请求失败: {str(e)}")
    
    def query_today_trades(self, usrid: str) -> Dict:
        """
        查询当日成交
        
        Args:
            usrid: 资金账号（使用 usrname 字段传递）
            
        Returns:
            当日成交信息字典
            
        Raises:
            Exception: 查询失败时抛出异常
        """
        # 构建URL参数 - 使用 usrname 字段（值为资金账号）
        params = {
            "usrname": usrid,
            "kind": "1",  # 1表示资金账号
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_qry_busin_nocache"
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # 检查HTTP状态码
            if response.status_code >= 400:
                raise Exception(f"HTTP请求失败: 状态码 {response.status_code}, 响应内容: {response.text}")
            
            data = response.json()
            
            # 检查业务状态码
            errorcode = data.get("errorcode", -1)
            if errorcode != 0:
                errormsg = data.get("errormsg", "未知错误")
                raise Exception(f"查询当日成交失败: {errormsg}")
            
            # 提取成交数据 - 数据在 result 或 list 字段中
            trade_items = data.get("result", []) or data.get("list", [])
            
            return {
                "trades": trade_items,
                "total_count": len(trade_items) if isinstance(trade_items, list) else 1
            }
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询当日成交请求失败: {str(e)}")
    
    def query_history_trades(
        self,
        usrid: str,
        start_date: str,
        end_date: str,
        yybid: str = "997376"
    ) -> Dict:
        """
        查询历史成交
        
        Args:
            usrid: 资金账号
            start_date: 开始日期（格式：YYYYMMDD）
            end_date: 结束日期（格式：YYYYMMDD）
            yybid: 营业部ID（默认997376）
            
        Returns:
            历史成交信息字典
            
        Raises:
            Exception: 查询失败时抛出异常
        """
        # 构建URL参数 - 使用 usrname 字段（值为资金账号）
        params = {
            "usrname": usrid,
            "start": start_date,
            "end": end_date,
            "yhbId": yybid,
            "kind": "1",  # 1表示资金账号
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_qry_busin1"
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # 检查HTTP状态码
            if response.status_code >= 400:
                raise Exception(f"HTTP请求失败: 状态码 {response.status_code}, 响应内容: {response.text}")
            
            data = response.json()
            
            # 检查业务状态码
            errorcode = data.get("errorcode", -1)
            if errorcode != 0:
                errormsg = data.get("errormsg", "未知错误")
                raise Exception(f"查询历史成交失败: {errormsg}")
            
            # 提取成交数据
            trade_list = data.get("list", [])
            
            return {
                "trades": trade_list,
                "total_count": len(trade_list)
            }
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询历史成交请求失败: {str(e)}")
    
    def query_30day_gain(self, usrid: str) -> Dict:
        """
        查询近30天收益
        
        Args:
            usrid: 资金账号
            
        Returns:
            近30天收益信息字典
            
        Raises:
            Exception: 查询失败时抛出异常
        """
        # 构建URL参数
        params = {
            "usrid": usrid
        }
        
        url = f"{self.BASE_URL}/pt_qry_gainstat"
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # 检查HTTP状态码
            if response.status_code >= 400:
                raise Exception(f"HTTP请求失败: 状态码 {response.status_code}, 响应内容: {response.text}")
            
            data = response.json()
            
            # 检查业务状态码
            errorcode = data.get("errorcode", -1)
            if errorcode != 0:
                erromsg = data.get("erromsg", "未知错误")
                raise Exception(f"查询近30天收益失败: {erromsg}")
            
            # 提取收益数据
            gain_data = data.get("data", {})
            
            return gain_data
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询近30天收益请求失败: {str(e)}")


def main():
    """命令行入口"""
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="股票查询工具")
    parser.add_argument("--action", type=str, choices=["positions", "profit", "fund", "today", "history", "30day"], help="查询类型")
    parser.add_argument("--usrid", type=str, help="资金账号")
    parser.add_argument("--username", type=str, help="用户名")
    parser.add_argument("--start-date", type=str, help="开始日期（格式：YYYYMMDD）")
    parser.add_argument("--end-date", type=str, help="结束日期（格式：YYYYMMDD）")
    parser.add_argument("--yybid", type=str, default="997376", help="营业部ID")
    
    args = parser.parse_args()
    
    service = StockQueryService()
    
    result = None
    
    if args.action == "positions":
        result = service.query_positions(args.usrid, args.yybid)
    elif args.action == "profit":
        result = service.query_profit_info(args.username, args.yybid)
    elif args.action == "fund":
        result = service.query_fund(args.usrid)
    elif args.action == "today":
        result = service.query_today_trades(args.usrid)
    elif args.action == "history":
        result = service.query_history_trades(args.usrid, args.start_date, args.end_date, args.yybid)
    elif args.action == "30day":
        result = service.query_30day_gain(args.usrid)
    
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
