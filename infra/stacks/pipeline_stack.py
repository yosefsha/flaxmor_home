from aws_cdk import Stack, Tags
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_codepipeline as codepipeline
from aws_cdk import aws_codepipeline_actions as actions
from aws_cdk import aws_sns as sns
from constructs import Construct


class PipelineStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, env_config: dict, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        source_output = codepipeline.Artifact("SourceOutput")
        backend_build_output = codepipeline.Artifact("BackendBuildOutput")
        frontend_build_output = codepipeline.Artifact("FrontendBuildOutput")

        source_action = actions.CodeStarConnectionsSourceAction(
            action_name="GitHub",
            owner=env_config["github_owner"],
            repo=env_config["github_repo"],
            branch=env_config["github_branch"],
            connection_arn=env_config["codestar_connection_arn"],
            output=source_output,
        )

        backend_build = codebuild.PipelineProject(
            self,
            "BackendBuild",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"python": "3.12"},
                        "commands": ["pip install -r requirements.txt"],
                    },
                    "pre_build": {
                        "commands": ["pytest"],
                    },
                    "build": {
                        "commands": [
                            "docker build -t $ECR_REPO_URI:$CODEBUILD_RESOLVED_SOURCE_VERSION .",
                            "aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REPO_URI",
                            "docker push $ECR_REPO_URI:$CODEBUILD_RESOLVED_SOURCE_VERSION",
                        ],
                    },
                },
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,
            ),
        )

        frontend_build = codebuild.PipelineProject(
            self,
            "FrontendBuild",
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "install": {
                        "runtime-versions": {"nodejs": "20"},
                        "commands": ["npm ci"],
                    },
                    "build": {
                        "commands": [
                            "npm run lint",
                            "npm run build",
                        ],
                    },
                },
                "artifacts": {
                    "base-directory": "dist",
                    "files": ["**/*"],
                },
            }),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
            ),
        )

        approval_topic = sns.Topic(self, "ApprovalTopic", display_name="Pipeline Approval")

        codepipeline.Pipeline(
            self,
            "Pipeline",
            stages=[
                codepipeline.StageProps(
                    stage_name="Source",
                    actions=[source_action],
                ),
                codepipeline.StageProps(
                    stage_name="Build",
                    actions=[
                        actions.CodeBuildAction(
                            action_name="BackendBuild",
                            project=backend_build,
                            input=source_output,
                            outputs=[backend_build_output],
                        ),
                        actions.CodeBuildAction(
                            action_name="FrontendBuild",
                            project=frontend_build,
                            input=source_output,
                            outputs=[frontend_build_output],
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy-Staging",
                    actions=[
                        actions.ManualApprovalAction(
                            action_name="PromoteToProd",
                            notification_topic=approval_topic,
                            run_order=1,
                        ),
                    ],
                ),
                codepipeline.StageProps(
                    stage_name="Deploy-Prod",
                    actions=[
                        actions.ManualApprovalAction(
                            action_name="ProdApproval",
                            notification_topic=approval_topic,
                        ),
                    ],
                ),
            ],
        )

        Tags.of(self).add("Environment", env_config["environment"])
        Tags.of(self).add("Service", env_config["service_name"])
        Tags.of(self).add("Owner", env_config["owner"])
