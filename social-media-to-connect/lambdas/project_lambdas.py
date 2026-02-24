from aws_cdk import Duration, aws_lambda
from constructs import Construct
from layers import Strands


LAMBDA_CONFIG = dict(
    timeout=Duration.seconds(60),
    memory_size=256,
    runtime=aws_lambda.Runtime.PYTHON_3_13,
    architecture=aws_lambda.Architecture.ARM_64,
    tracing=aws_lambda.Tracing.ACTIVE,
)



class Lambdas(Construct):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        strands_layer = Strands(self, "StrandsLayer")


        # ======================================================================
        # 01 Get latest 1000 changes from Social Service (Pull)
        # ======================================================================
        self.get_changes = aws_lambda.Function( self,"1-GetChanges",
            code=aws_lambda.Code.from_asset("./lambdas/code/1_get_changes/"),
            handler="lambda_function.lambda_handler", **LAMBDA_CONFIG) # type: ignore
        
        # ======================================================================
        # 02 Process Changes (Event)
        # ======================================================================
        self.changes_processor = aws_lambda.Function( self,"2-Changes-Processor",
            code=aws_lambda.Code.from_asset("./lambdas/code/2_changes_processor/"),
            layers = [strands_layer.layer],
            handler="lambda_function.lambda_handler", **LAMBDA_CONFIG) # type: ignore
        
        # ======================================================================
        # 03 actions to be executed 
        # ======================================================================
        self.execute_actions = aws_lambda.Function( self,"3-Actions",
            code=aws_lambda.Code.from_asset("./lambdas/code/3_actions/"),
            handler="lambda_function.lambda_handler", **LAMBDA_CONFIG) # type: ignore
        

    def get_all_functions(self):
        return [self.get_changes,self.changes_processor, self.execute_actions]