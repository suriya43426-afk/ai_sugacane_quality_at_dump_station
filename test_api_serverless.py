import requests
import json
import sys

# ==============================================================================
# CONFIGURATION
# Please paste the values you got from AWS API Gateway below.
# ==============================================================================
API_URL = "https://CHANGE_ME.execute-api.ap-southeast-1.amazonaws.com/v1/log-ai"
API_KEY = "CHANGE_ME_SecretKey"
# ==============================================================================

def test_api_insert():
    print("="*50)
    print("Testing Serverless API Integration")
    print("="*50)
    
    if "CHANGE_ME" in API_URL:
        print("[ERROR] Please update API_URL and API_KEY in test_api_serverless.py first!")
        return

    # Payload matching the Lambda function expectation
    payload = {
        "factory": "MDC",
        "dump_no": 1,
        "plate": "88-8888",
        "ai_result": 5,
        "process": "A"
    }
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY
    }
    
    print(f"[INFO] Sending POST request to: {API_URL}")
    print(f"[INFO] Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=10)
        
        print("\n" + "-"*30)
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        print("-" * 30)
        
        if response.status_code == 200:
            print("[SUCCESS] Data sent successfully to Redshift via API Gateway!")
        elif response.status_code == 403:
            print("[ERROR] 403 Forbidden - Check your API Key.")
        else:
            print(f"[FAILED] Unexpected Error: {response.status_code}")
            
    except Exception as e:
        print(f"[CRITICAL] Request failed: {e}")

if __name__ == "__main__":
    test_api_insert()
