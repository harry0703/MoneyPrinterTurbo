<template>
  <div class="video-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">{{ t('Video Settings') }}</h2>
        </div>
      </template>
      
      <div class="settings-form">
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Source'))"></label>
          <el-select v-model="form.videoSource" :placeholder="t('Select video source')" class="form-select">
            <el-option :label="t('Pexels')" value="pexels" />
            <el-option :label="t('Pixabay')" value="pixabay" />
            <el-option :label="t('Local file')" value="local" />
            <el-option :label="t('TikTok')" value="douyin" />
            <el-option :label="t('Bilibili')" value="bilibili" />
            <el-option :label="t('Xiaohongshu')" value="xiaohongshu" />
          </el-select>
        </div>
        
        <div v-if="form.videoSource === 'local'" class="local-files-section">
          <div class="form-item">
            <label class="form-label" v-html="parseLabelMarkdown(t('Local Files'))"></label>
            <FileUploader
              :multiple="true"
              :accept="'video/*,image/*'"
              :auto-upload="false"
              :upload-text="t('Upload Local Files')"
              v-model="localFiles"
              @remove="handleFileRemove"
            />
            <div v-if="localFiles.length > 0" class="uploaded-files-info">
              <el-alert
                :title="t('Uploaded Files')"
                type="info"
                :closable="false"
                show-icon
                class="mt-2"
              >
                <p>{{ t('Successfully uploaded ' + localFiles.length + ' files') }}</p>
                <div v-for="file in localFiles" :key="file.uid" class="file-item">
                  📄 {{ file.name }}
                </div>
              </el-alert>
            </div>
          </div>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Concat Mode'))"></label>
          <el-select v-model="form.videoConcatMode" :placeholder="t('Select concat mode')" class="form-select">
            <el-option :label="t('Sequential')" value="sequential" />
            <el-option :label="t('Random')" value="random" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Transition Mode'))"></label>
          <el-select v-model="form.videoTransitionMode" :placeholder="t('Select transition mode')" class="form-select">
            <el-option :label="t('None')" value="none" />
            <el-option :label="t('Shuffle')" value="shuffle" />
            <el-option :label="t('FadeIn')" value="fade_in" />
            <el-option :label="t('FadeOut')" value="fade_out" />
            <el-option :label="t('SlideIn')" value="slide_in" />
            <el-option :label="t('SlideOut')" value="slide_out" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Ratio'))"></label>
          <el-select v-model="form.videoAspect" :placeholder="t('Select video ratio')" class="form-select">
            <el-option :label="t('Landscape')" value="landscape" />
            <el-option :label="t('Portrait')" value="portrait" />
            <el-option :label="t('Square')" value="square" />
            <el-option :label="t('3:4 Portrait')" value="portrait_3_4" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Clip Duration'))"></label>
          <el-select v-model="form.videoClipDuration" :placeholder="t('Select clip duration')" class="form-select">
            <el-option v-for="duration in [2, 3, 4, 5, 6, 7, 8, 9, 10]" :key="duration" :label="duration" :value="duration" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Number of Videos Generated Simultaneously'))"></label>
          <el-select v-model="form.videoCount" :placeholder="t('Select number of videos')" class="form-select">
            <el-option v-for="count in [1, 2, 3, 4, 5]" :key="count" :label="count" :value="count" />
          </el-select>
        </div>
        
        <div class="form-item">
          <label class="form-label" v-html="parseLabelMarkdown(t('Video Style'))"></label>
          <el-select v-model="form.videoStyle" :placeholder="t('Select video style')" class="form-select">
            <el-option :label="t('Video Style None')" value="none" />
            <el-option :label="t('People/Human')" value="people" />
            <el-option :label="t('Nature/Landscape')" value="nature" />
            <el-option :label="t('Animation')" value="animation" />
            <el-option :label="t('Cartoon')" value="cartoon" />
          </el-select>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted } from 'vue';
import FileUploader from '../components/FileUploader.vue';
import { useI18nStore } from '../stores/i18n';
import { parseLabelMarkdown } from '../utils/markdownParser';

interface FileItem {
  name: string;
  url?: string;
  status?: string;
  uid: string;
}

const i18nStore = useI18nStore();
const t = i18nStore.t;
const settingsStore = useSettingsStore();

const localFiles = ref<FileItem[]>([]);

const form = reactive({
  videoSource: settingsStore.video.source,
  videoConcatMode: settingsStore.video.concatMode,
  videoTransitionMode: settingsStore.video.transitionMode,
  videoAspect: settingsStore.video.aspect,
  videoClipDuration: settingsStore.video.clipDuration,
  videoCount: settingsStore.video.count,
  videoStyle: settingsStore.video.style
});

const handleFileRemove = (file: FileItem) => {
  const index = localFiles.value.findIndex(item => item.uid === file.uid);
  if (index !== -1) {
    localFiles.value.splice(index, 1);
  }
};

watch(() => form.videoSource, (newValue) => {
  settingsStore.updateVideoSetting('source', newValue);
});

watch(() => form.videoConcatMode, (newValue) => {
  settingsStore.updateVideoSetting('concatMode', newValue);
});

watch(() => form.videoTransitionMode, (newValue) => {
  settingsStore.updateVideoSetting('transitionMode', newValue);
});

watch(() => form.videoAspect, (newValue) => {
  settingsStore.updateVideoSetting('aspect', newValue);
});

watch(() => form.videoClipDuration, (newValue) => {
  settingsStore.updateVideoSetting('clipDuration', newValue);
});

watch(() => form.videoCount, (newValue) => {
  settingsStore.updateVideoSetting('count', newValue);
});

watch(() => form.videoStyle, (newValue) => {
  settingsStore.updateVideoSetting('style', newValue);
});

onMounted(() => {
  form.videoSource = settingsStore.video.source;
  form.videoConcatMode = settingsStore.video.concatMode;
  form.videoTransitionMode = settingsStore.video.transitionMode;
  form.videoAspect = settingsStore.video.aspect;
  form.videoClipDuration = settingsStore.video.clipDuration;
  form.videoCount = settingsStore.video.count;
  form.videoStyle = settingsStore.video.style;
});

defineExpose({
  form,
  localFiles
});
</script>

<style scoped>
.video-settings {
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
  margin-bottom: 4px;
  line-height: 1.4;
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

.local-files-section {
  margin-top: 16px;
  padding: 16px;
  background-color: #f9f9f9;
  border-radius: 4px;
}

.uploaded-files-info {
  margin-top: 12px;
}

.file-item {
  margin-top: 6px;
  font-size: 14px;
}

.mt-2 {
  margin-top: 8px;
}
</style>