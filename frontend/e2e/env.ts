// Shared, fail-fast lookup for the IDs backend/scripts/seed_e2e_demo.py
// prints. Missing an env var here means the seed step didn't run (or its
// output wasn't wired into the shell) — better to fail immediately with a
// clear message than have every spec time out waiting on a selector that
// can never appear.
export function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set — run backend/scripts/seed_e2e_demo.py and export its output first (see README.md).`,
    );
  }
  return value;
}
