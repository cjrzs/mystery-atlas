export const API_BASE = "/api/v1";
export const AUTH_REQUIRED_EVENT = "mystery-atlas:auth-required";

export type CurrentUser = {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
};

export type BookImport = {
  id: string;
  original_name: string;
  source_format: "epub" | "txt" | "pdf";
  size_bytes: number;
  status: "queued" | "parsing" | "completed" | "failed";
  stage: string;
  progress: number;
  detected_title: string | null;
  detected_author: string | null;
  detected_tags: string[];
  publisher: string | null;
  translator: string | null;
  isbn: string | null;
  visibility: "pending" | "private" | "public";
  rights_confirmed: boolean;
  work_id: string | null;
  edition_id: string | null;
  chapter_count: number;
  chapters: {
    number: number;
    title: string;
    characters: number;
    structural_path?: string[];
    blocks?: ReaderBlock[];
  }[];
  language: string | null;
  parser_version: string | null;
  structure_version: string | null;
  structure_source: string | null;
  structure_confidence: "high" | "medium" | "low";
  structure_warnings: string[];
  structure_tree: unknown[];
  structure_requires_review: boolean;
  preview: string;
  error: string | null;
};

export type ArchiveWork = {
  id: string | null;
  slug: string;
  title: string;
  author: string;
  region: string;
  year: number;
  tags: string[];
  cases: number;
  people: number;
  clues: number;
  analysis_progress: number;
  status: string;
  visibility: string;
  edition_count: number;
  unresolved_feedback_count: number;
  maintainer_name: string;
  updated_at: string | null;
};

export type LibraryItem = {
  id: string;
  kind: "private_upload" | "public_owner" | "public_reading";
  work_id: string | null;
  work_slug: string | null;
  edition_id: string | null;
  title: string;
  author: string;
  tags: string[];
  visibility: string;
  current_chapter: number;
  progress: number;
  analysis_progress: number;
  is_maintainer: boolean;
  updated_at: string;
};

export type ReaderChapter = {
  number: number;
  title: string;
  text: string;
  characters: number;
  blocks: ReaderBlock[];
  structural_path: string[];
  content_type: string;
  source_locator: Record<string, unknown>;
  structure_version: string;
  structure_confidence: string;
  structure_warnings: string[];
};

export type ReaderChapterSummary = {
  number: number;
  title: string;
  characters: number;
  structural_path: string[];
  content_type: string;
};

export type ReaderBlock = {
  type:
    | "paragraph"
    | "heading"
    | "quote"
    | "divider"
    | "pre"
    | "figure"
    | "pagebreak";
  text: string;
  level?: number | null;
  semantic_type?: string;
  anchors?: string[];
  links?: Record<string, unknown>[];
  src?: string;
  alt?: string;
  resource?: string;
  fragment?: string;
  missing?: boolean;
};

export type ReaderBook = {
  work_id: string;
  work_slug: string;
  work_title: string;
  author: string;
  edition_id: string;
  edition_title: string;
  language: string;
  visibility: string;
  chapters: ReaderChapterSummary[];
  structure_version: string;
  structure_source: string;
  structure_confidence: string;
  structure_warnings: string[];
  structure_requires_review: boolean;
};

export type ReaderPreferences = {
  font_size: number;
  line_height: number;
  content_width: number;
  theme: "light" | "sepia" | "dark";
};

export type GraphNode = {
  id: string;
  name: string;
  role: string;
  group: string;
  first_chapter: number;
  description: string;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  kind: string;
  status: "confirmed" | "inferred" | "disputed";
  first_chapter: number;
  evidence: string;
};

export type WorkbenchAnalysis = {
  work_id: string;
  work_slug: string;
  job_id: string | null;
  through_chapter: number;
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  heartbeat_at: string | null;
  current_call_id: string | null;
  stage_detail: string | null;
  response_chars: number;
  content_idle_seconds: number;
  can_manage_retry: boolean;
  can_retry: boolean;
  can_restart: boolean;
  retry_hint: string;
  graph: {
    work_slug: string;
    through_chapter: number;
    nodes: GraphNode[];
    edges: GraphEdge[];
  };
  timeline: {
    chapter: number;
    sequence: number;
    summary: string;
    story_time: string;
    narrative_time: string;
  }[];
  chapters: { chapter: number; summary: string }[];
  evidence: {
    id: string;
    title: string;
    summary: string;
    source_type: string;
    status: string;
    first_chapter: number;
    excerpt: string;
  }[];
};

export type ArchiveFeedback = {
  id: string;
  work_id: string | null;
  edition_id: string | null;
  entity_type: string;
  entity_id: string | null;
  category: string;
  chapter: number | null;
  content: string;
  status: string;
  resolution: string;
  same_issue_count: number;
  reporter_name: string;
  assignee_name: string;
  created_at: string;
  updated_at: string;
};

export type MaintenanceOverview = {
  works: { id: string; slug: string; title: string; progress: number }[];
  editions: { id: string; work_id: string; title: string; visibility: string }[];
  open_feedback: number;
  is_super_admin: boolean;
};

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: init?.body instanceof FormData
      ? init.headers
      : { "Content-Type": "application/json", ...init?.headers },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string | { message?: string } } | null;
    const detail = payload?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    if (response.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
    }
    throw new ApiError(message ?? "请求失败，请稍后重试", response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
