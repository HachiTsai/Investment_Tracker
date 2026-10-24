"""輕量 Google Sheets API v4 客戶端模組。

透過 Google Cloud Service Account（GCP_SA_KEY 或 GOOGLE_APPLICATION_CREDENTIALS）
以最小依賴（google-auth + requests）完成 Google Sheets 讀取、覆寫、批次更新與清空操作。
專為 GitHub Actions 無人值守排程與本機自動化設計。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"


def get_credentials():
    """解析服務帳戶憑證並取得 OAuth2 存取權限。"""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError:
        raise RuntimeError("未安裝 google-auth 套件，請執行 pip install google-auth")

    sa_key_str = os.environ.get("GCP_SA_KEY")
    if sa_key_str:
        try:
            info = json.loads(sa_key_str)
        except Exception as e:
            raise ValueError(f"GCP_SA_KEY 環境變數無法解析為 JSON: {e}")
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path or not os.path.exists(creds_path):
            raise RuntimeError("未設定 GCP_SA_KEY 或 GOOGLE_APPLICATION_CREDENTIALS，無法進行 Google Sheets 認證。")
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)

    if not creds.valid:
        creds.refresh(Request())
    return creds


class GoogleSheetsClient:
    """輕量 Google Sheets v4 REST API 客戶端。"""

    def __init__(self, token: Optional[str] = None):
        self._token = token

    @property
    def token(self) -> str:
        if not self._token:
            creds = get_credentials()
            self._token = creds.token
        return self._token

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_values(self, sheet_id: str, range_name: str) -> List[List[Any]]:
        """讀取指定範圍之二維陣列值。"""
        url = f"{SHEETS_API_BASE}/{sheet_id}/values/{range_name}"
        resp = requests.get(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json().get("values", [])

    def update_values(
        self,
        sheet_id: str,
        range_name: str,
        values: List[List[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        """覆寫指定範圍之二維陣列值。"""
        url = f"{SHEETS_API_BASE}/{sheet_id}/values/{range_name}?valueInputOption={value_input_option}"
        resp = requests.put(url, headers=self.headers, json={"values": values}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def batch_update_values(
        self,
        sheet_id: str,
        data: List[Dict[str, Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> Dict[str, Any]:
        """批次覆寫多個範圍（適合大量分批寫入）。"""
        url = f"{SHEETS_API_BASE}/{sheet_id}/values:batchUpdate"
        body = {
            "valueInputOption": value_input_option,
            "data": data,
        }
        resp = requests.post(url, headers=self.headers, json=body, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def clear_values(self, sheet_id: str, range_name: str) -> Dict[str, Any]:
        """清空指定範圍之資料（不刪除列）。"""
        url = f"{SHEETS_API_BASE}/{sheet_id}/values/{range_name}:clear"
        resp = requests.post(url, headers=self.headers, json={}, timeout=30)
        resp.raise_for_status()
        return resp.json()
