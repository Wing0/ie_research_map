import json
import requests
from ai_apis import ask_ai


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
    
    clean_conditions = [condition[0] for condition in sorted_conditions if condition[1] > 1]
    answer = ask_ai(f"Which of the following conditions are related to child and adolescent health in developing countries? Please respond with a JSON list of conditions at key 'relevant_conditions'.\n{clean_conditions}", json_mode=True)
    profile["relevant_conditions"] = json.loads(answer)['relevant_conditions']

    unique_collaborators = list(set(collaborators))
    collaborator_counts = {collaborator: collaborators.count(collaborator) for collaborator in unique_collaborators}
    sorted_collaborators = sorted(collaborator_counts.items(), key=lambda x: x[1], reverse=True)
    profile["top5_collaborators"] = sorted_collaborators[:5]
    
    return profile


def latest_trials_data_by_condition(condition_name, since=False):
    url = "https://clinicaltrials.gov/api/v2/studies"
    studies = []
    response = {"nextPageToken": None}
    while "nextPageToken" in response.keys():
        if response["nextPageToken"]:
            response = requests.get(url, timeout=5, params={"query.cond": condition_name, "pageSize": 1000, "pageToken": response["nextPageToken"]}).json()
        else:
            response = requests.get(url, timeout=5, params={"query.cond": condition_name, "pageSize": 1000}).json()
        studies += response["studies"]

    print("Found", len(response["studies"]), "studies for", condition_name)
    return studies
    # for study in response.json()["studies"]:
    #     description = study["protocolSection"]["descriptionModule"]["briefSummary"]
    #     conditions += study["protocolSection"]["conditionsModule"]["conditions"]
    #     collaborators += [collaborator["name"] for collaborator in study["protocolSection"]["sponsorCollaboratorsModule"].get("collaborators", [])]

    # unique_conditions = list(set(conditions))
    # condition_counts = {condition: conditions.count(condition) for condition in unique_conditions}
    # sorted_conditions = sorted(condition_counts.items(), key=lambda x: x[1], reverse=True)
    # profile["top5_conditions"] = sorted_conditions[:5]
    
    # clean_conditions = [condition[0] for condition in sorted_conditions if condition[1] > 1]
    # answer = ask_ai(f"Which of the following conditions are related to child and adolescent health in developing countries? Please respond with a JSON list of conditions at key 'relevant_conditions'.\n{clean_conditions}", json_mode=True)
    # profile["relevant_conditions"] = json.loads(answer)['relevant_conditions']

    # unique_collaborators = list(set(collaborators))
    # collaborator_counts = {collaborator: collaborators.count(collaborator) for collaborator in unique_collaborators}
    # sorted_collaborators = sorted(collaborator_counts.items(), key=lambda x: x[1], reverse=True)
    # profile["top5_collaborators"] = sorted_collaborators[:5]
    
    # return profile