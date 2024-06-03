from datetime import datetime, timedelta
from eventregistry import EventRegistry, QueryArticlesIter, ArticleInfoFlags, ReturnInfo
from decouple import config
import json
import requests

API_KEY = config('NEWSREGISTRY_API_KEY')

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
        print(response_data)
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


def events_search(concept_uri, days_before_today=None):
    """
    Finds the date when the events were last searched for this URI, searches for events since that date, and saves the events to a JSON file.

    Args:
        concept_uri (str): The URI of the concept to search for events.

    Returns:
        list: A list of events found for the given concept URI.

    Raises:
        FileNotFoundError: If the events JSON file is not found.

    Example:
        >>> events_search("http://en.wikipedia.org/wiki/Oxygen")
    """
    # TODO: search multiple concept_uris at the same time
    # TODO: measure historical article volume to predict how many terms to couple together
    global API_KEY

    # Load the existing events from the JSON file
    events_file_path = "news/events.json"
    try:
        with open(events_file_path, "r") as json_file:
            events_data = json.load(json_file)
    except FileNotFoundError:
        events_data = {}

    # Get the last search date for the concept URI
    last_search_date = events_data.get(concept_uri, {}).get("last_search_date")
    data_since = events_data.get(concept_uri, {}).get("data_since", None)  # the first day of the data
    events = events_data.get(concept_uri, {}).get("events", [])
    print(f"{len(events)} events before search")
    # Set the search start date based on the last search date
    search_end_date = datetime.today().date()
    if last_search_date:
        last_search_date = datetime.strptime(last_search_date, "%Y-%m-%d")
        search_start_date = last_search_date  # The end date is searched twice, in case there were new events during the rest of the day
    else:
        search_start_date = None

    # Calculate the search period if days before today is provided
    double_search = False
    if days_before_today:
        if data_since:
            # Do we already have data that covers the days_before_today?
            data_since_date = datetime.strptime(data_since, "%Y-%m-%d").date()
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
    elif last_search_date is not None and not datetime.today().date() > last_search_date.date():
        print("No new events since the last search date.")
        return events

    
    if double_search:
        # Search before and after the current data
        events = find_all_events_by_concept(concept_uri, start_date=search_start_date, end_date=search_end_date) + events + find_all_events_by_concept(concept_uri, start_date=last_search_date)
    else:
        events += find_all_events_by_concept(concept_uri, start_date=search_start_date, end_date=search_end_date)
    
    # Filter out potential duplicates
    final_events = []
    for event in events:
        if event["uri"] not in [e["uri"] for e in final_events]:
            final_events.append(event)
    
    # Save the updated events to the JSON file
    data_since_field = data_since
    if not data_since_field and search_start_date:
        data_since_field = search_start_date.strftime("%Y-%m-%d")
    if not data_since_field:
        data_since_field = (datetime.today().date() - timedelta(days=31)).strftime("%Y-%m-%d")

    events_data[concept_uri] = {
        "last_search_date": datetime.today().strftime("%Y-%m-%d"),
        "data_since": data_since_field,
        "events": final_events
    }
    with open(events_file_path, "w") as json_file:
        json.dump(events_data, json_file, indent=4)
    
    print(f"{len(final_events)} events after search")
    return final_events



def find_all_events_by_concept(concept_uri, page=False, start_date=None, end_date=None):
    """
    Find all events from the past 31 days or from the given range for a given concept URI.

    Args:
        concept_uri (str): The URI of the concept to search for events.
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
    global API_KEY
    # Define the endpoint and search parameters
    endpoint = "https://eventregistry.org/api/v1/event/getEvents"
    params = {
        "apiKey": API_KEY,
        "conceptUri": concept_uri
    }

    if start_date:
        params["dateStart"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["dateEnd"] = end_date.strftime("%Y-%m-%d")
        else:
            params["dateEnd"] = datetime.today().strftime("%Y-%m-%d")
    else:
        params["forceMaxDataTimeWindow"] = 31

    if page:
        params["eventsPage"] = page

    # Send the GET request
    print(params)
    response = requests.get(endpoint, params=params)
    # Check for successful response
    if response.status_code == 200:
        data = response.json()
        events = data.get("events", {}).get("results", [])
        if not page and data.get("events", {}).get("pages", 0) > 1:
            for page in range(2, data["events"]["pages"] + 1):
                events += find_all_events_by_concept(concept_uri, page=page)
        return events
    else:
        print(f"Error: {response.status_code}")
    
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

    try:
        with open("news/events.json", "r") as json_file:
            events_data = json.load(json_file)
    except FileNotFoundError:
        events_data = {}
        print("No events found.")
    if events_data:
        print(f"Number of organizations before search: {len(events_data)}")
        categories = []
        for concept_uri, entry in events_data.items():
            print(f"{len(entry['events'])} events found for {concept_uri} since {entry['data_since']}")
            earliest_date = None
            for i, event in enumerate(sorted(entry["events"], key=lambda x: -x["relevance"])):
                if i == 0:
                    print(f"\tMost relevant event: {event['title']} ({event['relevance']})")
                event_date = datetime.strptime(event["eventDate"], "%Y-%m-%d")
                if not earliest_date or event_date < earliest_date:
                    earliest_date = event_date
                categories += event["categories"]
            print(f"\tEarliest event date: {earliest_date} for {concept_uri}")
        categories = list(set([c["uri"] for c in categories]))
        categories.sort()
        for c in categories:
            print(c)