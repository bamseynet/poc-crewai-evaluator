import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Aws, CfnOutput, Duration, Stack, type StackProps } from "aws-cdk-lib";
import {
  AllowedMethods,
  CachePolicy,
  Distribution,
  OriginProtocolPolicy,
  OriginRequestPolicy,
  ViewerProtocolPolicy,
} from "aws-cdk-lib/aws-cloudfront";
import { VpcOrigin } from "aws-cdk-lib/aws-cloudfront-origins";
import { Peer, Port, SubnetType, Vpc } from "aws-cdk-lib/aws-ec2";
import { Platform } from "aws-cdk-lib/aws-ecr-assets";
import {
  Cluster,
  ContainerImage,
  FargateService,
  FargateTaskDefinition,
  LogDrivers,
  Secret as EcsSecret,
} from "aws-cdk-lib/aws-ecs";
import {
  ApplicationLoadBalancer,
  ApplicationProtocol,
} from "aws-cdk-lib/aws-elasticloadbalancingv2";
import { RetentionDays } from "aws-cdk-lib/aws-logs";
import { Secret } from "aws-cdk-lib/aws-secretsmanager";
import {
  AwsCustomResource,
  AwsCustomResourcePolicy,
  PhysicalResourceId,
} from "aws-cdk-lib/custom-resources";
import type { Construct } from "constructs";
import { bedrockInvokeStatements } from "./bedrock-access.js";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const CONTAINER_PORT = 8000;

export interface PolicyDrafterStackProps extends StackProps {
  /** Inference profile for the evaluator. */
  modelId: string;
  /** Inference profile for the researcher and drafter. */
  workerModelId: string;
  /** Regions the inference profiles route to from the deployment Region. */
  destinationRegions: string[];
}

/**
 * Viewer -> CloudFront (HTTPS) -> VPC origin -> internal ALB -> one Fargate task -> Bedrock.
 *
 * CloudFront provides HTTPS without needing a domain, and nothing in the VPC is reachable from the
 * internet. There is one task because runs are held in memory.
 */
export class PolicyDrafterStack extends Stack {
  constructor(scope: Construct, id: string, props: PolicyDrafterStackProps) {
    super(scope, id, props);

    const vpc = new Vpc(this, "Vpc", { maxAzs: 2, natGateways: 1 });

    const accessToken = new Secret(this, "ApiAccessToken", {
      description: "Bearer token that protects the Policy Drafter API, whose runs cost money.",
      generateSecretString: { passwordLength: 48, excludePunctuation: true },
    });

    const taskDefinition = new FargateTaskDefinition(this, "Task", {
      cpu: 1024,
      memoryLimitMiB: 2048,
    });
    for (const statement of bedrockInvokeStatements(
      [props.modelId, props.workerModelId],
      props.destinationRegions,
    )) {
      taskDefinition.addToTaskRolePolicy(statement);
    }
    taskDefinition.addContainer("Api", {
      image: ContainerImage.fromAsset(REPOSITORY_ROOT, { platform: Platform.LINUX_AMD64 }),
      portMappings: [{ containerPort: CONTAINER_PORT }],
      environment: {
        LLM_MODE: "bedrock",
        BEDROCK_MODEL_ID: props.modelId,
        BEDROCK_WORKER_MODEL_ID: props.workerModelId,
        AWS_REGION: Aws.REGION,
      },
      secrets: { API_ACCESS_TOKEN: EcsSecret.fromSecretsManager(accessToken) },
      logging: LogDrivers.awsLogs({
        streamPrefix: "api",
        logRetention: RetentionDays.ONE_MONTH,
      }),
    });

    const service = new FargateService(this, "Service", {
      cluster: new Cluster(this, "Cluster", { vpc }),
      taskDefinition,
      desiredCount: 1,
      minHealthyPercent: 100,
      assignPublicIp: false,
      vpcSubnets: { subnetType: SubnetType.PRIVATE_WITH_EGRESS },
      circuitBreaker: { rollback: true },
    });

    const loadBalancer = new ApplicationLoadBalancer(this, "LoadBalancer", {
      vpc,
      internetFacing: false,
      // Longer than the API's 15 second SSE keepalive, so that idle streams stay open.
      idleTimeout: Duration.seconds(120),
    });
    const listener = loadBalancer.addListener("Http", {
      port: 80,
      protocol: ApplicationProtocol.HTTP,
      open: false,
    });
    listener.addTargets("Api", {
      port: CONTAINER_PORT,
      protocol: ApplicationProtocol.HTTP,
      targets: [service],
      healthCheck: { path: "/api/health" },
      deregistrationDelay: Duration.seconds(30),
    });

    // Looked up at deploy time, because the id differs per Region and a synth-time lookup would
    // need AWS credentials in CI.
    const prefixList = new AwsCustomResource(this, "CloudFrontPrefixList", {
      installLatestAwsSdk: false,
      onUpdate: {
        service: "EC2",
        action: "describeManagedPrefixLists",
        parameters: {
          Filters: [
            {
              Name: "prefix-list-name",
              Values: ["com.amazonaws.global.cloudfront.origin-facing"],
            },
          ],
        },
        physicalResourceId: PhysicalResourceId.of("cloudfront-origin-facing"),
        outputPaths: ["PrefixLists.0.PrefixListId"],
      },
      policy: AwsCustomResourcePolicy.fromSdkCalls({
        resources: AwsCustomResourcePolicy.ANY_RESOURCE,
      }),
    });
    loadBalancer.connections.allowFrom(
      Peer.prefixList(prefixList.getResponseField("PrefixLists.0.PrefixListId")),
      Port.tcp(80),
      "CloudFront origin-facing servers",
    );

    const distribution = new Distribution(this, "Distribution", {
      comment: "Policy Drafter",
      defaultBehavior: {
        origin: VpcOrigin.withApplicationLoadBalancer(loadBalancer, {
          protocolPolicy: OriginProtocolPolicy.HTTP_ONLY,
          // Applies between packets as well as to the first byte, and the SSE keepalive is 15s.
          readTimeout: Duration.seconds(60),
        }),
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: AllowedMethods.ALLOW_ALL,
        // Access control happens at the origin, so nothing may be served from a cache.
        cachePolicy: CachePolicy.CACHING_DISABLED,
        // CloudFront strips Authorization from GET requests unless told otherwise, which would
        // make the event stream return 401.
        originRequestPolicy: OriginRequestPolicy.ALL_VIEWER,
        compress: false,
      },
    });

    new CfnOutput(this, "AppUrl", { value: `https://${distribution.distributionDomainName}` });
    new CfnOutput(this, "AccessTokenSecretName", { value: accessToken.secretName });
  }
}
