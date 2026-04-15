<template>
  <div class="script-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">文案设置</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label">视频主题（给定一个关键词，<span style="color: red;">AI自动生成视频文案</span>）</label>
          <el-input
            v-model="form.videoSubject"
            placeholder="输入视频主题"
            type="text"
            maxlength="100"
            show-word-limit
            class="form-input"
          />
        </div>
        
        <div class="form-item">
          <label class="form-label">生成视频脚本的语言（一般情况AI会自动根据你输入的主题语言输出）</label>
          <el-select v-model="form.language" placeholder="选择语言" class="form-select">
            <el-option label="自动检测" value="auto" />
            <el-option label="Chinese" value="zh" />
            <el-option label="English" value="en" />
            <el-option label="German" value="de" />
            <el-option label="Portuguese" value="pt" />
            <el-option label="Russian" value="ru" />
            <el-option label="Turkish" value="tr" />
            <el-option label="Vietnamese" value="vi" />
          </el-select>
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button">根据主题生成【视频文案】</el-button>
        </div>
        
        <div class="form-item">
          <label class="form-label">视频文案 <span style="color: blue;">（①可不填，使用AI生成 ②合理使用标点断句，有助于生成字幕）</span></label>
          <el-input
            v-model="form.videoScript"
            placeholder="输入视频文案"
            type="textarea"
            :rows="6"
            maxlength="5000"
            show-word-limit
            class="form-textarea"
          />
        </div>
        
        <div class="form-item">
          <el-button type="primary" class="form-button">解析当前【视频文案】</el-button>
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
  videoSubject: '',
  videoScript: '',
  language: 'auto'
});

defineExpose({
  form
});
</script>

<style scoped>
.script-settings {
  width: 100%;
}

.card-header {
  margin-bottom: 4px;
}

.title {
  font-weight: bold;
  font-size: 20px;
  margin: 0;
  color: #333;
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
  font-weight: normal;
  font-size: 14px;
  color: #333;
  margin: 0;
  line-height: 1.4;
}

.form-input {
  width: 100%;
  border: 1px solid #e0e0e0;
  background-color: transparent;
  padding: 6px 8px;
  font-size: 14px;
  border-radius: 4px;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-input:hover {
  border-color: #000;
}

.form-input:focus {
  outline: none;
  border-color: #000;
}

.form-textarea {
  width: 100%;
  border: 1px solid #e0e0e0;
  background-color: transparent;
  padding: 6px 8px;
  font-size: 14px;
  border-radius: 4px;
  transition: border-color 0.2s;
  box-sizing: border-box;
  resize: vertical;
}

.form-textarea:hover {
  border-color: #000;
}

.form-textarea:focus {
  outline: none;
  border-color: #000;
}

.form-select {
  width: 100%;
  border: 1px solid #e0e0e0;
  background-color: transparent;
  padding: 6px 8px;
  font-size: 14px;
  border-radius: 4px;
  transition: border-color 0.2s;
  box-sizing: border-box;
}

.form-select:hover {
  border-color: #000;
}

.form-select:focus {
  outline: none;
  border-color: #000;
}

.tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}

.form-button {
  width: 100%;
  padding: 10px;
  font-size: 14px;
  border-radius: 4px;
  transition: all 0.3s;
}

.form-button:hover {
  opacity: 0.9;
}
</style>