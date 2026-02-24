import json
from aws_cdk import (
    aws_events,
    aws_events_targets, aws_lambda_event_sources as event_sources, 
    Stack, aws_lambda,
    aws_ssm as ssm,
    aws_iam,
    aws_secretsmanager as sm,
    SecretValue,
    Duration
)
from constructs import Construct

from lambdas import Lambdas
from databases import Tables
import config


class SocialMediaToConnectStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.create_resources()
        self.set_up_env_vars()
        self.create_parameters()
        self.set_up_permissions()
        

    def create_resources(self):
        self.lambda_functions = Lambdas(self, "L")
        self.tables = Tables(self, "T")
        self.rule = aws_events.Rule(
            self,
            "every15m",
            schedule=aws_events.Schedule.cron(minute="0,15,30,45"),
            # targets=[aws_events_targets.LambdaFunction(self.lambda_functions.get_changes)],  # type: ignore
        )

        self.lambda_functions.changes_processor.add_event_source(
            event_sources.DynamoEventSource(
                self.tables.raw_changes,
                starting_position=aws_lambda.StartingPosition.TRIM_HORIZON,
                batch_size=1,
                retry_attempts=2,
            )
        )

        self.lambda_functions.execute_actions.add_event_source(
            event_sources.DynamoEventSource(
                self.tables.processed_changes,
                starting_position=aws_lambda.StartingPosition.TRIM_HORIZON,
                batch_size=1,
                retry_attempts=2,
            )
        )
    
        self.secret = sm.Secret(
            self,
            "wallsSecret",
            secret_name="wallsio-secret",
            secret_string_value=SecretValue("REPLACE_WITH_REAL_SECRET"),
        )

    def create_ssm_parameter(self, parameter_name: str, string_value: str):
        return ssm.StringParameter(
            self,
            parameter_name.replace("/", "").replace("_", "").title(),
            parameter_name=parameter_name,
            string_value=string_value,
        )

    def create_parameters(self):
        self.api_config_ssm = self.create_ssm_parameter( config.API_CONFIG_PARAM_NAME, json.dumps(config.API_CONFIG_CONTENT))
        self.process_config_ssm = self.create_ssm_parameter( config.PROCESS_CONFIG_PARAM_NAME, json.dumps(config.PROCESS_CONFIG_CONTENT))
        self.connect_config_ssm = self.create_ssm_parameter( config.CONNECT_CONFIG_PARAM_NAME, json.dumps(config.CONNECT_CONFIG_CONTENT))

    def set_up_permissions(self):
        self.tables.raw_changes.grant_read_write_data(self.lambda_functions.get_changes)
        self.tables.raw_changes.grant_read_data(self.lambda_functions.changes_processor)
        self.tables.processed_changes.grant_read_write_data( self.lambda_functions.changes_processor)
        self.tables.processed_changes.grant_read_write_data( self.lambda_functions.execute_actions)

        self.tables.raw_changes.grant_read_data(self.lambda_functions.execute_actions)

        self.api_config_ssm.grant_read(self.lambda_functions.get_changes)
        self.connect_config_ssm.grant_read(self.lambda_functions.execute_actions)
        self.process_config_ssm.grant_read(self.lambda_functions.changes_processor)

        self.secret.grant_read(self.lambda_functions.get_changes)
        self.lambda_functions.changes_processor.add_to_role_policy( aws_iam.PolicyStatement(actions=["bedrock:Invoke*"], resources=["*"]))
        self.lambda_functions.execute_actions.add_to_role_policy( aws_iam.PolicyStatement(actions=["connect:StartTaskContact"], resources=["*"]))

    def set_up_env_vars(self):
        self.lambda_functions.get_changes.add_environment( key="TABLE_NAME", value=self.tables.raw_changes.table_arn)
        self.lambda_functions.get_changes.add_environment( key="SECRET_ARN", value=self.secret.secret_arn)
        self.lambda_functions.get_changes.add_environment( key="API_CONFIG_PARAM_NAME", value=config.API_CONFIG_PARAM_NAME)
        self.lambda_functions.changes_processor.add_environment( key="PROCESS_CONFIG_PARAM_NAME", value=config.PROCESS_CONFIG_PARAM_NAME)
        self.lambda_functions.changes_processor.add_environment( key="TABLE_NAME", value=self.tables.processed_changes.table_arn)
        self.lambda_functions.execute_actions.add_environment( key="TABLE_NAME", value=self.tables.processed_changes.table_arn)

        self.lambda_functions.execute_actions.add_environment( key="CONNECT_CONFIG_PARAM_NAME", value=config.CONNECT_CONFIG_PARAM_NAME)

