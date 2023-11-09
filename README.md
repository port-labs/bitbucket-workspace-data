# Ingesting Bitbucket Resources


## Getting started

In this example, you will create blueprints for `bitbucketProject`, `bitbucketRepository` and `bitbucketPullrequest` that ingests all projects, repositories and pull requests from your Bitbucket cloud account. Also, you will add some python script to make API calls to Bitbucket REST API and fetch data for your account. 

## Project blueprint
Create the project blueprint in Port [using this json file](./resources/project.json)

## Repository blueprint
Create the repository blueprint in Port [using this json file](./resources/repository.json)

## Pull request blueprint
Create the pull request blueprint in Port [using this json file](./resources/pullrequest.json)


### Variables

The list of the required variables to run this script are:
- `PORT_CLIENT_ID`
- `PORT_CLIENT_SECRET`
- `BITBUCKET_USERNAME`
- `BITBUCKET_APP_PASSWORD`


Follow the documentation on how to [create a bitbucket app password](https://support.atlassian.com/bitbucket-cloud/docs/create-an-app-password/). 
