import os
import logging
from typing import Dict, Any
from config_service import get_ssm_parameter, get_secret_value
from api_client import call_api, extract_data_entries
from table_service import TableService

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """
    Lambda handler to fetch changes from external API.
    
    Environment Variables:
        TABLE_NAME: DynamoDB table name for storing changes
        SECRET_ARN: ARN of the secret containing the API access token
        API_CONFIG_PARAM_NAME: SSM parameter name containing API configuration
    """
    try:
        # Read environment variables
        table_name = os.environ.get('TABLE_NAME')
        secret_arn = os.environ.get('SECRET_ARN')
        api_config_param_name = os.environ.get('API_CONFIG_PARAM_NAME')
        
        # Validate environment variables
        if not table_name:
            raise ValueError("TABLE_NAME environment variable is required")
        if not secret_arn:
            raise ValueError("SECRET_ARN environment variable is required")
        if not api_config_param_name:
            raise ValueError("API_CONFIG_PARAM_NAME environment variable is required")
        
        logger.info(f"Starting lambda execution with table: {table_name}")
        
        # Get API configuration from SSM Parameter Store
        api_config = get_ssm_parameter(api_config_param_name)
        logger.info("Successfully retrieved API configuration from SSM")
        
        # Get access token from Secrets Manager
        access_token = get_secret_value(secret_arn)
        logger.info("Successfully retrieved access token from Secrets Manager")
        
        # Replace access token in API config
        if 'params' not in api_config:
            api_config['params'] = {}
        api_config['params']['access_token'] = access_token
        
        # Call the external API
        api_response = call_api(api_config)
        logger.info(f"API call successful. Response contains {len(api_response.get('data', []))} items")
        
        # Extract and validate data entries
        valid_posts = extract_data_entries(api_response)
        
        # Initialize table service
        table_service = TableService(table_name)
        
        # Write each valid post to DynamoDB
        success_count = 0
        error_count = 0
        
        for post in valid_posts:
            try:
                table_service.write_post_to_dynamodb(post)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to write post {post.get('id')}: {str(e)}")
                error_count += 1
        
        logger.info(f"Processed {len(valid_posts)} posts: {success_count} successful, {error_count} failed")
        
        # Return the response
        return {
            'statusCode': 200,
            'body': {
                'message': 'Processing complete',
                'total_posts': len(valid_posts),
                'successful_writes': success_count,
                'failed_writes': error_count
            }
        }
        
    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return {
            'statusCode': 400,
            'error': str(e)
        }
        
    except Exception as e:
        logger.error(f"Lambda execution failed: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e)
        }
