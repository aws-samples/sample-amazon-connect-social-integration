# Connect Social CX - AWS CDK Deployment

## Architecture

![Architecture Diagram](./connect-social-cx.svg)

This project deploys an automated social media monitoring and customer service integration system using AWS CDK. The architecture processes social media posts, analyzes them using Amazon Bedrock LLM and Strands Framework, and creates tasks in Amazon Connect for customer service agents.

## Overview

The system consists of three Lambda functions orchestrated through DynamoDB Streams:

1. **Get Changes Lambda**: Polls the Walls.io API every 15 minutes to fetch new social media posts
2. **Changes Processor Lambda**: Analyzes posts using Amazon Bedrock to determine priority and required actions
3. **Execute Actions Lambda**: Creates tasks in Amazon Connect based on the analysis

This project is set up as a standard Python CDK project. The initialization process creates a virtualenv within this project, stored under the `.venv` directory.

To manually create a virtualenv on MacOS and Linux:

```
python3 -m venv .venv
```

After the init process completes and the virtualenv is created, you can use the following
step to activate your virtualenv.

```
source .venv/bin/activate # % .venv\Scripts\activate.bat for windows
```

Once the virtualenv is activated, you can install the required dependencies.

```bash
pip install -r requirements.txt
```

## Prerequisites

Before deploying, ensure you have:

1. **AWS CLI** configured with appropriate credentials
2. **AWS CDK** installed globally (`npm install -g aws-cdk`)
3. **Python 3.10+** installed
4. **Walls.io API access token** (from your Walls.io account)
5. **Amazon Connect instance** set up in your AWS account
6. **Amazon Bedrock** access enabled in your AWS region (for Claude Haiku model)

## Deployment Process

### Step 1: Bootstrap CDK (First-time only)

If this is your first time using CDK in your AWS account/region, you need to bootstrap it. This creates the necessary S3 buckets and IAM roles for CDK deployments:

```bash
$ cdk bootstrap aws://ACCOUNT-NUMBER/REGION
```

Example:
```bash
$ cdk bootstrap aws://123456789012/us-east-1
```

**Note**: Bootstrapping only needs to be done once per account/region combination.

### Step 2: Synthesize CloudFormation Template

Verify your CDK code by synthesizing the CloudFormation template:

```bash
$ cdk synth
```

This generates the CloudFormation template in the `cdk.out` directory.

### Step 3: Deploy the Stack

Deploy the stack to your AWS account:

```bash
$ cdk deploy
```

Review the changes and confirm when prompted. The deployment will create:
- 3 Lambda functions, 1 lamnda layer (with Strands sdk)
- 2 DynamoDB tables (raw_changes and processed_changes)
- EventBridge rule (scheduled every 15 minutes)
- SSM Parameters for configuration
- Secrets Manager secret for Walls.io API token
- IAM roles and policies

## Post-Deployment Configuration

After successful deployment, you must update several configurations:

### 1. Update Walls.io Secret

Go to [Secrets Manager Console](console.aws.amazon.com/secretsmanager/secret?name=wallsio-secret) and replace the placeholder secret with your actual Walls.io API access token. Only the first lambda has permissions to read this secret.


### 2. Update Amazon Connect Configuration

Update the `/config/connect` SSM parameter in [AWS Systems Manaer Console](console.aws.amazon.com/systems-manager/parameters) with your `instance_id` and `contact_flow_id`


**To find your Amazon Connect IDs:**
- **Instance ID**: Go to Amazon Connect console → Select your instance → The instance ID is in the instance ARN
- **Contact Flow ID**: Go to your Connect instance → Routing → Contact flows → Select your flow → The ID is in the Details tab.


## Testing the Deployment

### Test Individual Lambda Functions 

You can test `SOCIAL-LISTENING-TO-CONNECT-L1GetChanges...` lambda function to see posts pulled from Walls.io.

### Monitor DynamoDB Tables

- Check if posts are being stored in raw_changes table
- Verify processed_changes table gets populated by the second lambda 
- Verify llm_analysis results in processed_changes table
- Verify new tasks appear in your Amazon Connect instance

## Configuration Files

The system uses three main configuration parameters stored in SSM Parameter Store:

- **/config/api**: Walls.io API configuration and authentication
- **/config/process**: Bedrock AI model configuration and analysis prompt
- **/config/connect**: Amazon Connect instance and contact flow settings

You can update these configurations at any time without redeploying the stack.

## Useful CDK Commands

 * `cdk ls`          list all stacks in the app
 * `cdk synth`       emits the synthesized CloudFormation template
 * `cdk deploy`      deploy this stack to your default AWS account/region
 * `cdk diff`        compare deployed stack with current state
 * `cdk destroy`     remove all resources created by this stack
 * `cdk docs`        open CDK documentation

## Troubleshooting

### Lambda Function Errors

Check CloudWatch Logs for detailed error messages. Common issues:
- Invalid Walls.io access token
- Amazon Connect instance ID or contact flow ID incorrect



## Clean Up

To remove all resources created by this stack:

```bash
$ cdk destroy
```

