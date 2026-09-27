import { afterEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { nextTick } from "vue";
import type { WorkerInfo } from "@/api";
import { useNow } from "@/i18n";
import WorkerRow from "@/features/nodes/components/WorkerRow.vue";

vi.mock("@/features/nodes/useWorkerLifecycle", async () => {
  const { ref } = await import("vue");
  return { useWorkerLifecycle: () => ({
    pause: { isPending: ref(false) }, gc: { isPending: ref(false) },
    revoke: { isPending: ref(false) }, purge: { isPending: ref(false) }, pending: ref(false),
  }) };
});

const cleanups: Array<() => void> = [];
const lastSeen = "2026-09-27T00:00:00Z";
const worker: WorkerInfo = {
  worker_id: "worker-a", version: "1.0.22", capacity: 2, public_url: null, last_seen: lastSeen,
  disk_used_gb: 1, disk_total_gb: 100, cpu_percent: 1, mem_percent: 2, monthly_egress_gb: 0,
  queue_pending_download: 2, queue_downloading: 0, queue_pending_processing: 0,
  queue_processing: 0, queue_pending_upload: 0, queue_uploading: 0,
  paused: false, operator_paused: false, removed_at: null,
  download_concurrency: null, process_concurrency: null,
  live_download_concurrency: 2, live_process_concurrency: 2,
};
function mountRow(tab: "active" | "history" = "active") {
  useNow().value = Date.parse(lastSeen) + 10_000;
  const wrapper = mount(WorkerRow, {
    props: { worker, tab, selected: false },
    global: { stubs: {
      RouterLink: true,
      HintTip: { props: ["text"], template: '<span :title="text"><slot /></span>' },
    } },
  });
  cleanups.push(() => wrapper.unmount());
  return wrapper;
}
afterEach(() => {
  cleanups.splice(0).forEach((cleanup) => cleanup());
  useNow().value = Date.now();
});

describe("worker row updates", () => {
  it("updates stage distribution when the total queue size stays the same", async () => {
    const wrapper = mountRow();
    expect(wrapper.find('[title^="待下载"]').attributes("title")).toContain("待下载 2 · 下载中 0");
    await wrapper.setProps({ worker: { ...worker, queue_pending_download: 0, queue_downloading: 2 } });
    expect(wrapper.find('[title^="待下载"]').attributes("title")).toContain("待下载 0 · 下载中 2");
    expect(wrapper.find(".bg-sky-500\\/70").attributes("style")).toContain("width: 100%");
  });

  it("ages the heartbeat and status without a new server response", async () => {
    const wrapper = mountRow();
    expect(wrapper.text()).toContain("10 秒前");
    expect(wrapper.find('[title="在线"]').exists()).toBe(true);
    useNow().value = Date.parse(lastSeen) + 70_000;
    await nextTick();
    expect(wrapper.text()).toContain("1 分钟前");
    expect(wrapper.find('[title="心跳延迟"]').exists()).toBe(true);
    useNow().value = Date.parse(lastSeen) + 310_000;
    await nextTick();
    expect(wrapper.find('[title="离线"]').exists()).toBe(true);
  });

  it("ages the last heartbeat of removed workers too", async () => {
    const wrapper = mountRow("history");
    useNow().value = Date.parse(lastSeen) + 120_000;
    await nextTick();
    expect(wrapper.text()).toContain("2 分钟前");
    expect(wrapper.text()).toContain("已移除");
  });
});
