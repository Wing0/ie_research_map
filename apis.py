import os
import random
import time
from decouple import config
from fp.fp import FreeProxy
import requests
import json
import replicate

import tiktoken
from utils import prompt, say, DEBUG
from openai import OpenAI


def parse_json_from_file(filename):
    with open(filename, 'r') as file:
        return json.load(file)
    

def ask_ai(content, system_role=None, model=False, json_mode=False):
    if not model:
        model, tokens, difficulty = choose_model(content, json_mode)
    else:
        tokens = count_tokens(content)
        difficulty = None
    if tokens > 100000 or (tokens > 10000 and DEBUG):
        if prompt(f"The prompt length is {tokens} tokens. Would you like to shorten it to 8k tokens?", default=True):
            content = trucate_to_tokens(content, 8000)
            tokens = count_tokens(content)
    say(f"Asking {model}: {content[:150]}... [{tokens} tokens, {difficulty}]")
    if model == 'gemini-pro':
        gemini_response = query_gemini(content, system_role)
        if gemini_response:
            return gemini_response
        return ask_ai(content, system_role, 'gpt-4o')
    elif model == 'llama3':
        llama3_response = query_llama3(content, system_role)
        if llama3_response:
            return llama3_response
        return ask_ai(content, system_role, 'gpt-4o')
    elif model == 'gpt-3.5-turbo-0125':
        openai_response = query_openai(content, system_role, 'gpt-3.5-turbo-0125', json_mode)
        if openai_response:
            return openai_response
        return ask_ai(content, system_role, 'gpt-4o')
    elif model == 'gpt-4o':
        openai_response = query_openai(content, system_role, 'gpt-4o', json_mode)
        if openai_response:
            return openai_response
        raise Exception("Failed to get a response from OpenAI API")
    
    return False


def count_tokens(string: str, encoding_name="cl100k_base") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def choose_model(content, json_mode=False):
    tokens = count_tokens(content)
    prompt_start = " ".join(content.split(" ")[:200])
    difficulty = estimate_prompt_difficulty(prompt_start)

    if not difficulty:
        return 'llama3', tokens, difficulty
    if difficulty == "easy":
        if tokens < 8000 and not json_mode:
            model = 'llama3'
        elif tokens < 15500:
            model = 'gpt-3.5-turbo-0125'
        elif tokens < 30000:
            model = 'gpt-4o'
        else:
            model = 'gemini-pro'
    elif difficulty == "moderate":
        if tokens < 8000 and not json_mode:
            model = 'llama3'
        elif tokens < 30000:
            model = 'gpt-4o'
        else:
            model = 'gemini-pro'
    else:
        if tokens < 30000:
            model = 'gpt-4o'
        else:
            model = 'gemini-pro'
    
    return model, tokens, difficulty
            

def estimate_prompt_difficulty(prompt, tries=0):
    response = query_openai(prompt, "Please estimate the difficulty and complexity grade of the following prompt. If the prompt is too long, you will only receive the beginning. Only provide a JSON string with the following keys: 'difficulty' enumerating options (easy, moderate, hard)", model='gpt-3.5-turbo-0125', json_mode=True)
    try:
        response = json.loads(response)
    except:
        response = False
    if response and response.get("difficulty") in ["easy", "moderate", "hard"]:
        return response.get("difficulty")
    if tries > 3:
        return False
    return estimate_prompt_difficulty(prompt, tries+1)


def latest_trials_data_by_organization(profile, since=False):
    url = "https://clinicaltrials.gov/api/v2/studies"
    response = requests.get(url, timeout=5, params={"query.spons": profile["organization_name"], "pageSize": 1000})
    # print(json.dumps(response.json()["studies"][0], indent=4))
    print("Found", len(response.json()["studies"]), "studies for", profile["organization_name"])
    conditions = []
    collaborators = []
    for study in response.json()["studies"]:
        description = study["protocolSection"]["descriptionModule"]["briefSummary"]
        conditions += study["protocolSection"]["conditionsModule"]["conditions"]
        collaborators += [collaborator["name"] for collaborator in study["protocolSection"]["sponsorCollaboratorsModule"].get("collaborators", [])]

    unique_conditions = list(set(conditions))
    condition_counts = {condition: conditions.count(condition) for condition in unique_conditions}
    sorted_conditions = sorted(condition_counts.items(), key=lambda x: x[1], reverse=True)
    profile["top5_conditions"] = sorted_conditions[:5]

    unique_collaborators = list(set(collaborators))
    collaborator_counts = {collaborator: collaborators.count(collaborator) for collaborator in unique_collaborators}
    sorted_collaborators = sorted(collaborator_counts.items(), key=lambda x: x[1], reverse=True)
    profile["top5_collaborators"] = sorted_collaborators[:5]
    
    return profile


def query_gemini(content, system_role=None):
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

    if system_role:
        prompt = f"Role description: {system_role}\n\nPrompt:\n{content}"
    else:
        prompt = content
    response = False
    for i in range(3):
        proxies = {
            'https': str(proxy)
        }
        url = f'https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={config("GEMINI_API_KEY")}'
        data = {"contents": [{"parts": [{"text": prompt}]}]}
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
            say("Failed to send request due to the following error:", e)
            proxy = FreeProxy(country_id=['US'], https=True).get()
    
    if response:
        try:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            say(response.text)
            say("Failed to parse response due to the following error:", e)
            return None
    return None


def query_llama3(content, system_role):
    if system_role is None:
        system_role = "You are a helpful assistant."
    os.environ["REPLICATE_API_TOKEN"] = config('REPLICATE_API_KEY')
    prompt = {
        "top_p": 0.95,
        "prompt": content,
        "system_prompt": system_role,
        "temperature": 0.7,
        "prompt_template": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
        "presence_penalty": 0,
        "max_tokens": 2048,
    }
    output = False
    try:
        output = replicate.run(
            "meta/meta-llama-3-70b-instruct",
            input=prompt
        )
    except replicate.exceptions.ModelError as e:
        if "please retry" in str(e):
            output = replicate.run(
                "meta/meta-llama-3-70b-instruct",
                input=prompt
            )
    if output:
        return "".join(output)
    return output


def query_openai(content, system_role, model='gpt-4o', json_mode=False):
    if system_role is None:
        system_role = "You are a helpful assistant."

    ai_client = OpenAI(
        organization='org-OjCSzLcscYwYrWwsc7EWJZs7',
        project='proj_LL7UZDSKgr42Lp0P7QnO30i1',
        api_key=config('OPENAI_API_KEY')
    )
    
    messages = [
        {
            "role": "system",
            "content": system_role
        },
        {
            "role": "user",
            "content": content
        },
    ]

    try:
        response = ai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.6,
            response_format={ "type": "json_object" } if json_mode else { "type": "text" },
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )

    except Exception as e:
        say(f"Error querying OpenAI API: {e}")
        return None
    
    if response:
        return response.choices[0].message.content
    else:
        return None


def trucate_to_tokens(prompt, max_tokens=8000):
    tokens = count_tokens(prompt)
    say("Tokens before truncation:", tokens)
    while tokens > max_tokens:
        prompt = " ".join(prompt.split(" ")[:int(max_tokens/tokens*len(prompt.split(" ")))-5])
        tokens = count_tokens(prompt)
    say("Tokens after truncation:", tokens)
    return prompt