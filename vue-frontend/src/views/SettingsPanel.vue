<template>
  <div class="settings-panel">
    <el-dialog
      v-model="visible"
      :title="t('Settings')"
      width="800px"
      destroy-on-close
    >
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('LLM Settings')"></span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item :label="t('LLM Provider')">
            <el-select v-model="form.llmProvider" @change="handleLLMProviderChange">
              <el-option v-for="provider in llmProviders" :key="provider.value" :label="provider.label" :value="provider.value" />
            </el-select>
          </el-form-item>
        </el-form>
        
        <el-alert
          :title="t('LLM Provider Recommendation')"
          type="info"
          :closable="false"
          show-icon
          class="mb-4"
        >
          <p v-html="t('LLM Provider Recommendation Content')"></p>
        </el-alert>
        
        <div v-if="llmTips" class="llm-tips">
          <el-alert
            :title="llmTips.title"
            :type="llmTips.type"
            :closable="false"
            show-icon
          >
            <div v-html="llmTips.content"></div>
          </el-alert>
        </div>
        
        <el-form :model="form" label-width="150px">
          
          <el-form-item>
            <template #label>
              <span>{{ t('API Key') }} <span style="color: red;">*</span></span>
            </template>
            <el-input v-model="form.llmApiKey" type="password" />
          </el-form-item>
          
          <el-form-item :label="t('Base Url')">
            <el-input v-model="form.llmBaseUrl" />
          </el-form-item>
          
          <el-form-item v-if="form.llmProvider !== 'ernie'">
            <template #label>
              <el-tooltip :content="t('Model Name Tooltip')" placement="top">
                <span>{{ t('Model Name') }}</span>
              </el-tooltip>
            </template>
            <el-input v-model="form.llmModelName" />
          </el-form-item>
          
          <el-form-item :label="t('Secret Key')" v-if="form.llmProvider === 'ernie'">
            <el-input v-model="form.llmSecretKey" type="password" />
          </el-form-item>
          
          <el-form-item :label="t('Account ID')" v-if="form.llmProvider === 'cloudflare'">
            <el-input v-model="form.llmAccountId" />
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Video Source Settings')"></span>
        </template>
        
        <el-form :model="form" label-position="top">
          <el-form-item>
            <template #label>
              <span v-html="t('Pexels API Key')"></span>
            </template>
            <div v-for="(_, index) in form.pexelsApiKeys" :key="index" class="api-key-input-group">
              <el-input v-model="form.pexelsApiKeys[index]" type="password">
                <template #append>
                  <el-button 
                    v-if="form.pexelsApiKeys.length > 1" 
                    type="danger" 
                    circle 
                    @click="removePexelsApiKey(index)"
                  >
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-input>
            </div>
            <el-button type="primary" plain @click="addPexelsApiKey" class="mt-2">
              <el-icon><Plus /></el-icon>
              {{ t('Add') }}
            </el-button>
          </el-form-item>
          
          <el-form-item>
            <template #label>
              <span v-html="t('Pixabay API Key')"></span>
            </template>
            <div v-for="(_, index) in form.pixabayApiKeys" :key="index" class="api-key-input-group">
              <el-input v-model="form.pixabayApiKeys[index]" type="password">
                <template #append>
                  <el-button 
                    v-if="form.pixabayApiKeys.length > 1" 
                    type="danger" 
                    circle 
                    @click="removePixabayApiKey(index)"
                  >
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-input>
            </div>
            <el-button type="primary" plain @click="addPixabayApiKey" class="mt-2">
              <el-icon><Plus /></el-icon>
              {{ t('Add') }}
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Whisper Settings')"></span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item :label="t('Whisper Device')">
            <el-select v-model="form.whisperDevice">
              <el-option :label="t('CPU')" value="CPU" />
              <el-option :label="t('GPU')" value="GPU" />
              <el-option :label="t('Auto')" value="auto" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span v-html="t('Video Encoder Settings')"></span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item :label="t('Video Encoder')">
            <el-select v-model="form.videoEncoder">
              <el-option :label="t('CPU')" value="CPU" />
              <el-option :label="t('GPU')" value="GPU" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-card>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="visible = false">{{ t('Cancel') }}</el-button>
          <el-button type="primary" @click="saveSettings">{{ t('Save') }}</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed, onMounted } from 'vue';
import { useSettingsStore } from '../stores/settings';
import { useI18nStore } from '../stores/i18n';
import { Delete, Plus } from '@element-plus/icons-vue';
import { apiService } from '../services/api';

const props = defineProps<{
  visible: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void;
  (e: 'settings-saved'): void;
}>();

const visible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value)
});

const i18nStore = useI18nStore();
const t = computed(() => i18nStore.t);

const settingsStore = useSettingsStore();

const form = reactive({
  llmProvider: 'openai',
  llmApiKey: '',
  llmBaseUrl: '',
  llmModelName: '',
  llmSecretKey: '',
  llmAccountId: '',
  pexelsApiKeys: [''],
  pixabayApiKeys: [''],
  whisperDevice: 'CPU',
  videoEncoder: 'CPU'
});

// API Key management methods
const addPexelsApiKey = () => {
  form.pexelsApiKeys.push('');
};

const removePexelsApiKey = (index: number) => {
  if (form.pexelsApiKeys.length > 1) {
    form.pexelsApiKeys.splice(index, 1);
  }
};

const addPixabayApiKey = () => {
  form.pixabayApiKeys.push('');
};

const removePixabayApiKey = (index: number) => {
  if (form.pixabayApiKeys.length > 1) {
    form.pixabayApiKeys.splice(index, 1);
  }
};

const llmProviders = [
  { label: 'OpenAI', value: 'openai' },
  { label: 'Moonshot', value: 'moonshot' },
  { label: 'Azure', value: 'azure' },
  { label: 'Qwen', value: 'qwen' },
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'ModelScope', value: 'modelscope' },
  { label: 'Gemini', value: 'gemini' },
  { label: 'Ollama', value: 'ollama' },
  { label: 'G4f', value: 'g4f' },
  { label: 'OneAPI', value: 'oneapi' },
  { label: 'Cloudflare', value: 'cloudflare' },
  { label: 'ERNIE', value: 'ernie' },
  { label: 'Pollinations', value: 'pollinations' }
];

const llmTips = computed(() => {
  const provider = form.llmProvider;
  let title = '';
  let content = '';
  
  switch (provider) {
    case 'deepseek':
      title = t.value('DeepSeek Configuration');
      content = `
        <p>${t.value('API Key')}: ${t.value('DeepSeek API Key Tip').replace('API Key: ', '')}</p>
        <p>${t.value('Base Url')}: ${t.value('DeepSeek Base Url Tip').replace('Base Url: ', '')}</p>
        <p>${t.value('Model Name')}: ${t.value('DeepSeek Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    case 'moonshot':
      title = t.value('Moonshot Configuration');
      content = `
        <p>${t.value('API Key')}: ${t.value('Moonshot API Key Tip').replace('API Key: ', '')}</p>
        <p>${t.value('Base Url')}: ${t.value('Moonshot Base Url Tip').replace('Base Url: ', '')}</p>
        <p>${t.value('Model Name')}: ${t.value('Moonshot Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    case 'openai':
      title = t.value('OpenAI Configuration');
      content = `
        <p>${t.value('OpenAI VPN Tip')}</p>
        <p>${t.value('API Key')}: ${t.value('OpenAI API Key Tip').replace('API Key: ', '')}</p>
        <p>${t.value('Base Url')}: ${t.value('OpenAI Base Url Tip').replace('Base Url: ', '')}</p>
        <p>${t.value('Model Name')}: ${t.value('OpenAI Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    case 'ollama':
      title = t.value('Ollama Configuration');
      content = `
        <p>${t.value('API Key')}: ${t.value('Ollama API Key Tip').replace('API Key: ', '')}</p>
        <p>${t.value('Base Url')}: ${t.value('Ollama Base Url Tip').replace('Base Url: ', '')}</p>
        <p>- ${t.value('Ollama Base Url Tip 2')}</p>
        <p>- ${t.value('Ollama Base Url Tip 3')}</p>
        <p>${t.value('Model Name')}: ${t.value('Ollama Model Name Tip').replace('Model Name: ', '')}</p>
      `;
      break;
    default:
      title = t.value('LLM Configuration');
      content = `
        <p>${t.value('API Key')}: ${t.value('Please Enter LLM API Key')}</p>
        <p>${t.value('Base Url')}: ${t.value('Base Url Tooltip')}</p>
        <p>${t.value('Model Name')}: ${t.value('Model Name Tooltip')}</p>
      `;
  }
  
  return {
    title: title,
    type: 'info',
    content: content
  };
});

const handleLLMProviderChange = () => {
  // Set default values based on selected LLM provider
  const provider = form.llmProvider;
  
  switch (provider) {
    case 'ollama':
      form.llmModelName = 'qwen:7b';
      form.llmBaseUrl = 'http://localhost:11434/v1';
      break;
    case 'openai':
      form.llmModelName = 'gpt-3.5-turbo';
      form.llmBaseUrl = '';
      break;
    case 'moonshot':
      form.llmModelName = 'moonshot-v1-8k';
      form.llmBaseUrl = 'https://api.moonshot.cn/v1';
      break;
    case 'deepseek':
      form.llmModelName = 'deepseek-chat';
      form.llmBaseUrl = 'https://api.deepseek.com';
      break;
    case 'qwen':
      form.llmModelName = 'qwen-max';
      form.llmBaseUrl = '';
      break;
    case 'gemini':
      form.llmModelName = 'gemini-1.0-pro';
      form.llmBaseUrl = '';
      break;
    case 'modelscope':
      form.llmModelName = 'Qwen/Qwen3-32B';
      form.llmBaseUrl = 'https://api-inference.modelscope.cn/v1/';
      break;
    case 'g4f':
      form.llmModelName = 'gpt-3.5-turbo';
      form.llmBaseUrl = '';
      break;
    case 'oneapi':
      form.llmModelName = 'claude-3-5-sonnet-20240620';
      form.llmBaseUrl = '';
      break;
    default:
      form.llmModelName = '';
      form.llmBaseUrl = '';
  }
};

const saveSettings = async () => {
  try {
    // Save settings to state management
    settingsStore.updateAppSetting('llmProvider', form.llmProvider);

    // Save LLM configuration
    settingsStore.updateLLMSetting(form.llmProvider, 'apiKey', form.llmApiKey);
    settingsStore.updateLLMSetting(form.llmProvider, 'baseUrl', form.llmBaseUrl);
    if (form.llmProvider !== 'ernie') {
      settingsStore.updateLLMSetting(form.llmProvider, 'modelName', form.llmModelName);
    }

    // Save video source configuration
    const pexelsKeys = form.pexelsApiKeys.map(key => key.trim()).filter(Boolean);
    const pixabayKeys = form.pixabayApiKeys.map(key => key.trim()).filter(Boolean);
    settingsStore.updateVideoSourceSetting('pexels', pexelsKeys);
    settingsStore.updateVideoSourceSetting('pixabay', pixabayKeys);

    // Save Whisper configuration
    settingsStore.updateWhisperSetting('device', form.whisperDevice);

    // Save video encoder configuration
    settingsStore.updateAppSetting('useGpu', form.videoEncoder === 'GPU');

    // Build app config based on LLM provider
    const appConfig: Record<string, any> = {
      llm_provider: form.llmProvider,
      use_gpu: form.videoEncoder === 'GPU',
      pexels_api_keys: pexelsKeys,
      pixabay_api_keys: pixabayKeys
    };

    // Add LLM specific configs based on provider
    switch (form.llmProvider) {
      case 'openai':
        appConfig.openai_api_key = form.llmApiKey;
        appConfig.openai_base_url = form.llmBaseUrl;
        appConfig.openai_model_name = form.llmModelName;
        break;
      case 'moonshot':
        appConfig.moonshot_api_key = form.llmApiKey;
        appConfig.moonshot_base_url = form.llmBaseUrl;
        appConfig.moonshot_model_name = form.llmModelName;
        break;
      case 'deepseek':
        appConfig.deepseek_api_key = form.llmApiKey;
        appConfig.deepseek_base_url = form.llmBaseUrl;
        appConfig.deepseek_model_name = form.llmModelName;
        break;
    }

    // Prepare config object to send to backend
    const configToSave = {
      app: appConfig,
      whisper: {
        device: form.whisperDevice
      }
    };

    // Send config to backend
    await apiService.updateConfig(configToSave);

    // Save to local storage
    settingsStore.saveToLocalStorage();

    // Close dialog
    visible.value = false;

    // Trigger settings saved event
    emit('settings-saved');
  } catch (error) {
    console.error('Failed to save settings:', error);
  }
};

onMounted(async () => {
  try {
    // Fetch config from backend first
    await settingsStore.fetchConfig();
    
    // Load settings from state management
    form.llmProvider = settingsStore.app.llmProvider;
    
    // Load LLM configuration
    const llmConfig = settingsStore.getLLMConfig(form.llmProvider);
    form.llmApiKey = llmConfig.apiKey || '';
    form.llmBaseUrl = llmConfig.baseUrl || '';
    form.llmModelName = llmConfig.modelName || '';
    
    // Load video source configuration
    const pexelsKeys = settingsStore.getVideoSourceConfig('pexels');
    form.pexelsApiKeys = pexelsKeys.length > 0 ? pexelsKeys : [''];
    
    const pixabayKeys = settingsStore.getVideoSourceConfig('pixabay');
    form.pixabayApiKeys = pixabayKeys.length > 0 ? pixabayKeys : [''];
    
    // Load Whisper configuration
    form.whisperDevice = settingsStore.whisper.device || 'CPU';
    
    // Load video encoder configuration
    form.videoEncoder = settingsStore.app.useGpu ? 'GPU' : 'CPU';
  } catch (error) {
    console.error('Failed to load settings:', error);
  }
});
</script>

<style scoped>
.settings-panel {
  width: 100%;
}

.mt-4 {
  margin-top: 16px;
}

.llm-tips {
  margin-top: 16px;
}

.dialog-footer {
  width: 100%;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.api-key-input-group {
  margin-bottom: 12px;
  width: 100%;
}

.api-key-input-group:last-of-type {
  margin-bottom: 12px;
}

.api-key-input-group .el-input {
  width: 100%;
}

/* Style for input fields to match ui-setting.png */
.el-input__inner {
  background-color: #f5f5f5;
  border-color: #d9d9d9;
}

/* Style for LLM tips to match the blue box background */
.llm-tips {
  margin: 16px 0;
}

.llm-tips .el-alert {
  background-color: #e6f7ff;
  border-color: #91d5ff;
  border-radius: 4px;
}

/* Style for LLM provider recommendation to match the yellow box background */
.mb-4 {
  background-color: #fff7e6;
  border-color: #ffd591;
  border-radius: 4px;
}

.mt-2 {
  margin-top: 8px;
}
</style>