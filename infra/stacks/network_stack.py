from aws_cdk import Stack, Tags
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, env_config: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        self.alb_sg = ec2.SecurityGroup(
            self,
            "AlbSg",
            vpc=self.vpc,
            description="ALB - allow inbound HTTPS only",
            allow_all_outbound=False,
        )
        self.alb_sg.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")
        self.alb_sg.add_egress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(8000), "To ECS tasks")

        self.ecs_sg = ec2.SecurityGroup(
            self,
            "EcsSg",
            vpc=self.vpc,
            description="ECS tasks - allow inbound from ALB only",
            allow_all_outbound=True,
        )
        self.ecs_sg.add_ingress_rule(self.alb_sg, ec2.Port.tcp(8000), "From ALB")

        Tags.of(self).add("Environment", env_config["environment"])
        Tags.of(self).add("Service", env_config["service_name"])
        Tags.of(self).add("Owner", env_config["owner"])
