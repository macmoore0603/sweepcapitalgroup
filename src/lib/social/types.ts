export type Platform = "instagram" | "x" | "linkedin" | "tiktok" | "youtube";

export const PLATFORMS: Platform[] = ["instagram", "x", "linkedin", "tiktok", "youtube"];

export const PLATFORM_LABEL: Record<Platform, string> = {
  instagram: "Instagram",
  x: "X / Twitter",
  linkedin: "LinkedIn",
  tiktok: "TikTok",
  youtube: "YouTube Shorts",
};

export type PostStatus =
  | "draft"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed"
  | "cancelled";

export type PostingWindow = { hour: number; minute: number };

export const DEFAULT_WINDOWS: PostingWindow[] = [
  { hour: 9, minute: 0 },
  { hour: 13, minute: 0 },
  { hour: 18, minute: 0 },
];

export const MIN_POSTS_PER_DAY = 3;
