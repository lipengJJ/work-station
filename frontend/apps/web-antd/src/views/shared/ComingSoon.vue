<script lang="ts" setup>
import { Fallback } from '@vben/common-ui';

defineProps<{
  title: string;
}>();
</script>

<template>
  <Fallback status="coming-soon" :title="title" description="功能待 Phase 3 接入" />
</template>
