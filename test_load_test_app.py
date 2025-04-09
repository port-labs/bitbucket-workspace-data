"""
This script is used to test the performance of the app.py script.
It simulates a large number of requests to the Bitbucket API and measures the time it takes to complete.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List
import httpx
from loguru import logger
import pytest

# Simulated data sizes
NUM_USERS = 12000
NUM_PROJECTS = 140
REPOS_PER_PROJECT = 30  # This will give us 4200 total repositories
PRS_PER_REPO = 5

# Constants for concurrent processing
MAX_CONCURRENT_REQUESTS = 50
BATCH_SIZE = 500

class MockBitbucketAPI:
    def __init__(self):
        self.base_url = "http://mock-bitbucket"
        self.client = httpx.AsyncClient()
        
    async def _simulate_request(self):
        """Simulate minimal network delay"""
        await asyncio.sleep(5)  # Each API call takes 1 second
        
    def _generate_user(self, user_id: int) -> Dict[str, Any]:
        return {
            "name": f"user{user_id}",
            "displayName": f"User {user_id}",
            "emailAddress": f"user{user_id}@example.com",
            "links": {"self": [{"href": f"http://bitbucket/users/{user_id}"}]}
        }
    
    def _generate_project(self, project_id: int) -> Dict[str, Any]:
        return {
            "key": f"PROJ{project_id}",
            "name": f"Project {project_id}",
            "description": f"Description for project {project_id}",
            "public": True,
            "type": "NORMAL",
            "links": {"self": [{"href": f"http://bitbucket/projects/{project_id}"}]}
        }
    
    def _generate_repo(self, project_key: str, repo_id: int) -> Dict[str, Any]:
        return {
            "slug": f"repo{repo_id}",
            "name": f"Repository {repo_id}",
            "description": f"Description for repo {repo_id}",
            "state": "AVAILABLE",
            "forkable": True,
            "public": True,
            "project": {"key": project_key},
            "links": {"self": [{"href": f"http://bitbucket/repos/{repo_id}"}]}
        }
    
    def _generate_pr(self, repo_slug: str, pr_id: int) -> Dict[str, Any]:
        return {
            "id": pr_id,
            "title": f"PR {pr_id}",
            "description": f"Description for PR {pr_id}",
            "state": "OPEN",
            "createdDate": int((datetime.now() - timedelta(days=pr_id)).timestamp() * 1000),
            "updatedDate": int(datetime.now().timestamp() * 1000),
            "closedDate": None,
            "fromRef": {
                "displayId": f"feature/{pr_id}",
                "repository": {"slug": repo_slug},
                "latestCommit": f"abc{pr_id}"
            },
            "toRef": {
                "displayId": "main",
                "repository": {"slug": repo_slug}
            },
            "author": {
                "user": {"emailAddress": f"author{pr_id}@example.com"}
            },
            "reviewers": [
                {"user": {"emailAddress": f"reviewer{pr_id}@example.com"}}
            ],
            "participants": [
                {"user": {"emailAddress": f"participant{pr_id}@example.com"}}
            ],
            "links": {"self": [{"href": f"http://bitbucket/prs/{pr_id}"}]}
        }

    async def get_users(self, start: int = 0, limit: int = 25) -> Dict[str, Any]:
        await self._simulate_request()
        end = min(start + limit, NUM_USERS)
        users = [self._generate_user(i) for i in range(start, end)]
        return {
            "values": users,
            "nextPageStart": end if end < NUM_USERS else None
        }

    async def get_projects(self, start: int = 0, limit: int = 25) -> Dict[str, Any]:
        await self._simulate_request()
        end = min(start + limit, NUM_PROJECTS)
        projects = [self._generate_project(i) for i in range(start, end)]
        return {
            "values": projects,
            "nextPageStart": end if end < NUM_PROJECTS else None
        }

    async def get_repositories(self, project_key: str, start: int = 0, limit: int = 25) -> Dict[str, Any]:
        await self._simulate_request()
        end = min(start + limit, REPOS_PER_PROJECT)
        repos = [self._generate_repo(project_key, i) for i in range(start, end)]
        return {
            "values": repos,
            "nextPageStart": end if end < REPOS_PER_PROJECT else None
        }

    async def get_pull_requests(self, project_key: str, repo_slug: str, start: int = 0, limit: int = 25) -> Dict[str, Any]:
        await self._simulate_request()
        end = min(start + limit, PRS_PER_REPO)
        prs = [self._generate_pr(repo_slug, i) for i in range(start, end)]
        return {
            "values": prs,
            "nextPageStart": end if end < PRS_PER_REPO else None
        }

    async def get_readme(self, project_key: str, repo_slug: str) -> Dict[str, Any]:
        await self._simulate_request()
        return {
            "lines": [
                {"text": f"# {repo_slug}"},
                {"text": "This is a mock README file."}
            ]
        }

    async def close(self):
        await self.client.aclose()

async def fetch_all_paginated(api: MockBitbucketAPI, fetch_func, *args, **kwargs) -> List[Dict[str, Any]]:
    """Helper function to fetch all pages of a paginated resource"""
    results = []
    start = 0
    while True:
        response = await fetch_func(*args, start=start, **kwargs)
        results.extend(response["values"])
        if not response["nextPageStart"]:
            break
        start = response["nextPageStart"]
    return results

@pytest.mark.asyncio
async def test_performance():
    api = MockBitbucketAPI()
    start_time = datetime.now()
    
    # Test users with concurrent requests
    logger.info("Testing users...")
    users = await fetch_all_paginated(api, api.get_users)
    
    # Test projects with concurrent requests
    logger.info("Testing projects...")
    projects = await fetch_all_paginated(api, api.get_projects)
    
    # Test repositories for each project with concurrent requests
    logger.info("Testing repositories...")
    repos = []
    for i in range(0, len(projects), MAX_CONCURRENT_REQUESTS):
        project_chunk = projects[i:i + MAX_CONCURRENT_REQUESTS]
        repo_tasks = []
        for project in project_chunk:
            repo_tasks.append(fetch_all_paginated(api, api.get_repositories, project["key"]))
        
        chunk_results = await asyncio.gather(*repo_tasks)
        for chunk in chunk_results:
            repos.extend(chunk)
    
    # Test PRs for each repository with concurrent requests
    logger.info("Testing pull requests...")
    prs = []
    for i in range(0, len(repos), MAX_CONCURRENT_REQUESTS):
        repo_chunk = repos[i:i + MAX_CONCURRENT_REQUESTS]
        pr_tasks = []
        for repo in repo_chunk:
            pr_tasks.append(fetch_all_paginated(api, api.get_pull_requests, repo["project"]["key"], repo["slug"]))
        
        chunk_results = await asyncio.gather(*pr_tasks)
        for chunk in chunk_results:
            prs.extend(chunk)
    
    end_time = datetime.now()
    duration = end_time - start_time
    
    logger.info(f"Test completed in {duration}")
    logger.info(f"Total users: {len(users)}")
    logger.info(f"Total projects: {len(projects)}")
    logger.info(f"Total repositories: {len(repos)}")
    logger.info(f"Total pull requests: {len(prs)}")
    
    # Verify counts
    assert len(users) == NUM_USERS, f"Expected {NUM_USERS} users, got {len(users)}"
    assert len(projects) == NUM_PROJECTS, f"Expected {NUM_PROJECTS} projects, got {len(projects)}"
    assert len(repos) == NUM_PROJECTS * REPOS_PER_PROJECT, f"Expected {NUM_PROJECTS * REPOS_PER_PROJECT} repositories, got {len(repos)}"
    assert len(prs) == NUM_PROJECTS * REPOS_PER_PROJECT * PRS_PER_REPO, f"Expected {NUM_PROJECTS * REPOS_PER_PROJECT * PRS_PER_REPO} pull requests, got {len(prs)}"
    
    await api.close()

if __name__ == "__main__":
    asyncio.run(test_performance()) 