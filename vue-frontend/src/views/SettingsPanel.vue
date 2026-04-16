<template>
  <div class="settings-panel">
    <el-dialog
      v-model="visible"
      title="Settings"
      width="800px"
      destroy-on-close
    >
      <el-card :body-style="{ padding: '20px' }">
        <template #header>
          <span>Basic Settings</span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <!-- Basic Settings -->
          <el-form-item label="Hide Basic Settings">
            <el-switch v-model="form.hideConfig" />
          </el-form-item>
          
          <el-form-item label="Hide Log">
            <el-switch v-model="form.hideLog" />
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span>LLM Settings</span>
        </template>
        
        <el-alert
          title="Recommendation for Chinese Users"
          type="info"
          :closable="false"
          show-icon
          class="mb-4"
        >
          <p>We recommend using <strong style="color: #ff4d4f;">DeepSeek</strong> or <strong style="color: #ff4d4f;">Moonshot</strong> as your LLM provider</p>
          <p>- Accessible directly in China without VPN</p>
          <p>- Free credits upon registration, generally sufficient for use</p>
        </el-alert>
        
        <el-form :model="form" label-width="150px">
          <el-form-item label="LLM Provider">
            <el-select v-model="form.llmProvider" @change="handleLLMProviderChange">
              <el-option v-for="provider in llmProviders" :key="provider.value" :label="provider.label" :value="provider.value" />
            </el-select>
          </el-form-item>
          
          <el-form-item label="API Key">
            <el-input v-model="form.llmApiKey" type="password" />
          </el-form-item>
          
          <el-form-item label="Base Url">
            <el-input v-model="form.llmBaseUrl" />
          </el-form-item>
          
          <el-form-item label="Model Name" v-if="form.llmProvider !== 'ernie'">
            <el-input v-model="form.llmModelName" />
          </el-form-item>
          
          <el-form-item label="Secret Key" v-if="form.llmProvider === 'ernie'">
            <el-input v-model="form.llmSecretKey" type="password" />
          </el-form-item>
          
          <el-form-item label="Account ID" v-if="form.llmProvider === 'cloudflare'">
            <el-input v-model="form.llmAccountId" />
          </el-form-item>
          
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
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span>Video Source Settings</span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item label="Pexels API Key">
            <el-input v-model="form.pexelsApiKey" type="password" />
          </el-form-item>
          
          <el-form-item label="Pixabay API Key">
            <el-input v-model="form.pixabayApiKey" type="password" />
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span>Whisper Settings</span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item label="Whisper Device">
            <el-select v-model="form.whisperDevice">
              <el-option label="CPU" value="CPU" />
              <el-option label="GPU" value="GPU" />
              <el-option label="Auto" value="auto" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-card>
      
      <el-card :body-style="{ padding: '20px' }" class="mt-4">
        <template #header>
          <span>Video Encoder Settings</span>
        </template>
        
        <el-form :model="form" label-width="150px">
          <el-form-item label="Video Encoder">
            <el-select v-model="form.videoEncoder">
              <el-option label="CPU" value="CPU" />
              <el-option label="GPU" value="GPU" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-card>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="visible = false">Cancel</el-button>
          <el-button type="primary" @click="saveSettings">Save</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, computed, onMounted } from 'vue';
import { useSettingsStore } from '../stores/settings';

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

const settingsStore = useSettingsStore();

const form = reactive({
  hideConfig: false,
  hideLog: false,
  llmProvider: 'openai',
  llmApiKey: '',
  llmBaseUrl: '',
  llmModelName: '',
  llmSecretKey: '',
  llmAccountId: '',
  pexelsApiKey: '',
  pixabayApiKey: '',
  whisperDevice: 'CPU',
  videoEncoder: 'CPU'
});

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
  
  switch (provider) {
    case 'ollama':
      return {
        title: 'Ollama Configuration',
        type: 'info',
        content: `
          <p><strong>API Key:</strong>随便填写，比如 123</p>
          <p><strong>Base Url:</strong>一般为 http://localhost:11434/v1</p>
          <p>- 如果 MoneyPrinterTurbo 和 Ollama 不在同一台机器上，需要填写 Ollama 机器的IP地址</p>
          <p>- 如果 MoneyPrinterTurbo 是 Docker 部署，建议填写 http://host.docker.internal:11434/v1</p>
          <p><strong>Model Name:</strong>使用 ollama list 查看，比如 qwen:7b</p>
        `
      };
    case 'openai':
      return {
        title: 'OpenAI Configuration',
        type: 'info',
        content: `
          <p><strong>需要VPN开启全局流量模式</strong></p>
          <p><strong>API Key:</strong><a href="https://platform.openai.com/api-keys" target="_blank">点击到官网申请</a></p>
          <p><strong>Base Url:</strong>可以留空</p>
          <p><strong>Model Name:</strong>填写有权限的模型，<a href="https://platform.openai.com/settings/organization/limits" target="_blank">点击查看模型列表</a></p>
        `
      };
    case 'moonshot':
      return {
        title: 'Moonshot Configuration',
        type: 'info',
        content: `
          <p><strong>API Key:</strong><a href="https://platform.moonshot.cn/console/api-keys" target="_blank">点击到官网申请</a></p>
          <p><strong>Base Url:</strong>固定为 https://api.moonshot.cn/v1</p>
          <p><strong>Model Name:</strong>比如 moonshot-v1-8k，<a href="https://platform.moonshot.cn/docs/intro#%E6%A8%A1%E5%9E%8B%E5%88%97%E8%A1%A8" target="_blank">点击查看模型列表</a></p>
        `
      };
    case 'deepseek':
      return {
        title: 'DeepSeek Configuration',
        type: 'info',
        content: `
          <p><strong>API Key:</strong><a href="https://platform.deepseek.com/api_keys" target="_blank">点击到官网申请</a></p>
          <p><strong>Base Url:</strong>固定为 https://api.deepseek.com</p>
          <p><strong>Model Name:</strong>固定为 deepseek-chat</p>
        `
      };
    default:
      return null;
  }
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

const saveSettings = () => {
  // Save settings to state management
  settingsStore.updateAppSetting('hideConfig', form.hideConfig);
  settingsStore.updateUISetting('hideLog', form.hideLog);
  settingsStore.updateAppSetting('llmProvider', form.llmProvider);
  
  // Save LLM configuration
  settingsStore.updateLLMSetting(form.llmProvider, 'apiKey', form.llmApiKey);
  settingsStore.updateLLMSetting(form.llmProvider, 'baseUrl', form.llmBaseUrl);
  if (form.llmProvider !== 'ernie') {
    settingsStore.updateLLMSetting(form.llmProvider, 'modelName', form.llmModelName);
  }
  
  // Save video source configuration
  settingsStore.updateVideoSourceSetting('pexels', form.pexelsApiKey.split(',').map(key => key.trim()).filter(Boolean));
  settingsStore.updateVideoSourceSetting('pixabay', form.pixabayApiKey.split(',').map(key => key.trim()).filter(Boolean));
  
  // Save Whisper configuration
  settingsStore.updateWhisperSetting('device', form.whisperDevice);
  
  // Save video encoder configuration
  settingsStore.updateAppSetting('useGpu', form.videoEncoder === 'GPU');
  
  // Save to local storage
  settingsStore.saveToLocalStorage();
  
  // Close dialog
  visible.value = false;
  
  // Trigger settings saved event
  emit('settings-saved');
};

onMounted(() => {
  // Load settings from state management
  form.hideConfig = settingsStore.app.hideConfig;
  form.hideLog = settingsStore.ui.hideLog;
  form.llmProvider = settingsStore.app.llmProvider;
  
  // Load LLM configuration
  const llmConfig = settingsStore.getLLMConfig(form.llmProvider);
  form.llmApiKey = llmConfig.apiKey;
  form.llmBaseUrl = llmConfig.baseUrl;
  form.llmModelName = llmConfig.modelName;
  
  // Load video source configuration
  form.pexelsApiKey = settingsStore.getVideoSourceConfig('pexels').join(', ');
  form.pixabayApiKey = settingsStore.getVideoSourceConfig('pixabay').join(', ');
  
  // Load Whisper configuration
  form.whisperDevice = settingsStore.whisper.device;
  
  // Load video encoder configuration
  form.videoEncoder = settingsStore.app.useGpu ? 'GPU' : 'CPU';
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
</style>