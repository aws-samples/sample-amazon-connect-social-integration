import boto3
import time
import logging
from typing import Dict, Any
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from botocore.config import Config

import os

logger = logging.getLogger()


class TableService:
    def __init__(self, table_name=os.environ.get("TABLE_NAME")) -> None:

        self.config = Config(retries={"max_attempts": 10, "mode": "adaptive"})
        self.dynamodb = boto3.resource("dynamodb", config=self.config)
        self.table = self.dynamodb.Table(table_name) # type: ignore

    def update(self, key, details):
        try:
            attr_names, attr_values, update_expression = self.build_update_expression(
                details
            )

            table_update = self.table.update_item(
                Key=key,
                UpdateExpression=update_expression,
                ExpressionAttributeNames=attr_names,
                ExpressionAttributeValues=attr_values,
                ReturnValues="UPDATED_NEW",
            )

        except Exception as e:
            print(e)
        else:
            return table_update

    def put_if_not_exists(self, job):
        try:
            response = self.table.put_item(
                Item=job,
                ConditionExpression="attribute_not_exists(id)",
                ReturnValues="NONE",
            )
            # print ("put item:", response)
            return {"status": "inserted", "job": job}
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return {"status": "already_exists", "job": job}
            else:
                raise e

    def get_item(self, key):
        try:
            response = self.table.get_item(Key=key)
            return response.get('Item')
        except ClientError as e:
            print(e)
            return None

    def query_by_partition_key(self, partition_key_name, partition_key_value, attributes=None):
        try:
            items = []
            last_evaluated_key = None
            
            while True:
                query_params = {
                    'KeyConditionExpression': Key(partition_key_name).eq(partition_key_value)
                }
                
                if attributes:
                    query_params['ProjectionExpression'] = ','.join(attributes) # type: ignore
                    
                if last_evaluated_key:
                    query_params['ExclusiveStartKey'] = last_evaluated_key
                    
                response = self.table.query(**query_params)
                
                items.extend(response.get('Items', []))
                last_evaluated_key = response.get('LastEvaluatedKey')
                
                if not last_evaluated_key:
                    break
                    
            return items
        except ClientError as e:
            print(e)
            return []

    def scan(self, attributes=None, filter_expression=None):
        try:
            items = []
            last_evaluated_key = None
            
            while True:
                scan_params = {}
                
                if attributes:
                    scan_params['ProjectionExpression'] = ','.join(attributes) # type: ignore
                    
                if filter_expression:
                    scan_params['FilterExpression'] = filter_expression
                    
                if last_evaluated_key:
                    scan_params['ExclusiveStartKey'] = last_evaluated_key
                    
                response = self.table.scan(**scan_params)
                
                items.extend(response.get('Items', []))
                last_evaluated_key = response.get('LastEvaluatedKey')
                
                if not last_evaluated_key:
                    break
                    
            return items
        except ClientError as e:
            print(e)
            return []

    def build_update_expression(self, to_update):
        attr_names = {}
        attr_values = {}
        update_expression_list = []
        for i, (key, val) in enumerate(to_update.items()):
            attr_names[f"#item{i}"] = key
            attr_values[f":val{i}"] = val

        for par in zip(attr_names.keys(), attr_values.keys()):
            update_expression_list.append(f"{par[0]} = {par[1]}")
        return attr_names, attr_values, f"SET {', '.join(update_expression_list)}"


    def write_post_to_dynamodb(self, post: Dict[str, Any]) -> None:
        """
        Write a social media post to DynamoDB table.
        Optimized to only include attributes defined in raw_changes table.
        
        Args:
            post: Dictionary containing post data from API
        """
        # Extract required fields for primary key
        post_id = str(post.get('id', ''))
        created_timestamp = post.get('created_timestamp')
        
        if not post_id:
            raise ValueError("Post missing required 'id' field")
        if not created_timestamp:
            raise ValueError("Post missing required 'id' field")
        
        # Debug logging
        logger.info(f"Processing post {post_id}: created_timestamp={created_timestamp}, type={type(created_timestamp)}")
        source_id = str(post.get('source', {}).get('id', '')) if isinstance(post.get('source'), dict) else ''

        post["source_id"] = source_id
        
        # Write to DynamoDB
        try:
            self.table.put_item(Item=post)
            logger.info(f"Successfully wrote post {post_id} to DynamoDB")
        except ClientError as e:
            logger.error(f"DynamoDB write failed for post {post_id}: {str(e)}")
            raise Exception(f"Failed to write post {post_id} to DynamoDB: {str(e)}")
