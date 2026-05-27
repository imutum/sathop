import { type ComputedRef, type ShallowRef, computed, shallowRef, watch } from "vue";
import type { CompiledSchema, Row, RowErrors, Schema } from "./types";
import { compileSchema, rowHasErrors, validateRow } from "./validation";

export function useBatchRowValidation(
  rows: ShallowRef<Row[]>,
  schema: ComputedRef<Schema | null>,
) {
  const compiledSchema = computed<CompiledSchema | null>(() =>
    schema.value ? compileSchema(schema.value) : null,
  );

  const cache = shallowRef(new WeakMap<Row, RowErrors>());
  watch(compiledSchema, () => {
    cache.value = new WeakMap();
  });

  const rowErrors = computed<RowErrors[]>(() => {
    const c = compiledSchema.value;
    if (!c) return [];
    const m = cache.value;
    return rows.value.map((r) => {
      let cached = m.get(r);
      if (!cached) {
        cached = validateRow(r, c);
        m.set(r, cached);
      }
      return cached;
    });
  });

  const allRowsOk = computed(
    () => !!schema.value && rows.value.length > 0 && rowErrors.value.every((e) => !rowHasErrors(e)),
  );

  return { compiledSchema, rowErrors, allRowsOk };
}
