
from aws_cdk import aws_apigateway as apg
from constructs import Construct

from lambdas import Lambdas

class WebhookApi(Construct):

    def __init__(self, scope: Construct, construct_id: str,lambdas:Lambdas, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        self.api = apg.RestApi(self, "meta")
        self.api.root.add_cors_preflight(allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

        self.messages = self.api.root.add_resource("messages",default_integration=apg.LambdaIntegration(lambdas.messages_in, allow_test_invoke=False)) # type: ignore
        self.messages.add_method("GET") 
        self.messages.add_method("POST")



