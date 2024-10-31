# Ingesting Bitbucket Resources


## Overview

In this example, you will create blueprints for `bitbucketUser`, `bitbucketProject`, `bitbucketRepository` and `bitbucketPullrequest` that ingests all projects, repositories and pull requests from your Bitbucket account. Also, you will add some python script to make API calls to Bitbucket REST API and fetch data for your account. In addition to ingesting data via REST API, you will also configure webhooks to automatically update your entities in Port anytime an event occurs in your Bitbucket account. For this example, you will subscribe to `project` updates, `repository` updates events as well as `pull request` events.

## Getting started

Log in to your Port account and create the following blueprints:

### User blueprint
Create the project blueprint in Port [using this json file](./resources/user.json)

### Project blueprint
Create the project blueprint in Port [using this json file](./resources/project.json)

### Repository blueprint
Create the repository blueprint in Port [using this json file](./resources/repository.json)

### Pull request blueprint
Create the pull request blueprint in Port [using this json file](./resources/pullrequest.json)


### Running the python script

To ingest data from your Bitbucket account to Port, run the following commands: 

```bash
export PORT_CLIENT_ID=<ENTER CLIENT ID>
export PORT_CLIENT_SECRET=<ENTER CLIENT SECRET>
export BITBUCKET_USERNAME=<ENTER BITBUCKET USERNAME>
export BITBUCKET_PASSWORD=<ENTER BITBUCKET PASSWORD>
export BITBUCKET_HOST=<ENTER BITBUCKET HOST>
# optional
export BITBUCKET_PROJECTS_FILTER=<ENTER COMMA SEPARATED PROJECTS>
export WEBHOOK_SECRET=<ENTER WEBHOOK SECRET>
export PORT_API_URL=<ENTER PORT API URL>
export IS_VERSION_8_7_OR_OLDER=<True>

git clone https://github.com/port-labs/bitbucket-workspace-data.git

cd bitbucket-workspace-data

pip install -r ./requirements.txt

python app.py
```


> ### Port Webhook Configuration
> 
> This app will automatically set up a webhook that allows Bitbucket to send events to Port. To understand more about how Bitbucket sends event payloads via webhooks, you can refer to [this documentation](https://confluence.atlassian.com/bitbucketserver/event-payload-938025882.html).
> 
> Ensure that the Bitbucket credentials you use have `PROJECT_ADMIN` permissions to successfully configure the webhook. For more details on the necessary permissions and setup, see the [official Bitbucket documentation](https://developer.atlassian.com/server/bitbucket/rest/v910/api-group-project/#api-api-latest-projects-projectkey-webhooks-post).


The list of variables required to run this script are:
- `PORT_CLIENT_ID`
- `PORT_CLIENT_SECRET`
- `BITBUCKET_HOST` - BitBucket server host such as `http://localhost:7990`
- `BITBUCKET_USERNAME` - BitBucket username to use when accessing the BitBucket resources
- `BITBUCKET_PASSWORD` - BitBucket account password
- `BITBUCKET_PROJECTS_FILTER` - An optional comma separated list of BitBucket projects to filter. If not provided, all projects will be fetched.
- `WEBHOOK_SECRET` - An optional secret to use when creating a webhook in Port. If not provided, `bitbucket_webhook_secret` will be used.
- `PORT_API_URL` - If not provided, the variable defaults to the EU Port API. For US organizations use `https://api.us.getport.io/v1` instead.
- `IS_VERSION_8_7_OR_OLDER` - An optional variable that specifies whether the Bitbucket version is older than 8.7. This setting determines if webhooks should be created at the repository level (for older versions <=8.7) or at the project level (for newer versions >=8.8).
- `GET_MERGED_PRS` - An optional variable that specifies whether the Bitbucket PR already merged should be ingested. If not provided, the variable defaults to `False`.

Done! any change that happens to your project, repository or pull requests in Bitbucket will trigger a webhook event to the webhook URL provided by Port. Port will parse the events according to the mapping and update the catalog entities accordingly.
