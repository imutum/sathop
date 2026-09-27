import { deleteJson, downloadFile, getJson, postJson, putJson } from "./apiClient";

export const DELIVERY_PAGE_SIZE = 20;

export type TaskTemplateInput = {
  name: string;
  bundle_ref: string;
  target_receiver_id: string | null;
  execution_env: Record<string, string>;
};
export type TaskTemplate = TaskTemplateInput & {
  template_id: string;
  created_at: string;
  updated_at: string;
};
export type Delivery = {
  id: number;
  batch_id: string;
  batch_name: string;
  bundle_ref: string;
  granule_id: string;
  object_key: string;
  size: number;
  sha256: string;
  receiver_id: string | null;
  delivered_at: string;
  batch_exists: boolean;
};
export type DeliveryPage = {
  items: Delivery[];
  total: number;
  total_bytes: number;
  granules: number;
  batches: number;
};

export function deliveryParams(q: string, batch: string, start: string, end: string): URLSearchParams {
  const params = new URLSearchParams();
  if (q.trim()) params.set("q", q.trim());
  if (batch) params.set("batch_id", batch);
  if (start) params.set("since", new Date(`${start}T00:00:00`).toISOString());
  if (end) {
    const exclusiveEnd = new Date(`${end}T00:00:00`);
    exclusiveEnd.setDate(exclusiveEnd.getDate() + 1);
    params.set("until", exclusiveEnd.toISOString());
  }
  return params;
}

export const serviceAPI = {
  templates: () => getJson<TaskTemplate[]>("/api/task-templates"),
  saveTemplate: (body: TaskTemplateInput, id?: string) =>
    id
      ? putJson<TaskTemplate>(`/api/task-templates/${encodeURIComponent(id)}`, body)
      : postJson<TaskTemplate>("/api/task-templates", body),
  deleteTemplate: (id: string) => deleteJson(`/api/task-templates/${encodeURIComponent(id)}`),
  deliveries: (params: string, offset: number) =>
    getJson<DeliveryPage>(`/api/deliveries?${params}&limit=${DELIVERY_PAGE_SIZE}&offset=${offset}`),
  exportDeliveries: (params: string) =>
    downloadFile(`/api/deliveries/export?${params}`, "delivery-ledger.csv"),
};
