import json
import logging
from typing import Dict, Any, List
from urllib import request, error, parse

logger = logging.getLogger()


def call_api(api_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call the external API with the provided configuration.
    
    Args:
        api_config: Dictionary containing url, method, headers, params, and body
        
    Returns:
        Dict containing the API response
        
    Raises:
        ValueError: If the HTTP method is not supported
        Exception: If the API call fails or returns invalid JSON
    """
    url = api_config.get('url')
    if not url:
        raise ValueError("API configuration must include 'url'")
    
    method = api_config.get('method', 'GET').upper()
    headers = api_config.get('headers', {})
    params = api_config.get('params', {})
    body = api_config.get('body', {})
    
    # Filter out null/empty parameters for cleaner API calls
    filtered_params = {}
    for key, value in params.items():
        if value is not None and value != "" and value != []:
            filtered_params[key] = value
    
    # Log the filtered parameters (without access token for security)
    log_params = {k: v for k, v in filtered_params.items() if k != 'access_token'}
    if 'access_token' in filtered_params:
        log_params['access_token'] = '[REDACTED]'  # nosec B105 - not a real password, just a log placeholder 
    logger.info(f"API call parameters: {log_params}")
    
    # Set default headers
    if 'Content-Type' not in headers and method in ['POST', 'PUT', 'PATCH']:
        headers['Content-Type'] = 'application/json'
    
    try:
        # Build the full URL with query parameters for GET requests
        if method == 'GET' and filtered_params:
            query_string = parse.urlencode(filtered_params)
            full_url = f"{url}?{query_string}"
        else:
            full_url = url
        
        # Prepare request data for POST/PUT/PATCH
        request_data = None
        if method in ['POST', 'PUT', 'PATCH']:
            if body:
                request_data = json.dumps(body).encode('utf-8')
            # Add params to URL for non-GET methods too if needed
            if filtered_params:
                query_string = parse.urlencode(filtered_params)
                full_url = f"{url}?{query_string}"
        
        # Validate URL scheme to prevent file:/ or custom scheme access
        parsed = parse.urlparse(full_url)
        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

        # Create request object
        req = request.Request(
            full_url,
            data=request_data,
            headers=headers,
            method=method
        )
        
        logger.info(f"Making {method} request to {url}")
        
        # Make the request - URL scheme already validated above
        with request.urlopen(req, timeout=30) as response:  # nosec B310 # nosemgrep: dynamic-urllib-use-detected
            response_data = response.read().decode('utf-8')
            return json.loads(response_data)
            
    except error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else 'No error body'
        logger.error(f"HTTP Error {e.code}: {e.reason}. Body: {error_body}")
        raise Exception(f"API call failed with HTTP {e.code}: {e.reason}")
        
    except error.URLError as e:
        logger.error(f"URL Error: {str(e.reason)}")
        raise Exception(f"API call failed: {str(e.reason)}")
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse API response as JSON: {str(e)}")
        raise Exception(f"Invalid JSON response from API: {str(e)}")
        
    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error during API call: {str(e)}")
        raise Exception(f"API call failed: {str(e)}")


def extract_data_entries(api_response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract data entries from Walls.io API response.
    
    Args:
        api_response: The API response dictionary
        
    Returns:
        List of valid post dictionaries
    """
    # Check if response has the expected Walls.io structure
    if api_response.get('status') != 'success':
        logger.warning(f"API response status is not 'success': {api_response.get('status')}")
    
    # Log response metadata
    count = api_response.get('count', 0)
    current_time = api_response.get('current_time')
    logger.info(f"API response: {count} posts, timestamp: {current_time}")
    
    # Extract data array from Walls.io response
    data = api_response.get('data', [])
    if not isinstance(data, list):
        logger.warning("Expected 'data' to be a list, converting to list")
        data = [data] if data else []
    
    # Validate that we have posts with required fields
    valid_posts = []
    for i, post in enumerate(data):
        if not isinstance(post, dict):
            logger.warning(f"Post {i} is not a dictionary, skipping")
            continue
        
        # Check for required fields
        if 'id' not in post:
            logger.warning(f"Post {i} missing 'id' field, skipping")
            continue
        
        valid_posts.append(post)
    
    logger.info(f"Extracted {len(valid_posts)} valid posts from {len(data)} total entries")
    return valid_posts
