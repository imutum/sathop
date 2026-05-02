import type { Directive, DirectiveBinding } from "vue";
import { hasPermission, type Permission } from "@/composables/usePermissions";

// v-permission usage:
//   v-permission="'batch:delete'"            single permission required
//   v-permission="['batch:delete', 'admin']" all of these required
//   v-permission.any="['a', 'b']"            any of these required (OR)
//
// When the check fails the element is removed from the DOM; the previous
// position is held by a comment node so re-evaluation on update can put
// the element back without re-running its setup. This matches Vue's own
// v-if semantics rather than just toggling display:none, which would
// leak the markup to screen readers and a11y tooling.

type PermissionValue = Permission | Permission[];

const PLACEHOLDER_KEY = Symbol("v-permission-placeholder");

type ElWithPlaceholder = HTMLElement & {
  [PLACEHOLDER_KEY]?: Comment;
};

function check(binding: DirectiveBinding<PermissionValue>): boolean {
  const mode = binding.modifiers.any ? "any" : "all";
  return hasPermission(binding.value, mode);
}

function update(el: ElWithPlaceholder, binding: DirectiveBinding<PermissionValue>) {
  const allowed = check(binding);
  const placeholder = el[PLACEHOLDER_KEY];
  if (allowed) {
    if (placeholder?.parentNode) {
      placeholder.parentNode.replaceChild(el, placeholder);
      el[PLACEHOLDER_KEY] = undefined;
    }
  } else if (!placeholder && el.parentNode) {
    const ph = document.createComment(" v-permission ");
    el.parentNode.replaceChild(ph, el);
    el[PLACEHOLDER_KEY] = ph;
  }
}

export const permissionDirective: Directive<ElWithPlaceholder, PermissionValue> = {
  mounted: update,
  updated: update,
};
