import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router';
import VideoSettings from '../views/VideoSettings.vue';
import ScriptSettings from '../views/ScriptSettings.vue';
import AudioSettings from '../views/AudioSettings.vue';
import SubtitleSettings from '../views/SubtitleSettings.vue';
import TitleSettings from '../views/TitleSettings.vue';
import SceneIntegration from '../views/SceneIntegration.vue';
import TaskManagement from '../views/TaskManagement.vue';
import LogsView from '../views/LogsView.vue';

const routes: Array<RouteRecordRaw> = [
  {
    path: '/',
    redirect: '/script'
  },
  {
    path: '/video',
    name: 'VideoSettings',
    component: VideoSettings
  },
  {
    path: '/script',
    name: 'ScriptSettings',
    component: ScriptSettings
  },
  {
    path: '/audio',
    name: 'AudioSettings',
    component: AudioSettings
  },
  {
    path: '/subtitle',
    name: 'SubtitleSettings',
    component: SubtitleSettings
  },
  {
    path: '/title',
    name: 'TitleSettings',
    component: TitleSettings
  },
  {
    path: '/scene',
    name: 'SceneIntegration',
    component: SceneIntegration
  },
  {
    path: '/task',
    name: 'TaskManagement',
    component: TaskManagement
  },
  {
    path: '/logs',
    name: 'LogsView',
    component: LogsView
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

export default router;