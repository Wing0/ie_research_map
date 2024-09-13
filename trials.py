import json
import os
import requests
from json.decoder import JSONDecodeError
from ai_apis import ask_ai
from utils import post_to_slack


def post_new_trials_on_slack(threshold=85):
    """
    Posts new clinical trials on Slack if their relevance score exceeds a given threshold.

    Args:
        threshold (int): The minimum relevance score required for a study to be posted on Slack. Default is 85.

    Workflow:
        1. Load settings and conditions from JSON files.
        2. Retrieve all studies and filter out the first one.
        3. Identify brand new studies based on conditions and update the studies dictionary.
        4. Save the updated studies and settings back to their respective JSON files.
        5. Grade and render the most relevant studies using an AI model.
        6. Post the most relevant studies on Slack, ensuring no duplicates are posted.

    Raises:
        Any exceptions related to file I/O or JSON parsing will be handled gracefully.
    """
    # Load only fresh studies from the database
    with open("trials/settings.json", "r") as settings_file:
        settings = json.load(settings_file)
    with open("trials/conditions.json", "r") as file:
        conditions = json.load(file)

    studies = get_all_studies()
    k = list(studies.keys())[0]
    print(studies[k]["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"]["date"], studies[k]['protocolSection']['identificationModule']['officialTitle'], studies[k]["protocolSection"]["conditionsModule"]["conditions"])
    del studies[k]

    brand_new_studies = {}
    for keyword in conditions:
        additional_studies, studies = latest_trials_data_by_condition(
            keyword,
            studies=studies,
            since=settings.get("last_search_date", "2024-09-01"),
            save=False)
        brand_new_studies.update(additional_studies)

    with open("trials/trials.json", "w") as f:
        f.write(json.dumps(studies, indent=4))

    try:
        lookup_date = sorted([s["protocolSection"]["statusModule"]["lastUpdatePostDateStruct"][
                                  "date"] if "lastUpdatePostDateStruct" in s["protocolSection"][
            "statusModule"] else None for k, s in studies.items()])[-1]
        settings["last_search_date"] = lookup_date
    except IndexError:
        pass

    with open("trials/settings.json", "w") as settings_file:
        settings_file.write(json.dumps(settings, indent=4))
    print(len(list(brand_new_studies.keys())), "new studies found in total")
    # Grade and render the most relevant studies
    for id, study in brand_new_studies.items():
        if "biie" not in study:
            study["biie"] = {}
        study["biie"]["url"] = f"https://clinicaltrials.gov/study/{id}"

        if "relevance" not in study["biie"]:
            description = study["protocolSection"]["descriptionModule"]["detailedDescription"] if "detailedDescription" in \
                                                                                                  study["protocolSection"][
                                                                                                      "descriptionModule"] else \
            study["protocolSection"]["descriptionModule"]["briefSummary"]
            title = study['protocolSection']['identificationModule']['officialTitle']
            status = study['protocolSection']['statusModule']['overallStatus']
            phase = ', '.join(study['protocolSection']['designModule']['phases']) if 'phases' in study['protocolSection'][
                'designModule'] else ''
            response = ask_ai(
                f"Please estimate the relevance of the following clinical study with a score from 0 (least relevant) to 100 (most relevant). In your estimation, the following factors carry the most weight in this order: 1) Relevance on child and adolescent health 2) Relevance to global health (not only local) 3) Phase and status of the study. Please give your integer estimate in JSON format under the key 'relevance'.\n===Study===\nTitle: {title}\nPhase: {phase}\nStatus: {status}\nDescription: {description}",
                json_mode=True)
            if response:
                study["biie"]["relevance"] = json.loads(response)["relevance"]

        if study["biie"]["relevance"] > 80:
            summary = describe_study(study, add_title=False)
            study["biie"]["summary"] = summary

        studies[id] = study
        brand_new_studies[id] = study
    with open("trials/trials.json", "w") as f:
        f.write(json.dumps(studies, indent=4))

    # Post on slack
    try:
        with open("trials/slack_posts.json", "r") as json_file:
            slack_posts = json.load(json_file)
    except:
        slack_posts = []
    max_posts = 2
    posts = 0
    new_study_list = list(brand_new_studies.values())
    new_study_list.sort(key=lambda s: s["biie"]["relevance"], reverse=True)
    for study in new_study_list:
        if posts >= max_posts:
            break
        if study["protocolSection"]["identificationModule"]["nctId"] in [s["protocolSection"]["identificationModule"]["nctId"] for s in slack_posts]:
            continue
        if study["biie"]["relevance"] >= threshold:
            title = study['protocolSection']['identificationModule']['officialTitle']
            status = study['protocolSection']['statusModule']['overallStatus']
            phase = ', '.join(study['protocolSection']['designModule']['phases']) if 'phases' in study['protocolSection'][
                'designModule'] else ''
            block = {
                "text": f"New trial: {title}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*New trial:* {title}\n[{phase}{", " if phase else ""}{status}]"
                        }
                    }, {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{study['biie']['summary']}"
                        }
                    }, {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Read more"
                                },
                                "style": "primary",
                                "url": study['biie']['url']
                            }
                        ]
                    }
                ]
            }
            if post_to_slack(block, True):
                posts += 1
                slack_posts.append(study)
    with open("trials/slack_posts.json", "w") as json_file:
        json.dump(slack_posts, json_file, indent=4)


def get_all_studies():
    """
    Load all the studies saved in the archive
    """
    try:
        with open("trials/trials.json", 'r') as studies_file:
            studies = json.load(studies_file)
    except:
        return {}
    return studies


def count_characters(obj):
    """
    Recursively counts the total number of characters in a given object.
    """
    if isinstance(obj, dict):
        return sum(count_characters(v) for v in obj.values())
    elif isinstance(obj, list):
        return sum(count_characters(item) for item in obj)
    else:
        return len(str(obj))


def remove_large_leaves(data, threshold=10000):
    """
    Recursively removes leaf nodes (keys) from the dictionary if their content exceeds the threshold.
    A list is treated as a leaf.
    """
    if not isinstance(data, dict):
        return data

    keys_to_remove = []

    # Iterate over each key-value pair
    for key, value in data.items():
        # If the value is a dictionary, apply the function recursively
        if isinstance(value, dict):
            data[key] = remove_large_leaves(value, threshold)
        else:
            # Check the character count of the current leaf
            if count_characters(value) > threshold:
                keys_to_remove.append(key)

    # Remove the keys that exceeded the threshold
    for key in keys_to_remove:
        data[key] = None

    return data


def latest_trials_data_by_condition(condition_name, studies=None, since=False, save=True):
    """
    Fetches and updates clinical trials data for a specific condition from the ClinicalTrials.gov API.

    Parameters:
    - condition_name (str): The name of the medical condition to search for in clinical trials.
    - studies (dict, optional): An existing dictionary of studies to be updated. If None, the function will
      fetch all existing studies using `get_all_studies()`. Default is None.
    - since (str, optional): A date string in 'YYYY-MM-DD' format to filter trials updated since this date.
      If False, no date filtering is applied. Default is False.

    Returns:
    - tuple: A tuple containing:
        - dict: A dictionary of new trials data. The keys are the NCT IDs of the new studies, and the values
          are the details of these studies.
        - dict: The updated dictionary of all studies including both existing and new data.

    Notes:
    - The function updates a local file named "trials/trials.json" with the latest studies data.
    - It uses pagination to fetch all available studies matching the condition.
    - The function prints the number of new studies found, the total number of studies returned from the API,
      and the number of studies already existing in the archive for the specified condition.
    """

    url = "https://clinicaltrials.gov/api/v2/studies"
    if not studies:
        studies = get_all_studies()
    existing_ids = list(studies.keys())
    response_data = {"nextPageToken": None}
    responded_count = 0
    all_new_ids = []
    while "nextPageToken" in response_data.keys():
        parameters = {"query.cond": condition_name, "pageSize": 1000}
        if since:
            parameters["filter.advanced"] = f"AREA[protocolSection.statusModule.lastUpdateSubmitDate]RANGE[{since}, MAX]"
        try:
            if response_data["nextPageToken"]:
                parameters["pageToken"] = response_data["nextPageToken"]
            response = requests.get(url, timeout=5, params=parameters)
            response_data = response.json()
        except JSONDecodeError as e:
            print(str(e), str(response.text))
            return {}
        responded_count += len(response_data["studies"])
        new_ids = [s["protocolSection"]["identificationModule"]["nctId"] for s in response_data["studies"] if s["protocolSection"]["identificationModule"]["nctId"] not in existing_ids]
        all_new_ids += new_ids
        studies.update({s["protocolSection"]["identificationModule"]["nctId"]: remove_large_leaves(s) for s in response_data["studies"]})
        existing_ids += new_ids
        if save:
            with open("trials/trials.json", "w") as f:
                f.write(json.dumps(studies, indent=4))

    print("Found", f'{len(all_new_ids)} new studies of {responded_count} returned from the API while {len([s for k, s in studies.items() if condition_name.lower() in str(s["protocolSection"]["conditionsModule"]["conditions"]).lower()])}', "studies already exist in archive for", condition_name)

    return {k: s for k, s in studies.items() if k in all_new_ids}, studies


def describe_study(study, print_it=True, add_title=True):
    description = ""
    if add_title:
        description += f"\n[{(', '.join(study['protocolSection']['designModule']['phases']) + ': ') if 'phases' in study['protocolSection']['designModule'].keys() else '' }{study['protocolSection']['statusModule']['overallStatus']}]"
        description += study["protocolSection"]["identificationModule"]["briefTitle"]
        description += f" ({study['protocolSection']['statusModule']['lastUpdateSubmitDate']})"

    study_description = study["protocolSection"]["descriptionModule"]["detailedDescription"] if "detailedDescription" in study["protocolSection"]["descriptionModule"] else study["protocolSection"]["descriptionModule"]["briefSummary"]
    summary = ask_ai("Please summarize the following clinical trials description in up to three bullet points. Start each point with '<bullet>', which will later be replaced with the correct symbol. Only provide the bullets and nothing else (e.g. here's the summary). Text:\n" + study_description, always_shorten=True)
    summary = summary.replace("\n", "").replace("<bullet> ", "\n• ")

    description += summary if add_title else summary[1:]
    if study["protocolSection"]["statusModule"]["overallStatus"] == "COMPLETED" and study["hasResults"] and study.get("resultsSection"):
        description += "\nRESULTS:"
        results = ask_ai("Please explain the primary outcome, observed adverse effects if any and the results for a clinical trial in up to 5 bullet points. Start each bullet with <bullet>, which I will later replace with the current symbol. Only provide bullets without any additional description. Trials data in JSON:\n" + json.dumps(study["resultsSection"]), always_shorten=True)
        results = results.replace("\n", "").replace("<bullet> ", "\n• ")
        description += results
    if print_it:
        print(description)
    return description


if __name__ == "__main__":
    os.chdir("/Users/vinkoo/code/ie_research_map")
    post_new_trials_on_slack(threshold=85)