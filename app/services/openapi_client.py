import os
import requests
import base64
import time
import json
from datetime import datetime, timedelta

class OpenAPIClient:
    def __init__(self):
        self.email = os.getenv("OPENAPI_EMAIL")
        self.api_key = os.getenv("OPENAPI_KEY")
        self.base_auth_url = "https://oauth.openapi.it/token"
        self.base_api_url = "https://company.openapi.com"
        self._token = None
        self._token_expire = 0

    def _get_auth_header(self):
        """Construct Basic Auth header for token request"""
        if not self.email or not self.api_key:
            raise ValueError("OPENAPI_EMAIL and OPENAPI_KEY must be set in environment")
        
        credentials = f"{self.email}:{self.api_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def _refresh_token(self):
        """Get new access token from OpenAPI"""
        headers = self._get_auth_header()
        headers["Content-Type"] = "application/json"
        
        # Scopes for Advanced and Full endpoints
        payload = {
            "scopes": [
                "GET:company.openapi.com/IT-advanced",
                "GET:company.openapi.com/IT-full"
            ],
            "ttl": 86400  # 24 hours
        }
        
        print(f"DEBUG: Requesting OpenAPI token...")
        try:
            response = requests.post(self.base_auth_url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("success") is True:
                # Handle potential flat structure vs nested 'data'
                token_source = data.get("data", data)
                self._token = token_source.get("token")
                
                # API returns 'expire' as timestamp (ms)
                expire_ms = token_source.get("expire", 0)
                self._token_expire = expire_ms / 1000
                
                print(f"DEBUG: OpenAPI token obtained. Expires at {datetime.fromtimestamp(self._token_expire)}")
            else:
                raise Exception(f"Failed to get token: {data}")
                
        except requests.exceptions.RequestException as e:
            print(f"ERROR: OpenAPI Auth failed: {str(e)}")
            if e.response:
                print(f"Response: {e.response.text}")
            raise

    def get_token(self):
        """Return valid token, refreshing if necessary"""
        # Buffer of 60 seconds
        if not self._token or time.time() > (self._token_expire - 60):
            self._refresh_token()
        return self._token

    def get_company_data(self, piva: str, mode: str = "advanced"):
        """
        Fetch company data.
        mode: 'advanced' or 'full'
        """
        token = self.get_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        endpoint = "IT-advanced" if mode == "advanced" else "IT-full"
        url = f"{self.base_api_url}/{endpoint}/{piva}"
        
        print(f"DEBUG: Fetching {mode} data for {piva} from {url}")
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                answer = response.json()
                if answer.get("success"):
                    data = answer["data"]
                    if isinstance(data, list) and len(data) > 0:
                         return data[0]
                    return data
                else:
                     # Business logic error (e.g. not found)
                     return {"error": answer.get("message", "Unknown error"), "details": answer}
            
            elif response.status_code == 404:
                return {"error": "Company not found"}
            
            elif response.status_code == 402:
                 return {"error": "Insufficient credit"}
            
            else:
                response.raise_for_status()
                
        except requests.exceptions.RequestException as e:
            print(f"ERROR: OpenAPI Request failed: {str(e)}")
            raise

# Singleton instance
openapi_client = OpenAPIClient()
