import random
import time
from decouple import config
from fp.fp import FreeProxy
import requests
import json

def query_gemini(prompt):
    # Load the last working proxy from the json file
    try:
        with open('last_proxy.json', 'r') as file:
            last_proxy = json.load(file)
    except FileNotFoundError:
        last_proxy = None

    # Use the last working proxy if available
    if last_proxy:
        proxy = last_proxy
    else:
        # Get a new proxy
        proxy = FreeProxy(country_id=['US'], https=True).get()

    # Save the current proxy to the json file
    with open('last_proxy.json', 'w') as file:
        json.dump(proxy, file)

    response = False
    for i in range(3):
        proxies = {
            'https': str(proxy)
        }
        url = f'https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={config("GEMINI_API_KEY")}'
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        # print("Sending request to", url, "with proxy", proxy)
        try:
            response = requests.post(url, proxies=proxies, json=data, timeout=10)
            # print(response.text)
            if not response.status_code == 200:
                raise Exception("Failed to send request due to status code", response.status_code)
            with open('last_proxy.json', 'w') as file:
                json.dump(proxy, file)
            break
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                time.sleep(random.random()*5)
        except Exception as e:
            print("Failed to send request due to the following error:", e)
            proxy = FreeProxy(country_id=['US'], https=True).get()
    
    if response:
        try:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(response.text)
            print("Failed to parse response due to the following error:", e)
            return None
    return None