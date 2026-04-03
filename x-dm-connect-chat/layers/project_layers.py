from constructs import Construct

from aws_cdk import aws_lambda as _lambda




class Tweepy(Construct):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.layer = _lambda.LayerVersion(
            self, "Strands", code=_lambda.Code.from_asset("./layers/tweepy.zip"),
            compatible_runtimes = [_lambda.Runtime.PYTHON_3_12, _lambda.Runtime.PYTHON_3_13, _lambda.Runtime.PYTHON_3_14], 
            description = 'tweepy')
        