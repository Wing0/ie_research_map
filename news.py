from datetime import datetime, timedelta
import os
from eventregistry import EventRegistry, QueryArticlesIter, ArticleInfoFlags, ReturnInfo
from decouple import config
import json
import requests

from ai_apis import ask_ai
from utils import post_to_slack

API_KEY = config('NEWSREGISTRY_API_KEY')


def search_and_post_on_slack():
    # TODO: Save the bullets to the event data, perhaps refer to events by uri, instead of duplicating the data to slack_posts
    try:
        with open("news/slack_posts.json", "r") as json_file:
            slack_posts = json.load(json_file)
    except:
        slack_posts = []
    try:
        with open("news/events.json", "r") as json_file:
            event_data = json.load(json_file)
    except:
        event_data = []
    
    all_events = search_latest_events()
    for event in all_events:
        event["relevance_filter_score"] = (30 - (datetime.today().date() - datetime.strptime(event["eventDate"], "%Y-%m-%d").date()).days) + event["relevance"]

    all_events.sort(key=lambda x: x["relevance_filter_score"], reverse=True)
    
    final_events = []
    for event in all_events:
        if event["uri"] not in [e["uri"] for e in final_events] and event["uri"] not in [e["uri"] for e in slack_posts]:
            final_events.append(event)

    for event in final_events:
        if event["relevance_filter_score"] < 200:
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
                "alt_text": f"Relevance: {event['relevance_filter_score']}"
            }
        if post_to_slack(block, True):
            print(f"\n{event.get('eventDate', '')} - {title}")
            slack_posts.append(event)

    with open("news/slack_posts.json", "w") as json_file:
        json.dump(slack_posts, json_file, indent=4)
        


def discover_concept_uris():

    with open("players.txt", "r") as file:
        players = file.readlines()

    all_players = []
    for player in players:
        concept_label = player.strip()
        concept_uri = get_concept_uri(concept_label)
        all_players.append({"name": concept_label, "uri": concept_uri})
    
    with open("news/players.json", "w") as json_file:
        json.dump(all_players, json_file, indent=4)

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
    try:
        with open("news/players.json", "r") as json_file:
            players_data = json.load(json_file)
    except FileNotFoundError:
        players_data = {}
        print("No events file found.")
    
    uris = [p["uri"] for p in players_data if p.get("uri")]
    return events_search(uris)
    


def events_search(concept_uris, days_before_today=None):
    """
    Finds the date when the events were last searched for this URI, searches for events since that date, and saves the events to a JSON file.

    Args:
        concept_uri (list): List of the URIs of the concepts to search for events.

    Returns:
        list: A list of lists of events found for the given concept URIs.

    Raises:
        FileNotFoundError: If the events JSON file is not found.

    Example:
        >>> events_search("http://en.wikipedia.org/wiki/Oxygen")
    """
    # TODO: capture all fields for the events
    # TODO: Write tests to ensure the function works as expected

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
    datas_since = [events_data.get(concept_uri, {}).get("data_since") for concept_uri in concept_uris]
    data_since = max(datas_since) if None not in datas_since else None
    events = [e for concept_uri in concept_uris for e in events_data.get(concept_uri, {}).get("events", [])]
    original_number_of_events = len(events)

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
                    return events
        else:
            search_start_date = datetime.today().date() - timedelta(days=days_before_today)
    elif not datetime.today().date() > search_start_date:
        print("No new events since the last search date.")
        return events

    
    if double_search:
        # Search before and after the current data
        events = find_all_events_by_concepts(
            concept_uris,
            start_date=search_start_date,
            end_date=search_end_date,
            exclude_event_uris=existing_preceding_events) + events + find_all_events_by_concepts(
                concept_uris,
                start_date=last_search_date,
                exclude_event_uris=existing_later_events)
    else:
        events += find_all_events_by_concepts(concept_uris, start_date=search_start_date, end_date=search_end_date, exclude_event_uris=existing_later_events)
    
    # Filter out potential duplicates
    final_events = []
    for event in events:
        if event["uri"] not in [e["uri"] for e in final_events]:
            final_events.append(event)
        else:
            print(f"Duplicate event found: {event['uri']}")
    
    # Add translations to title and summary, if English not available
    try:
        for event in final_events:
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
    
    print(f"{len(final_events)-original_number_of_events} new events found in search")
    return final_events



def find_all_events_by_concepts(concept_uris, page=False, start_date=None, end_date=None, exclude_event_uris=[], use_categories=True):
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
        try:
            with open("news/categories.json", "r") as json_file:
                categories = json.load(json_file)
        except FileNotFoundError:
            categories = []
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
    response = requests.get(endpoint, params=params)
    # Check for successful response
    if response.status_code == 200:
        data = response.json()
        events = [event for event in data.get("events", {}).get("results", [])]
        if not page and data.get("events", {}).get("pages", 0) > 1:
            for page in range(2, data["events"]["pages"] + 1):
                events += find_all_events_by_concepts(concept_uris, page=page)
        print("Mined events: ", len(events))
        return events
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
    
    return []

def get_articles():

    # Set the search parameters
    keywords = "Moderna"
    # Search for articles in the past 30 days
    today = datetime.today()
    past_30_days = today - timedelta(days=30)
    date_start = past_30_days.strftime('%Y-%m-%d')
    date_end = today.strftime('%Y-%m-%d')

    # Create an EventRegistry object
    er = EventRegistry(apiKey=API_KEY)

    # Define the properties to return for articles
    return_info = ReturnInfo(
        articleInfo=ArticleInfoFlags(
            title=True, date=True, body=True, url=True, source=True, image=True
        )
    )

    # Create a query object
    q = QueryArticlesIter(
        keywords=keywords,
        dateStart=date_start,
        dateEnd=date_end
    )

    # Execute the query and iterate over the results
    print(f"Searching for news articles about {keywords}...")

    articles = []
    json_file_path = "news/articles.json"
    try:
        with open(json_file_path, "r") as json_file:
            articles = json.load(json_file)
    except FileNotFoundError:
        pass
    for article in q.execQuery(er, sortBy="date", maxItems=100, returnInfo=return_info):
        articles.append(article)
        # Print the article details
        print(f"\nHeadline: {article['title']}")
        print(f"Date: {article['date']}")
        print(f"Source: {article['source']['title']}")
        print(f"URL: {article['url']}")
        if article['image']:
            print(f"Image: {article['image']}")
        print(f"Summary: {article['body'][:200]}...")  # Print the first 200 characters of the body

    print("\nSearch complete.")



    # Save the articles to the JSON file
    with open(json_file_path, "w") as json_file:
        json.dump(articles, json_file, indent=4)

    print(f"Articles saved to {json_file_path}")

if __name__ == "__main__":
    # with open("news/players.json", "r") as json_file:
    #     players = json.load(json_file)
    # for player in players:
    #     concept_uri = player["uri"]
    #     if concept_uri:
    #         print(f"Searching for events for {player["name"]}...")
    #         events_search(concept_uri)

    # try:
    #     with open("news/events.json", "r") as json_file:
    #         events_data = json.load(json_file)
    # except FileNotFoundError:
    #     events_data = {}
    #     print("No events found.")
    # if events_data:
    #     print(f"Number of organizations before search: {len(events_data)}")
    #     categories = []
    #     for concept_uri, entry in events_data.items():
    #         print(f"{len(entry['events'])} events found for {concept_uri} since {entry['data_since']}")
    #         earliest_date = None
    #         for i, event in enumerate(sorted(entry["events"], key=lambda x: -x["relevance"])):
    #             if i == 0:
    #                 print(f"\tMost relevant event: {event['title']} ({event['relevance']})")
    #             event_date = datetime.strptime(event["eventDate"], "%Y-%m-%d")
    #             if not earliest_date or event_date < earliest_date:
    #                 earliest_date = event_date
    #             categories += event["categories"]
    #         print(f"\tEarliest event date: {earliest_date} for {concept_uri}")
    #     categories = list(set([c["uri"] for c in categories]))
    #     categories.sort()
    #     for c in categories:
    #         print(c)
    
    os.chdir("/Users/vinkoo/code/ie_research_map")
    search_and_post_on_slack()
