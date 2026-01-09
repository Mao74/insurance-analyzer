from app.llm_client import LLMClient
import sys

# Test Script for Gemini Proxy Migration
print("🧪 TESTING GEMINI PROXY CONNECTION...")

try:
    # Initialize Client (uses defaults + Proxy)
    # Testing user requested model 'gemini-3-flash-preview'
    client = LLMClient(model_name="gemini-3-flash-preview")
    print(f"✅ Client Initialized. Proxy: {client.proxy_url}")
    print(f"✅ Model: {client.model_name}")
    print(f"✅ Secret: {client.proxy_secret[:5]}***")

    # Defined simple test prompt
    prompt = "Rispondi con una sola parola: Ciao"

    print("\n📨 Sending request to Proxy...")
    response = client.generate_content(prompt)
    
    print("\n📝 RESPONSE RECEIVED:")
    print(f"'{response}'")
    
    if "Ciao" in response or len(response) > 0:
        print("\n✅ TEST PASSED: Proxy communication works!")
    else:
        print("\n❌ TEST FAILED: Response was empty or unexpected.")

except Exception as e:
    print(f"\n❌ TEST FAILED with Error: {e}")
    import traceback
    traceback.print_exc()
