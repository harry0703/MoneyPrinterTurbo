<template>
  <div class="audio-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <h2 class="title">🔊 {{ t('Audio Settings') }}</h2>
        </div>
      </template>

      <div class="settings-form">
        <div class="form-item">
          <label class="form-label">{{ t('TTS Server') }}</label>
          <el-select v-model="form.ttsServer" :placeholder="t('Select TTS server')" class="form-select" @change="onTtsServerChange">
            <el-option :label="t('Azure TTS V1')" value="azure-tts-v1" />
            <el-option :label="t('Azure TTS V2')" value="azure-tts-v2" />
            <el-option :label="t('SiliconFlow TTS')" value="siliconflow" />
            <el-option :label="t('Google Gemini TTS')" value="gemini-tts" />
            <el-option :label="t('Coze TTS')" value="coze-tts" />
          </el-select>
        </div>

        <div v-if="form.ttsServer === 'coze-tts'" class="form-item coze-settings">
          <div class="coze-header">
            <span>{{ t('Coze TTS') }}</span>
            <el-button type="primary" size="small" icon="Refresh" @click="refreshCozeVoices" :loading="refreshingVoices">
              {{ t('Refresh') }}
            </el-button>
          </div>
          <el-input
            v-model="searchKeyword"
            :placeholder="t('Enter voice keyword to search...')"
            class="form-input"
            clearable
          />
        </div>

        <div class="form-item">
          <label class="form-label">
            {{ t('Speaking Voice') }}
            <span style="color: red;" v-if="form.ttsServer === 'azure-tts-v1'">{{ t('(Keep consistent with copy language)') }}</span>
            <span v-if="form.ttsServer === 'azure-tts-v1'" style="color: red;">{{ t('(Note: V2 version is better, but requires API KEY)') }}</span>
          </label>
          <el-select
            v-model="form.speechSynthesis"
            :placeholder="t('Select voice')"
            class="form-select"
            filterable
            :loading="loadingVoices"
          >
            <el-option
              v-for="voice in filteredVoiceList"
              :key="voice.value"
              :label="voice.label"
              :value="voice.value"
            />
          </el-select>
        </div>

        <div v-if="form.ttsServer === 'coze-tts' && currentVoiceSupportsEmotion" class="form-item">
          <label class="form-label">{{ t('Voice Emotion') }}</label>
          <el-select v-model="form.voiceEmotion" :placeholder="t('Select emotion')" class="form-select">
            <el-option
              v-for="emotion in currentVoiceEmotions"
              :key="emotion.value"
              :label="t(emotion.label)"
              :value="emotion.value"
            />
          </el-select>
        </div>

        <div class="form-item">
          <el-button type="primary" class="form-button" @click="testVoice" :loading="testingVoice">
            {{ testingVoice ? t('Testing...') : t('Test Speech Synthesis') }}
          </el-button>
        </div>

        <audio v-if="audioUrl" :src="audioUrl" controls class="audio-preview"></audio>

        <div v-if="form.ttsServer === 'azure-tts-v2'" class="azure-v2-settings">
          <div class="form-item">
            <label class="form-label">{{ t('Service Region') }} <span style="color: blue;">{{ t('(Required, ') }}<a href="https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices" target="_blank">{{ t('click to get') }}</a>{{ t(')') }}</span></label>
            <el-input
              v-model="form.speechRegion"
              :placeholder="t('Enter service region')"
              class="form-input"
            />
          </div>

          <div class="form-item">
            <label class="form-label">{{ t('API Key') }} <span style="color: blue;">{{ t('(Required, either key 1 or key 2 ') }}<a href="https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/SpeechServices" target="_blank">{{ t('click to get') }}</a>{{ t(')') }}</span></label>
            <el-input
              v-model="form.speechKey"
              :placeholder="t('Enter API Key')"
              type="password"
              show-password
              class="form-input"
            />
          </div>
        </div>

        <div v-if="form.ttsServer === 'siliconflow'" class="siliconflow-settings">
          <div class="form-item">
            <label class="form-label">{{ t('SiliconFlow API Key') }} <a href="https://cloud.siliconflow.cn/account/ak" target="_blank">{{ t('click to get') }}</a></label>
            <el-input
              v-model="form.siliconflowApiKey"
              :placeholder="t('Enter API key')"
              type="password"
              show-password
              class="form-input"
            />
          </div>

          <div class="form-item">
            <el-alert
              :title="t('SiliconFlow TTS Settings:')"
              type="info"
              :closable="false"
            >
              <ul>
                <li>{{ t('Speech rate range [0.25, 4.0], default value is 1.0') }}</li>
                <li>{{ t('Volume: Use speaking volume setting, default value 1.0 corresponds to gain 0') }}</li>
              </ul>
            </el-alert>
          </div>
        </div>

        <div v-if="form.ttsServer === 'coze-tts'" class="coze-settings-panel">
          <div class="form-item">
            <label class="form-label">{{ t('Coze API Key') }}</label>
            <el-input
              v-model="form.cozeApiKey"
              :placeholder="t('Enter API Key')"
              type="password"
              show-password
              class="form-input"
            />
          </div>

          <div class="form-item">
            <el-alert
              :title="t('Coze TTS Settings:')"
              type="info"
              :closable="false"
            >
              <ul>
                <li>{{ t('Speech rate range [0.5, 2.0], default value is 1.0') }}</li>
                <li>{{ t('Volume range [0.1, 2.0], default value is 1.0') }}</li>
                <li>{{ t('Get API Key from') }} <a href="https://www.coze.cn" target="_blank">https://www.coze.cn</a></li>
              </ul>
            </el-alert>
          </div>
        </div>

        <div class="form-item">
          <label class="form-label">{{ t('Speaking Volume (1.0 means 100%)') }}</label>
          <el-select v-model="form.speechVolume" :placeholder="t('Select volume')" class="form-select">
            <el-option label="0.0" value="0.0" />
            <el-option label="0.1" value="0.1" />
            <el-option label="0.2" value="0.2" />
            <el-option label="0.3" value="0.3" />
            <el-option label="0.4" value="0.4" />
            <el-option label="0.5" value="0.5" />
            <el-option label="0.6" value="0.6" />
            <el-option label="0.7" value="0.7" />
            <el-option label="0.8" value="0.8" />
            <el-option label="0.9" value="0.9" />
            <el-option label="1.0" value="1.0" />
            <el-option label="1.1" value="1.1" />
            <el-option label="1.2" value="1.2" />
            <el-option label="1.3" value="1.3" />
            <el-option label="1.4" value="1.4" />
            <el-option label="1.5" value="1.5" />
            <el-option label="1.6" value="1.6" />
            <el-option label="1.7" value="1.7" />
            <el-option label="1.8" value="1.8" />
            <el-option label="1.9" value="1.9" />
            <el-option label="2.0" value="2.0" />
          </el-select>
        </div>

        <div class="form-item">
          <label class="form-label">{{ t('Speaking Rate (1.0 means normal speed)') }}</label>
          <el-select v-model="form.speechRate" :placeholder="t('Select rate')" class="form-select">
            <el-option label="0.5" value="0.5" />
            <el-option label="0.6" value="0.6" />
            <el-option label="0.7" value="0.7" />
            <el-option label="0.8" value="0.8" />
            <el-option label="0.9" value="0.9" />
            <el-option label="1.0" value="1.0" />
            <el-option label="1.1" value="1.1" />
            <el-option label="1.2" value="1.2" />
            <el-option label="1.3" value="1.3" />
            <el-option label="1.4" value="1.4" />
            <el-option label="1.5" value="1.5" />
            <el-option label="1.6" value="1.6" />
            <el-option label="1.7" value="1.7" />
            <el-option label="1.8" value="1.8" />
            <el-option label="1.9" value="1.9" />
            <el-option label="2.0" value="2.0" />
          </el-select>
        </div>

        <div class="form-item">
          <label class="form-label">{{ t('Background Music') }}</label>
          <el-select v-model="form.backgroundMusic" :placeholder="t('Select background music')" class="form-select">
            <el-option :label="t('No Background Music')" value="none" />
            <el-option :label="t('Random Background Music')" value="random" />
            <el-option :label="t('Custom Background Music')" value="custom" />
          </el-select>
        </div>

        <div v-if="form.backgroundMusic === 'custom'" class="form-item">
          <el-upload
            ref="bgmUploadRef"
            class="bgm-uploader"
            :auto-upload="false"
            :limit="1"
            :on-change="handleBgmChange"
            accept=".mp3,.wav,.ogg"
          >
            <el-button type="primary" size="small">{{ t('Upload Background Music') }}</el-button>
            <template #tip>
              <div class="el-upload__tip">{{ t('Only MP3, WAV, OGG files less than 50MB') }}</div>
            </template>
          </el-upload>
        </div>

        <div class="form-item">
          <label class="form-label">{{ t('Background Music Volume') }}</label>
          <el-select v-model="form.backgroundMusicVolume" :placeholder="t('Select volume')" class="form-select">
            <el-option label="0.0" value="0.0" />
            <el-option label="0.1" value="0.1" />
            <el-option label="0.2" value="0.2" />
            <el-option label="0.3" value="0.3" />
            <el-option label="0.4" value="0.4" />
            <el-option label="0.5" value="0.5" />
            <el-option label="0.6" value="0.6" />
            <el-option label="0.7" value="0.7" />
            <el-option label="0.8" value="0.8" />
            <el-option label="0.9" value="0.9" />
            <el-option label="1.0" value="1.0" />
          </el-select>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue';
import { ElMessage } from 'element-plus';
import { useI18nStore } from '../stores/i18n';
import { useSettingsStore } from '../stores/settings';
import { apiService } from '../services/api';

const i18nStore = useI18nStore();
const t = i18nStore.t;

const settingsStore = useSettingsStore();

const form = reactive({
  ttsServer: settingsStore.audio.ttsServer,
  speechSynthesis: settingsStore.audio.speechSynthesis,
  speechRegion: settingsStore.audio.speechRegion,
  speechKey: settingsStore.audio.speechKey,
  siliconflowApiKey: settingsStore.audio.siliconflowApiKey,
  cozeApiKey: settingsStore.audio.cozeApiKey,
  voiceEmotion: settingsStore.audio.voiceEmotion,
  speechVolume: settingsStore.audio.speechVolume,
  speechRate: settingsStore.audio.speechRate,
  backgroundMusic: settingsStore.audio.backgroundMusic,
  backgroundMusicVolume: settingsStore.audio.backgroundMusicVolume
});

const searchKeyword = ref('');
const loadingVoices = ref(false);
const refreshingVoices = ref(false);
const testingVoice = ref(false);
const audioUrl = ref('');
const bgmFile = ref<File | null>(null);
const bgmUploadRef = ref();

const allVoices = ref<string[]>([]);

interface Voice {
  label: string;
  value: string;
  supportsEmotion?: boolean;
  emotions?: string[];
  previewText?: string;
  previewAudio?: string;
}

const voiceList = computed<Voice[]>(() => {
  const voices: Voice[] = [];
  for (const v of allVoices.value) {
    if (v.startsWith('coze|')) {
      const parts = v.split('|');
      if (parts.length >= 3) {
        const voiceNameGender = parts[2];
        let label = voiceNameGender.replace('Female', t('Female')).replace('Male', t('Male'));
        const emotions: string[] = [];
        let supportsEmotion = false;

        if (parts.length >= 6 && parts[5]) {
          const emotionParts = parts[5].split(',');
          for (const ep of emotionParts) {
            if (ep.trim()) {
              emotions.push(ep.trim());
              supportsEmotion = true;
            }
          }
        }

        voices.push({
          label,
          value: v,
          supportsEmotion,
          emotions,
          previewText: parts.length >= 5 ? parts[4] : '',
          previewAudio: parts.length >= 4 ? parts[3] : ''
        });
      }
    } else if (v.startsWith('siliconflow:')) {
      const parts = v.split(':');
      if (parts.length >= 3) {
        const voiceWithGender = parts[2];
        const label = voiceWithGender.replace('Female', t('Female')).replace('Male', t('Male'));
        voices.push({ label, value: v });
      }
    } else if (v.startsWith('gemini:')) {
      const parts = v.split(':');
      if (parts.length >= 2) {
        const voiceWithGender = parts[1];
        const label = voiceWithGender.replace('Female', t('Female')).replace('Male', t('Male'));
        voices.push({ label, value: v });
      }
    } else {
      const label = v.replace('Female', t('Female')).replace('Male', t('Male')).replace('Neural', '').replace('-V2', ' V2');
      voices.push({ label, value: v });
    }
  }
  return voices;
});

const filteredVoiceList = computed(() => {
  if (!searchKeyword.value) {
    return voiceList.value;
  }
  const keyword = searchKeyword.value.toLowerCase();
  return voiceList.value.filter((voice: Voice) =>
    voice.label.toLowerCase().includes(keyword)
  );
});

const currentVoice = computed(() => {
  return voiceList.value.find((v: Voice) => v.value === form.speechSynthesis);
});

const currentVoiceSupportsEmotion = computed(() => {
  return currentVoice.value?.supportsEmotion || false;
});

const currentVoiceEmotions = computed(() => {
  if (!currentVoice.value?.emotions) {
    return [];
  }
  return currentVoice.value.emotions.map((e: string) => {
    const parts = e.split('-');
    return {
      value: parts[0],
      label: e
    };
  });
});

const getVoiceId = (voiceValue: string): string => {
  if (voiceValue.startsWith('coze|')) {
    const parts = voiceValue.split('|');
    return parts.length >= 2 ? parts[1] : voiceValue;
  }
  return voiceValue;
};

const loadVoices = async (forceRefresh: boolean = false) => {
  loadingVoices.value = true;
  try {
    const response = await apiService.getVoices(form.ttsServer, forceRefresh);
    if (response.status === 200 && response.data?.voices) {
      allVoices.value = response.data.voices;
      // Check if current speechSynthesis is valid for this TTS server
      if (allVoices.value.length > 0) {
        const isValidVoice = allVoices.value.includes(form.speechSynthesis);
        
        if (!form.speechSynthesis || !isValidVoice) {
          // For Coze voices, try to match by voice ID (since URL changes)
          const savedVoiceId = getVoiceId(form.speechSynthesis);
          const matchingVoice = allVoices.value.find(v => getVoiceId(v) === savedVoiceId);
          
          if (matchingVoice) {
            form.speechSynthesis = matchingVoice;
          } else {
            form.speechSynthesis = allVoices.value[0];
          }
        }
      }
    }
  } catch (error: any) {
    console.error('Failed to load voices:', error);
    ElMessage.error(t('Failed to load voice list'));
  } finally {
    loadingVoices.value = false;
  }
};

const loadConfig = async () => {
  try {
    const response = await apiService.getConfig();
    if (response.status === 200 && response.data) {
      const cfg = response.data;
      if (cfg.ui) {
        if (cfg.ui.tts_server) {
          form.ttsServer = cfg.ui.tts_server;
        }
        if (cfg.ui.voice_name) {
          form.speechSynthesis = cfg.ui.voice_name;
        }
        if (cfg.ui.voice_volume !== undefined) {
          form.speechVolume = String(cfg.ui.voice_volume);
        }
        if (cfg.ui.voice_rate !== undefined) {
          form.speechRate = String(cfg.ui.voice_rate);
        }
        if (cfg.ui.bgm_type !== undefined) {
          form.backgroundMusic = cfg.ui.bgm_type === '' ? 'none' : cfg.ui.bgm_type;
        }
        if (cfg.ui.bgm_volume !== undefined) {
          form.backgroundMusicVolume = String(cfg.ui.bgm_volume);
        }
      }
      if (cfg.azure) {
        form.speechRegion = cfg.azure.speech_region || '';
        form.speechKey = cfg.azure.speech_key || '';
      }
      if (cfg.siliconflow) {
        form.siliconflowApiKey = cfg.siliconflow.api_key || '';
      }
      if (cfg.coze) {
        form.cozeApiKey = cfg.coze.api_key || '';
      }
    }
  } catch (error: any) {
    console.error('Failed to load config:', error);
  }
};

const saveConfig = async () => {
  try {
    const cfg = {
      ui: {
        tts_server: form.ttsServer,
        voice_name: form.speechSynthesis,
        voice_volume: parseFloat(form.speechVolume),
        voice_rate: parseFloat(form.speechRate),
        bgm_type: form.backgroundMusic === 'none' ? '' : form.backgroundMusic,
        bgm_volume: parseFloat(form.backgroundMusicVolume)
      },
      azure: {
        speech_region: form.speechRegion,
        speech_key: form.speechKey
      },
      siliconflow: {
        api_key: form.siliconflowApiKey
      },
      coze: {
        api_key: form.cozeApiKey
      }
    };
    await apiService.updateConfig(cfg);
    console.log('[AudioSettings] Config saved:', cfg);
  } catch (error: any) {
    console.error('Failed to save config:', error);
  }
};

const refreshCozeVoices = async () => {
  refreshingVoices.value = true;
  try {
    await loadVoices(true);
    ElMessage.success(t('Coze voice list refreshed'));
  } finally {
    refreshingVoices.value = false;
  }
};

const testVoice = async () => {
  if (!form.speechSynthesis) {
    ElMessage.warning(t('Please select a voice first'));
    return;
  }

  testingVoice.value = true;
  audioUrl.value = '';

  try {
    let text = '';
    if (currentVoice.value?.previewText) {
      text = currentVoice.value.previewText;
    }
    if (!text) {
      text = t('Voice Example');
    }

    const blob = await apiService.previewAudio({
      text,
      voice_name: form.speechSynthesis,
      voice_rate: parseFloat(form.speechRate),
      voice_volume: parseFloat(form.speechVolume),
      voice_emotion: form.voiceEmotion
    });

    if (blob) {
      audioUrl.value = URL.createObjectURL(blob);
    }
  } catch (error: any) {
    console.error('Failed to test voice:', error);
    ElMessage.error(t('Failed to generate voice preview'));
  } finally {
    testingVoice.value = false;
  }
};

const handleBgmChange = (file: any) => {
  bgmFile.value = file.raw;
};

const onTtsServerChange = () => {
  form.speechSynthesis = '';
  form.voiceEmotion = '';
  searchKeyword.value = '';
  loadVoices();
};

watch([
  () => form.ttsServer,
  () => form.speechSynthesis,
  () => form.speechRegion,
  () => form.speechKey,
  () => form.siliconflowApiKey,
  () => form.cozeApiKey,
  () => form.voiceEmotion,
  () => form.speechVolume,
  () => form.speechRate,
  () => form.backgroundMusic,
  () => form.backgroundMusicVolume
], () => {
  saveConfig();
  settingsStore.updateAudioSetting('ttsServer', form.ttsServer);
  settingsStore.updateAudioSetting('speechSynthesis', form.speechSynthesis);
  settingsStore.updateAudioSetting('speechRegion', form.speechRegion);
  settingsStore.updateAudioSetting('speechKey', form.speechKey);
  settingsStore.updateAudioSetting('siliconflowApiKey', form.siliconflowApiKey);
  settingsStore.updateAudioSetting('cozeApiKey', form.cozeApiKey);
  settingsStore.updateAudioSetting('voiceEmotion', form.voiceEmotion);
  settingsStore.updateAudioSetting('speechVolume', form.speechVolume);
  settingsStore.updateAudioSetting('speechRate', form.speechRate);
  settingsStore.updateAudioSetting('backgroundMusic', form.backgroundMusic);
  settingsStore.updateAudioSetting('backgroundMusicVolume', form.backgroundMusicVolume);
});

watch(() => settingsStore.audio, (newAudio) => {
  console.log('[AudioSettings] Store audio changed, updating form:', newAudio);
  form.ttsServer = newAudio.ttsServer;
  form.speechSynthesis = newAudio.speechSynthesis;
  form.speechRegion = newAudio.speechRegion;
  form.speechKey = newAudio.speechKey;
  form.siliconflowApiKey = newAudio.siliconflowApiKey;
  form.cozeApiKey = newAudio.cozeApiKey;
  form.voiceEmotion = newAudio.voiceEmotion;
  form.speechVolume = newAudio.speechVolume;
  form.speechRate = newAudio.speechRate;
  form.backgroundMusic = newAudio.backgroundMusic;
  form.backgroundMusicVolume = newAudio.backgroundMusicVolume;
}, { deep: true });

watch(() => form.speechSynthesis, () => {
  // Clear audio URL when voice changes
  audioUrl.value = '';
  if (!currentVoiceSupportsEmotion.value) {
    form.voiceEmotion = '';
  } else if (!form.voiceEmotion && currentVoiceEmotions.value.length > 0) {
    form.voiceEmotion = currentVoiceEmotions.value[0].value;
  }
});

onMounted(async () => {
  await loadConfig();
  await loadVoices();
});

defineExpose({
  form,
  bgmFile
});
</script>

<style scoped>
.audio-settings {
  width: 100%;
}

.card-header {
  margin-bottom: 4px;
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
}

.form-input {
  width: 100%;
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

.audio-preview {
  width: 100%;
  margin-top: 8px;
}

.coze-settings {
  background-color: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
}

.coze-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.azure-v2-settings,
.siliconflow-settings {
  border: 1px solid #dcdfe6;
  padding: 12px;
  border-radius: 4px;
  margin-top: 8px;
}

.coze-settings-panel {
  margin-top: 8px;
}

.coze-settings-panel .form-item {
  margin-bottom: 16px;
}

.coze-settings-panel .el-alert {
  width: 100%;
  box-sizing: border-box;
}

.bgm-uploader {
  width: 100%;
}
</style>