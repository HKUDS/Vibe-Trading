#!/usr/bin/env python3
"""
开户模块
负责资金账号开户和股东账号查询
"""

import requests
from typing import Dict, Optional


class OpenAccountService:
    """开户服务"""
    
    # API基础URL
    BASE_URL = "http://trade.10jqka.com.cn:8088"
    
    # 浏览器User-Agent
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    def __init__(self, timeout: int = 30):
        """
        初始化开户服务
        
        Args:
            timeout: 请求超时时间（秒）
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": self.USER_AGENT
        }
    
    def create_account(self, username: str, yybid: str = "997376") -> Dict:
        """
        创建资金账号
        
        Args:
            username: 用户名
            yybid: 营业部ID（默认997376）
            
        Returns:
            包含资金账号的字典
            
        Raises:
            Exception: 开户失败时抛出异常
        """
        # 构建URL参数
        params = {
            "usrname": username,
            "yybid": yybid,
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_add_user"
        
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
                raise Exception(f"开户失败: {errormsg}")
            
            # 提取资金账号
            capital_account = data.get("errormsg")
            if not capital_account:
                raise Exception("开户成功但未返回资金账号")
            
            return {
                "capital_account": capital_account,
                "department_id": yybid
            }
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"开户请求失败: {str(e)}")
    
    def query_shareholder_account(self, usrid: str, yybid: str = "997376") -> Dict:
        """
        查询股东账号
        
        Args:
            usrid: 资金账号
            yybid: 营业部ID（默认997376）
            
        Returns:
            包含深圳和上海股东账号的字典
            
        Raises:
            Exception: 查询失败时抛出异常
        """
        # 构建URL参数
        params = {
            "usrid": usrid,
            "yybid": yybid,
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_qry_stkaccount_dklc"
        
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
                raise Exception(f"查询股东账号失败: {errormsg}")
            
            # 提取股东账号信息
            result = data.get("result", [])
            if not result:
                raise Exception("未查询到股东账号信息")
            
            shareholder_accounts = {}
            market_codes = {}
            
            for item in result:
                gddm = item.get("gddm")  # 股东账号
                scdm = item.get("scdm")  # 市场代码（1：深圳；2：上海）
                
                if scdm == "1":
                    # 深交所
                    shareholder_accounts["sz"] = gddm
                    market_codes["sz"] = "1"
                elif scdm == "2":
                    # 上交所
                    shareholder_accounts["sh"] = gddm
                    market_codes["sh"] = "2"
            
            if "sz" not in shareholder_accounts and "sh" not in shareholder_accounts:
                raise Exception("未查询到有效的股东账号")
            
            return {
                "shareholder_accounts": shareholder_accounts,
                "market_codes": market_codes
            }
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询股东账号请求失败: {str(e)}")


def main():
    """命令行入口"""
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="开户工具")
    parser.add_argument("--username", type=str, help="用户名")
    parser.add_argument("--usrid", type=str, help="资金账号（用于查询股东账号）")
    parser.add_argument("--yybid", type=str, default="997376", help="营业部ID")
    parser.add_argument("--action", type=str, choices=["create", "query"], help="操作类型")
    
    args = parser.parse_args()
    
    service = OpenAccountService()
    
    if args.action == "create":
        result = service.create_account(args.username, args.yybid)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "query":
        result = service.query_shareholder_account(args.usrid, args.yybid)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
