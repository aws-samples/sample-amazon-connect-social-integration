import json
from aws_cdk import (
    Stack,
    SecretValue,
    aws_iam as iam,
    aws_ssm as ssm,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

from lambdas import Lambdas
from databases import Tables
from apis import WebhookApi
from topic import Topic

import config

class InstagramDmConnectChatStack(Stack):


    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.create_resources()
        self.set_up_env_vars()
        self.create_parameters()
        self.set_up_permissions()

    def create_resources(self):

        self.secrets = secretsmanager.Secret(
            self,
            "Secret",
            secret_name=config.SECRET_NAME,
            secret_string_value=SecretValue("FROM_INSTAGRAM"),
        )

        self.lambda_functions = Lambdas(self, "L")
        self.tables = Tables(self, "T")
        self.webhook = WebhookApi(self, "API", lambdas=self.lambda_functions)
        self.topic_messages_out = Topic(
            self,
            "MsgAout",
            name="messages_out",
            lambda_function=self.lambda_functions.messages_out,
        )

    def set_up_env_vars(self):
        for l in [
            self.lambda_functions.messages_in,
            self.lambda_functions.messages_out,
        ]:
            l.add_environment("TABLE_NAME", self.tables.active_connections.table_name)
            l.add_environment("SECRET_ARN", self.secrets.secret_arn)
            l.add_environment("CONFIG_PARAM_NAME", config.INSTAGRAM_CONFIG_PARAM_NAME)
            l.add_environment("META_API_VERSION", config.META_API_VERSION)
        self.lambda_functions.messages_in.add_environment(
            "TOPIC_ARN", self.topic_messages_out.topic.topic_arn
        )
        self.lambda_functions.messages_in.add_environment(
            "USERS_TABLE_NAME", self.tables.instagram_users.table_name
        )

    def create_parameters(self):
        self.config_parameters = self.create_ssm_parameter(
            config.INSTAGRAM_CONFIG_PARAM_NAME,
            json.dumps(config.INSTAGRAM_CONFIG_PARAM_CONTENT),
        )
        self.create_ssm_parameter(
            config.INSTAGRAM_WEBHOOK_PARAM_NAME,
            self.webhook.api.url_for_path("/messages"),
        )

    def create_ssm_parameter(self, parameter_name: str, string_value: str):
        return ssm.StringParameter(
            self,
            parameter_name.replace("/", "").replace("_", "").title(),
            parameter_name=parameter_name,
            string_value=string_value,
        )

    def set_up_permissions(self):
        self.tables.active_connections.grant_read_write_data(
            self.lambda_functions.messages_in
        )
        self.tables.active_connections.grant_read_write_data(
            self.lambda_functions.messages_out
        )

        self.tables.instagram_users.grant_read_write_data(
            self.lambda_functions.messages_in
        )

        self.secrets.grant_read(self.lambda_functions.messages_out)
        self.secrets.grant_read(self.lambda_functions.messages_in)
        self.config_parameters.grant_read(self.lambda_functions.messages_in)

        self.lambda_functions.messages_in.add_to_role_policy(
            iam.PolicyStatement(
                actions=["connect:StartChatContact", "connect:StartContactStreaming"],
                resources=[f"arn:aws:connect:*:{self.account}:instance/*"],
            )
        )
