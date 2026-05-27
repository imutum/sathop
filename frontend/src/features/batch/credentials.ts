import type { Credential as ApiCredential } from "@/api";

export type CredDraft = {
  scheme: "basic" | "bearer";
  username: string;
  secret: string;
};

export function emptyCred(): CredDraft {
  return { scheme: "basic", username: "", secret: "" };
}

export function credDraftToApi(name: string, d: CredDraft): ApiCredential {
  if (d.scheme === "basic") {
    return { name, scheme: "basic", username: d.username || null, password: d.secret || null };
  }
  return { name, scheme: "bearer", token: d.secret || null };
}

export function credentialsHaveDraftContent(drafts: Record<string, CredDraft>): boolean {
  return Object.values(drafts).some((d) => d.username.trim() !== "" || d.secret.trim() !== "");
}

export function credentialsPayload(drafts: Record<string, CredDraft>): Record<string, ApiCredential> {
  return Object.fromEntries(Object.entries(drafts).map(([name, draft]) => [name, credDraftToApi(name, draft)]));
}

export function credentialsAreValid(names: string[], drafts: Record<string, CredDraft>): boolean {
  return names.every((name) => {
    const draft = drafts[name];
    if (!draft) return false;
    return draft.secret.trim() !== "" && (draft.scheme !== "basic" || draft.username.trim() !== "");
  });
}
