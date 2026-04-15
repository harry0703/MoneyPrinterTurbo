import { defineStore } from 'pinia';

export const useSettingsStore = defineStore('settings', {
  state: () => ({
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
    updateAppSetting(key: string, value: any) {
      this.app[key as keyof typeof this.app] = value;
    },
    
    updateLLMSetting(provider: string, key: string, value: any) {
      if (this.llm[provider as keyof typeof this.llm]) {
        this.llm[provider as keyof typeof this.llm][key as keyof typeof this.llm[keyof typeof this.llm]] = value;
      }
    },
    
    updateVideoSourceSetting(source: string, keys: string[]) {
      if (source === 'pexels') {
        this.videoSources.pexelsApiKeys = keys;
      } else if (source === 'pixabay') {
        this.videoSources.pixabayApiKeys = keys;
      }
    },
    
    updateWhisperSetting(key: string, value: any) {
      this.whisper[key as keyof typeof this.whisper] = value;
    },
    
    updateUISetting(key: string, value: any) {
      this.ui[key as keyof typeof this.ui] = value;
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