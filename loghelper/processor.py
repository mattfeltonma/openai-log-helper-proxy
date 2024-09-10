import os
import time
import logging
import re
import json
import asyncio
import sys
import uuid
import tiktoken
from azure.eventhub import EventData
from azure.eventhub.aio import EventHubProducerClient
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import (
    LoggerProvider,
    LoggingHandler
)
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter

# Configure an OpenTelemetry logger with support to send to Azure Monitor
logger_provider = LoggerProvider()
set_logger_provider(logger_provider)
exporter = AzureMonitorLogExporter.from_connection_string(
    os.environ.get("APPLICATION_INSIGHTS_CONNECTION_STRING")
)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
opentelemetry_handler = LoggingHandler()

# Create a logging mechanism
logging.basicConfig(
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        opentelemetry_handler,
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EVENT_HUB_CONNECTION_STR = os.environ.get("EVENT_HUB_CONNECTION_STR")
EVENT_HUB_NAME = os.environ.get("EVENT_HUB_NAME")

producer = EventHubProducerClient.from_connection_string(
    conn_str=EVENT_HUB_CONNECTION_STR, eventhub_name=EVENT_HUB_NAME,
)

def parse_headers(headers_str):
    logger.debug("Parsing headers...")
    headers = {}
    for header in headers_str.split(" | "):
        if header != "":
            key, value = header.split(": ", 1)
            headers[key] = value
    logger.debug("Headers parsed...")
    return headers

def parse_response_body(body_str):
    logger.debug("Parsing response body...")
    cleaned_body_str = re.sub(r'\[DONE\]', '', body_str)
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
                        response = response + \
                            entry['choices'][0]['delta']['content']
    logger.debug("Response body parsed...")
    return (response)

def num_tokens_from_string(string: str, model_name: str) -> int:
    if model_name == "not_supported":
        logging.info("Deployment name does not match a valid model supported by the tokenizer. Setting token count to 0...")
        return 0
    else:
        logging.debug("Calculating number of tokens...")
        encoding = tiktoken.encoding_for_model(model_name)
        num_tokens = len(encoding.encode(string))
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
    logger.info("Logging event being packaged...")
    event_batch = await producer.create_batch()
    event_batch.add(event)
    await producer.send_batch(event_batch)
    logger.info("Logging event successfully delivered...")


def main():
    
    log_file_path = "/var/log/nginx_access.log"
    with open(log_file_path, "r") as log_file:
        for line in follow(log_file):
            try:
                raw_log_data = line.strip()

                # Create JSON object from log entry
                json_log_data = json.loads(raw_log_data)

                # Extract the deployment name. This should be the model name to ensure the correct tokenizer is chosen.
                # If the deployment name is not supported, the model name will be set to "not_supported" and the tokens used
                # will be set to 0.
                uri = json_log_data["uri"]
                match = re.search(r'deployments/([^/]+)/', uri)
                
                # Specify valid models supported by the tokenizer
                valid_models = [
                    'gpt-35-turbo',
                    'gpt-4o',
                    'gpt-4'
                ]
                deployment_name = match.group(1)
                
                # Check to see if the deployment name matches a valid model and if not set to not_supported
                if any(valid_model in deployment_name for valid_model in valid_models):
                    model_name = deployment_name
                else:
                    model_name = "not_supported"
   
                # Extract the prompt from the request body
                prompt = json.dumps(json.loads(json_log_data["request_body"])[
                    'messages'][0])
                
                # Process completion
                if json_log_data['status'] == 200:
                    logger.debug('Detected 200 response...')

                    # Generate GUID for message to uniquely identify it
                    message_guid = str(uuid.uuid4())

                    # Process the streaming completion for logging
                    if 'stream' in json.loads(json_log_data['request_body']):
                        logger.info('Detected streaming completion...')
                        streaming = "true"

                        # Parse the response body to consolidate the events and extract the completion
                        response_body = json_log_data['response_body']
                        completion = parse_response_body(response_body)
                        
                        # Calculate the number of completion tokens
                        prompt_tokens = num_tokens_from_string(
                            prompt, model_name)
                        completion_tokens = num_tokens_from_string(
                            completion, model_name)

                    # Process the non-streaming completion for logging
                    else:
                        logger.info('Detected non-streaming completion...')
                        streaming = "false"

                        # Extract the completion from the response body
                        response_body = json.loads(json_log_data['response_body'])[
                            'choices'][0]['message']['content']
                        completion = response_body

                        # Extract tokens from reponse
                        prompt_tokens = json.loads(json_log_data["response_body"])[
                            'usage']['prompt_tokens']
                        completion_tokens = json.loads(json_log_data["response_body"])[
                            'usage']['completion_tokens']

                # Parse the headers
                request_headers = parse_headers(json_log_data["request_headers"])
                response_headers = parse_headers(json_log_data["response_headers"])

                # Send the event to Event Hub
                if completion_tokens > 0:
                    event = EventData(json.dumps({
                        # Add the log data to the event
                        "Type": "openai-logger",
                        "message_guid": message_guid,
                        "req_headers": request_headers,
                        "resp_headers": response_headers,
                        "prompt": prompt,
                        "model": model_name,
                        "streaming": streaming,
                        "completion": completion,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                        "client_ip": json_log_data["address"],
                        "response_time": json_log_data["resp_time"]
                    }).encode("utf-8"))
                    asyncio.run(send_to_event_hub(event))
                    
            except Exception as e:
                logging.error(f"Error in tailing: {e}")


if __name__ == "__main__":
    asyncio.run(main())
    main()
