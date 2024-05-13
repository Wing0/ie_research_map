import os
import random
import time
import googlesearch
import replicate
from decouple import config
import requests
from bs4 import BeautifulSoup
from utils import choice_menu
import json
import tiktoken
import concurrent.futures
from gemini_api import query_gemini

DEBUG = False


def analyze_organization(organization_name):
    try:
        profile = compile_profile(organization_name)
        print(f'{profile["relevance"]}/10 - {organization_name}: {profile["shortly"]}')
    except replicate.exceptions.ModelError as e:
        print("Could not analyze organization", organization_name, "due to the following error:", e)

def analyze_organizations(filename):
    with open(filename, "r") as file:
        lines = file.readlines()
    
    organization_names = [line.strip() for line in lines]

    # with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    #     executor.map(analyze_organization, organization_names)

    for organization_name in organization_names:
        analyze_organization(organization_name)

def ask_question():
    q =  input("What would you like to know?\n")

    # Check if the profiles.json file exists
    if not os.path.exists("profiles_gemini.json"):
        # Create an empty dictionary to store profiles
        profiles = {}
    else:
        # Load existing profiles from the profiles.json file
        with open("profiles_gemini.json", "r") as file:
            profiles = json.load(file)

    property_name = ask_ai(f"How would you call the property of an object that contains the answer to the question: {q.replace('?','')}? Only provide the lower case snake_case_name of the property and nothing else.")
    property_type = ask_ai(f"Given this question: '{q.replace('?','')}', what is the data type of the answer? Please provide the data type in lower case and nothing else. Choose from the following options: integer, string, float, boolean, list, dictionary.")
    print(f"{property_name} ({property_type}):")
    if not property_name and property_name not in next(iter(profiles.values())).keys():
        return False
    
    for key in profiles.keys():
        profile = profiles[key]
        if not profile.get("questions", False):
            profile["questions"] = []
        
        profile["questions"].append((q.replace('?',''), property_name, property_type))
        if property_type == "integer":
            instruction = "Please provide an integer value as the answer and nothing else."
        elif property_type == "string":
            instruction = ""
        elif property_type == "float":
            instruction = "Please provide a float value as the answer and nothing else."
        elif property_type == "boolean":
            instruction = "Please provide a boolean value (True or False) as the answer and nothing else"
        elif property_type == "list":
            instruction = "Please provide a JSON list as the answer and nothing else."
        elif property_type == "dictionary":
            instruction = "Please provide a JSON dictionary value as the answer and nothing else."
        else:
            instruction = ""

        answer = ask_ai(f"I would like to know something about an organization called {key}. Please give a conscise answer to question: {q.replace('?','')}? {instruction}")
        if answer:
            if property_type == "integer":
                profile[property_name] = int(answer)
            elif property_type == "string":
                profile[property_name] = answer
            elif property_type == "float":
                profile[property_name] = float(answer)
            elif property_type == "boolean":
                profile[property_name] = bool(answer)
            elif property_type == "list":
                profile[property_name] = json.loads(answer)
            elif property_type == "dictionary":
                profile[property_name] = json.loads(answer)
            else:
                profile[property_name] = answer
            profiles[key] = profile
            print(f"{key} - {answer}")

            with open("profiles_gemini.json", "w") as file:
                json.dump(profiles, file, indent=4)


def say(*args):
    if DEBUG:
        print(*args)
    else:
        pass

def ask_ai(content, system_prompt="You're a helpful assistant.", gemini=True):
    say("Asking AI:", content[:80] + "...")
    if gemini:
        gemini_response = query_gemini(content)
        # print(gemini_response)
        if gemini_response:
            return gemini_response
    os.environ["REPLICATE_API_TOKEN"] = config('REPLICATE_API_KEY')
    prompt = {
        "top_p": 0.95,
        "prompt": content,
        "system_prompt": system_prompt,
        "temperature": 0.7,
        "prompt_template": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
        "presence_penalty": 0,
        "max_tokens": 2048,
    }

    # result = replicate.models.predictions.create(
    #     model="meta/meta-llama-3-8b-instruct",
    #     input=prompt
    # )
    # while replicate.predictions.get(result.id).status in ["starting", "processing", "running"]:
    #     time.sleep(0.5)
    # print("".join(replicate.predictions.get(result.id).output))

    output = replicate.run(
        "meta/meta-llama-3-70b-instruct",
        input=prompt
    )

    return "".join(output)


def compile_profile(organization_name):
    # Check if the profiles.json file exists
    if not os.path.exists("profiles_gemini.json"):
        # Create an empty dictionary to store profiles
        profiles = {}
    else:
        # Load existing profiles from the profiles.json file
        with open("profiles_gemini.json", "r") as file:
            profiles = json.load(file)

    # Check if the organization profile already exists
    if organization_name in profiles:
        # Profile already exists, do nothing
        profile = profiles[organization_name]
    else:
        # Create a new profile for the organization
        print("\tAnalyzing organization", organization_name)
        profile = {
            "organization_name": organization_name,
            "ai_summary": ask_ai(f"Please write a profile on an organization called {organization_name} and summarize its current operations and goals.")
        }
        say("Organization shortly")
        profile["shortly"] = ask_ai(f"Please write a short summary (without meta information, e.g. here's a short summary) of the organization {organization_name} in one sentence based on this longer description:\n{profile['ai_summary']}")
        say("Finding initiatives")
        profile["ai_recent_initiatives"] = ask_ai(f"What are the most recent initiatives, publications, treatments or trials driven by {organization_name}?")
        # Search for information about the organization on Google
        say("Searching google...")
        search_query = f"{organization_name} information"
        try:
            search_results = googlesearch.search(search_query, num_results=5, sleep_interval=5)
        except requests.exceptions.HTTPError as e:
            time.sleep(random.random()*5)
            search_results = googlesearch.search(search_query, num_results=5, sleep_interval=5)
        
        profile["search_urls"] = []
        for url in search_results:
            profile["search_urls"].append(url)
            time.sleep(random.random()*1)

        # Compile the search results into a single string
        # Make a GET request to each URL in search_results and extract text
        search_text = ""
        for url in profile["search_urls"]:
            try:
                response = requests.get(url, timeout=5)
            except requests.exceptions.SSLError:
                continue
            except requests.exceptions.ReadTimeout:
                say("Read timeout for", url)
                continue

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                visible_text = soup.get_text()
                search_text += visible_text + "\n"

        say("Seach text complete")
        search_text = trucate_to_tokens(search_text) # not necessary for gemini
        profile["summary"] = ask_ai(f"Please summarize the information about {organization_name} extracted from various websites below. Please only write the overview and no meta information (e.g. <here's the overview>):\n{search_text}")
        profile["relevance"] = ask_ai(f"Please give an integer score between 0 and 10 for the relevance of {organization_name} in improving the health of children and adolescents in developing countries. Only provide the integer score and nothing else.")


        profiles[organization_name] = profile

        # Save the updated profiles to the profiles.json file
        with open("profiles_gemini.json", "w") as file:
            json.dump(profiles, file, indent=4)

    return profile


def count_tokens(string: str, encoding_name="cl100k_base") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens


def trucate_to_tokens(prompt, max_tokens=8096):
    tokens = count_tokens(prompt)
    while tokens > max_tokens:
        prompt = " ".join(prompt.split(" ")[:int(max_tokens/tokens*len(prompt.split(" ")))-5])
        tokens = count_tokens(prompt)
    return prompt

# ask_ai("Write a JSON list of the 10 most common health challenges for children and adolescents in the low and middle income countries? Respond with valid JSON only: list of dictionaries with keys: rank, health_challenge.")
# analyze_organizations("players.txt")
choice = True
while choice is not False:
    choices = ["Ask a question"]
    choice = choice_menu(choices, "What would you like to do?")
    if choice is not False:
        if choices[choice] == "Ask a question":
            ask_question()
    else:
        break

print("Bye!")
