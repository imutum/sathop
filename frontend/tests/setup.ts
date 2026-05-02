import { config } from "@vue/test-utils";
import { createPinia } from "pinia";

config.global.plugins = [createPinia()];
