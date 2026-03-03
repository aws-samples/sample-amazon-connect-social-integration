from aws_cdk import RemovalPolicy, aws_dynamodb as ddb
from constructs import Construct

TABLE_CONFIG = dict (removal_policy=RemovalPolicy.DESTROY, billing_mode= ddb.BillingMode.PAY_PER_REQUEST)


class Tables(Construct):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.active_connections = ddb.Table(
            self, "ActiveChats", 
            partition_key=ddb.Attribute(name="contactId", type=ddb.AttributeType.STRING),
            **TABLE_CONFIG) # type: ignore

        self.active_connections.add_global_secondary_index(
            index_name='byUser',
            partition_key=ddb.Attribute(name="userId", type=ddb.AttributeType.STRING),
        )

        self.instagram_users = ddb.Table(
            self, "InstagramUsers",
            partition_key=ddb.Attribute(name="id", type=ddb.AttributeType.STRING),
            time_to_live_attribute='timestamp',
            **TABLE_CONFIG) # type: ignore
