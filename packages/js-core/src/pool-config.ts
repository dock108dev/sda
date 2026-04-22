/**
 * Pool configuration Zod discriminated union.
 *
 * Mirrors api/app/schemas/pool_config.py — both must stay in sync.
 * Discriminator field: `variant`.
 */

import { z } from "zod";

export const RvccPoolConfigSchema = z.object({
  variant: z.literal("rvcc"),
  pick_count: z.literal(7).default(7),
  count_best: z.literal(5).default(5),
  min_cuts_to_qualify: z.literal(5).default(5),
  uses_buckets: z.literal(false).default(false),
});

export const CrestmontPoolConfigSchema = z.object({
  variant: z.literal("crestmont"),
  pick_count: z.literal(6).default(6),
  count_best: z.literal(4).default(4),
  min_cuts_to_qualify: z.literal(4).default(4),
  uses_buckets: z.literal(true).default(true),
  // bucket_count has no default — must be explicitly provided
  bucket_count: z.literal(6),
});

export const PoolConfigSchema = z.discriminatedUnion("variant", [
  RvccPoolConfigSchema,
  CrestmontPoolConfigSchema,
]);

export type RvccPoolConfig = z.infer<typeof RvccPoolConfigSchema>;
export type CrestmontPoolConfig = z.infer<typeof CrestmontPoolConfigSchema>;
export type PoolConfig = z.infer<typeof PoolConfigSchema>;

/**
 * Parse unknown input as a typed PoolConfig.
 * Throws ZodError on invalid input.
 */
export function parsePoolConfig(input: unknown): PoolConfig {
  return PoolConfigSchema.parse(input);
}
