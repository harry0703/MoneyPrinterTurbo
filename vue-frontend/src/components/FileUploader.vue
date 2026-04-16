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
import { ref } from 'vue';
import { Plus } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';

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

const handleFileChange = (_file: any, fileList: FileItem[]) => {
  emit('update:modelValue', fileList);
};

const handleFileRemove = (file: any, fileList: FileItem[]) => {
  emit('update:modelValue', fileList);
  emit('remove', file);
};

const handleUploadSuccess = (response: any, _file: any, fileList: FileItem[]) => {
  loading.value = false;
  emit('update:modelValue', fileList);
  emit('upload-success', response, _file, fileList);
};

const handleUploadError = (error: any, _file: any, fileList: FileItem[]) => {
  loading.value = false;
  emit('upload-error', error, _file, fileList);
};

const handleExceed = (files: File[], _fileList: FileItem[]) => {
  ElMessage.warning(`The limit is ${props.limit}, you selected ${files.length} files this time, please upload no more than ${props.limit} files.`);
};

const beforeUpload = (_file: File) => {
  loading.value = true;
  // File validation logic can be added here
  return true;
};
</script>

<style scoped>
.file-uploader {
  width: 100%;
}
</style>