/** Branded type for entity IDs — prevents mixing up different ID types. */
export type EntityId = string & { readonly __brand: "EntityId" };

export function EntityId(value: string): EntityId {
  if (!value || typeof value !== "string") {
    throw new Error("EntityId must be a non-empty string");
  }
  return value as EntityId;
}

export function generateId(): EntityId {
  return crypto.randomUUID() as EntityId;
}
