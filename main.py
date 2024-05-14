import random
import re
import time
import googlesearch
import concurrent.futures
from decouple import config
import requests
from bs4 import BeautifulSoup
from apis import latest_trials_data_by_organization
from utils import choice_menu, load_profile, load_profiles, save_profile, say
import json
from apis import ask_ai, query_gemini, trucate_to_tokens

savefile = "profiles_gemini.json"


def analyze_organization(organization_name):
    # try:
    profile = compile_profile(organization_name)
    print(f'{profile["relevance"]}/10 - {organization_name}: {profile["shortly"]}')
    # except replicate.exceptions.ModelError as e:
    #     print("Could not analyze organization", organization_name, "due to the following error:", e)

def analyze_organizations(filename):
    with open(filename, "r") as file:
        lines = file.readlines()
    
    organization_names = [line.strip() for line in lines]

    # with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    #     executor.map(analyze_organization, organization_names)

    for organization_name in organization_names:
        analyze_organization(organization_name)

def analyze_trials(filename):
    with open(filename, "r") as file:       
        lines = file.readlines()
    
    organization_names = [line.strip() for line in lines]

    for organization_name in organization_names:
        profile = load_profile(savefile, organization_name)
        if profile:
            new_profile = latest_trials_data_by_organization(profile)
            save_profile(savefile, organization_name, new_profile)

def ask_question():
    q =  input("What would you like to know?\n")

    profiles = load_profiles(savefile)

    property_name = ask_ai(f"How would you call the property of an object that contains the answer to the question: {q.replace('?','')}? Only provide the lower case snake_case_name of the property and nothing else.")
    property_type = ask_ai(f"Given this question: '{q.replace('?','')}', what is the data type of the answer? Please provide the data type in lower case and nothing else. Choose from the following options: integer, string, float, boolean, list, dictionary.")
    print(f"{property_name} ({property_type}):")
    if not property_name or property_name in next(iter(profiles.values())).keys():
        return False
    
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(
            ask_an_organization,
            profiles.keys(),
            [q]*len(profiles),
            [instruction]*len(profiles),
            [property_name]*len(profiles),
            [property_type]*len(profiles))
    

def ask_an_organization(organization_name, q, instruction, property_name, property_type):
    profile = load_profile(savefile, organization_name)
    if not profile.get("questions", False):
        profile["questions"] = []
    
    profile["questions"].append((q.replace('?',''), property_name, property_type))

    answer = ask_ai(f"I would like to know something about an organization called {organization_name}. Please give a conscise answer to question: {q.replace('?','')}? {instruction}")
    if answer:
        try:
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
        except ValueError:
            profile[property_name] = None
        
        print(f"{organization_name}: {profile[property_name]}")

        save_profile(savefile, organization_name, profile)


def finish_question():
    profiles = load_profiles(savefile)
    all_questions = []
    for organization_name, profile in profiles.items():
        if not profile.get("questions", False):
            continue
        all_questions += profile["questions"]
    
    unique_qs = list(set([q[0] for q in all_questions]))
    unique_questions = []
    for q in unique_qs:
        for question in all_questions:
            if question[0] == q:
                unique_questions.append(question)

    unanswered_questions = []
    for question in unique_questions:
        for organization_name, profile in profiles.items():
            if question not in unanswered_questions and question not in profile["questions"]:
                unanswered_questions.append(question)
                break
    choice = choice_menu([q[0] for q in unanswered_questions], "Which question would you like to complete?")
    if choice is not False:
        question, property_name, property_type = unanswered_questions[choice]    
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
        params = []
        for organization_name, profile in profiles.items():
            if question not in [q[0] for q in profile["questions"]]:
                params.append((organization_name, question, instruction, property_name, property_type))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(
                ask_an_organization,
                *[[p[i] for p in params] for i in range(len(params[0]))])



def compile_profile(organization_name):
    profile = load_profile(savefile, organization_name)
    if not profile:
        # Create a new profile for the organization
        print("\tAnalyzing organization:", organization_name, "...")
        profile = {
            "organization_name": organization_name,
            "ai_summary": ask_ai(f"Please write a profile on an organization called {organization_name} and summarize its current operations and goals. Please only write the profile and no meta information (e.g. <here's the overview>)")
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

        search_text = re.sub(r"\n+", "\n", search_text)
        search_text = re.sub(r"\s+", " ", search_text)

        say("Search text complete")
        profile["search_text"] = search_text
        profile["summary"] = ask_ai(f"Please summarize the information about {organization_name} extracted from various websites below and write a profile about the organization. Please only write the overview and no meta information (e.g. <here's the overview>):\n{search_text}")
        profile["relevance"] = ask_ai(f"Please give an integer score between 0 and 10 for the relevance of {organization_name} in improving the health of children and adolescents in developing countries. Only provide the integer score and nothing else.")

        save_profile(savefile, organization_name, profile)

    return profile


choice = True
while choice is not False:
    choices = ["Ask a question", "Complete data on already asked question", "Update profiles (from players.txt)", "Parse clinical trials data"]
    choice = choice_menu(choices, "What would you like to do?")
    if choice is not False:
        if choices[choice] == "Ask a question":
            ask_question()
        if choices[choice] == "Complete data on already asked question":
            finish_question()
        elif choices[choice] == "Update profiles (from players.txt)":
            analyze_organizations("players.txt")
        elif choices[choice] == "Parse clinical trials data":
            analyze_trials("players.txt")
    else:
        break

print("Bye!")
