<template>
  <div class="subtitle-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">{{ t('Subtitle Settings') }}</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <el-checkbox v-model="form.enableSubtitles">{{ t('Enable subtitles (if unchecked, the following settings will not take effect)') }}</el-checkbox>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <label class="form-label">{{ t('Subtitle Font') }}</label>
          <el-select v-model="form.subtitleFont" :placeholder="t('Select font')" class="form-select">
            <el-option label="MicrosoftYaHeiBold.ttc" value="MicrosoftYaHeiBold.ttc" />
            <el-option label="Arial" value="Arial" />
            <el-option label="SimHei" value="SimHei" />
            <el-option label="Microsoft YaHei" value="Microsoft YaHei" />
            <el-option label="STHeiti" value="STHeiti" />
          </el-select>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <label class="form-label">{{ t('Subtitle Position') }}</label>
          <el-select v-model="form.subtitlePosition" :placeholder="t('Select position')" class="form-select">
            <el-option :label="t('Top')" value="top" />
            <el-option :label="t('Middle')" value="middle" />
            <el-option :label="t('Bottom (Recommended)')" value="bottom" />
            <el-option :label="t('Custom Position (70, means 70% from top)')" value="custom" />
          </el-select>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles && form.subtitlePosition === 'custom'">
          <label class="form-label">{{ t('Custom Position (% from top)') }}</label>
          <el-input v-model="form.subtitleCustomPosition" :placeholder="t('Enter custom position')" class="form-input" />
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <div style="display: flex; justify-content: space-between; gap: 20px;">
            <div style="flex: 1;">
              <label class="form-label">{{ t('Subtitle Color') }}</label>
              <div class="color-picker-container">
                <el-color-picker v-model="form.subtitleColor" show-alpha />
              </div>
            </div>
            <div style="flex: 2;">
              <label class="form-label">{{ t('Subtitle Size') }}</label>
              <el-slider
                v-model="form.subtitleFontSize"
                :min="30"
                :max="100"
                :step="1"
                show-input
              />
            </div>
          </div>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <div style="display: flex; justify-content: space-between; gap: 20px;">
            <div style="flex: 1;">
              <label class="form-label">{{ t('Outline Color') }}</label>
              <div class="color-picker-container">
                <el-color-picker v-model="form.subtitleOutlineColor" show-alpha />
              </div>
            </div>
            <div style="flex: 2;">
              <label class="form-label">{{ t('Outline Width') }}</label>
              <el-slider
                v-model="form.subtitleOutlineWidth"
                :min="0"
                :max="10"
                :step="0.1"
                show-input
              />
            </div>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue';
import { useI18nStore } from '../stores/i18n';

const i18nStore = useI18nStore();
const t = i18nStore.t;

const form = reactive({
  enableSubtitles: true,
  subtitleFont: 'MicrosoftYaHeiBold.ttc',
  subtitlePosition: 'custom',
  subtitleCustomPosition: '80.0',
  subtitleColor: '#FFFF00',
  subtitleFontSize: 60,
  subtitleOutlineColor: '#000000',
  subtitleOutlineWidth: 1.5
});

defineExpose({
  form
});
</script>

<style scoped>
.subtitle-settings {
  width: 100%;
}

.card-header {
  margin-bottom: 4px;
}

.title {
  font-size: 18px;
  font-weight: bold;
  margin: 0;
}

.settings-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-item {
  display: flex;
  flex-direction: column;
  gap: 0px;
}

.form-label {
  font-size: 14px;
  margin-bottom: 4px;
}

.form-select {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  box-sizing: border-box;
}

.form-select :deep(.el-select) {
  width: 100%;
}

.form-input {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  box-sizing: border-box;
}

.form-input :deep(.el-input) {
  width: 100%;
}

.color-picker-container {
  margin-top: 4px;
}
</style>