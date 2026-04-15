import { defineStore } from 'pinia';

interface LLMConfig {
  apiKey: string;
  baseUrl: string;
  modelName: string;
}

interface LLMConfigs {
  [key: string]: LLMConfig;
  openai: LLMConfig;
  moonshot: LLMConfig;
  deepseek: LLMConfig;
}

interface AppSettings {
  llmProvider: string;
  videoSource: string;
  useGpu: boolean;
  hideConfig: boolean;
}

interface VideoSources {
  pexelsApiKeys: string[];
  pixabayApiKeys: string[];
}

interface WhisperSettings {
  device: string;
}

interface UISettings {
  language: string;
  hideLog: boolean;
}

export const useSettingsStore = defineStore('settings', {
  state: (): {
    app: AppSettings;
    llm: LLMConfigs;
    videoSources: VideoSources;
    whisper: WhisperSettings;
    ui: UISettings;
  } => ({
    // 应用设置
    app: {
      llmProvider: 'openai',
      videoSource: 'pexels',
      useGpu: false,
      hideConfig: false
    },
    
    // LLM配置
    llm: {
      openai: {
        apiKey: '',
        baseUrl: '',
        modelName: 'gpt-3.5-turbo'
      },
      moonshot: {
        apiKey: '',
        baseUrl: 'https://api.moonshot.cn/v1',
        modelName: 'moonshot-v1-8k'
      },
      deepseek: {
        apiKey: '',
        baseUrl: 'https://api.deepseek.com',
        modelName: 'deepseek-chat'
      }
    },
    
    // 视频源配置
    videoSources: {
      pexelsApiKeys: [],
      pixabayApiKeys: []
    },
    
    // Whisper配置
    whisper: {
      device: 'CPU'
    },
    
    // UI配置
    ui: {
      language: 'zh',
      hideLog: false
    }
  }),
  
  getters: {
    getLLMConfig: (state) => (provider: string) => {
      return state.llm[provider as keyof typeof state.llm] || {};
    },
    
    getVideoSourceConfig: (state) => (source: string) => {
      if (source === 'pexels') {
        return state.videoSources.pexelsApiKeys;
      } else if (source === 'pixabay') {
        return state.videoSources.pixabayApiKeys;
      }
      return [];
    }
  },
  
  actions: {
    updateAppSetting<K extends keyof AppSettings>(key: K, value: AppSettings[K]) {
      this.app[key] = value;
    },
    
    updateLLMSetting<P extends keyof LLMConfigs, K extends keyof LLMConfig>(provider: P, key: K, value: LLMConfig[K]) {
      if (this.llm[provider]) {
        this.llm[provider][key] = value;
      }
    },
    
    updateVideoSourceSetting(source: string, keys: string[]) {
      if (source === 'pexels') {
        this.videoSources.pexelsApiKeys = keys;
      } else if (source === 'pixabay') {
        this.videoSources.pixabayApiKeys = keys;
      }
    },
    
    updateWhisperSetting<K extends keyof WhisperSettings>(key: K, value: WhisperSettings[K]) {
      this.whisper[key] = value;
    },
    
    updateUISetting<K extends keyof UISettings>(key: K, value: UISettings[K]) {
      this.ui[key] = value;
    },
    
    loadFromLocalStorage() {
      const savedSettings = localStorage.getItem('moneyprinter-settings');
      if (savedSettings) {
        try {
          const parsed = JSON.parse(savedSettings);
          Object.assign(this, parsed);
        } catch (e) {
          console.error('Failed to load settings from localStorage:', e);
        }
      }
    },
    
    saveToLocalStorage() {
      localStorage.setItem('moneyprinter-settings', JSON.stringify(this));
    }
  }
});