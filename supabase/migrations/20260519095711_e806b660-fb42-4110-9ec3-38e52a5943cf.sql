
-- Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- Enums
DO $$ BEGIN
  CREATE TYPE public.social_platform AS ENUM ('instagram','x','linkedin','tiktok','youtube');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE public.social_post_status AS ENUM ('draft','scheduled','publishing','published','failed','cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- social_accounts
CREATE TABLE IF NOT EXISTS public.social_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  platform public.social_platform NOT NULL,
  handle TEXT NOT NULL,
  platform_account_id TEXT,
  access_token_encrypted BYTEA,
  refresh_token_encrypted BYTEA,
  expires_at TIMESTAMPTZ,
  scopes TEXT[],
  min_posts_per_day INTEGER NOT NULL DEFAULT 3 CHECK (min_posts_per_day >= 3),
  posting_windows JSONB NOT NULL DEFAULT '[{"hour":9,"minute":0},{"hour":13,"minute":0},{"hour":18,"minute":0}]'::jsonb,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, platform, handle)
);

ALTER TABLE public.social_accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owner can view own accounts" ON public.social_accounts
  FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Owner can insert own accounts" ON public.social_accounts
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner can update own accounts" ON public.social_accounts
  FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner can delete own accounts" ON public.social_accounts
  FOR DELETE TO authenticated USING (auth.uid() = user_id);

CREATE TRIGGER social_accounts_updated_at
  BEFORE UPDATE ON public.social_accounts
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX IF NOT EXISTS idx_social_accounts_user ON public.social_accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_social_accounts_active ON public.social_accounts(active) WHERE active = true;

-- scheduled_posts
CREATE TABLE IF NOT EXISTS public.scheduled_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id UUID NOT NULL REFERENCES public.social_accounts(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  status public.social_post_status NOT NULL DEFAULT 'draft',
  scheduled_for TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  body TEXT NOT NULL DEFAULT '',
  media_urls TEXT[] NOT NULL DEFAULT '{}',
  platform_post_id TEXT,
  platform_post_url TEXT,
  error TEXT,
  source TEXT NOT NULL DEFAULT 'manual', -- 'manual' | 'autofill' | 'ai'
  goal TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.scheduled_posts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owner can view own posts" ON public.scheduled_posts
  FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Owner can insert own posts" ON public.scheduled_posts
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner can update own posts" ON public.scheduled_posts
  FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner can delete own posts" ON public.scheduled_posts
  FOR DELETE TO authenticated USING (auth.uid() = user_id);

CREATE TRIGGER scheduled_posts_updated_at
  BEFORE UPDATE ON public.scheduled_posts
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE INDEX IF NOT EXISTS idx_scheduled_posts_account ON public.scheduled_posts(account_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON public.scheduled_posts(status, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_scheduled_posts_account_day ON public.scheduled_posts(account_id, scheduled_for);

-- post_metrics
CREATE TABLE IF NOT EXISTS public.post_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id UUID NOT NULL REFERENCES public.scheduled_posts(id) ON DELETE CASCADE,
  impressions INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  shares INTEGER NOT NULL DEFAULT 0,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.post_metrics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owner can view own metrics" ON public.post_metrics
  FOR SELECT TO authenticated USING (
    EXISTS (SELECT 1 FROM public.scheduled_posts p WHERE p.id = post_metrics.post_id AND p.user_id = auth.uid())
  );

CREATE INDEX IF NOT EXISTS idx_post_metrics_post ON public.post_metrics(post_id, fetched_at DESC);

-- agent_settings
CREATE TABLE IF NOT EXISTS public.agent_settings (
  user_id UUID PRIMARY KEY,
  min_posts_per_day INTEGER NOT NULL DEFAULT 3 CHECK (min_posts_per_day >= 3),
  default_posting_windows JSONB NOT NULL DEFAULT '[{"hour":9,"minute":0},{"hour":13,"minute":0},{"hour":18,"minute":0}]'::jsonb,
  brand_voice_notes TEXT,
  autofill_enabled BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.agent_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owner can view own settings" ON public.agent_settings
  FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Owner can insert own settings" ON public.agent_settings
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner can update own settings" ON public.agent_settings
  FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

CREATE TRIGGER agent_settings_updated_at
  BEFORE UPDATE ON public.agent_settings
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
