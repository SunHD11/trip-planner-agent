<script setup lang="ts">
import type { TripPlan } from '@/types/trip'

defineProps<{ plan: TripPlan }>()

function mealLabel(type: string): string {
  return { breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '加餐' }[type] || type
}
</script>

<template>
  <section class="result-panel" aria-live="polite">
    <div class="result-heading">
      <div>
        <p class="eyebrow">你的专属行程</p>
        <h2>{{ plan.city }} · {{ plan.days.length }} 日计划</h2>
        <p>{{ plan.start_date }} — {{ plan.end_date }}</p>
      </div>
      <div v-if="plan.budget?.total" class="budget">
        <span>预计总预算</span>
        <strong>¥{{ plan.budget.total }}</strong>
      </div>
    </div>

    <div class="timeline">
      <article v-for="day in plan.days" :key="`${day.date}-${day.day_index}`" class="day-card">
        <div class="day-marker">{{ day.day_index + 1 }}</div>
        <div class="day-content">
          <div class="day-title">
            <h3>第 {{ day.day_index + 1 }} 天</h3>
            <time :datetime="day.date">{{ day.date }}</time>
          </div>
          <p class="day-description">{{ day.description }}</p>

          <div v-if="day.attractions?.length" class="plan-block">
            <h4>目的地</h4>
            <ul class="attraction-list">
              <li v-for="attraction in day.attractions" :key="attraction.name">
                <strong>{{ attraction.name }}</strong>
                <span v-if="attraction.address">{{ attraction.address }}</span>
                <small v-if="attraction.description">{{ attraction.description }}</small>
              </li>
            </ul>
          </div>

          <div v-if="day.meals?.length" class="meal-list">
            <span v-for="meal in day.meals" :key="`${meal.type}-${meal.name}`">
              {{ mealLabel(meal.type) }} · {{ meal.name }}
            </span>
          </div>
        </div>
      </article>
    </div>

    <aside v-if="plan.overall_suggestions" class="suggestion">
      <strong>出发前的小纸条</strong>
      <p>{{ plan.overall_suggestions }}</p>
    </aside>
  </section>
</template>
