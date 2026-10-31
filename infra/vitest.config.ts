import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // cdk.out holds a staged copy of the Docker build context, including the web tests.
    include: ["test/**/*.test.ts"],
  },
});
