export function go(path: string) {
  window.location.hash = path;
}

export const runPath = (id: string) => `/runs/${encodeURIComponent(id)}`;
