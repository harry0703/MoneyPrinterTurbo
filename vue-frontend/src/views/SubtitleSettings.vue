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
          <el-checkbox v-model="form.enableSubtitles">{{ t('Enable Subtitles') }}</el-checkbox>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <label class="form-label">{{ t('Font') }}</label>
          <el-select v-model="form.subtitleFont" :placeholder="t('Select font')" class="form-select">
            <el-option label="MicrosoftYaHeiBold.ttc" value="MicrosoftYaHeiBold.ttc" />
            <el-option label="Arial" value="Arial" />
            <el-option label="SimHei" value="SimHei" />
            <el-option label="Microsoft YaHei" value="Microsoft YaHei" />
            <el-option label="STHeiti" value="STHeiti" />
          </el-select>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <label class="form-label">{{ t('Position') }}</label>
          <el-select v-model="form.subtitlePosition" :placeholder="t('Select position')" class="form-select">
            <el-option :label="t('Top')" value="top" />
            <el-option :label="t('Center')" value="middle" />
            <el-option :label="t('Bottom')" value="bottom" />
            <el-option :label="t('Custom')" value="custom" />
          </el-select>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles && form.subtitlePosition === 'custom'">
          <label class="form-label">{{ t('Custom') }}</label>
          <el-input v-model="form.subtitleCustomPosition" :placeholder="t('Enter custom position')" class="form-input" />
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <div style="display: flex; justify-content: space-between; gap: 20px;">
            <div style="flex: 1;">
              <label class="form-label">{{ t('Font Color') }}</label>
              <div class="color-picker-container">
                <el-color-picker v-model="form.subtitleColor" show-alpha />
              </div>
            </div>
            <div style="flex: 2;">
              <label class="form-label">{{ t('Font Size') }}</label>
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
              <label class="form-label">{{ t('Stroke Color') }}</label>
              <div class="color-picker-container">
                <el-color-picker v-model="form.subtitleOutlineColor" show-alpha />
              </div>
            </div>
            <div style="flex: 2;">
              <label class="form-label">{{ t('Stroke Width') }}</label>
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
import { reactive, watch, onMounted } from 'vue';
import { useI18nStore } from '../stores/i18n';
import { useSettingsStore } from '../stores/settings';

const i18nStore = useI18nStore();
const t = i18nStore.t;
const settingsStore = useSettingsStore();

const form = reactive({
  enableSubtitles: settingsStore.subtitle.enable,
  subtitleFont: settingsStore.subtitle.font,
  subtitlePosition: settingsStore.subtitle.position,
  subtitleCustomPosition: settingsStore.subtitle.customPosition,
  subtitleColor: settingsStore.subtitle.color,
  subtitleFontSize: settingsStore.subtitle.fontSize,
  subtitleOutlineColor: settingsStore.subtitle.outlineColor,
  subtitleOutlineWidth: settingsStore.subtitle.outlineWidth
});

watch(() => form.enableSubtitles, (newValue) => {
  settingsStore.updateSubtitleSetting('enable', newValue);
});

watch(() => form.subtitleFont, (newValue) => {
  settingsStore.updateSubtitleSetting('font', newValue);
});

watch(() => form.subtitlePosition, (newValue) => {
  settingsStore.updateSubtitleSetting('position', newValue);
});

watch(() => form.subtitleCustomPosition, (newValue) => {
  settingsStore.updateSubtitleSetting('customPosition', newValue);
});

watch(() => form.subtitleColor, (newValue) => {
  settingsStore.updateSubtitleSetting('color', newValue);
});

watch(() => form.subtitleFontSize, (newValue) => {
  settingsStore.updateSubtitleSetting('fontSize', newValue);
});

watch(() => form.subtitleOutlineColor, (newValue) => {
  settingsStore.updateSubtitleSetting('outlineColor', newValue);
});

watch(() => form.subtitleOutlineWidth, (newValue) => {
  settingsStore.updateSubtitleSetting('outlineWidth', newValue);
});

onMounted(() => {
  form.enableSubtitles = settingsStore.subtitle.enable;
  form.subtitleFont = settingsStore.subtitle.font;
  form.subtitlePosition = settingsStore.subtitle.position;
  form.subtitleCustomPosition = settingsStore.subtitle.customPosition;
  form.subtitleColor = settingsStore.subtitle.color;
  form.subtitleFontSize = settingsStore.subtitle.fontSize;
  form.subtitleOutlineColor = settingsStore.subtitle.outlineColor;
  form.subtitleOutlineWidth = settingsStore.subtitle.outlineWidth;
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