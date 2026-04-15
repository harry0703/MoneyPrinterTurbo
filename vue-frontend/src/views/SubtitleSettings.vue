<template>
  <div class="subtitle-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <span>{{ t('Subtitle Settings') }}</span>
        </div>
      </template>
      
      <BaseForm ref="formRef" :model="form" :rules="rules">
        <el-form-item label="Subtitle Language" prop="subtitleLanguage">
          <el-select v-model="form.subtitleLanguage" placeholder="Select subtitle language">
            <el-option label="Chinese" value="zh" />
            <el-option label="English" value="en" />
            <el-option label="German" value="de" />
            <el-option label="Portuguese" value="pt" />
            <el-option label="Russian" value="ru" />
            <el-option label="Turkish" value="tr" />
            <el-option label="Vietnamese" value="vi" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Subtitle Position" prop="subtitlePosition">
          <el-select v-model="form.subtitlePosition" placeholder="Select subtitle position">
            <el-option label="Bottom" value="bottom" />
            <el-option label="Top" value="top" />
            <el-option label="Middle" value="middle" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Subtitle Font" prop="subtitleFont">
          <el-select v-model="form.subtitleFont" placeholder="Select subtitle font">
            <el-option label="Arial" value="Arial" />
            <el-option label="SimHei" value="SimHei" />
            <el-option label="Microsoft YaHei" value="Microsoft YaHei" />
            <el-option label="STHeiti" value="STHeiti" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Subtitle Font Size" prop="subtitleFontSize">
          <el-slider
            v-model="form.subtitleFontSize"
            :min="10"
            :max="50"
            :step="1"
            show-input
          />
        </el-form-item>
        
        <el-form-item label="Subtitle Color" prop="subtitleColor">
          <el-color-picker v-model="form.subtitleColor" show-alpha />
        </el-form-item>
        
        <el-form-item label="Subtitle Background" prop="subtitleBackground">
          <el-color-picker v-model="form.subtitleBackground" show-alpha />
        </el-form-item>
        
        <el-form-item label="Subtitle Bold" prop="subtitleBold">
          <el-switch v-model="form.subtitleBold" />
        </el-form-item>
        
        <el-form-item label="Subtitle Italic" prop="subtitleItalic">
          <el-switch v-model="form.subtitleItalic" />
        </el-form-item>
      </BaseForm>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';
import BaseForm from '../components/BaseForm.vue';
import { useI18nStore } from '../stores/i18n';

const i18nStore = useI18nStore();
const t = i18nStore.t;

const formRef = ref();

const form = reactive({
  subtitleLanguage: 'zh',
  subtitlePosition: 'bottom',
  subtitleFont: 'Microsoft YaHei',
  subtitleFontSize: 24,
  subtitleColor: '#ffffff',
  subtitleBackground: 'rgba(0, 0, 0, 0.5)',
  subtitleBold: false,
  subtitleItalic: false
});

const rules = reactive({
  subtitleLanguage: [{ required: true, message: 'Please select subtitle language', trigger: 'change' }]
});

const validate = async () => {
  if (formRef.value) {
    return await formRef.value.validate();
  }
  return false;
};

defineExpose({
  form,
  validate
});
</script>

<style scoped>
.subtitle-settings {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>