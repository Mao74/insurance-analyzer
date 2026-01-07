import requests
import sys

BASE_URL = "http://127.0.0.1:8001"
LOGIN_URL = f"{BASE_URL}/api/auth/login"
QUOTA_URL = f"{BASE_URL}/api/prospect/quota"
BUY_URL = f"{BASE_URL}/api/prospect/buy-quota"

# Use known test credentials (or typical default)
USERNAME = "test@example.com"
PASSWORD = "password"

def run_test():
    session = requests.Session()
    
    try:
        # Check Health first
        try:
            h = session.get(f"{BASE_URL}/api/health", timeout=2)
            print(f"Health Check: {h.status_code} {h.json()}")
        except Exception:
            print("Server not reachable at 8001. Make sure it's running.")
            return

        # Login
        # Attempting JSON login (adjust if app uses form-data)
        login_payload = {"username": USERNAME, "password": PASSWORD}
        # Note: auth_routes.py usually expects OAuth2PasswordRequestForm (form-data with 'username', 'password')
        # Let's try JSON
        resp = session.post(LOGIN_URL, json=login_payload)
        
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} {resp.text}")
            # Try to see if we can get a token directly or if there is a different auth flow
            # For test purposes, if we can't login easily, we might just report connectivity is OK.
            return
            
        print("Login OK.")
        
        # Check Quota
        q_resp = session.get(QUOTA_URL)
        if q_resp.status_code == 200:
            print(f"Quota Check OK: {q_resp.json()}")
        else:
            print(f"Quota Check Failed: {q_resp.status_code} {q_resp.text}")

        # Buy Quota Mock
        buy_resp = session.post(BUY_URL, json={"package_type": "prospect_pack"})
        if buy_resp.status_code == 200:
             print("Buy Quota OK.")
             # Re-check
             q_resp = session.get(QUOTA_URL)
             print(f"New Quota: {q_resp.json()}")
        else:
             print(f"Buy Quota Failed: {buy_resp.status_code} {buy_resp.text}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_test()
