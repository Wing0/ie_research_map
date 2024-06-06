import json
import math
from news import load_settings, save_settings
from utils import choice_menu, toggle


if __name__ == '__main__':
    while True:
        settings = load_settings()
        choice = choice_menu(settings.keys(), "Which types of concepts would you like to manage?")
        if choice is False:
            print("Thank you, bye!")
            raise SystemExit
        key = list(settings)[choice]
        if key == "categories":
            categories = settings[key]
            #TODO add tracked categories
        else:
            concepts = settings[key]
            while True:
                concept_menu = ["Track new concepts", "Untrack concepts"]
                choice = choice_menu(concept_menu, "What would you like to do?")
                if choice is False:
                    break
                if concept_menu[choice] == "Track new concepts":
                    focus_concepts = [concept for concept in concepts if not concept["approved"]]
                elif concept_menu[choice] == "Untrack concepts":
                    focus_concepts = [concept for concept in concepts if concept["approved"]]
                    if not focus_concepts:
                        print("\nYou are not tracking any concepts in this category.\n")
                        continue
                
                focus_concepts.sort(key=lambda x: x["relevance_score"], reverse=False if concept_menu[choice] == "Untrack concepts" else True)
                i = 0
                for i in range(math.ceil(len(focus_concepts)/9)):
                    concepts_page = focus_concepts[i*9:(i+1)*9]
                    toggle_choices = [f"{c['name']} - ({c['relevance_score']}): {c.get("description", "")[:190-len(c["name"])]}..." for c in concepts_page] + ["Stop"]
                    toggle_values = [c["approved"] for c in concepts_page] + [False]
                    toggle_values = toggle(toggle_choices, toggle_values, f"Select which {key} to approve/disapprove")
                    for j, concept in enumerate(concepts_page):
                        for existing_concept in settings[concept["category"]]:
                            if existing_concept["uri"] == concept["uri"]:
                                existing_concept["approved"] = toggle_values[j]
                                break
                    with open("news/news_settings.json", "w") as json_file:
                        json.dump(settings, json_file, indent=4)
                    if toggle_values[-1]:
                        break

                    
        