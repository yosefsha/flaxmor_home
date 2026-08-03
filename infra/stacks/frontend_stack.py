from aws_cdk import Duration, RemovalPolicy, Stack, Tags
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from constructs import Construct


class FrontendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, env_config: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = s3.Bucket(
            self,
            "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        hosted_zone = route53.HostedZone.from_lookup(
            self, "Zone", domain_name=env_config["domain_name"]
        )

        certificate = acm.Certificate(
            self,
            "Certificate",
            domain_name=env_config["frontend_domain"],
            validation=acm.CertificateValidation.from_dns(hosted_zone),
        )

        spa_function = cloudfront.Function(
            self,
            "SpaRouting",
            code=cloudfront.FunctionCode.from_inline(
                "function handler(event) {"
                "  var request = event.request;"
                "  var uri = request.uri;"
                "  if (uri.endsWith('/') || !uri.includes('.')) {"
                "    request.uri = '/index.html';"
                "  }"
                "  return request;"
                "}"
            ),
        )

        immutable_cache_policy = cloudfront.CachePolicy(
            self,
            "ImmutableAssets",
            default_ttl=Duration.days(365),
            max_ttl=Duration.days(365),
            min_ttl=Duration.days(365),
            enable_accept_encoding_gzip=True,
            enable_accept_encoding_brotli=True,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_function,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            additional_behaviors={
                "/assets/*": cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=immutable_cache_policy,
                ),
            },
            domain_names=[env_config["frontend_domain"]],
            certificate=certificate,
        )

        route53.ARecord(
            self,
            "AliasRecord",
            zone=hosted_zone,
            record_name=env_config["frontend_domain"],
            target=route53.RecordTarget.from_alias(
                targets.CloudFrontTarget(self.distribution)
            ),
        )

        Tags.of(self).add("Environment", env_config["environment"])
        Tags.of(self).add("Service", env_config["service_name"])
        Tags.of(self).add("Owner", env_config["owner"])
