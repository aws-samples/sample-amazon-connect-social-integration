import json
import logging
import boto3
from typing import Dict, Any

logger = logging.getLogger()


def get_ssm_parameter(parameter_name: str) -> Dict[str, Any]:
    """
    Retrieve and parse SSM parameter value.
    
    Args:
        parameter_name: Name of the SSM parameter
        
    Returns:
        Dict containing the parsed JSON configuration
        
    Raises:
        ValueError: If parameter name is empty or parameter value is invalid JSON
        Exception: If SSM parameter retrieval fails
    """
    if not parameter_name:
        raise ValueError("Parameter name cannot be empty")
    
    try:
        ssm_client = boto3.client('ssm')
        logger.info(f"Retrieving SSM parameter: {parameter_name}")
        
        response = ssm_client.get_parameter(
            Name=parameter_name,
            WithDecryption=True
        )
        
        parameter_value = response['Parameter']['Value']
        
        # Parse JSON
        try:
            config = json.loads(parameter_value)
            logger.info("Successfully parsed SSM parameter")
            return config
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in SSM parameter {parameter_name}: {str(e)}")
            raise ValueError(f"SSM parameter contains invalid JSON: {str(e)}")
            
    except ssm_client.exceptions.ParameterNotFound:
        logger.error(f"SSM parameter not found: {parameter_name}")
        raise Exception(f"SSM parameter not found: {parameter_name}")
        
    except Exception as e:
        logger.error(f"Failed to retrieve SSM parameter {parameter_name}: {str(e)}")
        raise Exception(f"Failed to retrieve SSM parameter: {str(e)}")


def get_secret_value(secret_arn: str) -> Dict[str, str]:
    """
    Retrieve X API credentials from AWS Secrets Manager.
    
    Unlike the Instagram/Facebook integration which extracts a single token,
    this returns the full JSON dict containing all four OAuth 1.0a credentials
    needed for X API authentication.
    
    Args:
        secret_arn: ARN of the secret
        
    Returns:
        Dict containing consumer_key, consumer_secret, access_token, access_token_secret
        
    Raises:
        ValueError: If secret ARN is empty
        Exception: If secret retrieval fails
    """
    if not secret_arn:
        raise ValueError("Secret ARN cannot be empty")
    
    try:
        secrets_client = boto3.client('secretsmanager')
        logger.info(f"Retrieving secret: {secret_arn}")
        
        response = secrets_client.get_secret_value(SecretId=secret_arn)
        
        if 'SecretString' in response:
            secret = response['SecretString']
            secret_dict = json.loads(secret)
            logger.info("Successfully retrieved X API credentials")
            return secret_dict
        else:
            # Binary secret
            secret = response['SecretBinary'].decode('utf-8')
            secret_dict = json.loads(secret)
            logger.info("Successfully retrieved X API credentials from binary secret")
            return secret_dict
            
    except secrets_client.exceptions.ResourceNotFoundException:
        logger.error("Secret not found")
        raise Exception("Secret not found")
        
    except Exception as e:
        logger.error(f"Failed to retrieve secret: {type(e).__name__}")
        raise Exception("Failed to retrieve secret")
