import json
import logging
import re


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



def ask_openai_api(system, content, ai_client, model='gpt-4-turbo-preview'):
    messages = [
        {
            "role": "system",
            "content": system
        },
        {
            "role": "user",
            "content": content
        },
    ]
    response = _query_openai_api(messages, ai_client, model)
    if response:
        return response.choices[0].message.content
    else:
        return None


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

def start_run():
    with open(f'run_details.json', 'a') as _:
        pass

    try:
        with open(f'run_details.json', 'r') as file:
            data = json.load(file)
    except:
        data = {}

    data["current_run_cost"] = 0

    with open(f'run_details.json', 'w') as file:
        json.dump(data, file)


def _update_tokens(usage, model):

    try:
        with open(f'run_details.json', 'r') as file:
            data = json.load(file)
    except:
        print("Please call start_run() if you want get up to date cost analysis.")
        data = {}

    if "current_run_cost" not in data.keys():
        data["current_run_cost"] = 0
    if "total_tokens" in data.keys():
        data["total_tokens"] += usage.total_tokens
    else:
        data["total_tokens"] = usage.total_tokens
    if "prompt_tokens" in data.keys():
        data["prompt_tokens"] += usage.prompt_tokens
    else:
        data["prompt_tokens"] = usage.prompt_tokens
    if "completion_tokens" in data.keys():
        data["completion_tokens"] += usage.completion_tokens
    else:
        data["completion_tokens"] = usage.completion_tokens

    if "total_cost" not in data.keys():
        data["total_cost"] = 0
    if model == 'gpt-4-turbo-preview':
        cost_add = usage.prompt_tokens / 1000000 * 10.00 + usage.completion_tokens / 1000000 * 30.00
        data["total_cost"] += cost_add
        data["current_run_cost"] += cost_add
    elif model == 'gpt-4':
        cost_add = usage.prompt_tokens / 1000000 * 30.00 + usage.completion_tokens / 1000000 * 60.00
        data["total_cost"] += cost_add
        data["current_run_cost"] += cost_add
    else:
        cost_add = usage.prompt_tokens / 1000000 * 10.00 + usage.completion_tokens / 1000000 * 30.00
        data["total_cost"] += cost_add
        data["current_run_cost"] += cost_add

    with open(f'run_details.json', 'w') as file:
        json.dump(data, file)


def _query_openai_api(messages, ai_client, model='gpt-4-turbo-preview'):
    """
    This function sends a query to the OpenAI API.
    It takes a list of messages as input.
    Each message is a dictionary with a 'role' (either 'system' or 'user') and 'content' (the content of the message).
    The function returns the response from the OpenAI API.
    """
    try:
        logger.debug("Sending a request to OpenAI API...")
        response = ai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.6,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        logger.debug(response)
        _update_tokens(response.usage, model)

        return response

    except Exception as e:
        logger.error(f"Error querying OpenAI API: {e}")
        return None