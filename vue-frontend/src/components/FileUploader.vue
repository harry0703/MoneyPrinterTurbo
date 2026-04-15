<template>
  <div class="file-uploader">
    <el-upload
      :action="uploadUrl"
      :headers="headers"
      :multiple="multiple"
      :limit="limit"
      :file-list="fileList"
      :on-change="handleFileChange"
      :on-remove="handleFileRemove"
      :on-success="handleUploadSuccess"
      :on-error="handleUploadError"
      :on-exceed="handleExceed"
      :before-upload="beforeUpload"
      :show-file-list="true"
      :auto-upload="autoUpload"
      :accept="accept"
    >
      <el-button type="primary" :loading="loading">
        <el-icon><Plus /></el-icon>
        {{ uploadText }}
      </el-button>
      <template #tip>
        <div class="el-upload__tip" v-if="tip">
          {{ tip }}
        </div>
      </template>
    </el-upload>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { Plus } from '@element-plus/icons-vue';

interface FileItem {
  name: string;
  url?: string;
  status?: string;
  uid: string;
}

interface Props {
  uploadUrl?: string;
  headers?: Record<string, string>;
  multiple?: boolean;
  limit?: number;
  accept?: string;
  autoUpload?: boolean;
  uploadText?: string;
  tip?: string;
  modelValue?: FileItem[];
}

const props = withDefaults(defineProps<Props>(), {
  uploadUrl: '',
  headers: () => ({}),
  multiple: false,
  limit: 10,
  accept: '',
  autoUpload: true,
  uploadText: 'Upload File',
  tip: '',
  modelValue: () => []
});

const emit = defineEmits(['update:modelValue', 'upload-success', 'upload-error', 'remove']);

const fileList = ref<FileItem[]>([...props.modelValue]);
const loading = ref(false);

const handleFileChange = (file: any, fileList: FileItem[]) => {
  emit('update:modelValue', fileList);
};

const handleFileRemove = (file: any, fileList: FileItem[]) => {
  emit('update:modelValue', fileList);
  emit('remove', file);
};

const handleUploadSuccess = (response: any, file: any, fileList: FileItem[]) => {
  loading.value = false;
  emit('update:modelValue', fileList);
  emit('upload-success', response, file, fileList);
};

const handleUploadError = (error: any, file: any, fileList: FileItem[]) => {
  loading.value = false;
  emit('upload-error', error, file, fileList);
};

const handleExceed = (files: File[], fileList: FileItem[]) => {
  ElMessage.warning(`The limit is ${props.limit}, you selected ${files.length} files this time, please upload no more than ${props.limit} files.`);
};

const beforeUpload = (file: File) => {
  loading.value = true;
  // 可以在这里添加文件验证逻辑
  return true;
};
</script>

<style scoped>
.file-uploader {
  width: 100%;
}
</style>