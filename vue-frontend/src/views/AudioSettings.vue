<template>
  <div class="audio-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <span>{{ t('Audio Settings') }}</span>
        </div>
      </template>
      
      <BaseForm ref="formRef" :model="form" :rules="rules">
        <el-form-item label="Voice Provider" prop="voiceProvider">
          <el-select v-model="form.voiceProvider" placeholder="Select voice provider">
            <el-option label="Azure" value="azure" />
            <el-option label="Coze" value="coze" />
            <el-option label="Google" value="goggle" />
            <el-option label="Silicon" value="silicon" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Voice Type" prop="voiceType">
          <el-select v-model="form.voiceType" placeholder="Select voice type">
            <el-option label="Female" value="female" />
            <el-option label="Male" value="male" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Voice Name" prop="voiceName">
          <el-select v-model="form.voiceName" placeholder="Select voice name">
            <el-option v-for="voice in voiceOptions" :key="voice.value" :label="voice.label" :value="voice.value" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="Background Music" prop="bgm">
          <el-select v-model="form.bgm" placeholder="Select background music">
            <el-option label="None" value="" />
            <el-option v-for="bgm in bgmList" :key="bgm.id" :label="bgm.name" :value="bgm.path" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="BGM Volume" prop="bgmVolume">
          <el-slider
            v-model="form.bgmVolume"
            :min="0"
            :max="100"
            :step="5"
            show-input
          />
        </el-form-item>
        
        <el-form-item label="Voice Volume" prop="voiceVolume">
          <el-slider
            v-model="form.voiceVolume"
            :min="0"
            :max="100"
            :step="5"
            show-input
          />
        </el-form-item>
      </BaseForm>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import BaseForm from '../components/BaseForm.vue';
import { useI18nStore } from '../stores/i18n';
import { useUploadStore } from '../stores/upload';

const i18nStore = useI18nStore();
const uploadStore = useUploadStore();
const t = i18nStore.t;

const formRef = ref();

const form = reactive({
  voiceProvider: 'azure',
  voiceType: 'female',
  voiceName: 'zh-CN-XiaoxiaoNeural',
  bgm: '',
  bgmVolume: 30,
  voiceVolume: 80
});

const rules = reactive({
  voiceProvider: [{ required: true, message: 'Please select voice provider', trigger: 'change' }]
});

const voiceOptions = computed(() => {
  const options = {
    azure: [
      { label: 'zh-CN-XiaoxiaoNeural', value: 'zh-CN-XiaoxiaoNeural' },
      { label: 'zh-CN-YunxiNeural', value: 'zh-CN-YunxiNeural' },
      { label: 'zh-CN-YunxiaNeural', value: 'zh-CN-YunxiaNeural' },
      { label: 'zh-CN-YunyangNeural', value: 'zh-CN-YunyangNeural' }
    ],
    coze: [
      { label: 'cute', value: 'cute' },
      { label: 'energetic', value: 'energetic' },
      { label: 'gentle', value: 'gentle' },
      { label: 'professional', value: 'professional' }
    ],
    goggle: [
      { label: 'zh-CN-Standard-A', value: 'zh-CN-Standard-A' },
      { label: 'zh-CN-Standard-B', value: 'zh-CN-Standard-B' },
      { label: 'zh-CN-Standard-C', value: 'zh-CN-Standard-C' },
      { label: 'zh-CN-Standard-D', value: 'zh-CN-Standard-D' }
    ],
    silicon: [
      { label: 'zh-CN', value: 'zh-CN' },
      { label: 'en-US', value: 'en-US' }
    ]
  };
  return options[form.voiceProvider as keyof typeof options] || [];
});

const bgmList = computed(() => {
  return uploadStore.bgmFiles;
});

onMounted(async () => {
  await uploadStore.fetchBgmList();
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
.audio-settings {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>