import time
from datetime import datetime, timedelta
import asyncio
from typing import Any, Optional, Dict
import httpx
import yaml
from decouple import config
from loguru import logger
from httpx import BasicAuth
from pydantic import BaseModel, ValidationError

# These are the credentials passed by the variables of your pipeline to your tasks and into your env
PORT_CLIENT_ID = config("PORT_CLIENT_ID")
PORT_CLIENT_SECRET = config("PORT_CLIENT_SECRET")
BITBUCKET_USERNAME = config("BITBUCKET_USERNAME")
BITBUCKET_PASSWORD = config("BITBUCKET_PASSWORD")
BITBUCKET_API_URL = config("BITBUCKET_HOST")
BITBUCKET_PROJECTS_FILTER = config(
    "BITBUCKET_PROJECTS_FILTER", cast=lambda v: v.split(",") if v else None, default=[]
)
PORT_API_URL = config("PORT_API_URL", default="https://api.getport.io/v1")

# According to https://support.atlassian.com/bitbucket-cloud/docs/api-request-limits/
RATE_LIMIT = 1000  # Maximum number of requests allowed per hour
RATE_PERIOD = 3600  # Rate limit reset period in seconds (1 hour)
request_count = 0
rate_limit_start = time.time()
port_access_token, token_expiry_time = None, datetime.now()
port_headers = {}
bitbucket_auth = BasicAuth(username=BITBUCKET_USERNAME, password=BITBUCKET_PASSWORD)
client = httpx.AsyncClient(timeout=httpx.Timeout(60))

async def get_access_token():
    credentials = {"clientId": PORT_CLIENT_ID, "clientSecret": PORT_CLIENT_SECRET}
    token_response = await client.post(f"{PORT_API_URL}/auth/access_token", json=credentials)
    response_data = token_response.json()
    access_token = response_data['accessToken']
    expires_in = response_data['expiresIn']
    token_expiry_time = datetime.now() + timedelta(seconds=expires_in)
    return access_token, token_expiry_time

async def refresh_access_token():
    global port_access_token, token_expiry_time, port_headers
    logger.info("Refreshing access token...")
    port_access_token, token_expiry_time = await get_access_token()
    port_headers = {"Authorization": f"Bearer {port_access_token}"}
    logger.info(f"New token received. Expiry time: {token_expiry_time}")

async def refresh_token_if_expired():
    if datetime.now() >= token_expiry_time:
        await refresh_access_token()

async def refresh_token_and_retry(method: str, url: str, **kwargs):
    await refresh_access_token()
    response = await client.request(method, url, headers=port_headers, **kwargs)
    return response

async def send_port_request(method: str, endpoint: str, payload: Optional[dict] = None):
    global port_access_token, token_expiry_time, port_headers
    await refresh_token_if_expired()
    url = f"{PORT_API_URL}/{endpoint}"
    try:
        response = await client.request(method, url, headers=port_headers, json=payload)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            # Unauthorized, refresh token and retry
            logger.info("Received 401 Unauthorized. Refreshing token and retrying...")
            try:
                response = await refresh_token_and_retry(method, url, json=payload)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                logger.error(f"Error after retrying: {e.response.status_code}, {e.response.text}")
                return {"status_code": e.response.status_code, "response": e.response}
        else:
            logger.error(f"HTTP error occurred: {e.response.status_code}, {e.response.text}")
            return {"status_code": e.response.status_code, "response": e.response}
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {e}")
        return {"status_code": None, "error": e}

async def add_entity_to_port(blueprint_id, entity_object):
    response = await send_port_request(
        method="POST",
        endpoint=f"blueprints/{blueprint_id}/entities?upsert=true&merge=true",
        payload=entity_object
    )
    if not isinstance(response, dict):
        logger.info(response.json())

async def get_paginated_resource(
        path: str,
        params: dict[str, Any] = None,
        page_size: int = 25,
        full_response: bool = False,
):
    global request_count, rate_limit_start

    # Check if we've exceeded the rate limit, and if so, wait until the reset period is over
    if request_count >= RATE_LIMIT:
        elapsed_time = time.time() - rate_limit_start
        if elapsed_time < RATE_PERIOD:
            sleep_time = RATE_PERIOD - elapsed_time
            await asyncio.sleep(sleep_time)

        # Reset the rate limiting variables
        request_count = 0
        rate_limit_start = time.time()

    url = f"{BITBUCKET_API_URL}/rest/api/1.0/{path}"
    params = params or {}
    params["limit"] = page_size
    next_page_start = None

    while True:
        try:
            if next_page_start:
                params["start"] = next_page_start

            response = await client.get(url=url, auth=bitbucket_auth, params=params)
            response.raise_for_status()
            page_json = response.json()
            request_count += 1
            logger.debug(f"Requested data for {path}, with params: {params} and response code: {response.status_code}")
            if full_response:
                yield page_json
            else:
                batch_data = page_json["values"]
                yield batch_data

            next_page_start = page_json.get("nextPageStart")
            if not next_page_start:
                break
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.info(
                    f"Could not find the requested resources {path}. Terminating gracefully..."
                )
                return
            logger.error(
                f"HTTP error with code {e.response.status_code}, content: {e.response.text}"
            )
        except httpx.HTTPError as e:
            logger.error(f"HTTP occurred while fetching Bitbucket data: {e}")
        logger.info(f"Successfully fetched paginated data for {path}")

async def get_single_project(project_key: str):
    response = await client.get(
        f"{BITBUCKET_API_URL}/rest/api/1.0/projects/{project_key}", auth=bitbucket_auth
    )
    response.raise_for_status()
    return response.json()

def parse_repository_file_response(file_response: dict[str, Any]) -> str:
    lines = file_response.get("lines", [])
    logger.info(f"Received port.yaml file with {len(lines)} entries")
    content = ""
    for line in lines:
        content += line.get("text", "") + "\n"
    return content

async def get_repositories(project: dict[str, Any]):
    repositories_path = f"projects/{project['key']}/repos"
    async for repositories_batch in get_paginated_resource(path=repositories_path):
        logger.info(
            f"received repositories batch with size {len(repositories_batch)} from project: {project['key']}"
        )
        await asyncio.gather(*(create_or_update_entity_from_yaml(project_key=project["key"], repo_slug=repo["slug"]) for repo in repositories_batch))

async def read_port_yaml_from_bitbucket(project_key, repo_slug):
    url = f"projects/{project_key}/repos/{repo_slug}/browse/port.yaml"
    port_yaml_file = ""
    async for port_file_batch in get_paginated_resource(
            path=url, page_size=500, full_response=True
    ):
        file_content = parse_repository_file_response(port_file_batch)
        port_yaml_file += file_content
    return yaml.safe_load(port_yaml_file)

async def create_or_update_entity_from_yaml(project_key, repo_slug):
    entity_data = await read_port_yaml_from_bitbucket(project_key, repo_slug)
    if entity_data:
        logger.info(f"Creating entity from port.yaml: {entity_data}")
        for entity in entity_data:
            validated_entity = validate_port_yaml(entity)
            if validated_entity:
                await add_entity_to_port(blueprint_id=entity.get("blueprint"), entity_object=entity)
            else:
                logger.error(f"Invalid entity schema: {entity}")

class PortEntity(BaseModel):
    identifier: str
    title: str
    blueprint: str
    properties: Dict[str, Any]
    relations: Dict[str, Any]

def validate_port_yaml(data: dict):
    try:
        data['properties'] = data.get('properties') or {}
        data['relations'] = data.get('relations') or {}
        validated_entity = PortEntity(**data)
        return validated_entity.model_dump()
    except ValidationError as e:
        logger.error(f"Validation error for entity: {e.json()}")
        return None

async def main():
    logger.info("Starting Bitbucket data extraction")
    if BITBUCKET_PROJECTS_FILTER:
        projects = [await get_single_project(key) for key in BITBUCKET_PROJECTS_FILTER]
    else:
        projects = get_paginated_resource(path="projects")
    async for projects_batch in projects:
        logger.info(f"received projects batch with size {len(projects_batch)}")
        for project in projects_batch:
            await get_repositories(project=project)

    logger.info("Bitbucket gitops completed")
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
