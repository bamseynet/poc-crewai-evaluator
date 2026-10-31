import { App } from "aws-cdk-lib";
import { destinationRegionsFor } from "../lib/bedrock-access.js";
import { PolicyDrafterStack } from "../lib/policy-drafter-stack.js";

const app = new App();

// Inference profile ids from the Amazon Bedrock model cards. Override with `-c modelId=...`.
const modelId = (app.node.tryGetContext("modelId") as string) ?? "us.anthropic.claude-opus-5-5";
const workerModelId =
  (app.node.tryGetContext("workerModelId") as string) ?? "us.anthropic.claude-sonnet-5-5";
const explicitRegions = app.node.tryGetContext("bedrockDestinationRegions") as string | undefined;

new PolicyDrafterStack(app, "PolicyDrafter", {
  modelId,
  workerModelId,
  destinationRegions: destinationRegionsFor([modelId, workerModelId], explicitRegions?.split(",")),
  // Left undefined in CI, which makes synth environment-agnostic and free of AWS calls.
  env:
    process.env.CDK_DEFAULT_ACCOUNT && process.env.CDK_DEFAULT_REGION
      ? { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION }
      : undefined,
});
