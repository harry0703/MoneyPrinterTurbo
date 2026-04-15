<template>
  <div class="subtitle-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">字幕设置</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <el-checkbox v-model="form.enableSubtitles">启用字幕（若取消勾选，下面的设置都将不生效）</el-checkbox>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <label class="form-label">字幕字体</label>
          <el-select v-model="form.subtitleFont" placeholder="选择字体" class="form-select">
            <el-option label="MicrosoftYaHeiBold.ttc" value="MicrosoftYaHeiBold.ttc" />
            <el-option label="Arial" value="Arial" />
            <el-option label="SimHei" value="SimHei" />
            <el-option label="Microsoft YaHei" value="Microsoft YaHei" />
            <el-option label="STHeiti" value="STHeiti" />
          </el-select>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <label class="form-label">字幕位置</label>
          <el-select v-model="form.subtitlePosition" placeholder="选择位置" class="form-select">
            <el-option label="顶部" value="top" />
            <el-option label="中间" value="middle" />
            <el-option label="底部（推荐）" value="bottom" />
            <el-option label="自定义位置（70，表示离顶部70%的位置）" value="custom" />
          </el-select>
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles && form.subtitlePosition === 'custom'">
          <label class="form-label">Custom Position (% from top)</label>
          <el-input v-model="form.subtitleCustomPosition" placeholder="输入自定义位置" class="form-input" />
        </div>
        
        <div class="form-item" v-if="form.enableSubtitles">
          <div style="display: flex; justify-content: space-between; gap: 20px;">
            <div style="flex: 1;">
              <label class="form-label">字幕颜色</label>
              <div class="color-picker-container">
                <el-color-picker v-model="form.subtitleColor" show-alpha />
              </div>
            </div>
            <div style="flex: 2;">
              <label class="form-label">字幕大小</label>
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
              <label class="form-label">描边颜色</label>
              <div class="color-picker-container">
                <el-color-picker v-model="form.subtitleOutlineColor" show-alpha />
              </div>
            </div>
            <div style="flex: 2;">
              <label class="form-label">描边粗细</label>
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
import { ref, reactive } from 'vue';
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
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  transition: border-color 0.3s;
  box-sizing: border-box;
}

.form-select:hover {
  border-color: #000;
}

.form-select:focus {
  border-color: #000;
  outline: none;
}

.form-input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  transition: border-color 0.3s;
  box-sizing: border-box;
}

.form-input:hover {
  border-color: #000;
}

.form-input:focus {
  border-color: #000;
  outline: none;
}

.color-picker-container {
  margin-top: 4px;
}
</style>