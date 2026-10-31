import { Aws } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";

const GEOGRAPHIC_PROFILE = /^(us|eu|au|jp|ca)\.(.+)$/;

/**
 * Where US profiles route when called from us-east-1, us-east-2 or us-west-2, according to the
 * Bedrock model cards. Routing depends on the source Region and can change, so confirm it with
 * `aws bedrock get-inference-profile` before relying on it.
 */
const US_DESTINATION_REGIONS = ["us-east-1", "us-east-2", "us-west-2"];

/** "us.anthropic.claude-opus-5-5" -> "anthropic.claude-opus-5-5" */
export function foundationModelId(inferenceProfileId: string): string {
  const model = GEOGRAPHIC_PROFILE.exec(inferenceProfileId)?.[2];
  if (!model) {
    throw new Error(
      `${inferenceProfileId} is not a geographic inference profile. ` +
        "This stack needs a known set of destination Regions to scope its IAM policy.",
    );
  }
  return model;
}

export function destinationRegionsFor(modelIds: string[], explicit?: string[]): string[] {
  if (explicit && explicit.length > 0) return explicit;
  if (modelIds.every((id) => id.startsWith("us."))) return US_DESTINATION_REGIONS;
  throw new Error(
    "Set the bedrockDestinationRegions context to the Regions your inference profiles route to. " +
      "`aws bedrock get-inference-profile` lists them for your source Region.",
  );
}

/**
 * Permission to invoke exactly these inference profiles. A cross-Region profile needs access to
 * the profile and to its foundation model in every destination Region. The condition means that
 * the foundation models cannot be called directly, only through these profiles.
 */
export function bedrockInvokeStatements(
  inferenceProfileIds: string[],
  destinationRegions: string[],
): PolicyStatement[] {
  const profileIds = [...new Set(inferenceProfileIds)];
  const profileArns = profileIds.map(
    (id) =>
      `arn:${Aws.PARTITION}:bedrock:${Aws.REGION}:${Aws.ACCOUNT_ID}:inference-profile/${id}`,
  );
  const modelIds = [...new Set(profileIds.map(foundationModelId))];
  const modelArns = destinationRegions.flatMap((region) =>
    modelIds.map((id) => `arn:${Aws.PARTITION}:bedrock:${region}::foundation-model/${id}`),
  );

  return [
    new PolicyStatement({
      sid: "InvokeInferenceProfiles",
      effect: Effect.ALLOW,
      actions: ["bedrock:InvokeModel*"],
      resources: profileArns,
    }),
    new PolicyStatement({
      sid: "InvokeFoundationModelsThroughProfiles",
      effect: Effect.ALLOW,
      actions: ["bedrock:InvokeModel*"],
      resources: modelArns,
      conditions: { StringLike: { "bedrock:InferenceProfileArn": profileArns } },
    }),
  ];
}
