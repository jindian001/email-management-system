import paths from "./api-paths.json";

export type PathName = keyof typeof paths;

const KEY_STORAGE = "mailmind-key";

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) || "";
}

export function setApiKey(key: string): void {
  localStorage.setItem(KEY_STORAGE, key.trim());
}

/** 用清单里的模板拼 URL，例如 endpoint("mail", { id: 12 }) → /api/v1/mails/12 */
export function endpoint(name: PathName, params: Record<string, string | number> = {}): string {
  let path: string = paths[name];
  for (const [key, value] of Object.entries(params)) {
    path = path.replace(`:${key}`, encodeURIComponent(String(value)));
  }
  return path;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  params?: Record<string, string | number>;
  query?: Record<string, string | number | boolean | null | undefined>;
  method?: string;
  body?: unknown;
}

export async function api<T = unknown>(name: PathName, options: RequestOptions = {}): Promise<T> {
  let url = endpoint(name, options.params);
  if (options.query) {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(options.query)) {
      if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
    }
    const serialized = qs.toString();
    if (serialized) url += `?${serialized}`;
  }

  const headers: Record<string, string> = {};
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;

  let body: string | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(url, {
    method: options.method ?? (body ? "POST" : "GET"),
    headers,
    body,
  });

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("mailmind:unauthorized"));
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (payload.detail) detail = String(payload.detail);
    } catch {
      /* 保持 statusText */
    }
    throw new ApiError(response.status, `${response.status} ${detail}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** 带鉴权头下载二进制（原始 EML），避免 <a href> 无法附带 X-API-Key。 */
export async function download(path: string, filename: string): Promise<void> {
  const headers: Record<string, string> = {};
  const key = getApiKey();
  if (key) headers["X-API-Key"] = key;
  const response = await fetch(path, { headers });
  if (!response.ok) throw new ApiError(response.status, `${response.status} 下载失败`);
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}
