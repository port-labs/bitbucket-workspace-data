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
export BITBUCKET_HOST=<ENTER BITBUCKER HOST>
# optional
export BITBUCKET_PROJECTS_FILTER=<ENTER COMMA SEPARATED PROJECTS>

git clone https://github.com/port-labs/bitbucket-workspace-data.git

cd bitbucket-workspace-data

pip install -r ./requirements.txt

python app.py
```

The list of variables required to run this script are:
- `PORT_CLIENT_ID`
- `PORT_CLIENT_SECRET`
- `BITBUCKET_HOST` - BitBucket server host such as `http://localhost:7990`
- `BITBUCKET_USERNAME` - BitBucket username to use when accessing the BitBucket resources
- `BITBUCKET_PASSWORD` - BitBucket account password
- `BITBUCKET_PROJECTS_FILTER` - An optional comma separated list of BitBucket projects to filter. If not provided, all projects will be fetched.


## Port Webhook Configuration

Webhooks are a great way to receive updates from third party platforms, and in this case, Bitbucket. To [create a bitbucket webhook](https://confluence.atlassian.com/bitbucketserver/manage-webhooks-938025878.html), you will first need to generate a webhook URL from Port.

Follow the following steps to create a webhook:
1. Navigate to the **Builder** section in Port and click **Data source**;
2. Under **Webhook** tab, click **Custom integration**;
3. In the **basic details** tab, you will be asked to provide information about your webhook such as the `title`, `identifier` `description`, and `icon`;
4. In the **integration configuration** tab, copy and paste the [webhook configuration file](./resources/webhook_configuration.json) into the **Map the data from the external system into Port** form;
5. Take note of the webhook `URL` provided by Port on this page. You will need this `URL` when subscribing to events in Bitbucket;

6. Test the webhook configuration mapping and click on **Save**;
7. Under the **Advanced settings** tab, you will authenticate the payload from Bitbucket. Enter the following details:
    1. `Secret` - enter your webhook secret. You will need this value when setting up the webhook trigger in Bitbucket;
    2. `Signature Header Name` - enter `X-Hub-Signature`;
    3. `Signature Algorithm` - select `sha256` from the dropdown;
    4. `Signature Prefix` - enter `sha256=`.


## Subscribing to Bitbucket webhook
1. From your Bitbucket account, open the project where you want to add the webhook;
2. Click **Project settings** or the gear icon on the left sidebar;
3. On the Workflow section, select **Webhooks** on the left sidebar;
4. Click the **Add webhook** button to create a webhook for the repository; 
5. Input the following details:
    1. `Title` - use a meaningful name such as Port Webhook;
    2. `URL` - enter the value of the webhook `URL` you received after creating the webhook configuration in Port;
    3. `Secret` - enter the value of the secret you provided when configuring the webhook in Port;
    4.  `Triggers` - Under **Project** select `modified` Under **Repository** select `modified`. Under **Pull request** select any event based on your case;
6. Click **Save** to save the webhook;

Follow [this documentation](https://confluence.atlassian.com/bitbucketserver/event-payload-938025882.html) to learn more about webhook events payload in Bitbucket.

Done! any change that happens to your project, repository or pull requests in Bitbucket will trigger a webhook event to the webhook URL provided by Port. Port will parse the events according to the mapping and update the catalog entities accordingly.
