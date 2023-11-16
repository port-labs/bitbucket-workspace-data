## Import the needed libraries
import requests
from requests.auth import HTTPBasicAuth
from decouple import config
from loguru import logger
from typing import Any
import time

# Get environment variables using the config object or os.environ["KEY"]
# These are the credentials passed by the variables of your pipeline to your tasks and in to your env

PORT_CLIENT_ID = config("PORT_CLIENT_ID")
PORT_CLIENT_SECRET = config("PORT_CLIENT_SECRET")
BITBUCKET_USERNAME = config("BITBUCKET_USERNAME")
BITBUCKET_APP_PASSWORD = config("BITBUCKET_APP_PASSWORD")
BITBUCKET_API_URL = "https://api.bitbucket.org/2.0"
PORT_API_URL = "https://api.getport.io/v1"
PAGE_SIZE = 50

## According to https://support.atlassian.com/bitbucket-cloud/docs/api-request-limits/
RATE_LIMIT = 1000  # Maximum number of requests allowed per hour 
RATE_PERIOD = 3600  # Rate limit reset period in seconds (1 hour)

# Initialize rate limiting variables
request_count = 0
rate_limit_start = time.time()

## Get Port Access Token
credentials = {'clientId': PORT_CLIENT_ID, 'clientSecret': PORT_CLIENT_SECRET}
token_response = requests.post(f'{PORT_API_URL}/auth/access_token', json=credentials)
access_token = token_response.json()['accessToken']

# You can now use the value in access_token when making further requests
port_headers = {
	'Authorization': f'Bearer {access_token}'
}

## Bitbucket auth password https://support.atlassian.com/bitbucket-cloud/docs/create-an-app-password/
bitbucket_auth = HTTPBasicAuth(username=BITBUCKET_USERNAME, password=BITBUCKET_APP_PASSWORD)


def add_entity_to_port(blueprint_id, entity_object):
    response = requests.post(f'{PORT_API_URL}/blueprints/{blueprint_id}/entities?upsert=true&merge=true', json=entity_object, headers=port_headers)
    logger.info(response.json())

def get_paginated_resource(path: str):
    logger.info(f"Requesting data for {path}")

    global request_count, rate_limit_start

    # Check if we've exceeded the rate limit, and if so, wait until the reset period is over
    if request_count >= RATE_LIMIT:
        elapsed_time = time.time() - rate_limit_start
        if elapsed_time < RATE_PERIOD:
            sleep_time = RATE_PERIOD - elapsed_time
            time.sleep(sleep_time)

        # Reset the rate limiting variables
        request_count = 0
        rate_limit_start = time.time()

    url = f"{BITBUCKET_API_URL}/{path}"
    pagination_params: dict[str, Any] = {"pagelen": PAGE_SIZE}
    while url:
        try:
            response = requests.get(url=url, auth=bitbucket_auth, params=pagination_params)
            response.raise_for_status()
            page_json = response.json()
            request_count += 1
            batch_data = page_json["values"]
            yield batch_data

            url = page_json.get("next")
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP error with info: {e}"
            )
            raise
    logger.info(f"Successfully fetched paginated data for {path}")

def process_project_entities(projects_data: list[dict[str, Any]]):
    blueprint_id = "bitbucketProject"

    for project in projects_data:

        entity = {
            "identifier": project["key"],
            "title": project["name"],
            "properties": {
                "created_on": project["created_on"],
                "updated_on": project["updated_on"],
                "has_public_repos": project["has_publicly_visible_repos"],
                "description": project["description"],
                "is_private": project["is_private"],
                "owner": project["owner"]["display_name"],
                "workspace_name": project["workspace"]["name"],
                "link": project["links"]["html"]["href"]
            },
            "relations": {}
        }
        add_entity_to_port(blueprint_id=blueprint_id, entity_object=entity)

def process_repository_entities(repository_data: list[dict[str, Any]]):
    blueprint_id = "bitbucketRepository"

    for repo in repository_data:

        entity = {
        "identifier": repo["slug"],
        "title": repo["name"],
        "properties": {
            "created_on": repo["created_on"],
            "updated_on": repo["updated_on"],
            "fork_policy": repo["fork_policy"],
            "description": repo["description"],
            "is_private": repo["is_private"],
            "owner": repo["owner"]["display_name"],
            "workspace_name": repo["workspace"]["name"],
            "link": repo["links"]["html"]["href"],
            "website": repo["website"],
            "size": repo["size"],
            "language": repo["language"],
            "has_issues": repo["has_issues"],
            "main_branch": repo["mainbranch"]["name"]
        },
        "relations": {
            "project": repo["project"]["key"]
        }
        }
        add_entity_to_port(blueprint_id=blueprint_id, entity_object=entity)

def process_pullrequest_entities(pullrequest_data: list[dict[str, Any]]):
    blueprint_id = "bitbucketPullrequest"

    for pr in pullrequest_data:

        entity = {
            "identifier": str(pr["id"]),
            "title": pr["title"],
            "properties": {
                "created_on": pr["created_on"],
                "updated_on": pr["updated_on"],
                "merge_commit": pr["merge_commit"],
                "description": pr["description"],
                "state": pr["state"],
                "owner": pr["author"]["display_name"],
                "link": pr["links"]["html"]["href"],
                "closed_by": pr["closed_by"],
                "destination": pr["destination"]["branch"]["name"],
                "participants": [user["user"]["display_name"] for user in pr.get("participants", [])],
                "reviewers": [user["user"]["display_name"] for user in pr.get("reviewers", [])],
                "source": pr["source"]["branch"]["name"]
            },
            "relations": {
                "repository": pr["links"]["html"]["href"].split("/")[-3]
            }
        }
        add_entity_to_port(blueprint_id=blueprint_id, entity_object=entity)
    

def get_workspace_projects(workspace):
    projects_path = f"workspaces/{workspace['slug']}/projects"
    for projects_batch in get_paginated_resource(path=projects_path):
        logger.info(f"received projects batch with size {len(projects_batch)}")
        process_project_entities(projects_data=projects_batch)

def get_workspace_repositories(workspace):
    repositories_path = f"repositories/{workspace['slug']}"
    for repositories_batch in get_paginated_resource(path=repositories_path):
        logger.info(f"received repositories batch with size {len(repositories_batch)}")
        process_repository_entities(repository_data=repositories_batch)
    
        get_repository_pull_requests(repository_batch=repositories_batch)
    

def get_repository_pull_requests(repository_batch: list[dict[str, Any]]):
    for repository in repository_batch:
        pull_requests_path = f"repositories/{repository['workspace']['slug']}/{repository['slug']}/pullrequests"
        for pull_requests_batch in get_paginated_resource(path=pull_requests_path):
            logger.info(f"received pull requests batch with size {len(pull_requests_batch)}")
            process_pullrequest_entities(pullrequest_data=pull_requests_batch)

if __name__ == "__main__":
    workspaces_path = "workspaces"
    for workspace_batch in get_paginated_resource(path=workspaces_path):
        logger.info(f"received workspace batch with size {len(workspace_batch)}")
        for workspace in workspace_batch:
            get_workspace_projects(workspace)
            get_workspace_repositories(workspace)
