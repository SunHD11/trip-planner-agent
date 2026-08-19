export interface TripRequest {
  city: string
  start_date: string
  end_date: string
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input?: string
}

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address?: string
  location?: Location
  visit_duration?: number
  description?: string
  ticket_price?: number
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack' | string
  name: string
  description?: string
  estimated_cost?: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation?: string
  accommodation?: string
  attractions: Attraction[]
  meals: Meal[]
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  overall_suggestions?: string
  budget?: {
    total?: number
    total_attractions?: number
    total_hotels?: number
    total_meals?: number
    total_transportation?: number
  }
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data: TripPlan
}
