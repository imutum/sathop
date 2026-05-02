import { describe, it, expect } from "vitest";
import { cn } from "@/lib/utils";

describe("smoke", () => {
  it("cn merges tailwind classes", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-sm", { hidden: false }, "font-bold")).toBe("text-sm font-bold");
  });
});
