<script setup lang="ts">
import { onMounted, ref } from 'vue'

import TripForm from '@/components/TripForm.vue'
import TripPlanResult from '@/components/TripPlanResult.vue'
import { generateTripPlan, healthCheck } from '@/services/api'
import type { TripPlan, TripRequest } from '@/types/trip'

const loading = ref(false)
const errorMessage = ref('')
const plan = ref<TripPlan | null>(null)
const backendOnline = ref<boolean | null>(null)

onMounted(async () => {
  try {
    await healthCheck()
    backendOnline.value = true
  } catch {
    backendOnline.value = false
  }
})

async function handleSubmit(request: TripRequest) {
  loading.value = true
  errorMessage.value = ''

  try {
    const response = await generateTripPlan(request)
    plan.value = response.data
    requestAnimationFrame(() => {
      document.querySelector('.result-panel')?.scrollIntoView({ behavior: 'smooth' })
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '旅行计划生成失败，请稍后再试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main>
    <section class="hero">
      <nav class="topbar" aria-label="主导航">
        <a class="brand" href="#">旅途策划局</a>
        <span class="service-status" :class="{ online: backendOnline === true }">
          <i aria-hidden="true"></i>
          {{ backendOnline === null ? '正在检查服务' : backendOnline ? '规划服务在线' : '等待后端启动' }}
        </span>
      </nav>

      <div class="hero-content">
        <div class="intro">
          <p class="eyebrow">AI TRIP PLANNER</p>
          <h1>把想去的地方，<br /><em>变成走得通的旅程。</em></h1>
          <p class="intro-copy">
            告诉我们目的地和旅行偏好，规划助手会结合景点、天气与交通信息，为你整理每天的安排。
          </p>
          <div class="feature-notes">
            <span>真实地点信息</span><span>按天清晰安排</span><span>预算一目了然</span>
          </div>
        </div>

        <div class="form-card">
          <div class="form-card-heading">
            <span>01</span>
            <div>
              <h2>先聊聊这次旅行</h2>
              <p>填几个关键信息，剩下的交给规划助手。</p>
            </div>
          </div>
          <TripForm :loading="loading" @submit="handleSubmit" />
          <p v-if="errorMessage" class="error-banner" role="alert">{{ errorMessage }}</p>
        </div>
      </div>
    </section>

    <TripPlanResult v-if="plan" :plan="plan" />

    <footer>
      <span>旅途策划局</span>
      <p>计划可以精确，旅途记得保留一点意外。</p>
    </footer>
  </main>
</template>
