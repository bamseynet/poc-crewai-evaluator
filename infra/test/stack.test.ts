import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { beforeAll, describe, expect, it } from "vitest";
import { PolicyDrafterStack } from "../lib/policy-drafter-stack.js";

const MODEL = "us.anthropic.claude-opus-5-5";
const WORKER = "us.anthropic.claude-sonnet-5-5";
const CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad";
const ALL_VIEWER = "216adef6-5c7f-47e4-b989-5492eafa07d3";

let template: Template;

type Statement = { Action: string | string[]; Resource: unknown; Condition?: unknown };

function policyStatements(): Statement[] {
  return Object.values(template.findResources("AWS::IAM::Policy")).flatMap(
    (policy) => policy.Properties.PolicyDocument.Statement as Statement[],
  );
}

function bedrockStatements(): Statement[] {
  return policyStatements().filter((statement) =>
    [statement.Action].flat().some((action) => action.startsWith("bedrock:")),
  );
}

function container() {
  const [definition] = Object.values(template.findResources("AWS::ECS::TaskDefinition"));
  return definition?.Properties.ContainerDefinitions[0];
}

beforeAll(() => {
  const stack = new PolicyDrafterStack(new App(), "Test", {
    modelId: MODEL,
    workerModelId: WORKER,
    destinationRegions: ["us-east-1", "us-east-2", "us-west-2"],
  });
  template = Template.fromStack(stack);
});

describe("least-privilege Bedrock access", () => {
  it("allows only the InvokeModel actions", () => {
    const statements = bedrockStatements();

    expect(statements.length).toBeGreaterThan(0);
    for (const statement of statements) {
      expect([statement.Action].flat()).toEqual(["bedrock:InvokeModel*"]);
    }
  });

  it("names the two inference profiles and no others", () => {
    const text = JSON.stringify(bedrockStatements());

    expect(text).toContain(`inference-profile/${MODEL}`);
    expect(text).toContain(`inference-profile/${WORKER}`);
    expect(text.match(/inference-profile\/[^"]+/g)?.every((arn) => arn.includes("anthropic"))).toBe(
      true,
    );
  });

  it("names the foundation models in each destination Region", () => {
    const text = JSON.stringify(bedrockStatements());

    for (const region of ["us-east-1", "us-east-2", "us-west-2"]) {
      expect(text).toContain(`:bedrock:${region}::foundation-model/anthropic.claude-opus-5-5`);
      expect(text).toContain(`:bedrock:${region}::foundation-model/anthropic.claude-sonnet-5-5`);
    }
  });

  it("permits the foundation models only when reached through those profiles", () => {
    const modelStatement = bedrockStatements().find((statement) =>
      JSON.stringify(statement.Resource).includes("foundation-model"),
    );

    expect(JSON.stringify(modelStatement?.Condition)).toContain("bedrock:InferenceProfileArn");
    expect(JSON.stringify(modelStatement?.Condition)).toContain(`inference-profile/${MODEL}`);
  });

  it("has no wildcard resources on any Bedrock statement", () => {
    for (const statement of bedrockStatements()) {
      expect(JSON.stringify(statement.Resource)).not.toMatch(/"\*"|foundation-model\/\*/);
    }
  });

  it("does not give the running service Marketplace permissions", () => {
    expect(JSON.stringify(policyStatements())).not.toContain("aws-marketplace");
  });
});

describe("configuration and secrets", () => {
  it("passes the model ids and Region as configuration", () => {
    const environment = container().Environment as { Name: string; Value: unknown }[];

    expect(environment).toEqual(
      expect.arrayContaining([
        { Name: "LLM_MODE", Value: "bedrock" },
        { Name: "BEDROCK_MODEL_ID", Value: MODEL },
        { Name: "BEDROCK_WORKER_MODEL_ID", Value: WORKER },
      ]),
    );
    expect(environment.map((variable) => variable.Name)).toContain("AWS_REGION");
  });

  it("injects the access token from Secrets Manager, never as a plain variable", () => {
    const { Environment: environment, Secrets: secrets } = container();

    expect(secrets.map((secret: { Name: string }) => secret.Name)).toEqual(["API_ACCESS_TOKEN"]);
    expect(JSON.stringify(secrets)).toContain("Ref");
    expect(environment.map((variable: { Name: string }) => variable.Name)).not.toContain(
      "API_ACCESS_TOKEN",
    );
    template.resourceCountIs("AWS::SecretsManager::Secret", 1);
  });

  it("generates the token rather than containing one", () => {
    template.hasResourceProperties("AWS::SecretsManager::Secret", {
      GenerateSecretString: Match.objectLike({ PasswordLength: Match.anyValue() }),
      SecretString: Match.absent(),
    });
  });
});

describe("network path", () => {
  it("keeps the load balancer private", () => {
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
      Scheme: "internal",
    });
  });

  it("runs the service without a public IP", () => {
    template.hasResourceProperties("AWS::ECS::Service", {
      NetworkConfiguration: {
        AwsvpcConfiguration: Match.objectLike({ AssignPublicIp: "DISABLED" }),
      },
    });
  });

  it("runs exactly one task, because runs are held in memory", () => {
    template.hasResourceProperties("AWS::ECS::Service", { DesiredCount: 1 });
    template.hasResourceProperties("AWS::ECS::Service", { HealthCheckGracePeriodSeconds: 120 });
  });

  it("reaches the load balancer through a CloudFront VPC origin", () => {
    template.resourceCountIs("AWS::CloudFront::VpcOrigin", 1);
    template.hasResourceProperties("AWS::CloudFront::Distribution", {
      DistributionConfig: Match.objectLike({
        Origins: Match.arrayWith([
          Match.objectLike({ VpcOriginConfig: Match.objectLike({ VpcOriginId: Match.anyValue() }) }),
        ]),
      }),
    });
  });

  it("only accepts load balancer traffic from CloudFront's managed prefix list", () => {
    const ingress = template.findResources("AWS::EC2::SecurityGroupIngress", {
      Properties: { FromPort: 80, SourcePrefixListId: Match.anyValue() },
    });

    expect(Object.keys(ingress)).toHaveLength(1);
    const groups = JSON.stringify(template.findResources("AWS::EC2::SecurityGroup"));
    expect(groups).not.toContain("0.0.0.0/0\",\"Description\":\"Allow from anyone on port 80");
  });

  it("looks the prefix list up at deploy time, so synth needs no AWS access", () => {
    expect(JSON.stringify(template.findResources("Custom::AWS"))).toContain(
      "com.amazonaws.global.cloudfront.origin-facing",
    );
  });

  it("checks health on the unauthenticated endpoint", () => {
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::TargetGroup", {
      HealthCheckPath: "/api/health",
    });
  });

  it("outlasts the 15 second SSE keepalive on every timeout", () => {
    template.hasResourceProperties("AWS::ElasticLoadBalancingV2::LoadBalancer", {
      LoadBalancerAttributes: Match.arrayWith([
        { Key: "idle_timeout.timeout_seconds", Value: "120" },
      ]),
    });
    template.hasResourceProperties("AWS::CloudFront::Distribution", {
      DistributionConfig: Match.objectLike({
        Origins: Match.arrayWith([
          Match.objectLike({
            VpcOriginConfig: Match.objectLike({ OriginReadTimeout: 60 }),
          }),
        ]),
      }),
    });
  });
});

describe("streaming through CloudFront", () => {
  function behavior() {
    const [distribution] = Object.values(template.findResources("AWS::CloudFront::Distribution"));
    return distribution?.Properties.DistributionConfig.DefaultCacheBehavior;
  }

  it("forwards Authorization on GET requests, which CloudFront strips by default", () => {
    expect(behavior().OriginRequestPolicyId).toBe(ALL_VIEWER);
  });

  it("never caches responses, since access control happens at the origin", () => {
    expect(behavior().CachePolicyId).toBe(CACHING_DISABLED);
  });

  it("allows POST so that runs can be started", () => {
    expect(behavior().AllowedMethods).toContain("POST");
  });

  it("does not compress the event stream", () => {
    expect(behavior().Compress).toBe(false);
  });

  it("requires HTTPS, because the access token travels in a header", () => {
    expect(behavior().ViewerProtocolPolicy).toBe("redirect-to-https");
  });
});

describe("operations", () => {
  it("rolls back a deployment that fails its health checks", () => {
    template.hasResourceProperties("AWS::ECS::Service", {
      DeploymentConfiguration: Match.objectLike({
        DeploymentCircuitBreaker: { Enable: true, Rollback: true },
      }),
    });
  });

  it("limits log retention", () => {
    template.hasResourceProperties("AWS::Logs::LogGroup", { RetentionInDays: 30 });
  });

  it("publishes the URL and where to find the token", () => {
    const outputs = template.findOutputs("*");

    expect(Object.keys(outputs)).toEqual(
      expect.arrayContaining(["AppUrl", "AccessTokenSecretName"]),
    );
  });
});
