export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|; )tagp_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const method = (options.method || "GET").toUpperCase();
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-CSRF-Token", csrfToken());
  }
  const response = await fetch(path, { ...options, headers, credentials: "include" });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (response.status === 401 && !path.includes("/auth/login")) {
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, data.error?.code || "error", data.error?.message || "Request failed");
  }
  return data as T;
}

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
};

export type MetricCard = {
  key: string;
  label: string;
  value: number | null;
  value_state: "known" | "missing" | "zero_denominator" | string;
  definition: {
    numerator: string;
    denominator: string | null;
    time_window: string;
    event_source: string;
  };
  note?: string | null;
};
