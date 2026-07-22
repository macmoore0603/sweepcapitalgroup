export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      agent_settings: {
        Row: {
          autofill_enabled: boolean
          brand_voice_notes: string | null
          created_at: string
          default_posting_windows: Json
          min_posts_per_day: number
          updated_at: string
          user_id: string
        }
        Insert: {
          autofill_enabled?: boolean
          brand_voice_notes?: string | null
          created_at?: string
          default_posting_windows?: Json
          min_posts_per_day?: number
          updated_at?: string
          user_id: string
        }
        Update: {
          autofill_enabled?: boolean
          brand_voice_notes?: string | null
          created_at?: string
          default_posting_windows?: Json
          min_posts_per_day?: number
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      checkout_intents: {
        Row: {
          amount_cents: number | null
          completed_at: string | null
          created_at: string
          currency: string | null
          email: string | null
          environment: string
          id: string
          product_name: string | null
          recovery_sent_at: string | null
          status: string
          stripe_session_id: string
        }
        Insert: {
          amount_cents?: number | null
          completed_at?: string | null
          created_at?: string
          currency?: string | null
          email?: string | null
          environment: string
          id?: string
          product_name?: string | null
          recovery_sent_at?: string | null
          status?: string
          stripe_session_id: string
        }
        Update: {
          amount_cents?: number | null
          completed_at?: string | null
          created_at?: string
          currency?: string | null
          email?: string | null
          environment?: string
          id?: string
          product_name?: string | null
          recovery_sent_at?: string | null
          status?: string
          stripe_session_id?: string
        }
        Relationships: []
      }
      daily_reports: {
        Row: {
          created_at: string
          id: string
          metrics: Json
          report_date: string
          summary: string
        }
        Insert: {
          created_at?: string
          id?: string
          metrics?: Json
          report_date: string
          summary: string
        }
        Update: {
          created_at?: string
          id?: string
          metrics?: Json
          report_date?: string
          summary?: string
        }
        Relationships: []
      }
      email_send_log: {
        Row: {
          created_at: string
          error_message: string | null
          id: string
          message_id: string | null
          metadata: Json | null
          recipient_email: string
          status: string
          template_name: string
        }
        Insert: {
          created_at?: string
          error_message?: string | null
          id?: string
          message_id?: string | null
          metadata?: Json | null
          recipient_email: string
          status: string
          template_name: string
        }
        Update: {
          created_at?: string
          error_message?: string | null
          id?: string
          message_id?: string | null
          metadata?: Json | null
          recipient_email?: string
          status?: string
          template_name?: string
        }
        Relationships: []
      }
      email_send_state: {
        Row: {
          auth_email_ttl_minutes: number
          batch_size: number
          id: number
          retry_after_until: string | null
          send_delay_ms: number
          transactional_email_ttl_minutes: number
          updated_at: string
        }
        Insert: {
          auth_email_ttl_minutes?: number
          batch_size?: number
          id?: number
          retry_after_until?: string | null
          send_delay_ms?: number
          transactional_email_ttl_minutes?: number
          updated_at?: string
        }
        Update: {
          auth_email_ttl_minutes?: number
          batch_size?: number
          id?: number
          retry_after_until?: string | null
          send_delay_ms?: number
          transactional_email_ttl_minutes?: number
          updated_at?: string
        }
        Relationships: []
      }
      email_unsubscribe_tokens: {
        Row: {
          created_at: string
          email: string
          id: string
          token: string
          used_at: string | null
        }
        Insert: {
          created_at?: string
          email: string
          id?: string
          token: string
          used_at?: string | null
        }
        Update: {
          created_at?: string
          email?: string
          id?: string
          token?: string
          used_at?: string | null
        }
        Relationships: []
      }
      inbound_replies: {
        Row: {
          auto_reply_sent: boolean
          body: string | null
          confidence: number | null
          created_at: string
          from_email: string
          id: string
          intent: string | null
          raw: Json | null
          related_contact_id: string | null
          subject: string | null
        }
        Insert: {
          auto_reply_sent?: boolean
          body?: string | null
          confidence?: number | null
          created_at?: string
          from_email: string
          id?: string
          intent?: string | null
          raw?: Json | null
          related_contact_id?: string | null
          subject?: string | null
        }
        Update: {
          auto_reply_sent?: boolean
          body?: string | null
          confidence?: number | null
          created_at?: string
          from_email?: string
          id?: string
          intent?: string | null
          raw?: Json | null
          related_contact_id?: string | null
          subject?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "inbound_replies_related_contact_id_fkey"
            columns: ["related_contact_id"]
            isOneToOne: false
            referencedRelation: "outbound_contacts"
            referencedColumns: ["id"]
          },
        ]
      }
      leads: {
        Row: {
          booking_token: string
          capital_size: string | null
          confirmation_sent_at: string | null
          created_at: string
          email: string
          full_name: string
          id: string
          landing_page: string | null
          notes: string | null
          referrer: string | null
          scheduled_at: string | null
          status: Database["public"]["Enums"]["lead_status"]
          updated_at: string
          utm_campaign: string | null
          utm_content: string | null
          utm_medium: string | null
          utm_source: string | null
          utm_term: string | null
        }
        Insert: {
          booking_token?: string
          capital_size?: string | null
          confirmation_sent_at?: string | null
          created_at?: string
          email: string
          full_name: string
          id?: string
          landing_page?: string | null
          notes?: string | null
          referrer?: string | null
          scheduled_at?: string | null
          status?: Database["public"]["Enums"]["lead_status"]
          updated_at?: string
          utm_campaign?: string | null
          utm_content?: string | null
          utm_medium?: string | null
          utm_source?: string | null
          utm_term?: string | null
        }
        Update: {
          booking_token?: string
          capital_size?: string | null
          confirmation_sent_at?: string | null
          created_at?: string
          email?: string
          full_name?: string
          id?: string
          landing_page?: string | null
          notes?: string | null
          referrer?: string | null
          scheduled_at?: string | null
          status?: Database["public"]["Enums"]["lead_status"]
          updated_at?: string
          utm_campaign?: string | null
          utm_content?: string | null
          utm_medium?: string | null
          utm_source?: string | null
          utm_term?: string | null
        }
        Relationships: []
      }
      nurture_state: {
        Row: {
          created_at: string
          email: string
          id: string
          last_sent_at: string | null
          lead_id: string | null
          name: string | null
          next_send_at: string
          step: number
          stopped: boolean
          tier: string | null
        }
        Insert: {
          created_at?: string
          email: string
          id?: string
          last_sent_at?: string | null
          lead_id?: string | null
          name?: string | null
          next_send_at?: string
          step?: number
          stopped?: boolean
          tier?: string | null
        }
        Update: {
          created_at?: string
          email?: string
          id?: string
          last_sent_at?: string | null
          lead_id?: string | null
          name?: string | null
          next_send_at?: string
          step?: number
          stopped?: boolean
          tier?: string | null
        }
        Relationships: []
      }
      outbound_contacts: {
        Row: {
          added_by: string | null
          ai_angle: string | null
          ai_first_message: string | null
          company: string | null
          created_at: string
          email: string
          id: string
          last_error: string | null
          last_sent_at: string | null
          name: string | null
          next_send_at: string
          role: string | null
          source: string | null
          status: string
          step: number
          updated_at: string
        }
        Insert: {
          added_by?: string | null
          ai_angle?: string | null
          ai_first_message?: string | null
          company?: string | null
          created_at?: string
          email: string
          id?: string
          last_error?: string | null
          last_sent_at?: string | null
          name?: string | null
          next_send_at?: string
          role?: string | null
          source?: string | null
          status?: string
          step?: number
          updated_at?: string
        }
        Update: {
          added_by?: string | null
          ai_angle?: string | null
          ai_first_message?: string | null
          company?: string | null
          created_at?: string
          email?: string
          id?: string
          last_error?: string | null
          last_sent_at?: string | null
          name?: string | null
          next_send_at?: string
          role?: string | null
          source?: string | null
          status?: string
          step?: number
          updated_at?: string
        }
        Relationships: []
      }
      post_metrics: {
        Row: {
          comments: number
          fetched_at: string
          id: string
          impressions: number
          likes: number
          post_id: string
          shares: number
        }
        Insert: {
          comments?: number
          fetched_at?: string
          id?: string
          impressions?: number
          likes?: number
          post_id: string
          shares?: number
        }
        Update: {
          comments?: number
          fetched_at?: string
          id?: string
          impressions?: number
          likes?: number
          post_id?: string
          shares?: number
        }
        Relationships: [
          {
            foreignKeyName: "post_metrics_post_id_fkey"
            columns: ["post_id"]
            isOneToOne: false
            referencedRelation: "scheduled_posts"
            referencedColumns: ["id"]
          },
        ]
      }
      revenue_events: {
        Row: {
          amount_cents: number
          created_at: string
          currency: string
          email: string | null
          environment: string
          id: string
          product_name: string | null
          stripe_session_id: string
        }
        Insert: {
          amount_cents: number
          created_at?: string
          currency?: string
          email?: string | null
          environment: string
          id?: string
          product_name?: string | null
          stripe_session_id: string
        }
        Update: {
          amount_cents?: number
          created_at?: string
          currency?: string
          email?: string | null
          environment?: string
          id?: string
          product_name?: string | null
          stripe_session_id?: string
        }
        Relationships: []
      }
      revenue_settings: {
        Row: {
          id: number
          nurture_day_offsets: Json
          recovery_window_minutes: number
          target_cents: number
          updated_at: string
        }
        Insert: {
          id?: number
          nurture_day_offsets?: Json
          recovery_window_minutes?: number
          target_cents?: number
          updated_at?: string
        }
        Update: {
          id?: number
          nurture_day_offsets?: Json
          recovery_window_minutes?: number
          target_cents?: number
          updated_at?: string
        }
        Relationships: []
      }
      scheduled_posts: {
        Row: {
          account_id: string
          body: string
          created_at: string
          error: string | null
          goal: string | null
          id: string
          media_urls: string[]
          platform_post_id: string | null
          platform_post_url: string | null
          published_at: string | null
          scheduled_for: string | null
          source: string
          status: Database["public"]["Enums"]["social_post_status"]
          updated_at: string
          user_id: string
        }
        Insert: {
          account_id: string
          body?: string
          created_at?: string
          error?: string | null
          goal?: string | null
          id?: string
          media_urls?: string[]
          platform_post_id?: string | null
          platform_post_url?: string | null
          published_at?: string | null
          scheduled_for?: string | null
          source?: string
          status?: Database["public"]["Enums"]["social_post_status"]
          updated_at?: string
          user_id: string
        }
        Update: {
          account_id?: string
          body?: string
          created_at?: string
          error?: string | null
          goal?: string | null
          id?: string
          media_urls?: string[]
          platform_post_id?: string | null
          platform_post_url?: string | null
          published_at?: string | null
          scheduled_for?: string | null
          source?: string
          status?: Database["public"]["Enums"]["social_post_status"]
          updated_at?: string
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "scheduled_posts_account_id_fkey"
            columns: ["account_id"]
            isOneToOne: false
            referencedRelation: "social_accounts"
            referencedColumns: ["id"]
          },
        ]
      }
      sierra_conversations: {
        Row: {
          created_at: string
          id: string
          last_channel: string
          owner_user_id: string
          phone_e164: string
          updated_at: string
        }
        Insert: {
          created_at?: string
          id?: string
          last_channel?: string
          owner_user_id: string
          phone_e164: string
          updated_at?: string
        }
        Update: {
          created_at?: string
          id?: string
          last_channel?: string
          owner_user_id?: string
          phone_e164?: string
          updated_at?: string
        }
        Relationships: []
      }
      sierra_messages: {
        Row: {
          channel: string
          content: string
          conversation_id: string
          created_at: string
          id: string
          parts: Json | null
          role: string
          twilio_sid: string | null
        }
        Insert: {
          channel: string
          content?: string
          conversation_id: string
          created_at?: string
          id?: string
          parts?: Json | null
          role: string
          twilio_sid?: string | null
        }
        Update: {
          channel?: string
          content?: string
          conversation_id?: string
          created_at?: string
          id?: string
          parts?: Json | null
          role?: string
          twilio_sid?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "sierra_messages_conversation_id_fkey"
            columns: ["conversation_id"]
            isOneToOne: false
            referencedRelation: "sierra_conversations"
            referencedColumns: ["id"]
          },
        ]
      }
      sierra_owners: {
        Row: {
          created_at: string
          id: string
          is_admin: boolean
          label: string | null
          phone_e164: string
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          is_admin?: boolean
          label?: string | null
          phone_e164: string
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          is_admin?: boolean
          label?: string | null
          phone_e164?: string
          user_id?: string
        }
        Relationships: []
      }
      sierra_reminders: {
        Row: {
          body: string
          created_at: string
          due_at: string
          error: string | null
          id: string
          owner_user_id: string
          phone_e164: string
          sent_at: string | null
          status: string
        }
        Insert: {
          body: string
          created_at?: string
          due_at: string
          error?: string | null
          id?: string
          owner_user_id: string
          phone_e164: string
          sent_at?: string | null
          status?: string
        }
        Update: {
          body?: string
          created_at?: string
          due_at?: string
          error?: string | null
          id?: string
          owner_user_id?: string
          phone_e164?: string
          sent_at?: string | null
          status?: string
        }
        Relationships: []
      }
      sierra_settings: {
        Row: {
          created_at: string
          system_prompt: string
          twilio_phone_e164: string | null
          updated_at: string
          user_id: string
          voice: string
        }
        Insert: {
          created_at?: string
          system_prompt?: string
          twilio_phone_e164?: string | null
          updated_at?: string
          user_id: string
          voice?: string
        }
        Update: {
          created_at?: string
          system_prompt?: string
          twilio_phone_e164?: string | null
          updated_at?: string
          user_id?: string
          voice?: string
        }
        Relationships: []
      }
      social_accounts: {
        Row: {
          access_token_encrypted: string | null
          active: boolean
          created_at: string
          expires_at: string | null
          handle: string
          id: string
          min_posts_per_day: number
          platform: Database["public"]["Enums"]["social_platform"]
          platform_account_id: string | null
          posting_windows: Json
          refresh_token_encrypted: string | null
          scopes: string[] | null
          timezone: string
          updated_at: string
          user_id: string
        }
        Insert: {
          access_token_encrypted?: string | null
          active?: boolean
          created_at?: string
          expires_at?: string | null
          handle: string
          id?: string
          min_posts_per_day?: number
          platform: Database["public"]["Enums"]["social_platform"]
          platform_account_id?: string | null
          posting_windows?: Json
          refresh_token_encrypted?: string | null
          scopes?: string[] | null
          timezone?: string
          updated_at?: string
          user_id: string
        }
        Update: {
          access_token_encrypted?: string | null
          active?: boolean
          created_at?: string
          expires_at?: string | null
          handle?: string
          id?: string
          min_posts_per_day?: number
          platform?: Database["public"]["Enums"]["social_platform"]
          platform_account_id?: string | null
          posting_windows?: Json
          refresh_token_encrypted?: string | null
          scopes?: string[] | null
          timezone?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      suppressed_emails: {
        Row: {
          created_at: string
          email: string
          id: string
          metadata: Json | null
          reason: string
        }
        Insert: {
          created_at?: string
          email: string
          id?: string
          metadata?: Json | null
          reason: string
        }
        Update: {
          created_at?: string
          email?: string
          id?: string
          metadata?: Json | null
          reason?: string
        }
        Relationships: []
      }
      user_roles: {
        Row: {
          created_at: string
          id: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          role?: Database["public"]["Enums"]["app_role"]
          user_id?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      delete_email: {
        Args: { message_id: number; queue_name: string }
        Returns: boolean
      }
      email_queue_dispatch: { Args: never; Returns: undefined }
      enqueue_email: {
        Args: { payload: Json; queue_name: string }
        Returns: number
      }
      has_role: {
        Args: {
          _role: Database["public"]["Enums"]["app_role"]
          _user_id: string
        }
        Returns: boolean
      }
      move_to_dlq: {
        Args: {
          dlq_name: string
          message_id: number
          payload: Json
          source_queue: string
        }
        Returns: number
      }
      read_email_batch: {
        Args: { batch_size: number; queue_name: string; vt: number }
        Returns: {
          message: Json
          msg_id: number
          read_ct: number
        }[]
      }
      reschedule_lead_call: {
        Args: { _lead_id: string; _slot: string; _token: string }
        Returns: boolean
      }
      schedule_lead_call: {
        Args: { _lead_id: string; _slot: string; _token: string }
        Returns: boolean
      }
    }
    Enums: {
      app_role: "admin" | "user"
      lead_status: "new" | "contacted" | "qualified" | "closed" | "rejected"
      social_platform: "instagram" | "x" | "linkedin" | "tiktok" | "youtube"
      social_post_status:
        | "draft"
        | "scheduled"
        | "publishing"
        | "published"
        | "failed"
        | "cancelled"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      app_role: ["admin", "user"],
      lead_status: ["new", "contacted", "qualified", "closed", "rejected"],
      social_platform: ["instagram", "x", "linkedin", "tiktok", "youtube"],
      social_post_status: [
        "draft",
        "scheduled",
        "publishing",
        "published",
        "failed",
        "cancelled",
      ],
    },
  },
} as const
