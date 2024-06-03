import json
import os
import re
from decouple import config
import json
import threading

import requests

DEBUG = False

def post_to_slack(message, json_mode=False):
    url = "https://hooks.slack.com/services/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"
    if not json_mode:
        headers = {
            "Content-Type": "text/plain"
        }
        data = {
            "text": message
        }
    else:
        data = message
        headers = {
            "Content-Type": "application/json"
        }

    response = requests.post(url, json=data, headers=headers)
    if response.status_code != 200:
        print(f"Failed to post to Slack: {response.text}")
        if json_mode:
            print(json.dumps(message, indent=4))
        else:
            print(f"{message}")
        return False
    return True


def choice_menu(menu, title):
    """
    Display a menu of choices and prompt the user to make a selection.

    :param menu: list, the list of options to choose from
    :param title: str, the title of the menu
    :return: int|bool, the index of the chosen option or False if cancelled
    """
    print(title)
    for ind, option in enumerate(menu):
        print(f'{ind + 1}) {option}')
    print('q) Cancel')
    choice = input()
    while choice not in [str(i) for i in range(1, len(menu) + 1)] + ['q']:
        choice = input('Incorrect input. Try again:\n')
    return False if choice == 'q' else int(choice) - 1


def prompt(message, default=None):
    """
    Prompt the user with a yes/no question.

    :param message: str, the message to display
    :param default: bool, the default value if the user presses Enter
    :return: bool, the user's response
    """
    alternatives = ['N', 'n', 'y', 'Y', '0', '1']
    info = '\n[Y/n]: ' if default else '\n[y/N]: ' if default is False else '\n[y/n]: '
    choice = input(message + info).strip()
    while choice not in alternatives + ['']:
        print('Incorrect input. Please try again.')
        choice = input(message + info).strip()
    return {'N': False, 'n': False, 'y': True, 'Y': True, '0': False, '1': True}.get(choice, default)


def clean_string(input_string):
    # Replace whitespace with underscores
    underscore_string = input_string.replace(' ', '_')
    # Strip special characters
    stripped_string = re.sub(r'[^\w_]+', '', underscore_string)
    # Convert to lower case
    lower_case_string = stripped_string.lower()
    return lower_case_string


def cost_report():
    with open(f'run_details.json', 'r') as file:
        data = json.load(file)

    out = f"The current run has costed {round(data['current_run_cost'], 2)}$ so far while the project costs are {round(data['total_cost'], 2)}$ in total."
    print(out)
    return out

def load_profile(savefile, organization_name):
    """
    Load the organization profile from the savefile file.

    :param savefile: str, the path to the savefile file
    :param organization_name: str, the name of the organization
    :return: dict, the organization profile
    """
    # Check if the savefile file exists
    if not os.path.exists(savefile):
        # Create an empty dictionary to store profiles
        profiles = {}
    else:
        # Load existing profiles from the savefile file
        with open(savefile, "r") as file:
            profiles = json.load(file)["profiles"]

    # Check if the organization profile already exists
    if organization_name in profiles:
        # Profile already exists, do nothing
        profile = profiles[organization_name]
        return profile
    
    return False

def load_profiles(savefile):
    """
    Load the organization profiles from the savefile file.

    :param savefile: str, the path to the savefile file
    :return: dict, the organization profile
    """
    # Check if the savefile file exists
    if not os.path.exists(savefile):
        # Create an empty dictionary to store profiles
        profiles = {}
    else:
        # Load existing profiles from the savefile file
        with open(savefile, "r") as file:
            profiles = json.load(file)["profiles"]
        
    return profiles

def load_questions(savefile):
    """
    Load the questions.

    :param savefile: str, the path to the savefile file
    :return: dict, the organization profile
    """
    # Check if the savefile file exists
    if not os.path.exists(savefile):
        # Create an empty dictionary to store profiles
        questions = []
    else:
        # Load existing profiles from the savefile file
        with open(savefile, "r") as file:
            questions = json.load(file)["questions"]
        
    return questions

def save_question(savefile, question):
    """
    Save the question to the savefile file.

    :param savefile: str, the path to the savefile file
    :param profile: tuple, the question
    """
    # Load existing questions from the savefile file
    with open(savefile, "r") as file:
        data = json.load(file)

    # Save the question to the questions list
    if question[0] not in [q[0] for q in data["questions"]]:
        data["questions"].append(question)

    # Save the data to the savefile file
    with open(savefile, "w") as file:
        json.dump(data, file, indent=4)

def save_profile(savefile, organization_name, profile):
    """
    Save the organization profile to the savefile file.

    :param savefile: str, the path to the savefile file
    :param organization_name: str, the name of the organization
    :param profile: dict, the organization profile
    """
    lock = threading.Lock()  # Create a lock object

    with lock:
        # Load existing profiles from the savefile file
        with open(savefile, "r") as file:
            data = json.load(file)

        # Save the organization profile to the profiles dictionary
        data["profiles"][organization_name] = profile

        # Save the profiles dictionary to the savefile file
        with open(savefile, "w") as file:
            json.dump(data, file, indent=4)

def say(*args):
    if DEBUG:
        print(*args)
    else:
        pass
