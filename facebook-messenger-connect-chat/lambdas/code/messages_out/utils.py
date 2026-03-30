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

def validate_healthcheck(event, WHATS_VERIFICATION_TOKEN ):
    if('queryStringParameters' in event and 'hub.challenge' in event['queryStringParameters']):
        print(event['queryStringParameters'])
        print("Token challenge")
        if(event['queryStringParameters']['hub.verify_token'] == WHATS_VERIFICATION_TOKEN):
            print("Token verified")
            print(event['queryStringParameters']['hub.challenge'])
            response = event['queryStringParameters']['hub.challenge']
        else:
            response = ''
    else:
        print("Not challenge related")
        response = '<html><head></head><body> No key, no fun!</body></html>'
    return response
