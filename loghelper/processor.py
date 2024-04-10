
import os
import time
import logging
import tiktoken
import re
import json
import asyncio
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient

logging.basicConfig(filename="/var/log/loghelper_openai.log",
    filemode='a',
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    level=logging.DEBUG)

logger = logging.getLogger(__name__)

EVENT_HUB_CONNECTION_STR = os.environ.get("EVENT_HUB_CONNECTION_STR")
EVENT_HUB_NAME = os.environ.get("EVENT_HUB_NAME")

producer = EventHubProducerClient.from_connection_string(
        conn_str=EVENT_HUB_CONNECTION_STR, eventhub_name=EVENT_HUB_NAME,
    )

def cleanup_raw_logs(unprocessed_log_data):
    # Fix missing double quotes in the JSON
    logging.info("Processing raw logs and cleaning them up...")
    pattern = re.compile(r'{"source":.*?\[DONE\]\\n\\n}', re.DOTALL)
    match = re.search(pattern, unprocessed_log_data)
    matched_data = match.group(0)
    processed_log_data = matched_data[:-1] + '"}'
    json_log_data = json.loads(processed_log_data)
    logging.info("Cleanup complete...")
    return json_log_data


def parse_headers(headers_str):
    logging.info("Parsing headers...")
    headers = {}
    for header in headers_str.split(" | "):
        if header != "":
            key, value = header.split(": ", 1)
            headers[key] = value
    logging.info("Headers parsed...")
    return headers

def parse_response_body(body_str):
    logging.info("Parsing response body...")
    cleaned_body_str = re.sub(r'\[DONE\]', '', body_str)
    print(cleaned_body_str)
    entries = []
    response = ""
    for line in cleaned_body_str.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            entries.append(json.loads(line[len("data: "):]))
    for entry in entries:
        if 'choices' in entry:
            if len(entry['choices']) > 0:
                if 'delta' in entry['choices'][0]:
                    if 'content' in entry['choices'][0]['delta']:
                        response = response + entry['choices'][0]['delta']['content']
    logging.info("Response body parsed...")
    return(response)
    
def num_tokens_from_string(string: str, encoding_name: str) -> int:
    logging.info("Calculating number of tokens...")
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    logging.info("Number of tokens calculated...")
    return num_tokens

# https://medium.com/@aliasav/how-follow-a-file-in-python-tail-f-in-python-bca026a901cf
def follow(f):
    '''generator function that yields new lines in a file
    '''
    # seek the end of the file
    f.seek(0, os.SEEK_END)
    # start infinite loop
    while True:
        # read last line of file
        line = f.readline()
        # sleep if file hasn't been updated
        if not line:
            time.sleep(0.1)
            continue

        yield line   
        
async def send_to_event_hub(event: EventData):
    logging.info("!!! send to event hub start !!!")
    event_batch = await producer.create_batch()
    event_batch.add(event)
    await producer.send_batch(event_batch)
    logging.info("!!! send to event hub complete !!!")

def main():
    log_file_path = "/var/log/nginx_access.log"
    with open(log_file_path, "r") as log_file:
        for line in follow(log_file):
            try:
                unprocessed_log_data = line.strip()

                # Cleanup the logs
                json_log_data = cleanup_raw_logs(unprocessed_log_data)

                # Extract the prompt from the request body
                prompt = json.loads(json_log_data["request_body"])['messages'][0]['content']

                # Parse the headers
                request_headers = parse_headers(json_log_data["request_headers"])
                response_headers = parse_headers(json_log_data["response_headers"])
                
                # Add a header

                # Process the response body
                response_body = json_log_data["response_body"]
                completion = parse_response_body(response_body)

                # Calculate the number of tokens in the prompt and response
                prompt_tokens = num_tokens_from_string(prompt, "cl100k_base")
                completion_tokens = num_tokens_from_string(completion, "cl100k_base")

                if completion_tokens > 0:
                        event = EventData(json.dumps({
                            # Add the log data to the event
                            "Type": "openai-logger",
                            "req_headers": request_headers,
                            "resp_headers": response_headers,
                            "prompt": prompt,
                            "completion": completion,
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens
                        }).encode("utf-8"))
                        asyncio.run(send_to_event_hub(event))
            except Exception as e:
                logging.error(f"Error in tailing: {e}")


if __name__ == "__main__":
    logger.info("start main...")
    asyncio.run(main())
    main()
    logger.info("stop main...")


