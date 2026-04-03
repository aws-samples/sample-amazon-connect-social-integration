import hmac
import hashlib
import base64


def build_response(status_code, json_content):
        return {
        'statusCode': status_code,
        "headers": {
            "Content-Type": "text/html;charset=UTF-8",
            "charset": "UTF-8",
            "Access-Control-Allow-Origin": "*"
        },
        'body': json_content
    }


def compute_crc_response(crc_token, consumer_secret):
    """
    Compute the CRC response for X webhook validation.
    
    X sends a GET request with a crc_token query parameter.
    We must respond with HMAC-SHA256(consumer_secret, crc_token) base64-encoded.
    
    Args:
        crc_token: The CRC token string from X's GET request
        consumer_secret: The Consumer Secret from X API credentials
        
    Returns:
        Dict with response_token in format {"response_token": "sha256=<base64_hash>"}
    """
    digest = hmac.new(
        consumer_secret.encode('utf-8'),
        crc_token.encode('utf-8'),
        hashlib.sha256
    ).digest()
    
    encoded_hash = base64.b64encode(digest).decode('utf-8')
    
    return {"response_token": f"sha256={encoded_hash}"}
