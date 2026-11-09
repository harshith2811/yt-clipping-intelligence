-- ==============================================================================
-- Migration 002: Content Calendar Media Persistence & Outbound Link (DEF-02)
-- OmniPost Universal Multi-Platform Social Automation Engine
-- ==============================================================================

-- Idempotently add missing columns for public media delivery and outbound links
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS public_media_url TEXT DEFAULT '';
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS media_type       TEXT DEFAULT '';
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS link             TEXT DEFAULT '';

-- Metadata comments for schema documentation and introspection
COMMENT ON COLUMN public.content_calendar.public_media_url IS 'Publicly accessible URL for post media (image/video)';
COMMENT ON COLUMN public.content_calendar.media_type IS 'Media classification: text | image | video | carousel';
COMMENT ON COLUMN public.content_calendar.link IS 'Optional outbound link or landing URL for the post';
