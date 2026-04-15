<template>
  <div class="video-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <span>{{ t('Video Settings') }}</span>
        </div>
      </template>
      
      <BaseForm ref="formRef" :model="form" :rules="rules">
        <el-form-item label="Video Source" prop="videoSource">
          <el-select v-model="form.videoSource" placeholder="Select video source">
            <el-option label="Pexels" value="pexels" />
            <el-option label="Pixabay" value="pixabay" />
            <el-option label="Local file" value="local" />
            <el-option label="TikTok" value="douyin" />
            <el-option label="Bilibili" value="bilibili" />
            <el-option label="Xiaohongshu" value="xiaohongshu" />
          </el-select>
        </el-form-item>
        
        <div v-if="form.videoSource === 'local'" class="local-files-section">
          <el-form-item label="Local Files">
            <FileUploader
              :multiple="true"
              :accept="'video/*,image/*'"
              :auto-upload="false"
              :upload-text="'Upload Local Files'"
              :tip="'Supported formats: mp4, mov, avi, flv, mkv, jpg, jpeg, png'"
              v-model="localFiles"
              @remove="handleFileRemove"
            />
          </el-form-item>
        </div>
        
        <el-form-item label="Video Concat Mode" prop="videoConcatMode">
          <el-select v-model="form.videoConcatMode" placeholder="Select concat mode">
            <el-option label="Sequential" value="sequential" />
            <el-option label="Random" value="random" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Video Transition Mode" prop="videoTransitionMode">
          <el-select v-model="form.videoTransitionMode" placeholder="Select transition mode">
            <el-option label="None" value="none" />
            <el-option label="Shuffle" value="shuffle" />
            <el-option label="FadeIn" value="fade_in" />
            <el-option label="FadeOut" value="fade_out" />
            <el-option label="SlideIn" value="slide_in" />
            <el-option label="SlideOut" value="slide_out" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Video Ratio" prop="videoAspect">
          <el-select v-model="form.videoAspect" placeholder="Select video ratio">
            <el-option label="Portrait" value="portrait" />
            <el-option label="Landscape" value="landscape" />
            <el-option label="Square" value="square" />
            <el-option label="3:4 Portrait" value="portrait_3_4" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Clip Duration" prop="videoClipDuration">
          <el-select v-model="form.videoClipDuration" placeholder="Select clip duration">
            <el-option v-for="duration in [2, 3, 4, 5, 6, 7, 8, 9, 10]" :key="duration" :label="duration + 's'" :value="duration" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Number of Videos" prop="videoCount">
          <el-select v-model="form.videoCount" placeholder="Select number of videos">
            <el-option v-for="count in [1, 2, 3, 4, 5]" :key="count" :label="count" :value="count" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Video Style" prop="videoStyle">
          <el-select v-model="form.videoStyle" placeholder="Select video style">
            <el-option label="None" value="" />
            <el-option label="People/Human" value="people" />
            <el-option label="Nature/Landscape" value="nature" />
            <el-option label="Animation" value="animation" />
            <el-option label="Cartoon" value="cartoon" />
          </el-select>
        </el-form-item>
      </BaseForm>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';
import BaseForm from '../components/BaseForm.vue';
import FileUploader from '../components/FileUploader.vue';
import { useI18nStore } from '../stores/i18n';

interface FileItem {
  name: string;
  url?: string;
  status?: string;
  uid: string;
}

const i18nStore = useI18nStore();
const t = i18nStore.t;

const formRef = ref();
const localFiles = ref<FileItem[]>([]);

const form = reactive({
  videoSource: 'pexels',
  videoConcatMode: 'random',
  videoTransitionMode: 'none',
  videoAspect: 'portrait',
  videoClipDuration: 3,
  videoCount: 1,
  videoStyle: ''
});

const rules = reactive({
  videoSource: [{ required: true, message: 'Please select video source', trigger: 'change' }]
});

const handleFileRemove = (file: FileItem) => {
  console.log('File removed:', file);
};

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
.video-settings {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.local-files-section {
  margin-top: 20px;
  padding: 15px;
  background-color: #f9f9f9;
  border-radius: 4px;
}
</style>