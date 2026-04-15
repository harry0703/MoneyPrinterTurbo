import { createApp } from 'vue';
import { createPinia } from 'pinia';
import ElementPlus from 'element-plus';
import 'element-plus/dist/index.css';
import App from './App.vue';
import router from './router';

const app = createApp(App);

// 使用Pinia状态管理
app.use(createPinia());

// 使用Element Plus
app.use(ElementPlus);

// 使用路由
app.use(router);

// 挂载应用
app.mount('#app');

// 暴露全局变量以便组件间通信
declare global {
  interface Window {
    __VUE_APP_VIDEO_SETTINGS__: any;
    __VUE_APP_SCRIPT_SETTINGS__: any;
    __VUE_APP_AUDIO_SETTINGS__: any;
    __VUE_APP_SUBTITLE_SETTINGS__: any;
    __VUE_APP_SCENE_INTEGRATION__: any;
  }
}

window.__VUE_APP_VIDEO_SETTINGS__ = null;
window.__VUE_APP_SCRIPT_SETTINGS__ = null;
window.__VUE_APP_AUDIO_SETTINGS__ = null;
window.__VUE_APP_SUBTITLE_SETTINGS__ = null;
window.__VUE_APP_SCENE_INTEGRATION__ = null;