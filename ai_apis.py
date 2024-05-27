import os
import random
import time
from decouple import config
from fp.fp import FreeProxy
import requests
import json
import replicate

import tiktoken
from utils import prompt, save_profile, say, DEBUG
from openai import OpenAI
import os
import logging



def ask_ai(content, system_role=None, model="", json_mode=False):
    """
    Sends a quick query to an AI model and returns the response. Uses the DynamicAI class under the hood.

    Args:
        content (str): The input content or prompt for the AI model.
        system_role (str, optional): The system role for the AI model. Defaults to None.
        model (str, optional): The AI model to use. If not specified, a model will be chosen based on the content.
        json_mode (bool, optional): Whether to use JSON mode for the response from the AI model. Defaults to False.

    Returns:
        str or bool: The response from the AI model if successful, False otherwise.
    
    Raises:
        Exception: If failed to get a response from the OpenAI API.

    """

    client = DynamicAI(tracked=False)
    return client.ask(content, system_role, model, json_mode)


class DynamicAI:
    def __init__(self, project='default', tracked=True):
        self.project = project
        self.tracked = tracked
        self.start_run()


    def __del__(self):
        if self.tracked:
            self.cost_report()

    def ask(self, content, system_role=None, model="", json_mode=False):
        """
        Sends a query to the best fitting AI model and returns the response.

        Args:
            content (str): The input content or prompt for the AI model.
            system_role (str, optional): The system role for the AI model. Defaults to None.
            model (str, optional): The AI model to use. If not specified, a model will be chosen based on the content.
            json_mode (bool, optional): Whether to use JSON mode for the response from the AI model. Defaults to False.

        Returns:
            str or bool: The response from the AI model if successful, False otherwise.
        
        Raises:
            Exception: If failed to get a response from the OpenAI API.

        """
        
        if not model:
            model, tokens, difficulty = self.choose_model(content, json_mode)
        else:
            tokens = self.count_tokens(content)
            difficulty = None
        if tokens > 100000 or (tokens > 10000 and DEBUG):
            if prompt(f"The prompt length is {tokens} tokens. Would you like to shorten it to 8k tokens?", default=True):
                content = self.truncate_to_tokens(content, 8000)
                tokens = self.count_tokens(content)
        say(f"Asking {model}: {content[:150]}... [{tokens} tokens, {difficulty}]")
        if model == 'gemini-pro':
            gemini_response = self.query_gemini(content, system_role, json_mode)
            if gemini_response:
                return gemini_response
            return ask_ai(content, system_role, 'gpt-4o')
        elif model == 'llama3':
            llama3_response = self.query_llama3(content, system_role)
            if llama3_response:
                return llama3_response
            return ask_ai(content, system_role, 'gpt-4o')
        elif model == 'gpt-3.5-turbo-0125':
            openai_response = self.query_openai(content, system_role, 'gpt-3.5-turbo-0125', json_mode)
            if openai_response:
                return openai_response
            return ask_ai(content, system_role, 'gpt-4o')
        elif model == 'gpt-4o':
            openai_response = self.query_openai(content, system_role, 'gpt-4o', json_mode)
            if openai_response:
                return openai_response
            raise Exception("Failed to get a response from OpenAI API")
        
        return False

    def count_tokens(self, string: str, encoding_name="cl100k_base") -> int:
        """Returns the number of tokens in a text string."""
        encoding = tiktoken.get_encoding(encoding_name)
        num_tokens = len(encoding.encode(string))
        return num_tokens


    def choose_model(self, content, json_mode=False):
        """
        Chooses the appropriate language model based on the content and estimated prompt difficulty.

        Args:
            content (str): The content of the prompt.
            json_mode (bool, optional): Indicates whether the output should be in JSON format. Defaults to False.

        Returns:
            tuple: A tuple containing the chosen model, the number of tokens in the content, and the estimated prompt difficulty.
        """
        
        tokens = self.count_tokens(content)
        prompt_start = " ".join(content.split(" ")[:200])
        difficulty = self.estimate_prompt_difficulty(prompt_start)

        if not difficulty:
            return 'llama3', tokens, difficulty
        if difficulty == "easy":
            if tokens < 8000 and not json_mode:
                model = 'llama3'
            elif tokens < 15500:
                model = 'gpt-3.5-turbo-0125'
            elif tokens < 30000:
                model = 'gpt-4o'
            else:
                model = 'gemini-pro'
        elif difficulty == "moderate":
            if tokens < 8000 and not json_mode:
                model = 'llama3'
            elif tokens < 30000:
                model = 'gpt-4o'
            else:
                model = 'gemini-pro'
        else:
            if tokens < 30000:
                model = 'gpt-4o'
            else:
                model = 'gemini-pro'
        
        return model, tokens, difficulty
                

    def estimate_prompt_difficulty(self, prompt, _tries=0):
        """
        Estimates the difficulty and complexity grade of a given prompt.

        Args:
            prompt (str): The prompt to estimate the difficulty for.
            _tries (int, optional): The number of tries made to estimate the difficulty. Defaults to 0.

        Returns:
            str or bool: The estimated difficulty grade ('easy', 'moderate', 'hard') if successful, False otherwise.
        """
        
        response = self.query_openai(
            prompt,
            "Please estimate the difficulty and complexity grade of the following prompt. If the prompt is too long, you will only receive the beginning. Only provide a JSON string with the following keys: 'difficulty' enumerating options (easy, moderate, hard)", model='gpt-3.5-turbo-0125', json_mode=True)
        try:
            response = json.loads(response)
        except:
            response = False
        if response and response.get("difficulty") in ["easy", "moderate", "hard"]:
            return response.get("difficulty")
        if _tries > 3:
            return False
        return self.estimate_prompt_difficulty(prompt, _tries+1)


    def query_gemini(self, content, system_role=None, json_mode=False):
        """
        Queries the Gemini API to generate content based on the given prompt. A proxy is used to prevent geofencing.

        Args:
            content (str): The prompt for generating content.
            system_role (str, optional): The role description for the prompt. Defaults to None.
            json_mode (bool, optional): Flag to indicate whether to return the response in JSON format. Defaults to False.

        Returns:
            str: The generated content based on the prompt.
        """
        
        # Load the last working proxy from the json file
        
        try:
            with open('dynamic_ai/last_proxy.json', 'r') as file:
                last_proxy = json.load(file)
        except FileNotFoundError:
            last_proxy = None

        # Use the last working proxy if available
        if last_proxy:
            proxy = last_proxy
        else:
            # Get a new proxy
            proxy = FreeProxy(country_id=['US'], https=True).get()

        # Save the current proxy to the json file
        with open('dynamic_ai/last_proxy.json', 'w') as file:
            json.dump(proxy, file)

        if system_role:
            prompt = f"Role description: {system_role}\n\nPrompt:\n{content}"
        else:
            prompt = content
        response = False
        for i in range(3):
            proxies = {
                'https': str(proxy)
            }
            url = f'https://generativelanguage.googleapis.com/v1/models/gemini-pro:generateContent?key={config("GEMINI_API_KEY")}'
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            if json_mode:
                data["generationConfig"] = {"response_mime_type": "application/json"}

            try:
                response = requests.post(url, proxies=proxies, json=data, timeout=10)
                if not response.status_code == 200:
                    raise Exception("Failed to send request due to status code", response.status_code)
                with open('last_proxy.json', 'w') as file:
                    json.dump(proxy, file)
                break
            except requests.exceptions.HTTPError as e:
                if response.status_code == 429:
                    time.sleep(random.random()*5)
            except Exception as e:
                say("Failed to send request due to the following error:", e)
                proxy = FreeProxy(country_id=['US'], https=True).get()
        
        if response:
            try:
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                say(response.text)
                say("Failed to parse response due to the following error:", e)
                return None
        return None


    def query_llama3(self, content, system_role):
        if system_role is None:
            system_role = "You are a helpful assistant."
        os.environ["REPLICATE_API_TOKEN"] = config('REPLICATE_API_KEY')
        prompt = {
            "top_p": 0.95,
            "prompt": content,
            "system_prompt": system_role,
            "temperature": 0.7,
            "prompt_template": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n",
            "presence_penalty": 0,
            "max_tokens": 2048,
        }
        output = False
        try:
            output = replicate.run(
                "meta/meta-llama-3-70b-instruct",
                input=prompt
            )
        except replicate.exceptions.ModelError as e:
            if "please retry" in str(e):
                output = replicate.run(
                    "meta/meta-llama-3-70b-instruct",
                    input=prompt
                )
        if output:
            return "".join(output)
        return output


    def query_openai(self, content, system_role, model='gpt-4o', json_mode=False):
        if system_role is None:
            system_role = "You are a helpful assistant."

        ai_client = OpenAI(
            organization='org-OjCSzLcscYwYrWwsc7EWJZs7',
            project='proj_LL7UZDSKgr42Lp0P7QnO30i1',
            api_key=config('OPENAI_API_KEY')
        )
        
        messages = [
            {
                "role": "system",
                "content": system_role
            },
            {
                "role": "user",
                "content": content
            },
        ]

        try:
            response = ai_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.6,
                response_format={ "type": "json_object" } if json_mode else { "type": "text" },
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0
            )

        except Exception as e:
            say(f"Error querying OpenAI API: {e}")
            return None
        
        self._update_tokens(response.usage, model)
        
        if response:
            return response.choices[0].message.content
        else:
            return None


    def truncate_to_tokens(self, prompt, max_tokens=8000):
        tokens = self.count_tokens(prompt)
        say("Tokens before truncation:", tokens)
        while tokens > max_tokens:
            prompt = " ".join(prompt.split(" ")[:int(max_tokens/tokens*len(prompt.split(" ")))-5])
            tokens = self.count_tokens(prompt)
        say("Tokens after truncation:", tokens)
        return prompt


    def start_run(self, project='default'):
        if not os.path.exists('dynamic_ai'):
            os.makedirs('dynamic_ai')

        with open(f'dynamic_ai/run_details.json', 'a') as _:
            pass

        try:
            with open(f'dynamic_ai/run_details.json', 'r') as file:
                data = json.load(file)
        except:
            data = {project: {} }
        
        if project not in data.keys():
            data[project] = {}
        data[project]["current_run_cost"] = 0

        with open(f'dynamic_ai/run_details.json', 'w') as file:
            json.dump(data, file)


    def _update_tokens(self, usage, model, project='default'):

        try:
            with open(f'dynamic_ai/run_details.json', 'r') as file:
                data = json.load(file)
        except FileNotFoundError:
            self.start_run(project)
            return

        if "current_run_cost" not in data[project].keys():
            data[project]["current_run_cost"] = 0
        if "total_tokens" in data[project].keys():
            data[project]["total_tokens"] += usage.total_tokens
        else:
            data[project]["total_tokens"] = usage.total_tokens
        if "prompt_tokens" in data[project].keys():
            data[project]["prompt_tokens"] += usage.prompt_tokens
        else:
            data[project]["prompt_tokens"] = usage.prompt_tokens
        if "completion_tokens" in data[project].keys():
            data[project]["completion_tokens"] += usage.completion_tokens
        else:
            data[project]["completion_tokens"] = usage.completion_tokens

        if "total_cost" not in data[project].keys():
            data[project]["total_cost"] = 0
        if model == 'gpt-4-turbo-preview':
            cost_add = usage.prompt_tokens / 1000000 * 10.00 + usage.completion_tokens / 1000000 * 30.00
            data[project]["total_cost"] += cost_add
            data[project]["current_run_cost"] += cost_add
        elif model == 'gpt-4o':
            cost_add = usage.prompt_tokens / 1000000 * 5.00 + usage.completion_tokens / 1000000 * 15.00
            data[project]["total_cost"] += cost_add
            data[project]["current_run_cost"] += cost_add
        elif model == 'gpt-4':
            cost_add = usage.prompt_tokens / 1000000 * 30.00 + usage.completion_tokens / 1000000 * 60.00
            data[project]["total_cost"] += cost_add
            data[project]["current_run_cost"] += cost_add
        else:
            cost_add = usage.prompt_tokens / 1000000 * 10.00 + usage.completion_tokens / 1000000 * 30.00
            data[project]["total_cost"] += cost_add
            data[project]["current_run_cost"] += cost_add

        with open(f'dynamic_ai/run_details.json', 'w') as file:
            json.dump(data, file)



    def cost_report(self, project='default'):
        try:
            with open(f'dynamic_ai/run_details.json', 'a') as _:
                pass
        except FileNotFoundError:
            print("Please call start_run() if you want get up to date cost analysis.")
            return

        try:
            with open(f'dynamic_ai/run_details.json', 'r') as file:
                data = json.load(file)
        except:
            data = {project: {}}

        if "current_run_cost" not in data[project].keys():
            data[project]["current_run_cost"] = 0

        if "total_cost" not in data[project].keys():
            data[project]["total_cost"] = 0

        print("The current run has costed", round(data[project]["current_run_cost"], 2), f"$ so far while the project '{project}' costs are", round(data[project]["total_cost"], 2), "$ in total.")

        data[project]["current_run_cost"] = 0

        with open(f'dynamic_ai/run_details.json', 'w') as file:
            json.dump(data, file)