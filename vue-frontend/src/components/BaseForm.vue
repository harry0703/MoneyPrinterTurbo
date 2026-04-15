<template>
  <div class="base-form">
    <el-form :model="form" :rules="rules" ref="formRef" :label-width="labelWidth">
      <slot></slot>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';

interface Props {
  model?: Record<string, any>;
  rules?: Record<string, any[]>;
  labelWidth?: string;
}

const props = withDefaults(defineProps<Props>(), {
  model: () => ({}),
  rules: () => ({}),
  labelWidth: '120px'
});

const form = reactive({ ...props.model });
const formRef = ref();

const emit = defineEmits(['update:modelValue', 'submit']);

const validate = async () => {
  if (!formRef.value) return false;
  try {
    await formRef.value.validate();
    emit('update:modelValue', form);
    emit('submit', form);
    return true;
  } catch (error) {
    return false;
  }
};

const reset = () => {
  if (formRef.value) {
    formRef.value.resetFields();
  }
};

defineExpose({
  validate,
  reset,
  form
});
</script>

<style scoped>
.base-form {
  width: 100%;
}
</style>