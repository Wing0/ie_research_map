from datetime import datetime, timedelta
import math
import os
import re
from decouple import config
import json
import numpy as np
import requests

from ai_apis import ask_ai
from slack_api import post_on_slack
from utils import post_to_slack, say
import requests
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt


API_KEY = config('NEWSREGISTRY_API_KEY')
# TODO: Events are associated with concepts through uri, and the event data can be found in another dictionary with the uri to avoid duplication (otherwise, the event will be added to every concept)


def search_and_post_on_slack(new_only=True, relevance_threshold=100, max_posts=5, force_search=False):
    """
    Searches for latest events, assesses their relevance, and posts relevant events on Slack.

    Args:
        new_only (bool, optional): If True, only assesses and posts new events. Defaults to True.

    Returns:
        None
    """
    
    try:
        with open("news/slack_posts.json", "r") as json_file:
            slack_posts = json.load(json_file)
    except:
        slack_posts = []
    
    all_events, new_events = search_latest_events(force_search=force_search)

    iter_events = new_events if new_only else all_events
    if iter_events:
        print("Assessing relevance of the events...")
    else:
        print("No news posted on Slack.")
        return
    scores = {}
    for event in iter_events:
        if event.get("concept_relevance_score"):
            scores[event["uri"]], event["concept_relevance_score"], event["ai_relevance_score"] = measure_event_relevance(event)
        else:
            scores[event["uri"]], event["concept_relevance_score"], event["ai_relevance_score"] = measure_event_relevance(event)
            event = save_event(event, update=True)
    
    
    # Plot the relevance scores on a bar plot with bins of 5, bar height being the count of events in that bin
    relevance_scores = list(scores.values())
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

    iter_events.sort(key=lambda x: scores[x["uri"]], reverse=True)
    
    final_events = []
    for event in iter_events:
        if event["uri"] not in [e["uri"] for e in final_events] and event["uri"] not in [e["uri"] for e in slack_posts]:
            final_events.append(event)
    final_events.sort(key=lambda x: scores[x["uri"]], reverse=True)
    
    print("Summarizing content and posting on Slack...")
    posts_so_far = 0
    for event in final_events:
        if scores[event["uri"]] < relevance_threshold:
            continue
        if posts_so_far >= max_posts:
            break
        title = event["title"] if isinstance(event.get("title"), str) else event["title"].get("eng", "No title available")
        event, is_important = novel_summary(event, slack_posts)
        event = save_event(event, update=True)
        if not is_important:
            say(f"The news article '{title}' is overlapping too much with the past content and was not posted.")
            continue

        top_concepts = [find_or_create_concept(concept_uri)[0] for concept_uri in event.get("concepts", [])]
        top_concepts.sort(key=lambda x: x["relevance_score"], reverse=True)
        top_concepts = top_concepts[:5]
        article = event.get('stories', [])[0].get("medoidArticle") if event.get('stories', [])[0] else {}
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
                        "text": f"{event['bullets']}"
                    }
                }, {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"_{', '.join([concept['name'] for concept in top_concepts])}_"
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
                "alt_text": f"Relevance: {int(scores.get(event['uri'], 0))}: {int(event["concept_relevance_score"])} & {int(event['ai_relevance_score'])}"
            }
        if post_to_slack(block, True):
            print(f"\n{event.get('eventDate', '')} - {title}")
            slack_posts.append(event)
            posts_so_far += 1
    with open("news/slack_posts.json", "w") as json_file:
        json.dump(slack_posts, json_file, indent=4)


def novel_summary(post, previous_posts):
    title = post['title']['eng'] if isinstance(post['title'], dict) else post['title']
    concepts = post['concepts'] if isinstance(post['concepts'][0], str) else [p['uri'] for p in post["concepts"]]
    article = post.get('stories', [])[0].get("medoidArticle") if post.get('stories', [])[0] else {}

    bullets = None
    is_important = True
    if len(post["concepts"]):
        prompt = f"Please give the topic of the news below in json format in a key 'topic'. Only provide the topic and nothing else, e.g. 'Mpox vaccination development'. In addition, select the most relevant concept URI and specify it in key 'concept'.\nTitle:{title}\nContent:\n{article.get("body", "No content available")}\nConcept URIs:\n{', '.join(concepts)}"
        answer = json.loads(ask_ai(prompt, json_mode=True))
        post["main_concept"] = answer['concept']
        post["main_topic"] = answer['topic']

        previous_matching_posts = [p for p in previous_posts if "main_concept" in p and p["main_concept"] == post["main_concept"]]
        if len(previous_matching_posts):
            say(len(previous_matching_posts), "previous articles on the topic", post["main_concept"])
            posts_summary = [{"title": p["title"], "summary": p["bullets"]} for p in previous_matching_posts]
            response = ask_ai(
                f"Your task is to summarize an article in three bullets and evaluate if this article still provides important novel insight given the summary of news on the same topic from the past two weeks. Your answer will be in valid JSON format. Please summarize the following article to the key 'summary' as a string value by writing the three most important new facts in bullet points without repeating information in the recent articles. Each bullet starts with '<bullet> '. Provide only the bullet points and nothing else. Also give a boolean decision whether this article is provides important new insight in the key 'is_important'.\nThe new article:\n{article.get('body')}\n\nList of past articles:\n{posts_summary}") if article.get(
                "body") else "{}"
            try:
                answer = json.loads(response)
            except json.decoder.JSONDecodeError as e:
                return novel_summary(post, [])
            bullets = answer.get("summary", "")
            is_important = bool(answer.get("is_important"))

    if not bullets:
        bullets = ask_ai(f"Please summarize the following article by writing the three most important facts in bullet points. Each bullet starts with '<bullet> ' on their own line. Provide only the bullet points and nothing else. Article:\n{article.get("body")}") if article.get("body") else ""
    if bullets:
        bullets = bullets.replace("<bullet> ", "\n• ")

    post["bullets"] = bullets
    return post, is_important


def load_settings():
    with open("news/news_settings.json", "r") as json_file:
        settings = json.load(json_file)
    return settings

def save_settings(key, new_value):
    settings = load_settings()
    settings[key] = new_value
    with open("news/news_settings.json", "w") as json_file:
        json.dump(settings, json_file, indent=4)


def find_or_create_concept(concept, all_concepts={}):
    """
    Find or create a concept in the given dictionary of all concepts.

    Parameters:
    - concept (dict or str): The concept to find or create. If it's a string, it will be converted to a dictionary with a "uri" key.
    - all_concepts (dict): The dictionary containing all concepts. If not provided, it will be loaded from "news/concepts.json" file.

    Returns:
    - tuple: A tuple containing the created or found concept and the updated dictionary of all concepts.

    """
    
    if not all_concepts:
        with open("news/concepts.json", "r") as json_file:
            all_concepts = json.load(json_file)
    
    existing_concepts = all_concepts["concepts"]

    # Return the existing concept if found
    if isinstance(concept, str):
        concept = {
            "uri": concept
        }
    existing_concept = existing_concepts.get(concept["uri"])
    if existing_concept:
        if existing_concept.get("type"):
            return existing_concept, all_concepts
        else:
            # Was found, but it's incomplete
            concept.update(existing_concept)
    else:
        # Concept not found, so create a new concept
        say(f"Creating a new concept for '{concept['uri']}'")
        translation = {
            "disease": "conditions",
            "treatment": "treatments",
            "organization": "organizations",
            "other": "other_concepts"
        }
        if not concept.get("label"):
            if not concept.get("name"):
                return concept, all_concepts
            else:
                concept["label"] = {
                    "eng": concept["name"]
                }
        answer = json.loads(ask_ai(f"Please categorize the concept '{concept['label']} (url: {concept["uri"]})' as exactly one of the following categories: {", ".join(list(translation.keys()))}. Any condition will count as disease. Please give the answer in a key 'category' in your JSON formatted response. Additionally provide an integer relevance score between 0 (least relevant) and 100 (most relevant) in key 'score' that describes jointly how relevant the concept or topic is for 'Global Child and Adolescent Health' and 'Immune Engineering'. Finally, provide an up to 500 character description in plain text in key 'description'.", json_mode=True))
        if answer.get("category") in list(translation.keys()) and isinstance(answer.get("score"), int) and 0 <= answer.get("score") <= 100:
            concept["relevance_score"] = answer.get("score")
            name = concept["label"].get("eng", None)
            if not name:
                name = ask_ai(f"Please provide the English translation for a label '{concept['label'][list(concept['label'].keys())[0]]}'. Only provide the translated label and nothing else.")
            concept["name"]  = name
            concept["approved"] =  False
            concept["description"] = answer.get("description", "")
            concept["events"] = []
            concept["wiki"] = {}
            if "wikipedia.org" in concept["uri"]:
                concept["wiki"]["shortly"] = fetch_wikipedia_intro_content(concept["uri"])
            concept["category"] = translation[answer.get("category")]
        else:
            # Could not create a concept in the proper format
            return concept, all_concepts
    
    all_concepts["concepts"][concept["uri"]] = concept
    if concept["uri"] not in all_concepts["classification"][concept["category"]]:
        all_concepts["classification"][concept["category"]].append(concept["uri"])

    if existing_concept:
        print(f"Merged concept '{concept['name']}' ({concept.get("relevance_score", 0)}) to category '{concept['category']}'")
    else:
        print(f"Added concept '{concept['name']}' ({concept.get("relevance_score", 0)}) to category '{concept['category']}'")

    with open("news/concepts.json", "w") as json_file:
        json.dump(all_concepts, json_file, indent=4)
    
    return concept, all_concepts


def add_event_to_concept(concept, event):
    if event["uri"] not in concept["events"]:
        with open("news/concepts.json", "r") as json_file:
            all_concepts = json.load(json_file)
        if not all_concepts["concepts"].get(concept["uri"]):
            concept, all_concepts = find_or_create_concept(concept, all_concepts)
        if event["uri"] not in all_concepts["concepts"][concept["uri"]]:
            all_concepts["concepts"][concept["uri"]]["events"].append(event["uri"])
            with open("news/concepts.json", "w") as json_file:
                json.dump(all_concepts, json_file, indent=4)
            return True
    return False


def add_event_to_category(category, event):
    with open("news/categories.json", "r") as json_file:
        categories = json.load(json_file)
    for cat in categories:
        if cat["uri"] == category["uri"]:
            if cat["approved"]:
                if not category.get("events"):
                    category["events"] = []
                if event["uri"] not in category["events"]:
                    cat["events"].append(event["uri"])
                    with open("news/categories.json", "w") as json_file:
                        json.dump(categories, json_file, indent=4)
                    return True
            break
    return False


def save_event(event, update=False):
    with open("news/events.json", "r") as json_file:
        events_data = json.load(json_file)
    if not events_data.get(event["uri"]):
        concept_uri_list = []
        all_concepts = {}
        for concept in event.get("concepts"):
            saved_concept, all_concepts = find_or_create_concept(concept, all_concepts)
            concept_uri_list.append(saved_concept["uri"])
            if saved_concept["approved"] and event["uri"] not in saved_concept["events"]:
                add_event_to_concept(saved_concept, event)
        event["concepts"] = concept_uri_list

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

        for category in event.get("categories", []):
            add_event_to_category(category, event)

        events_data[event["uri"]] = event

    elif update:
        events_data[event["uri"]].update(event)
    
    with open("news/events.json", "w") as json_file:
        json.dump(events_data, json_file, indent=4)
    
    return event
    

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
    

def measure_event_relevance(event):
    if not event.get("concept_relevance_score"):
        analyzed_concept_list = []
        all_concepts = {}
        for concept in event["concepts"]:
            saved_concept, all_concepts = find_or_create_concept(concept, all_concepts)
            analyzed_concept_list.append(saved_concept)

        concept_scores = [100 if c.get("approved") else c["relevance_score"] for c in analyzed_concept_list if c.get("relevance_score") and c.get("relevance_score") > 0]
        
        concept_relevance_score = sum(concept_scores) / len(concept_scores) if concept_scores else 0
    else:
        concept_relevance_score = event["concept_relevance_score"]

    if not event.get("ai_relevance_score"):
        ai_relevance_score = None

        article = event.get('stories', [])[0].get("medoidArticle") if event.get('stories', [])[0] else {}
        content = article.get("body") if article.get("body") else ""
        if content:
            response = json.loads(ask_ai(f"Please estimate the relevance of the following news with a score from 0 (least relevant) to 100 (most relevant). In your estimation, the following factors carry the most weight: 1) Influence on child and adolescent health 2) Positive or negative influence to global health (not only local) 3) Updates on upcoming treatments relevant for child and adolescent health. The following factors make news less relevant: historical information, US specific articles, political discussion, regular events, scientific conferences. Please give your integer estimate in JSON format under the key 'relevance'.\nArticle:\n{content}", json_mode=True))
            if response.get("relevance"):
                ai_relevance_score = int(response.get("relevance"))
    else:
        ai_relevance_score = event["ai_relevance_score"]
    time_score = (30 - (datetime.today().date() - datetime.strptime(event["eventDate"], "%Y-%m-%d").date()).days)
    score = time_score + (concept_relevance_score + ai_relevance_score) / 2 if ai_relevance_score else time_score + concept_relevance_score 
    if event.get("title", {}).get("eng"):
        say(f"{round(score)} ({time_score} + {round(concept_relevance_score)} + {round(ai_relevance_score)})\t{event["title"]["eng"]}")
    return score, concept_relevance_score, ai_relevance_score


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


def search_latest_events(force_search=False):
    print("Searching for latest events...")
    with open("news/concepts.json", "r") as json_file:
        concepts = json.load(json_file)

    relevant_concepts = [concept["uri"] for concept in concepts["concepts"].values() if concept.get("approved", False)]
    return events_search(relevant_concepts, force_search=force_search)
    


def events_search(concept_uris, days_before_today=None, force_search=False):
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

    # Load the search information from the JSON file
    try:
        with open("news/searches.json", "r") as json_file:
            search_data = json.load(json_file)
    except FileNotFoundError:
        search_data = {}

    with open("news/events.json", "r") as json_file:
        event_data = json.load(json_file)

    with open("news/concepts.json", "r") as json_file:
        concept_data = json.load(json_file)

    # Get the earliest last search date and latest data since for the concept URI
    last_search_dates = [search_data.get(concept_uri, {}).get("last_search_date") for concept_uri in concept_uris]
    last_search_date = min(last_search_dates) if None not in last_search_dates else None
    data_since_dates = [search_data.get(concept_uri, {}).get("data_since") for concept_uri in concept_uris]
    data_since = max(data_since_dates) if None not in data_since_dates else None
    non_duplicate_event_uris = list(set([event_uri for concept_uri in concept_uris for event_uri in concept_data["concepts"][concept_uri]["events"]]))
    events = [event_data[event_uri] for event_uri in non_duplicate_event_uris]


    # Set the search start date based on the last search date
    search_end_date = datetime.today().date()
    search_start_date = datetime.strptime(last_search_date, "%Y-%m-%d").date() if last_search_date else datetime.today().date() - timedelta(days=31)
    data_since_date = datetime.strptime(data_since, "%Y-%m-%d").date() if data_since else None
    # Find events that are already in the JSON file that match the search range
    existing_later_events = [event["uri"] for event in events if event["eventDate"] > search_start_date.strftime("%Y-%m-%d")]
    existing_preceding_events = [event["uri"] for event in events if data_since is None or event["eventDate"] < data_since_date.strftime("%Y-%m-%d")]

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
                    print(f"No new events since the last search date ({last_search_date.date()}).")
                    return events, []
        else:
            search_start_date = datetime.today().date() - timedelta(days=days_before_today)
    elif not datetime.today().date() > search_start_date and not force_search:
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


    # Filter out potential duplicates
    final_events = []
    duplicates = 0
    for event in events + new_events:
        if event["uri"] not in [e["uri"] for e in final_events]:
            final_events.append(event)
        else:
            duplicates += 1
    say(f"{duplicates} duplicate event found.")

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
            "data_since": data_since_field if not search_data.get(concept_uri, {}).get("data_since") or data_since_field < search_data.get(concept_uri, {}).get("data_since") else search_data.get(concept_uri, {}).get("data_since"),
        }
        search_data[concept_uri] = entry
    with open("news/searches.json", "w") as json_file:
        json.dump(search_data, json_file, indent=4)
    
    say(f"Found {len(new_events)} new events since {search_start_date} for {len(concept_uris)} concepts. That makes {len(final_events)} events in total.")
    return final_events, new_events



def find_all_events_by_concepts(concept_uris, page=False, start_date=None, end_date=None, exclude_event_uris=[], use_categories=True, debug=False, tries=0):
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
    # TODO: Update concepts, events and categories when new events are found
    global API_KEY
    if not isinstance(concept_uris, list):
        raise ValueError("The concept_uris argument must be a list of URIs.")
    say(f"Searching for events for {len(concept_uris)} concepts...{f"(page {page}" if page else ""}")
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
        with open("news/categories.json", "r") as json_file:
            categories = json.load(json_file)

        params["query"]["$query"]["$and"].append({
            "$or": [{"categoryUri": cat["uri"] } for cat in categories if cat["approved"]]
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
    # params["forceMaxDataTimeWindow"] = 7

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
            event = save_event(event)
                
        if not page and data.get("events", {}).get("pages", 0) > 1:
            for page in range(2, data["events"]["pages"] + 1):
                events += find_all_events_by_concepts(concept_uris, page=page)
        say(f"Found {len(events)} events for {len(concept_uris)} concepts.")
        return events
    elif response.status_code == 414:
        if tries < 3:
            split_point = int(len(concept_uris)/2)
            # TODO: assign exclude event uris to the right halves
            events = []
            events += find_all_events_by_concepts(concept_uris[:split_point], page=page, start_date=start_date, end_date=end_date, exclude_event_uris=exclude_event_uris, use_categories=use_categories, debug=debug, tries=tries + 1)
            events += find_all_events_by_concepts(concept_uris[split_point:], page=page, start_date=start_date, end_date=end_date, exclude_event_uris=exclude_event_uris, use_categories=use_categories, debug=debug, tries=tries + 1)
            
            say(f"Found {len(events)} events for {len(concept_uris)} concepts.")
            return events
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
        print(params)
        raise ValueError(f"Error: {response.status_code}")
    
    say(f"Did not find events for {len(concept_uris)} concepts.")
    return []


if __name__ == "__main__":
    os.chdir("/Users/vinkoo/code/ie_research_map")
    search_and_post_on_slack(relevance_threshold=90)
