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
  chapter_count: number;
  chapters: { number: number; title: string; characters: number }[];
  preview: string;
  error: string | null;
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
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new ApiError(payload?.detail ?? "请求失败，请稍后重试", response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

