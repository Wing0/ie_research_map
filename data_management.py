import json
import math
from utils import choice_menu, toggle
from ai_apis import ask_ai
from news import load_settings


def remove_duplicate_categories():
    with open("news/categories.json", "r") as json_file:
        categories_data = json.load(json_file)
    
    final_categories = []
    for category in categories_data:
        if category["uri"] not in [c["uri"] for c in final_categories]:
            final_categories.append(category)
    
    with open("news/categories.json", "w") as json_file:
        json.dump(final_categories, json_file, indent=4)

def approve_terms():
    while True:
        start_menu = ["Manage concepts", "Manage categories"]
        choice = choice_menu(start_menu, "What would you like to manage?")
        if choice is False:
            print("Thank you, bye!")
            raise SystemExit
        
        if start_menu[choice] == "Manage categories":
            with open("news/categories.json", "r") as json_file:
                categories_data = json.load(json_file)

            while True:
                category_menu = ["Enable new categories", "Disable current categories"]
                choice = choice_menu(category_menu, "What would you like to do?")
                if choice is False:
                    break
                if category_menu[choice] == "Enable new categories":
                    focus_categories = [category for category in categories_data if not category["approved"]]
                elif category_menu[choice] == "Disable current categories":
                    focus_categories = [category for category in categories_data if category["approved"]]
                if not focus_categories:
                    print("\nYou don't have any categories enabled currently.\n")
                    continue
                
                with open("news/new_events.json", "r") as json_file:
                    all_events = json.load(json_file)
                
                counts = {category["uri"]: sum([1 for uri, event in all_events.items() if category["uri"] in event["categories"]]) for category in categories_data}
                focus_categories.sort(key=lambda x: counts[x["uri"]], reverse=(False if category_menu[choice] == "Disable current categories" else True))
                i = 0
                for i in range(math.ceil(len(focus_categories)/9)):
                    categories_page = focus_categories[i*9:(i+1)*9]
                    toggle_choices = [f"{c['uri']} ({counts[c['uri']]} events){f": {c.get('description', '')[:190-len(c['uri'])] if c.get('description', '') else ''}..." if c.get('description', '') else ""}" for c in categories_page] + ["Stop"]
                    toggle_values = [c["approved"] for c in categories_page] + [False]
                    toggle_values = toggle(toggle_choices, toggle_values, f"Select which category to approve/disapprove")
                    for j, category in enumerate(categories_page):
                        for cat in categories_data:
                            if cat["uri"] == category["uri"]:
                                if toggle_values[j]:
                                    cat = approve_category(category)
                                else:
                                    cat["approved"] = False
                                break

                    with open("news/categories.json", "w") as json_file:
                        json.dump(categories_data, json_file, indent=4)
                    if toggle_values[-1]:
                        break
        elif start_menu[choice] == "Manage concepts":
            # TODO test properly with the new structure
            with open("news/concepts.json", "r") as json_file:
                all_concepts = json.load(json_file)

            while True:
                main_menu = [f"{k} ({sum([1 for c in i if all_concepts["concepts"][c]["approved"]])}/{len(i)} approved)" for k, i in all_concepts["classification"].items()]
                choice = choice_menu(main_menu, "Which types of concepts would you like to manage?")
                if choice is False:
                    break
                key = list(all_concepts["classification"].keys())[choice]
                concepts_data = [all_concepts["concepts"][uri] for uri in all_concepts["classification"][key]]
                while True:
                    concept_menu = ["Track new concepts", "Untrack concepts"]
                    choice = choice_menu(concept_menu, "What would you like to do?")
                    if choice is False:
                        break
                    if concept_menu[choice] == "Track new concepts":
                        focus_concepts = [concept for concept in concepts_data if not concept["approved"]]
                    elif concept_menu[choice] == "Untrack concepts":
                        focus_concepts = [concept for concept in concepts_data if concept["approved"]]
                        if not focus_concepts:
                            print("\nYou are not tracking any concepts in this category.\n")
                            continue
                    
                    focus_concepts.sort(key=lambda x: x["relevance_score"], reverse=False if concept_menu[choice] == "Untrack concepts" else True)
                    i = 0
                    for i in range(math.ceil(len(focus_concepts)/9)):
                        concepts_page = focus_concepts[i*9:(i+1)*9]
                        toggle_choices = [f"{c['name']} - (relevance: {c['relevance_score']}{f", events: {len(c["events"])}" if c["approved"] else ""}): {c.get("description", "")[:170-len(c["name"])]}..." for c in concepts_page] + ["Stop"]
                        toggle_values = [c["approved"] for c in concepts_page] + [False]
                        toggle_values = toggle(toggle_choices, toggle_values, f"Select which {key} to approve/disapprove")
                        for j, concept in enumerate(concepts_page):
                            if toggle_values[j]:
                                all_concepts["concepts"][concept["uri"]] = approve_concept(concept)
                            else:
                                all_concepts["concepts"][concept["uri"]]["approved"] = False
                        with open("news/concepts.json", "w") as json_file:
                            json.dump(all_concepts, json_file, indent=4)
                        if toggle_values[-1]:
                            break
        else:
            print("Thank you, bye!")
            raise SystemExit


def migrate_data():
    edit_categories = False

    with open("news/events.json", "r") as file:
        events = json.load(file)

    settings = load_settings()
    concepts = {"concepts": {}, "classification": {}}
    for key, item in settings.items():
        if key != "categories":
            for concept in item:
                if concept.get("approved", False):
                    concept["events"] = [event["uri"] for search_object in events.values() for event in search_object["events"] if concept["uri"] in (event["concepts"] if isinstance(event["concepts"][0], list) else [c["uri"] for c in event["concepts"]])]
                concepts["concepts"][concept["uri"]] = concept
            concepts["classification"][key] = [c["uri"] for c in item]

    with open("news/concepts.json", "w") as file:
        json.dump(concepts, file, indent=4)

    new_events_structure = {}
    search_events = {}
    for concept_uri, search_object in events.items():
        for event in search_object["events"]:
            event["concepts"] = [c["uri"] for c in event["concepts"]]
            event["categories"] = [c["uri"] for c in event["categories"]]
            new_events_structure[event["uri"]] = event
        del search_object["events"]
        search_object["type"] = "concept"
        search_events[concept_uri] = search_object

    with open("news/searches.json", "w") as file:
        json.dump(search_events, file, indent=4)

    with open("news/new_events.json", "w") as file:
        json.dump(new_events_structure, file, indent=4)


def discover_new_categories_from_events():
    with open("news/categories.json", "r") as file:
        existing_categories = json.load(file)

    with open("news/new_events.json", "r") as file:
        events = json.load(file)

    categories = []
    for event in events.values():
        for category_object in event["categories"]:
            if category_object not in categories:    
                if category_object["uri"] not in [existing_category["uri"] for existing_category in existing_categories]:
                    create_category(category_object["uri"])
                    categories.append(category_object)


def create_category(uri):

    # This list will be deprecated
    approved_categories = [
            "dmoz/Health/Child_Health",
            "dmoz/Health/Conditions_and_Diseases/Immune_Disorders",
            "dmoz/Health/Conditions_and_Diseases/Infectious_Diseases",
            "dmoz/Health/Conditions_and_Diseases/Nutritional_and_Metabolic_Disorders",
            "dmoz/Health/Conditions_and_Diseases/Food_and_Water_Borne",
            "dmoz/Health/Conditions_and_Diseases/Blood_Disorders",
            "dmoz/Health/Conditions_and_Diseases/Cancer",
            "dmoz/Health/Conditions_and_Diseases/Cardiovascular_Disorders",
            "dmoz/Health/Conditions_and_Diseases/Chronic_Illness",
            "dmoz/Health/Nutrition/Disease_Prevention",
            "dmoz/Health/Public_Health_and_Safety",
            "dmoz/Health/Public_Health_and_Safety/Disease_Control_and_Prevention",
            "dmoz/Health/Public_Health_and_Safety/Developing_Countries",
            "dmoz/Health/Reproductive_Health/Sexually_Transmitted_Diseases",
            "dmoz/Science/Technology/Biotechnology",
            "dmoz/Science/Medicine",
            "dmoz/Science/Biology/Immunology",
            "dmoz/Science/Medicine/Research"
    ]

    approved = True if uri in approved_categories else False
    category_object = {
        "uri": uri,
        "description": None,
        "approved": approved,
        "parentUri": None,
        "events": []
    }
    if "/" in category_object["uri"]:
        parent = category_object["uri"].rsplit("/", 1)[0]
        if parent:
            category_object["parentUri"] = parent
    if category_object.get("approved", False):
        category_object = approve_category(category_object)
    
    with open("news/categories.json", "r") as file:
        categories = json.load(file)
    
    categories.append(category_object)

    with open("news/categories.json", "w") as file:
        json.dump(categories, file, indent=4)

    print(f"Added category: {category_object['uri']}")
    if category_object["parentUri"] and category_object["parentUri"] not in [existing_category["uri"] for existing_category in categories]:
        create_category(category_object["parentUri"])
    return category_object


def approve_category(category_object):
    with open("news/new_events.json", "r") as file:
        events = json.load(file)
    
    category_object["approved"] = True
    category_object["events"] = [event["uri"] for event in events.values() if category_object["uri"] in event["categories"]]
    if not category_object["description"]:
        description = ask_ai(f"Please write a description for the category with an uri of {category_object["uri"]}. Only write the description and nothing else (e.g. no 'This category is about...').")
        category_object["description"] = description
    return category_object


def approve_concept(concept_object):
    with open("news/new_events.json", "r") as file:
        events = json.load(file)
    
    concept_object["approved"] = True
    concept_object["events"] = [event["uri"] for event in events.values() if concept_object["uri"] in event["concepts"]]
    return concept_object


'''
=== DATA MODELS ===

events.json
-----------
{
    "uri": {
        "title": "title",
        "description": "description",
        "eventDate": "eventDate",
        "concepts": ["uri1", "uri2"],
        "concept_relevance": 0.0,
        "bullets": "description"
        ...
    },
    ...
}

concepts.json
-------------
{
    "concepts": {
        "uri": {
            "name": "name",
            "description": "description",
            "category": "category",
            "relevance_score": 0.0,
            "approved": false,
            "events": ["uri1", "uri2"], # only if approved
            "categories": ["uri1", "uri2"],
            ...
        },
        ...
    },
    "classification": {
        "treatments": ["uri1", "uri2"],
        "diseases: ["uri1", "uri2"],
        ...
    }
}

categories.json
---------------
{
    "categories": [
        {
            "uri": "uri",
            "description": "description",
            "events": ["uri1", "uri2"],  # Only if approved
            "approved": false
        },
        ...
    ]
}

searches.json
-------------
{
    "uri": {
        "data_since": YY-MM-DD,
        "last_search_date": YY-MM-DD
    },
    ...
}


TODO How about concepts that don't have an URI, but are based on specific keywords?
'''

if __name__ == "__main__":
    # migrate_data()
    # remove_duplicate_categories()
    approve_terms()
    # discover_new_categories_from_events()
