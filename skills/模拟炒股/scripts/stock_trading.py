#!/usr/bin/env python3
"""
交易模块
负责股票委托下单
"""

import requests
from typing import Dict, Optional


class StockTradingService:
    """股票交易服务"""
    
    # API基础URL
    BASE_URL = "http://trade.10jqka.com.cn:8088"
    
    # 浏览器User-Agent
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    def __init__(self, timeout: int = 30):
        """
        初始化交易服务
        
        Args:
            timeout: 请求超时时间（秒）
        """
        self.timeout = timeout
        self.headers = {
            "User-Agent": self.USER_AGENT
        }
    
    def validate_order_parameters(self, price: float, quantity: int) -> bool:
        """
        验证订单参数
        
        Args:
            price: 委托价格
            quantity: 委托数量
            
        Returns:
            参数有效返回True，否则返回False
            
        Raises:
            ValueError: 参数无效时抛出异常
        """
        if quantity <= 0:
            raise ValueError("委托数量必须大于0")
        
        if quantity % 100 != 0:
            raise ValueError("委托数量必须是100的整数倍")
        
        if price <= 0:
            raise ValueError("委托价格必须大于0")
        
        return True
    
    def place_order(
        self,
        usrid: str,
        stock_code: str,
        shareholder_account: str,
        market_code: str,
        price: float,
        quantity: int,
        direction: str,
        yybid: str = "997376"
    ) -> Dict:
        """
        委托下单
        
        Args:
            usrid: 资金账号
            stock_code: 股票代码
            shareholder_account: 股东账号
            market_code: 市场代码（1：深圳；2：上海）
            price: 委托价格
            quantity: 委托数量（必须是100的整数倍）
            direction: 买卖类别（B：买入；S：卖出）
            yybid: 营业部ID（默认997376）
            
        Returns:
            下单结果字典
            
        Raises:
            Exception: 下单失败时抛出异常
        """
        # 参数校验
        self.validate_order_parameters(price, quantity)
        
        if direction not in ["B", "S"]:
            raise ValueError("买卖类别必须是B（买入）或S（卖出）")
        
        # 构建URL参数
        params = {
            "usrid": usrid,
            "zqdm": stock_code,
            "gddh": shareholder_account,
            "scdm": market_code,
            "yybd": yybid,
            "wtjg": str(price),
            "wtsl": str(quantity),
            "mmlb": direction,
            "datatype": "json"
        }
        
        url = f"{self.BASE_URL}/pt_stk_weituo_dklc"
        
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
                raise Exception(f"委托下单失败: {errormsg}")
            
            # 提取委托结果 - result 是列表
            result_list = data.get("result", [])
            if not result_list:
                raise Exception("下单成功但未返回委托信息")
            
            result = result_list[0] if isinstance(result_list, list) else result_list
            
            return {
                "success": True,
                "entrust_no": result.get("entrust_no"),
                "message": "委托下单成功"
            }
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"委托下单请求失败: {str(e)}")


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="股票交易工具")
    parser.add_argument("--usrid", type=str, help="资金账号")
    parser.add_argument("--stock-code", type=str, help="股票代码")
    parser.add_argument("--shareholder-account", type=str, help="股东账号")
    parser.add_argument("--market-code", type=str, help="市场代码（1：深圳；2：上海）")
    parser.add_argument("--price", type=float, help="委托价格")
    parser.add_argument("--quantity", type=int, help="委托数量")
    parser.add_argument("--direction", type=str, choices=["B", "S"], help="买卖类别（B：买入；S：卖出）")
    parser.add_argument("--yybid", type=str, default="997376", help="营业部ID")
    
    args = parser.parse_args()
    
    service = StockTradingService()
    
    result = service.place_order(
        args.usrid,
        args.stock_code,
        args.shareholder_account,
        args.market_code,
        args.price,
        args.quantity,
        args.direction,
        args.yybid
    )
    
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
