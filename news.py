from datetime import datetime, timedelta
import math
import os
import re
from decouple import config
import json
import numpy as np
import requests

from ai_apis import ask_ai
from utils import post_to_slack
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt


API_KEY = config('NEWSREGISTRY_API_KEY')
# TODO: Events are associated with concepts through uri, and the event data can be found in another dictionary with the uri to avoid duplication (otherwise, the event will be added to every concept)


def search_and_post_on_slack(new_only=True, relevance_threshold=100, max_posts=5):
    #TODO save event scores to the event data
    """
    Searches for latest events, assesses their relevance, and posts relevant events on Slack.

    Args:
        new_only (bool, optional): If True, only assesses and posts new events. Defaults to True.

    Returns:
        None
    """
    
    # TODO: Save the bullets to the event data, perhaps refer to events by uri, instead of duplicating the data to slack_posts
    
    try:
        with open("news/slack_posts.json", "r") as json_file:
            slack_posts = json.load(json_file)
    except:
        slack_posts = []
    
    all_events, new_events = search_latest_events()

    print("Assessing relevance of the events...")
    iter_events = new_events if new_only else all_events
    for event in iter_events:
        event["relevance_filter_score"] = measure_event_relevance(event)
    relevance_scores = [event["relevance_filter_score"] for event in iter_events]

    # Plot the relevance scores on a bar plot with bins of 5, bar height being the count of events in that bin
    # Create the bins
    if len(relevance_scores) > 10:
        bins = range(math.floor(min(relevance_scores)), math.ceil(max(relevance_scores)) + 5, 5)

        # Calculate the histogram
        hist, bin_edges = np.histogram(relevance_scores, bins=bins)

        # Plot each bar individually
        for i in range(len(hist)):
            plt.bar(bin_edges[i], hist[i], color='blue' if bin_edges[i] < relevance_threshold else 'red')

        plt.xlabel('Relevance Score')
        plt.ylabel('Count')
        plt.title('Distribution of Event Relevance Scores')
        plt.savefig('news/relevance_scores.png')
        print('Figure added to news/relevance_scores.png')

    iter_events.sort(key=lambda x: x["relevance_filter_score"], reverse=True)
    
    final_events = []
    for event in iter_events:
        if event["uri"] not in [e["uri"] for e in final_events] and event["uri"] not in [e["uri"] for e in slack_posts]:
            final_events.append(event)

    print("Summarizing content and posting on Slack...")
    posts_so_far = 0
    for event in final_events:
        if event["relevance_filter_score"] < relevance_threshold:
            continue
        if posts_so_far >= max_posts:
            break
        title = event['title'].get("eng")
        article = event.get('stories', [])[0].get("medoidArticle") if event.get('stories', [])[0] else {}
        bullets = ask_ai(f"Please summarize the following article by writing the three most important facts in bullet points. Each bullet starts with '<bullet> ' on their own line. Provide only the bullet points and nothing else. Article:\n{article.get("body")}") if article.get("body") else ""
        if bullets:
            bullets = bullets.replace("<bullet> ", "• ")
            event["bullets"] = bullets
            
        block = {
            "text": title,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{title}*\n_{event.get('eventDate', '')}_"
                    }
                }, {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{bullets}"
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
                            "url": article.get("url", "")
                        }
                    ]
                }
            ]
        }
        if article.get("image"):
            block["blocks"][1]["accessory"] = {
                "type": "image",
                "image_url": article.get("image", ""),
                "alt_text": f"Relevance: {int(event['relevance_filter_score'])}"
            }
        if post_to_slack(block, True):
            print(f"\n{event.get('eventDate', '')} - {title}")
            slack_posts.append(event)
            posts_so_far += 1
    with open("news/slack_posts.json", "w") as json_file:
        json.dump(slack_posts, json_file, indent=4)


def load_settings():
    with open("news/news_settings.json", "r") as json_file:
        settings = json.load(json_file)
    return settings

def save_settings(key, new_value):
    settings = load_settings()
    settings[key] = new_value
    with open("news/news_settings.json", "w") as json_file:
        json.dump(settings, json_file, indent=4)


def discover_player_uris():
    with open("players.txt", "r") as file:
        players = file.readlines()
    labels = [player.strip() for player in players]
    discover_concept_uris_for_label(labels, "players")


def discover_concepts_from_events():
    with open("news/events.json", "r") as json_file:
        events_data = json.load(json_file)
    
    concepts = []
    for concept_uri, entry in events_data.items():
        for event in entry["events"]:
            for concept in event["concepts"]:
                concepts.append(concept)
                for story in event["stories"]:
                    for concept in story["concepts"]:
                        concepts.append(concept)
    print(f"Found {len(concepts)} concepts from events.")
    final_concepts = []
    for concept in concepts:
        if concept["uri"] not in [c["uri"] for c in final_concepts]:
            final_concepts.append(concept)
    
    print(f"There was {len(final_concepts)} non-duplicate concepts.")
    tick = int(len(final_concepts) / 100)
    for i, concept in enumerate(final_concepts):
        if i % tick == 0:
            print(f"Processing concepts {int(i / tick)}% complete...")
        match_and_merge_concept(concept)

    # Remove duplicates
    settings = load_settings()
    for key, concept_list in settings.items():
        if key != "categories":
            settings[key] = list({c["uri"]: c for c in concept_list}.values())
    
    with open("news/news_settings.json", "w") as json_file:
        json.dump(settings, json_file, indent=4)


def match_and_merge_concept(concept):
    settings = load_settings()
    existing_concepts = [concept for key, concept_list in settings.items() if key != "categories" for concept in concept_list]

    concept_exists = False
    no_update_needed = False
    for existing_concept in existing_concepts:
        if concept["uri"] == existing_concept["uri"]:
            concept_exists = True
            if existing_concept.get("type"):
                no_update_needed = True
            break
    if no_update_needed:
        return existing_concept
    if concept_exists:
        # Merge two concepts
        concept.update(existing_concept)
    else:
        answer = json.loads(ask_ai(f"Please categorize the concept '{concept['label']} (url: {concept["uri"]})' as exactly one of the following categories: disease, treatment, organization, other. Any condition will count as disease. Please give the answer in a key 'category' in your JSON formatted response. Additionally provide an integer relevance score between 0 (least relevant) and 100 (most relevant) in key 'score' that describes jointly how relevant the concept or topic is for 'Global Child and Adolescent Health' and 'Immune Engineering'. Finally, provide an up to 500 character description in plain text in key 'description'.", json_mode=True))
        if answer.get("category") in ["disease", "treatment", "organization", "other"] and isinstance(answer.get("score"), int) and 0 <= answer.get("score") <= 100:
            translation = {
                "disease": "conditions",
                "treatment": "treatments",
                "organization": "players",
                "other": "other_concepts"
            }
            concept["relevance_score"] = answer.get("score")
            name = concept["label"].get("eng", None)
            if not name:
                name = ask_ai(f"Please provide the English translation for a label '{concept['label'][list(concept['label'].keys())[0]]}'. Only provide the translated label and nothing else.")
            concept["name"]  = name
            concept["approved"] =  False
            concept["description"] = answer.get("description", "")
            concept["wiki"] = {}
            if "wikipedia.org" in concept["uri"]:
                concept["wiki"]["shortly"] = fetch_wikipedia_intro_content(concept["uri"])
            concept["category"] = translation[answer.get("category")]
        else:
            return concept
    if concept_exists:
        settings[concept["category"]].remove(existing_concept)    
    settings[concept["category"]].append(concept)
    if concept_exists:
        print(f"Merged concept '{concept['name']}' ({concept.get("relevance_score", 0)}) to category '{concept['category']}'")
    else:
        print(f"Added concept '{concept['name']}' ({concept.get("relevance_score", 0)}) to category '{concept['category']}'")

    with open("news/news_settings.json", "w") as json_file:
        json.dump(settings, json_file, indent=4)
    
    return concept


def fetch_wikipedia_intro_content(url):
    # Send a GET request to the Wikipedia article URL
    response = requests.get(url)

    text = ""
    if response.status_code == 200:
        # Parse the HTML content of the page
        soup = BeautifulSoup(response.content, 'html.parser')
        # Find the first section of the article
        content = soup.find('div', {'class': 'mw-content-ltr'})
        if content is not None:
            text = content.find('p', class_ = lambda value: value != 'mw-empty-elt').getText()
    else:
        print(f"Error: {response.status_code}:\n{response.text[:200]}")
    text = re.sub(r'\[\d+\]', '', text)
    return text


def discover_concept_uris_for_label(label_list, key):
    new_entries = []
    for label in label_list:
        concept_uri = get_concept_uri(label)
        answer = json.loads(ask_ai(f"I was given this URI '{concept_uri}' for this concept/entity: '{label}'. Does it make sense? Please give a boolean answer in a key 'answer' in your JSON formatted response. Additionally provide an integer relevance score between 0 (least relevant) and 100 (most relevant) in key 'score' that describes jointly how relevant the concept or topic is for 'Global Child and Adolescent Health' and 'Immune Engineering'. Finally, provide an up to 500 character description in plain text in key 'description'.", json_mode=True))
        if answer.get("answer") and isinstance(answer.get("score"), int) and 0 <= answer.get("score") <= 100:
            entry = {"name": label, "uri": concept_uri, "approved": False, "relevance_score": answer.get("score"), "description": answer.get("description", ""), "wiki": {}, "category": key}
            if "wikipedia.org" in concept_uri:
                entry["wiki"]["shortly"] = fetch_wikipedia_intro_content(concept_uri)
            new_entries.append(entry)
            print("Added concept:", label)
    
    settings = load_settings()
    for old_entry in settings.get(key, []):
        if old_entry["name"] not in [p["name"] for p in new_entries]:
            new_entries.append(old_entry)
        elif old_entry["uri"] and old_entry["approved"]:
            for new_entry in new_entries:
                if new_entry["name"] == old_entry["name"]:
                    new_entries.remove(new_entry)
            new_entries.append(old_entry)
                
    save_settings(key, new_entries)
    

def measure_event_relevance(event):
    analyzed_concept_list = []
    for concept in event["concepts"]:
        analyzed_concept_list.append(match_and_merge_concept(concept))

    concept_scores = [100 if c.get("approved") else c["relevance_score"] for c in analyzed_concept_list if c.get("relevance_score") and c.get("relevance_score") > 0]
    
    concept_relevance_score = sum(concept_scores) / len(concept_scores) if concept_scores else 0
    time_score = (30 - (datetime.today().date() - datetime.strptime(event["eventDate"], "%Y-%m-%d").date()).days)
    score = time_score + concept_relevance_score
    # if event.get("title", {}).get("eng"):
    #     print(f"{round(score)} ({time_score} + {round(concept_relevance_score)})\t{event["title"]["eng"]}")
    return score


def get_concept_uri(concept_label, tries=0):
    """
    This function retrieves the concept URI for a given concept label using the Event Registry API.

    Args:
    concept_label (str): The concept label to search for.
    api_key (str): Your Event Registry API key.

    Returns:
    str: The concept URI if found, otherwise None.
    """
    global API_KEY

    url = "https://eventregistry.org/api/v1/suggestConceptsFast"
    data = {
        "prefix": concept_label,
        "source": ["concepts"],
        "lang": "eng",
        "conceptLang": ["eng"],
          "articleBodyLen": -1,
        "apiKey": API_KEY
    }

    # Send the request
    response = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(data))
    if response.status_code == 200:
        response_data = response.json()
        if len(response_data):
            if response_data[0].get("uri", ""):
                return response_data[0]["uri"]
            else:
                if tries < 3:
                    return get_concept_uri(concept_label, tries=tries + 1)
                else:
                    print(f"Error: Concept URI not found for '{concept_label}'")
                    return None
    else:
        print(f"Error: API request failed with status code {response.status_code}")

    return None


def search_latest_events():
    # TODO only search for approved concepts
    print("Searching for latest events...")
    settings = load_settings()
    concepts = []
    concepts += settings.get("players", [])
    concepts += settings.get("conditions", [])
    concepts += settings.get("treatments", [])

    relevant_concepts = [concept["uri"] for concept in concepts if concept.get("approved", False) and concept.get("uri")]
    
    return events_search(relevant_concepts)
    


def events_search(concept_uris, days_before_today=None):
    """
    Finds the date when the events were last searched for these URIs, searches for events since that date, and saves the events to a JSON file.

    Args:
        concept_uris (list): List of the URIs of the concepts to search for events.

    Returns:
        tuple: A tuple containing two lists. The first list contains all the events found for the given concept URIs, including the ones that were already saved in the JSON file. The second list contains only the new events found in the search.

    Raises:
        FileNotFoundError: If the events JSON file is not found.

    Example:
        >>> events_search(["http://en.wikipedia.org/wiki/Oxygen", "http://en.wikipedia.org/wiki/Hydrogen"])
    """
    # TODO: Write tests to ensure the function works as expected
    # TODO: Only search with approved concept URIS

    global API_KEY

    # Load the existing events from the JSON file
    events_file_path = "news/events.json"
    try:
        with open(events_file_path, "r") as json_file:
            events_data = json.load(json_file)
    except FileNotFoundError:
        events_data = {}

    # Get the earliest last search date and latest data since for the concept URI
    last_search_dates = [events_data.get(concept_uri, {}).get("last_search_date") for concept_uri in concept_uris]
    last_search_date = min(last_search_dates) if None not in last_search_dates else None
    data_since_dates = [events_data.get(concept_uri, {}).get("data_since") for concept_uri in concept_uris]
    data_since = max(data_since_dates) if None not in data_since_dates else None
    events = [e for concept_uri in concept_uris for e in events_data.get(concept_uri, {}).get("events", [])]

    # Set the search start date based on the last search date
    search_end_date = datetime.today().date()
    search_start_date = datetime.strptime(last_search_date, "%Y-%m-%d").date() if last_search_date else datetime.today().date() - timedelta(days=31)
    data_since_date = datetime.strptime(data_since, "%Y-%m-%d").date() if data_since else None
    # Find events that are already in the JSON file that match the search range
    existing_later_events = [event["uri"] for concept_uri in concept_uris for event in events_data.get(concept_uri, {}).get("events", []) if event["eventDate"] > search_start_date.strftime("%Y-%m-%d")]
    existing_preceding_events = [event["uri"] for concept_uri in concept_uris for event in events_data.get(concept_uri, {}).get("events", []) if data_since is None or event["eventDate"] < data_since_date.strftime("%Y-%m-%d")]

    # Calculate the search period if days before today is provided
    double_search = False
    if days_before_today:
        if data_since_date:
            # Do we already have data that covers the days_before_today?
            days_since = (datetime.today().date() - data_since_date).days
            if days_since < days_before_today:
                # Search for events until the data since date
                search_start_date = datetime.today().date() - timedelta(days=days_before_today)
                search_end_date = data_since_date
                data_since = search_start_date.strftime("%Y-%m-%d")
                if datetime.today().date() > last_search_date.date():
                    # We need to search both before the current data and after
                    double_search = True
            else:
                if not datetime.today().date() > last_search_date.date():
                    print("No new events since the last search date.")
                    return events, []
        else:
            search_start_date = datetime.today().date() - timedelta(days=days_before_today)
    elif not datetime.today().date() > search_start_date:
        print("No new events since the last search date.")
        return events, []

    new_events = []
    if double_search:
        # Search before and after the current data
        pre_events =  find_all_events_by_concepts(
            concept_uris,
            start_date=search_start_date,
            end_date=search_end_date,
            exclude_event_uris=existing_preceding_events)
        post_events = find_all_events_by_concepts(
                concept_uris,
                start_date=last_search_date,
                exclude_event_uris=existing_later_events)
        new_events += pre_events + post_events
    else:
        new_events += find_all_events_by_concepts(concept_uris, start_date=search_start_date, end_date=search_end_date, exclude_event_uris=existing_later_events)
    
    
    # Add translations to title and summary, if English not available
    try:
        for event in new_events:
            title = event['title'].get("eng")
            if not title:
                title = event['title'][list(event["title"].keys())[0]]
                title = ask_ai(f"Please translate the following title to English: '{title}'. Please only provide the translation and nothing else.")
                event['title']["eng"] = title
            summary = event['summary'].get("eng")
            if not summary:
                summary = event['summary'][list(event["summary"].keys())[0]]
                summary = ask_ai(f"Please translate the following summary to English: '{summary}'. Please only provide the translation and nothing else.")
                event['summary']["eng"] = summary
    except Exception as e:
        print(f"Error: {e}. Will continue anyway.")


    # Filter out potential duplicates
    final_events = []
    for event in events + new_events:
        if event["uri"] not in [e["uri"] for e in final_events]:
            final_events.append(event)
        else:
            print(f"Duplicate event found: {event['uri']}")

    # Save the updated events to the JSON file
    data_since_field = data_since
    if not data_since_field and search_start_date:
        data_since_field = search_start_date.strftime("%Y-%m-%d")
    if not data_since_field:
        data_since_field = (datetime.today().date() - timedelta(days=31)).strftime("%Y-%m-%d")

    for concept_uri in concept_uris:
        # Save the data correctly
        entry = {
            "last_search_date": datetime.today().strftime("%Y-%m-%d"),
            "data_since": data_since_field if not events_data.get(concept_uri, {}).get("data_since") or data_since_field < events_data.get(concept_uri, {}).get("data_since") else events_data.get(concept_uri, {}).get("data_since"),
            "events": [e for e in final_events if concept_uri in [x["uri"] for x in e["concepts"]]],
        }
        events_data[concept_uri] = entry
    with open(events_file_path, "w") as json_file:
        json.dump(events_data, json_file, indent=4)
    
    print(f"Found {len(new_events)} new events since {search_start_date} for {len(concept_uris)} concepts. That makes {len(final_events)} events in total.")
    return final_events, new_events



def find_all_events_by_concepts(concept_uris, page=False, start_date=None, end_date=None, exclude_event_uris=[], use_categories=True, debug=False):
    """
    Find all events from the past 31 days or from the given range for a given concept URI.

    Args:
        concept_uris (list): The list of the URIs of the concepts to search for events.
        page (bool, optional): Whether to retrieve events from a specific page. Defaults to False.
        start_date (datetime.date, optional): The start date to filter events. Defaults to None, and the past 31 days are searched.
        end_date (datetime.date, optional): The end date to filter events. Defaults to None and is ignored if start_date is None. When None, the current date is used.

    Returns:
        list: A list of dictionaries containing event information.

    Raises:
        None

    Example:
        >>> find_all_events_by_concept("http://en.wikipedia.org/wiki/Oxygen")
    """
    # TODO: Archive searches by parameters
    global API_KEY
    if not isinstance(concept_uris, list):
        raise ValueError("The concept_uris argument must be a list of URIs.")
    # Define the endpoint and search parameters
    endpoint = "https://eventregistry.org/api/v1/event/getEvents"
    params = {
        "apiKey": API_KEY,
        "includeEventSummary": True,
        "includeEventSocialScore": True,
        "includeEventCommonDates": True,
        "includeEventStories": True,
        "eventImageCount": 1,
        "includeConceptImage": True,
        "includeConceptSynonyms": True,
        "includeStoryBasicStats": True,
        "includeStoryTitle": True,
        "includeStoryLocation": True,
        "includeStoryDate": True,
        "includeStoryConcepts": True,
        "includeStoryCategories": True,
        "includeStoryMedoidArticle": True,
        "includeStoryCommonDates": True,
        "storyImageCount": 1,
        "includeCategoryParentUri": True,
        "includeLocationPopulation": True,
        "includeLocationGeoNamesId": True,
        "includeLocationCountryArea": True,
        "includeLocationCountryContinent": True,
        "query": {
            "$query": {
                "$and": [
                    {
                        "$or": [{"conceptUri": uri} for uri in concept_uris]
                    }
                ]
            }
        }
    }

    if use_categories:
        settings = load_settings()
        categories = settings.get("categories", [])
        params["query"]["$query"]["$and"].append({
            "$or": [{"categoryUri": uri } for uri in categories]
        })

    if exclude_event_uris:
        params["query"]["$query"]["$and"].append({
            "$not": {
                "$or": {
                    "uri": uri for uri in exclude_event_uris
                }
            }
        })

    if start_date:
        params["query"]["$query"]["$and"].append({
            "dateStart": start_date.strftime("%Y-%m-%d"),
            "dateEnd": end_date.strftime("%Y-%m-%d") if end_date else datetime.today().strftime("%Y-%m-%d")
        })
    else:
        params["forceMaxDataTimeWindow"] = 31

    if page:
        params["eventsPage"] = page

    # Send the GET request
    params["query"] = json.dumps(params["query"])
    if debug:
        return []
    response = requests.get(endpoint, params=params)
    # Check for successful response
    if response.status_code == 200:
        data = response.json()
        events = [event for event in data.get("events", {}).get("results", [])]
        for event in events:
            for concept in event.get("concepts"):
                match_and_merge_concept(concept)
        if not page and data.get("events", {}).get("pages", 0) > 1:
            for page in range(2, data["events"]["pages"] + 1):
                events += find_all_events_by_concepts(concept_uris, page=page)
        return events
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
    
    return []


if __name__ == "__main__":
    os.chdir("/Users/vinkoo/code/ie_research_map")
    search_and_post_on_slack()
