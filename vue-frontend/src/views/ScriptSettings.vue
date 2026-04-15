<template>
  <div class="script-settings">
    <el-card :body-style="{ padding: '20px' }">
      <template #header>
        <div class="card-header">
          <span>{{ t('Script Settings') }}</span>
        </div>
      </template>
      
      <BaseForm ref="formRef" :model="form" :rules="rules">
        <el-form-item label="Video Subject" prop="videoSubject">
          <el-input
            v-model="form.videoSubject"
            placeholder="Enter video subject"
            type="text"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        
        <el-form-item label="Video Script" prop="videoScript">
          <el-input
            v-model="form.videoScript"
            placeholder="Enter video script"
            type="textarea"
            :rows="6"
            maxlength="5000"
            show-word-limit
          />
        </el-form-item>
        
        <el-form-item label="Keywords" prop="videoTerms">
          <el-input
            v-model="form.videoTerms"
            placeholder="Enter keywords separated by commas"
            type="text"
            maxlength="200"
            show-word-limit
          />
          <div class="tip">
            {{ t('Separate multiple keywords with commas') }}
          </div>
        </el-form-item>
        
        <el-form-item label="Language" prop="language">
          <el-select v-model="form.language" placeholder="Select language">
            <el-option label="Chinese" value="zh" />
            <el-option label="English" value="en" />
            <el-option label="German" value="de" />
            <el-option label="Portuguese" value="pt" />
            <el-option label="Russian" value="ru" />
            <el-option label="Turkish" value="tr" />
            <el-option label="Vietnamese" value="vi" />
          </el-select>
        </el-form-item>
      </BaseForm>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue';
import BaseForm from '../components/BaseForm.vue';
import { useI18nStore } from '../stores/i18n';

const i18nStore = useI18nStore();
const t = i18nStore.t;

const formRef = ref();

const form = reactive({
  videoSubject: '',
  videoScript: '',
  videoTerms: '',
  language: 'zh'
});

const rules = reactive({
  videoSubject: [{ required: false, message: 'Please enter video subject', trigger: 'blur' }],
  videoScript: [{ required: false, message: 'Please enter video script', trigger: 'blur' }]
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
.script-settings {
  width: 100%;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}
</style>