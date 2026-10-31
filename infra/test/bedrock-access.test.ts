import { describe, expect, it } from "vitest";
import { destinationRegionsFor, foundationModelId } from "../lib/bedrock-access.js";

describe("foundationModelId", () => {
  it.each([
    ["us.anthropic.claude-opus-5-5", "anthropic.claude-opus-5-5"],
    ["eu.anthropic.claude-sonnet-5-5", "anthropic.claude-sonnet-5-5"],
    ["au.anthropic.claude-haiku-5-5", "anthropic.claude-haiku-5-5"],
    ["jp.anthropic.claude-opus-5-5", "anthropic.claude-opus-5-5"],
    ["ca.anthropic.claude-haiku-5-5", "anthropic.claude-haiku-5-5"],
  ])("derives the model behind %s", (profile, model) => {
    expect(foundationModelId(profile)).toBe(model);
  });

  it.each([
    ["global.anthropic.claude-opus-5-5"],
    ["anthropic.claude-opus-5-5"],
    ["nonsense"],
  ])("rejects %s, which cannot be scoped to a known set of Regions", (id) => {
    expect(() => foundationModelId(id)).toThrow(/geographic inference profile/);
  });
});

describe("destinationRegionsFor", () => {
  it("defaults to the Regions the model cards list for US profiles", () => {
    expect(destinationRegionsFor(["us.anthropic.claude-opus-5-5"])).toEqual([
      "us-east-1",
      "us-east-2",
      "us-west-2",
    ]);
  });

  it("requires an explicit list for other geographies", () => {
    expect(() => destinationRegionsFor(["eu.anthropic.claude-opus-5-5"])).toThrow(
      /bedrockDestinationRegions/,
    );
  });

  it("uses an explicit list when one is given", () => {
    expect(destinationRegionsFor(["eu.anthropic.claude-opus-5-5"], ["eu-west-1"])).toEqual([
      "eu-west-1",
    ]);
  });
});
