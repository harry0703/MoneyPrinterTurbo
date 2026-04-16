import { defineStore } from 'pinia';

// Language type definition
export type Language = 'zh' | 'en' | 'de' | 'pt' | 'ru' | 'tr' | 'vi';

// Translation resources interface
interface TranslationResources {
  [key: string]: {
    Translation: {
      [key: string]: string;
    };
    Language: string;
  };
}

export const useI18nStore = defineStore('i18n', {
  state: () => ({
    currentLanguage: 'zh' as Language,
    resources: {} as TranslationResources,
    loading: false,
    error: null as string | null
  }),
  
  getters: {
    t: (state) => (key: string): string => {
      const lang = state.currentLanguage;
      if (state.resources[lang] && state.resources[lang].Translation[key]) {
        return state.resources[lang].Translation[key];
      }
      return key;
    },
    
    currentLanguageName: (state): string => {
      const lang = state.currentLanguage;
      return state.resources[lang]?.Language || lang;
    },
    
    availableLanguages: (state): { code: Language; name: string }[] => {
      return Object.entries(state.resources).map(([code, resource]) => ({
        code: code as Language,
        name: resource.Language
      }));
    }
  },
  
  actions: {
    async loadTranslations() {
      this.loading = true;
      this.error = null;
      
      try {
        // Load all language files
        const languages: Language[] = ['zh', 'en', 'de', 'pt', 'ru', 'tr', 'vi'];
        const resources: TranslationResources = {};
        
        for (const lang of languages) {
          try {
            const response = await import(`../i18n/${lang}.json`);
            resources[lang] = response.default;
          } catch (error) {
            console.warn(`Failed to load translation for ${lang}:`, error);
          }
        }
        
        this.resources = resources;
      } catch (error) {
        this.error = 'Failed to load translations';
        console.error('Error loading translations:', error);
      } finally {
        this.loading = false;
      }
    },
    
    setLanguage(lang: Language) {
      this.currentLanguage = lang;
      localStorage.setItem('moneyprinter-language', lang);
    },
    
    loadLanguageFromLocalStorage() {
      const savedLang = localStorage.getItem('moneyprinter-language') as Language;
      if (savedLang) {
        this.currentLanguage = savedLang;
      }
    },
    
    clearError() {
      this.error = null;
    }
  }
});