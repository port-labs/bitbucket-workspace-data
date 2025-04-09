import json
import re
import time
from datetime import datetime, timedelta
import asyncio
from typing import Any, Optional, Dict, List, AsyncGenerator, Union, Tuple, TypeVar, cast
import httpx
from decouple import config     # type: ignore
from loguru import logger
from httpx import BasicAuth, Response

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
WEBHOOK_SECRET = config("WEBHOOK_SECRET", default="bitbucket_webhook_secret")
IS_VERSION_8_7_OR_OLDER = config("IS_VERSION_8_7_OR_OLDER", default=False)
VALID_PULL_REQUEST_STATES = {"ALL", "OPEN", "MERGED", "DECLINED"}
PULL_REQUEST_STATE = config("PULL_REQUEST_STATE", default="OPEN").upper()


# According to https://support.atlassian.com/bitbucket-cloud/docs/api-request-limits/
RATE_LIMIT = 1000  # Maximum number of requests allowed per hour
RATE_PERIOD = 3600  # Rate limit reset period in seconds (1 hour)
WEBHOOK_IDENTIFIER = "bitbucket_mapper"
WEBHOOK_EVENTS = [
    "repo:modified",
    "project:modified",
    "pr:modified",
    "pr:opened",
    "pr:merged",
    "pr:reviewer:updated",
    "pr:declined",
    "pr:deleted",
    "pr:comment:deleted",
    "pr:from_ref_updated",
    "pr:comment:edited",
    "pr:reviewer:unapproved",
    "pr:reviewer:needs_work",
    "pr:reviewer:approved",
    "pr:comment:added",
]

# Initialize rate limiting variables
request_count = 0
rate_limit_start = time.time()
port_access_token, token_expiry_time = None, datetime.now()
port_headers = {}
bitbucket_auth = BasicAuth(username=BITBUCKET_USERNAME, password=BITBUCKET_PASSWORD)
client = httpx.AsyncClient(timeout=httpx.Timeout(60))

T = TypeVar('T')

async def get_access_token() -> Tuple[str, datetime]:
    credentials = {"clientId": PORT_CLIENT_ID, "clientSecret": PORT_CLIENT_SECRET}
    token_response = await client.post(
        f"{PORT_API_URL}/auth/access_token", json=credentials
    )
    response_data = token_response.json()
    access_token = response_data["accessToken"]
    expires_in = response_data["expiresIn"]
    token_expiry_time = datetime.now() + timedelta(seconds=expires_in)
    return access_token, token_expiry_time


async def refresh_access_token() -> None:
    global port_access_token, token_expiry_time, port_headers
    logger.info("Refreshing access token...")
    port_access_token, token_expiry_time = await get_access_token()
    port_headers = {"Authorization": f"Bearer {port_access_token}"}
    logger.info(f"New token received. Expiry time: {token_expiry_time}")


async def refresh_token_if_expired() -> None:
    if datetime.now() >= token_expiry_time:
        await refresh_access_token()


async def refresh_token_and_retry(method: str, url: str, **kwargs) -> Response:
    await refresh_access_token()
    response = await client.request(method, url, headers=port_headers, **kwargs)
    return response


def sanitize_identifier(identifier: str) -> str:
    pattern = r"[^A-Za-z0-9@_.+:\/=-]"
    # Replace any character that does not match the pattern with an underscore
    return re.sub(pattern, "_", identifier)


async def send_port_request(method: str, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Union[Response, Dict[str, Any]]:
    global port_access_token, token_expiry_time, port_headers
    await refresh_token_if_expired()
    url = f"{PORT_API_URL}/{endpoint}"
    try:
        response = await client.request(method, url, headers=port_headers, json=payload)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            logger.info("Received 401 Unauthorized. Refreshing token and retrying...")
            try:
                response = await refresh_token_and_retry(method, url, json=payload)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                error_response = e.response
                logger.error(
                    f"Error after retrying: {error_response.status_code}, {error_response.text}"
                )
                return {"status_code": error_response.status_code, "response": error_response}
        else:
            error_response = e.response  # type: ignore
            logger.error(
                f"HTTP error occurred: {error_response.status_code}, {error_response.text}"
            )
            return {"status_code": error_response.status_code, "response": error_response}
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {e}")
        return {"status_code": None, "error": e}


async def get_or_create_port_webhook() -> Optional[str]:
    logger.info("Checking if a Bitbucket webhook is configured on Port...")
    response = await send_port_request(
        method="GET", endpoint=f"webhooks/{WEBHOOK_IDENTIFIER}"
    )
    if isinstance(response, dict):
        if response.get("status_code") == 404:
            logger.info("Port webhook not found, creating a new one.")
            return await create_port_webhook()
        else:
            return None
    else:
        webhook_url = response.json().get("integration", {}).get("url")
        logger.info(f"Webhook configuration exists in Port. URL: {webhook_url}")
        return webhook_url


async def create_port_webhook() -> Optional[str]:
    logger.info("Creating a webhook for Bitbucket on Port...")
    with open("./resources/webhook_configuration.json", "r") as file:
        mappings = json.load(file)
    webhook_data = {
        "identifier": WEBHOOK_IDENTIFIER,
        "title": "Bitbucket Webhook",
        "description": "Webhook for receiving Bitbucket events",
        "icon": "BitBucket",
        "mappings": mappings,
        "enabled": True,
        "security": {
            "secret": WEBHOOK_SECRET,
            "signatureHeaderName": "X-Hub-Signature",
            "signatureAlgorithm": "sha256",
            "signaturePrefix": "sha256=",
            "requestIdentifierPath": ".headers['X-Request-ID']",
        },
        "integrationType": "custom",
    }
    response = await send_port_request(
        method="POST", endpoint="webhooks", payload=webhook_data
    )
    if isinstance(response, dict):
        if response.get("status_code") == 442:
            logger.error("Incorrect mapping, kindly fix!")
        return None
    else:
        webhook_url = response.json().get("integration", {}).get("url")
        logger.info(
            f"Webhook configuration successfully created in Port: {webhook_url}"
        )
        return webhook_url


def generate_webhook_data(webhook_url: str, events: List[str]) -> Dict[str, Any]:
    return {
        "name": f"Port Webhook-{webhook_url.split('/')[-1]}",
        "url": webhook_url,
        "events": events,
        "active": True,
        "sslVerificationRequired": True,
        "configuration": {"secret": WEBHOOK_SECRET, "createdBy": "Port"},
    }


async def create_project_level_webhook(
    project_key: str, webhook_url: str, events: List[str]
) -> Optional[Dict[str, Any]]:
    logger.info(f"Creating project-level webhook for project: {project_key}")
    webhook_data = generate_webhook_data(webhook_url, events)

    try:
        response = await client.post(
            f"{BITBUCKET_API_URL}/rest/api/1.0/projects/{project_key}/webhooks",
            json=webhook_data,
            auth=bitbucket_auth,
        )
        response.raise_for_status()
        logger.info(f"Successfully created project-level webhook for {project_key}")
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP error when creating webhook for project: {project_key} code: {e.response.status_code} response: {e.response.text}"
        )
        return None


async def create_repo_level_webhook(
    project_key: str, repo_key: str, webhook_url: str, events: List[str]
) -> Optional[Dict[str, Any]]:
    logger.info(f"Creating repo-level webhook for repo: {repo_key}")
    webhook_data = generate_webhook_data(webhook_url, events)

    try:
        response = await client.post(
            f"{BITBUCKET_API_URL}/rest/api/1.0/projects/{project_key}/repos/{repo_key}/webhooks",
            json=webhook_data,
            auth=bitbucket_auth,
        )
        response.raise_for_status()
        logger.info(f"Successfully created repo-level webhook for {repo_key}")
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"HTTP error when creating webhook for repo: {repo_key} code: {e.response.status_code} response: {e.response.text}"
        )
        return None


async def get_or_create_bitbucket_webhook(
    project_key: str,
    webhook_url: str,
    events: List[str],
    repo_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    logger.info(f"Checking webhooks for {repo_key or project_key}")
    if webhook_url is not None:
        try:
            webhook_path = (
                f"projects/{project_key}/repos/{repo_key}/webhooks"
                if repo_key
                else f"projects/{project_key}/webhooks"
            )
            
            webhook_identifier = f"Port Webhook-{webhook_url.split('/')[-1]}"
            
            webhook_generator = get_paginated_resource(path=webhook_path)
            
            matching_webhooks: List[Dict[str, Any]] = []
            async for webhook_batch in webhook_generator:
                for webhook in cast(List[Dict[str, Any]], webhook_batch):
                    if webhook.get("name") == webhook_identifier:
                        matching_webhooks.append(webhook)
            
            if matching_webhooks:
                logger.info(f"Webhook already exists for {repo_key or project_key}.")
                return matching_webhooks[0]
                
            logger.info(
                f"Webhook not found for {repo_key or project_key}. Creating a new one."
            )
            
            if repo_key:
                return await create_repo_level_webhook(
                    project_key, repo_key, webhook_url, events
                )
            else:
                return await create_project_level_webhook(
                    project_key, webhook_url, events
                )
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error when checking webhooks for project: {project_key} code: {e.response.status_code} response: {e.response.text}"
            )
            return None
    else:
        logger.error("Port webhook URL is not available. Skipping webhook check...")
        return None


async def add_entity_to_port(blueprint_id: str, entity_object: Dict[str, Any]) -> None:
    response = await send_port_request(
        method="POST",
        endpoint=f"blueprints/{blueprint_id}/entities?upsert=true&merge=true",
        payload=entity_object,
    )
    if not isinstance(response, dict):
        logger.info(response.json())


async def get_paginated_resource(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    page_size: int = 25,
    full_response: bool = False,
) -> AsyncGenerator[Union[Dict[str, Any], List[Dict[str, Any]]], None]:
    global request_count, rate_limit_start

    if request_count >= RATE_LIMIT:
        elapsed_time = time.time() - rate_limit_start
        if elapsed_time < RATE_PERIOD:
            sleep_time = RATE_PERIOD - elapsed_time
            await asyncio.sleep(sleep_time)

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
            logger.debug(
                f"Requested data for {path}, with params: {params} and response code: {response.status_code}"
            )
            if full_response:
                yield cast(Dict[str, Any], page_json)
            else:
                batch_data = page_json.get("values", [])
                yield cast(List[Dict[str, Any]], batch_data)

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


async def get_single_project(project_key: str) -> Dict[str, Any]:
    response = await client.get(
        f"{BITBUCKET_API_URL}/rest/api/1.0/projects/{project_key}", auth=bitbucket_auth
    )
    response.raise_for_status()
    return response.json()


def convert_to_datetime(timestamp: Optional[int]) -> str:
    if timestamp is None:
        return ""
    converted_datetime = datetime.utcfromtimestamp(timestamp / 1000.0)
    return converted_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_repository_file_response(file_response: Dict[str, Any]) -> str:
    lines = file_response.get("lines", [])
    logger.info(f"Received readme file with {len(lines)} entries")
    readme_content = ""

    for line in lines:
        readme_content += line.get("text", "") + "\n"

    return readme_content


async def stream_async_generators(
    generators: List[AsyncGenerator[Any, None]], 
    batch_size: int = 50
) -> AsyncGenerator[List[Any], None]:
    """Utility function to process multiple async generators concurrently"""
    results = []
    while True:
        tasks = []
        for gen in generators:
            try:
                tasks.append(anext(gen))
            except StopAsyncIteration:
                continue
        
        if not tasks:
            break
            
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        results.extend([r for r in batch_results if not isinstance(r, Exception)])
        
        if len(tasks) < batch_size:
            break
            
    yield results


async def process_user_entities(users_data: List[Dict[str, Any]]) -> None:
    blueprint_id = "bitbucketUser"
    tasks = []
    
    for user in users_data:
        entity = {
            "title": user.get("displayName"),
            "properties": {
                "username": user.get("name"),
                "url": user.get("links", {}).get("self", [{}])[0].get("href"),
            },
            "relations": {},
        }
        identifier = str(user.get("emailAddress"))
        if identifier:
            entity["identifier"] = sanitize_identifier(identifier)
        tasks.append(add_entity_to_port(blueprint_id=blueprint_id, entity_object=entity))
    
    await asyncio.gather(*tasks)


async def process_project_entities(projects_data: List[Dict[str, Any]]) -> None:
    blueprint_id = "bitbucketProject"
    tasks = []
    
    for project in projects_data:
        entity = {
            "title": project.get("name"),
            "properties": {
                "description": project.get("description"),
                "public": project.get("public"),
                "type": project.get("type"),
                "link": project.get("links", {}).get("self", [{}])[0].get("href"),
            },
            "relations": {},
        }
        identifier = str(project.get("key"))
        if identifier:
            entity["identifier"] = sanitize_identifier(identifier)
        tasks.append(add_entity_to_port(blueprint_id=blueprint_id, entity_object=entity))
    
    await asyncio.gather(*tasks)


async def process_repository_entities(repository_data: List[Dict[str, Any]]) -> None:
    blueprint_id = "bitbucketRepository"
    tasks = []
    
    for repo in repository_data:
        readme_content = await get_repository_readme(
            project_key=repo["project"]["key"], repo_slug=repo["slug"]
        )
        entity = {
            "title": repo.get("name"),
            "properties": {
                "description": repo.get("description"),
                "state": repo.get("state"),
                "forkable": repo.get("forkable"),
                "public": repo.get("public"),
                "link": repo.get("links", {}).get("self", [{}])[0].get("href"),
                "documentation": readme_content,
                "swagger_url": f"https://api.{repo.get('slug')}.com",
            },
            "relations": dict(
                project=repo.get("project", {}).get("key"),
                latestCommitAuthor=repo.get("__latestCommit", {})
                .get("committer", {})
                .get("emailAddress"),
            ),
        }
        identifier = str(repo.get("slug"))
        if identifier:
            entity["identifier"] = sanitize_identifier(identifier)
        tasks.append(add_entity_to_port(blueprint_id=blueprint_id, entity_object=entity))
    
    await asyncio.gather(*tasks)


async def process_pullrequest_entities(pullrequest_data: List[Dict[str, Any]]) -> None:
    blueprint_id = "bitbucketPullrequest"
    tasks = []
    
    for pr in pullrequest_data:
        entity = {
            "title": pr.get("title"),
            "properties": {
                "created_on": convert_to_datetime(pr.get("createdDate")),
                "updated_on": convert_to_datetime(pr.get("updatedDate")),
                "mergedAt": convert_to_datetime(pr.get("closedDate", 0)),
                "merge_commit": pr.get("fromRef", {}).get("latestCommit"),
                "description": pr.get("description"),
                "state": pr.get("state"),
                "owner": pr.get("author", {}).get("user", {}).get("emailAddress"),
                "link": pr.get("links", {}).get("self", [{}])[0].get("href"),
                "destination": pr.get("toRef", {}).get("displayId"),
                "reviewers": [
                    reviewer_email
                    for reviewer in pr.get("reviewers", [])
                    if (reviewer_email := reviewer.get("user", {}).get("emailAddress"))
                ],
                "source": pr.get("fromRef", {}).get("displayId"),
            },
            "relations": {
                "repository": pr["toRef"]["repository"]["slug"],
                "participants": [
                    email
                    for email in [
                        pr.get("author", {}).get("user", {}).get("emailAddress")
                    ]
                    + [
                        user.get("user", {}).get("emailAddress", "")
                        for user in pr.get("participants", [])
                    ]
                    if email
                ],
            },
        }
        identifier = str(pr.get("id"))
        if identifier:
            entity["identifier"] = sanitize_identifier(identifier)
        tasks.append(add_entity_to_port(blueprint_id=blueprint_id, entity_object=entity))
    
    await asyncio.gather(*tasks)


async def get_repository_readme(project_key: str, repo_slug: str) -> str:
    file_path = f"projects/{project_key}/repos/{repo_slug}/browse/README.md"
    readme_content = ""
    async for readme_file_batch in get_paginated_resource(
        path=file_path, page_size=500, full_response=True
    ):
        file_content = parse_repository_file_response(cast(Dict[str, Any], readme_file_batch))
        readme_content += file_content
    return readme_content


async def get_latest_commit(project_key: str, repo_slug: str) -> Dict[str, Any]:
    try:
        commit_path = f"projects/{project_key}/repos/{repo_slug}/commits"
        async for commit_batch in get_paginated_resource(path=commit_path):
            if commit_batch:
                latest_commit = cast(List[Dict[str, Any]], commit_batch)[0]
                return latest_commit
            return {}
    except Exception as e:
        logger.error(f"Error fetching latest commit for repo {repo_slug}: {e}")
    return {}


async def get_repositories(project: Dict[str, Any], port_webhook_url: Optional[str]) -> None:
    if not port_webhook_url:
        logger.error("Port webhook URL is not available. Skipping webhook setup...")
        return

    repositories_path = f"projects/{project['key']}/repos"
    repositories_generator = get_paginated_resource(path=repositories_path)
    
    async for repositories_batch in repositories_generator:
        logger.info(
            f"received repositories batch with size {len(repositories_batch)} from project: {project['key']}"
        )
        
        repos_with_commits = await asyncio.gather(*[
            get_latest_commit(project_key=project["key"], repo_slug=repo["slug"])
            for repo in cast(List[Dict[str, Any]], repositories_batch)
        ])
        
        await process_repository_entities(
            repository_data=[
                {**repo, "__latestCommit": commit}
                for repo, commit in zip(cast(List[Dict[str, Any]], repositories_batch), repos_with_commits)
            ]
        )
        
        if IS_VERSION_8_7_OR_OLDER:
            webhook_tasks = [
                get_or_create_bitbucket_webhook(
                    project_key=project["key"],
                    repo_key=repo["slug"],
                    webhook_url=port_webhook_url,
                    events=WEBHOOK_EVENTS,
                )
                for repo in cast(List[Dict[str, Any]], repositories_batch)
            ]
            await asyncio.gather(*webhook_tasks)
        
        await get_repository_pull_requests(repository_batch=cast(List[Dict[str, Any]], repositories_batch))


async def get_repository_pull_requests(repository_batch: List[Dict[str, Any]]) -> None:
    global PULL_REQUEST_STATE
    if PULL_REQUEST_STATE not in VALID_PULL_REQUEST_STATES:
        logger.warning(
            f"Invalid PULL_REQUEST_STATE '{PULL_REQUEST_STATE}' provided. Defaulting to 'OPEN'."
        )
        PULL_REQUEST_STATE = "OPEN"
    
    # Process PRs for all repositories concurrently
    pr_generators = [
        get_paginated_resource(
            path=f"projects/{repo['project']['key']}/repos/{repo['slug']}/pull-requests",
            params={"state": PULL_REQUEST_STATE},
        )
        for repo in repository_batch
    ]
    
    async for pull_requests_batch in stream_async_generators(pr_generators):
        logger.info(
            f"received pull requests batch with size {len(pull_requests_batch)}"
        )
        await process_pullrequest_entities(pullrequest_data=pull_requests_batch)


async def main() -> None:
    logger.info("Starting Bitbucket data extraction")
    
    # Process users concurrently
    users_generator = get_paginated_resource(path="admin/users")
    async for users_batch in users_generator:
        logger.info(f"received users batch with size {len(users_batch)}")
        await process_user_entities(users_data=cast(List[Dict[str, Any]], users_batch))

    # Process projects concurrently
    project_path = "projects"
    if BITBUCKET_PROJECTS_FILTER:
        projects = await asyncio.gather(*[
            get_single_project(key) for key in BITBUCKET_PROJECTS_FILTER
        ])
    else:
        projects_generator = get_paginated_resource(path=project_path)
        projects: List[Dict[str, Any]] = []  # type: ignore
        async for batch in projects_generator:
            projects.extend(cast(List[Dict[str, Any]], batch))

    port_webhook_url = await get_or_create_port_webhook()
    if not port_webhook_url:
        logger.error("Failed to get or create Port webhook. Skipping webhook setup...")

    # Process projects concurrently
    await process_project_entities(projects_data=projects)

    # Process repositories for all projects concurrently
    repo_tasks = [
        get_repositories(project=project, port_webhook_url=port_webhook_url)
        for project in projects
    ]
    await asyncio.gather(*repo_tasks)

    # Set up webhooks for all projects concurrently if needed
    if not IS_VERSION_8_7_OR_OLDER and port_webhook_url:
        webhook_tasks = [
            get_or_create_bitbucket_webhook(
                project_key=project["key"],
                webhook_url=port_webhook_url,
                events=WEBHOOK_EVENTS,
            )
            for project in projects
        ]
        await asyncio.gather(*webhook_tasks)

    logger.info("Bitbucket data extraction completed")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
