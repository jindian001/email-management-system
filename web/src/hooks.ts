import { useCallback, useEffect, useRef, useState } from "react";

export interface LoadState<T> {
  data: T | null;
  error: string;
  loading: boolean;
  reload: () => void;
}

/** 极简数据加载 hook：loader 每次渲染可变化，但只在挂载/手动 reload 时执行。 */
export function useLoad<T>(loader: () => Promise<T>): LoadState<T> {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    loaderRef
      .current()
      .then((result) => {
        if (alive) setData(result);
      })
      .catch((exc: unknown) => {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [tick]);

  return { data, error, loading, reload };
}
