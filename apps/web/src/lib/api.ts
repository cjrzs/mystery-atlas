export const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8010";
export const API_BASE = `${API_ORIGIN}/api/v1`;

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
  publisher: string | null;
  translator: string | null;
  isbn: string | null;
  visibility: "pending" | "private" | "public";
  rights_confirmed: boolean;
  work_id: string | null;
  edition_id: string | null;
  chapter_count: number;
  chapters: { number: number; title: string; characters: number }[];
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
};

export type ReaderBook = {
  work_id: string;
  work_slug: string;
  work_title: string;
  author: string;
  edition_id: string;
  edition_title: string;
  visibility: string;
  chapters: ReaderChapter[];
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
    throw new ApiError(message ?? "请求失败，请稍后重试", response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
