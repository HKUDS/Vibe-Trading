#!/usr/bin/env python3
"""
账户管理模块
负责账户信息的读取、保存和验证
"""

import json
import os
from typing import Dict, Optional
from pathlib import Path
import time


class AccountManager:
    """账户管理器"""
    
    # 默认账户文件名
    DEFAULT_ACCOUNT_FILE = "default.json"
    
    def __init__(self, accounts_dir: str = None):
        """
        初始化账户管理器
        
        Args:
            accounts_dir: 账户数据存储目录，默认使用workspace根目录下的user_accounts
        """
        if accounts_dir is None:
            # 使用workspace根目录下的user_accounts，保证skill无个人属性
            # workspace路径: /workspace/projects/workspace/
            workspace_dir = Path("/workspace/projects/workspace")
            accounts_dir = workspace_dir / "user_accounts"
        self.accounts_dir = Path(accounts_dir)
        self._ensure_accounts_dir()
    
    def _ensure_accounts_dir(self):
        """确保账户目录存在"""
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_account_file_path(self) -> Path:
        """
        获取默认账户文件路径
        
        Returns:
            账户文件路径
        """
        return self.accounts_dir / self.DEFAULT_ACCOUNT_FILE
    
    def check_account_exists(self) -> bool:
        """
        检查账户是否存在
        
        Returns:
            如果账户存在返回True，否则返回False
        """
        account_file = self._get_account_file_path()
        return account_file.exists()
    
    def read_account(self) -> Optional[Dict]:
        """
        读取账户信息
        
        Returns:
            账户信息字典，如果账户不存在返回None
        """
        if not self.check_account_exists():
            return None
        
        account_file = self._get_account_file_path()
        try:
            with open(account_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise Exception(f"读取账户信息失败: {str(e)}")
    
    def save_account(self, account_data: Dict) -> bool:
        """
        保存账户信息
        
        Args:
            account_data: 账户信息字典
            
        Returns:
            保存成功返回True，失败返回False
        """
        try:
            username = account_data.get('username')
            if not username:
                raise ValueError("账户信息中缺少username字段")
            
            account_file = self._get_account_file_path()
            with open(account_file, 'w', encoding='utf-8') as f:
                json.dump(account_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            raise Exception(f"保存账户信息失败: {str(e)}")
    
    def update_account(self, update_data: Dict) -> bool:
        """
        更新账户信息
        
        Args:
            update_data: 要更新的字段字典
            
        Returns:
            更新成功返回True，失败返回False
        """
        account = self.read_account()
        if not account:
            raise Exception(f"账户不存在")
        
        # 更新字段
        account.update(update_data)
        
        # 保存更新后的账户信息
        return self.save_account(account)
    
    def delete_account(self) -> bool:
        """
        删除账户信息
        
        Returns:
            删除成功返回True，失败返回False
        """
        try:
            account_file = self._get_account_file_path()
            if account_file.exists():
                account_file.unlink()
                return True
            return False
        except Exception as e:
            raise Exception(f"删除账户信息失败: {str(e)}")
    
    def generate_username(self) -> str:
        """
        生成用户名
        
        Returns:
            格式为 skill_13位时间戳 的用户名
        """
        # 生成13位时间戳（毫秒级）
        timestamp = int(time.time() * 1000)
        return f"skill_{timestamp}"


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="账户管理工具")
    parser.add_argument("--action", type=str, choices=["check", "read", "delete", "generate"], help="操作类型")
    
    args = parser.parse_args()
    
    manager = AccountManager()
    
    if args.action == "check":
        exists = manager.check_account_exists()
        print(f"账户存在: {exists}")
    elif args.action == "read":
        account = manager.read_account()
        if account:
            print(json.dumps(account, ensure_ascii=False, indent=2))
        else:
            print("账户不存在")
    elif args.action == "delete":
        result = manager.delete_account()
        print(f"删除结果: {result}")
    elif args.action == "generate":
        username = manager.generate_username()
        print(f"生成的用户名: {username}")


if __name__ == "__main__":
    main()
