<template>
  <label>
    <span>{{ label }}</span>

    <SliderRoot
      :model-value="[modelValue]"
      :min="min"
      :max="max"
      :step="step"
      :as-child="true"
      @update:model-value="
        (value) => emit('update:modelValue', value?.[0] || min)
      "
    >
      <span class="root">
        <SliderTrack class="track">
          <SliderRange class="range" />
        </SliderTrack>
        <SliderThumb :as-child="true">
          <div class="thumb" :aria-label="label" />
        </SliderThumb>
      </span>
    </SliderRoot>
  </label>
</template>

<script setup lang="ts">
import { SliderRange, SliderRoot, SliderThumb, SliderTrack } from "radix-vue";

type Props = {
  label: string;
  modelValue: number;
  min?: number;
  max?: number;
  step?: number;
};

withDefaults(defineProps<Props>(), { min: 0, max: 1, step: 0.1 });

type Emits = {
  "update:modelValue": [Props["modelValue"]];
};

const emit = defineEmits<Emits>();
</script>

<style scoped>
label {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
}

.root {
  display: flex;
  position: relative;
  align-items: center;
  height: 10px;
  margin-bottom: 5px;
  padding: 10px 0;
  cursor: pointer;
}

.track {
  position: relative;
  flex-grow: 1;
  height: 5px;

  border-radius: 999px;
  background: var(--light-gray);
}

.range {
  position: absolute;
  height: 100%;
  border-radius: 999px;
  background: var(--theme);
}

.thumb {
  position: absolute;
  width: 15px;
  height: 15px;
  transform: translate(-50%, -50%);
  border-radius: 999px;
  background: var(--theme);
}
</style>
