<script setup lang="ts">
import { computed, reactive } from 'vue'

import type { TripRequest } from '@/types/trip'

defineProps<{ loading: boolean }>()

const emit = defineEmits<{
  submit: [request: TripRequest]
}>()

const preferenceOptions = ['历史文化', '自然风光', '城市漫步', '当地美食', '亲子', '轻松慢游']

function futureDate(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

const form = reactive<TripRequest>({
  city: '',
  start_date: futureDate(1),
  end_date: futureDate(3),
  transportation: '公共交通',
  accommodation: '舒适型酒店',
  preferences: ['当地美食', '城市漫步'],
  free_text_input: '',
})

const dateError = computed(() =>
  form.end_date < form.start_date ? '结束日期不能早于开始日期' : '',
)

function togglePreference(preference: string) {
  const index = form.preferences.indexOf(preference)
  if (index >= 0) form.preferences.splice(index, 1)
  else form.preferences.push(preference)
}

function submit() {
  if (!form.city.trim() || dateError.value) return
  emit('submit', { ...form, city: form.city.trim(), preferences: [...form.preferences] })
}
</script>

<template>
  <form class="trip-form" @submit.prevent="submit">
    <div class="field">
      <label for="city">想去哪里？</label>
      <input id="city" v-model="form.city" required placeholder="例如：成都" />
    </div>

    <div class="field-grid">
      <div class="field">
        <label for="start-date">出发日期</label>
        <input id="start-date" v-model="form.start_date" type="date" required />
      </div>
      <div class="field">
        <label for="end-date">结束日期</label>
        <input id="end-date" v-model="form.end_date" type="date" required />
      </div>
    </div>
    <p v-if="dateError" class="field-error" role="alert">{{ dateError }}</p>

    <div class="field-grid">
      <div class="field">
        <label for="transportation">主要交通</label>
        <select id="transportation" v-model="form.transportation">
          <option>公共交通</option>
          <option>步行优先</option>
          <option>自驾</option>
          <option>打车</option>
        </select>
      </div>
      <div class="field">
        <label for="accommodation">住宿偏好</label>
        <select id="accommodation" v-model="form.accommodation">
          <option>经济型酒店</option>
          <option>舒适型酒店</option>
          <option>高档酒店</option>
          <option>特色民宿</option>
        </select>
      </div>
    </div>

    <fieldset class="field">
      <legend>旅行偏好</legend>
      <div class="preference-list">
        <button
          v-for="preference in preferenceOptions"
          :key="preference"
          class="preference-chip"
          :class="{ active: form.preferences.includes(preference) }"
          type="button"
          :aria-pressed="form.preferences.includes(preference)"
          @click="togglePreference(preference)"
        >
          {{ preference }}
        </button>
      </div>
    </fieldset>

    <div class="field">
      <label for="extra">还有什么特别要求？</label>
      <textarea
        id="extra"
        v-model="form.free_text_input"
        rows="3"
        placeholder="例如：行程不要太赶，希望安排一家本地人常去的餐馆"
      />
    </div>

    <button class="submit-button" type="submit" :disabled="loading || Boolean(dateError)">
      <span v-if="loading" class="spinner" aria-hidden="true"></span>
      {{ loading ? '正在规划旅程…' : '生成我的旅行计划' }}
    </button>
  </form>
</template>
