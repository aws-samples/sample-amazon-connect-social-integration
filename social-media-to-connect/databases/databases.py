from aws_cdk import RemovalPolicy, aws_dynamodb as ddb
from constructs import Construct


TABLE_CONFIG = dict( removal_policy=RemovalPolicy.DESTROY, billing_mode=ddb.BillingMode.PAY_PER_REQUEST)


class Tables(Construct):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.raw_changes = ddb.Table(
            self,
            "RaWChanges",
            partition_key=ddb.Attribute(name="id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="created_timestamp", type=ddb.AttributeType.NUMBER),
            stream=ddb.StreamViewType.NEW_IMAGE,
            time_to_live_attribute='ttl',
            **TABLE_CONFIG # type: ignore
        )

        self.processed_changes = ddb.Table(
            self,
            "ProcessedChange",
            partition_key=ddb.Attribute(name="id", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="created_timestamp", type=ddb.AttributeType.NUMBER),
            stream=ddb.StreamViewType.NEW_IMAGE,
            time_to_live_attribute='ttl',
            **TABLE_CONFIG # type: ignore
        )