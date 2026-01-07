import os
import sys
from dotenv import load_dotenv

# Force load .env
load_dotenv(r"c:\Antigravity\insurance-analyzer\.env")

# Add app to path
sys.path.append(r"c:\Antigravity\insurance-analyzer")

try:
    from app.services.openapi_client import openapi_client
    
    print(f"DEBUG: Email from env: {os.getenv('OPENAPI_EMAIL')}")
    print(f"DEBUG: Key len from env: {len(os.getenv('OPENAPI_KEY') or '')}")

    piva = "00905811006" # ENI
    print(f"Testing search for P.IVA {piva}...")
    
    data = openapi_client.get_company_data(piva, mode="advanced")
    
    print(f"DEBUG: Data type: {type(data)}")
    import json
    # It's already unwrapped by openapi_client now
    print(f"DEBUG: Full JSON: {json.dumps(data, indent=2)}")
    print(f"DEBUG: ShareHolders: {json.dumps(data.get('shareHolders', []), indent=2)}")

    if "error" in data:
        print(f"ERROR: {data}")
    else:
        print("SUCCESS! Data received.")
        print(f"Ragione Sociale: {data.get('anagrafica', {}).get('denominazione')}")

except Exception as e:
    print(f"EXCEPTION: {e}")
    import traceback
    traceback.print_exc()
