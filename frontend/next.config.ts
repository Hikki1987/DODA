import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Conditional, not unconditional: Next.js itself warns "next start"
  // does not work with "output: standalone" (confirmed — running it
  // after a standalone build prints exactly that warning). CI's e2e job
  // (.github/workflows/ci.yml) and local manual verification both use
  // `next build && next start`, never the standalone server.js — so
  // turning this on unconditionally would put a Next.js-flagged footgun
  // in the middle of an already-green, already-proven path for the sake
  // of a Docker image that isn't built by anything yet. The Dockerfile
  // sets DOCKER_BUILD=1 as a build ARG/ENV to opt in only for that build.
  output: process.env.DOCKER_BUILD === "1" ? "standalone" : undefined,
};

export default nextConfig;
