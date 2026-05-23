/** Result type for explicit error handling. Never throw in domain code. */
export type Result<T, E = Error> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E };

export function Ok<T>(value: T): Result<T, never> {
  return { ok: true, value };
}

export function Err<E = Error>(error: E): Result<never, E> {
  return { ok: false, error };
}

export function unwrap<T>(result: Result<T, unknown>): T {
  if (!result.ok) throw result.error;
  return result.value;
}

export function unwrapOr<T>(result: Result<T, unknown>, defaultValue: T): T {
  return result.ok ? result.value : defaultValue;
}
