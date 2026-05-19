declare const __APP_VERSION__: string;
declare const __BUILD_TIME__: string;
declare const __COMMIT_SHA__: string;

export interface HealthStatus {
  status: "healthy";
  timestamp: string;
  environment: string;
  version: string;
  commit: string;
  commitShort: string;
  buildTime: string;
}

export function getHealthStatus(): HealthStatus {
  const commit = __COMMIT_SHA__;
  return {
    status: "healthy",
    timestamp: new Date().toISOString(),
    environment: import.meta.env.MODE,
    version: __APP_VERSION__,
    commit,
    commitShort: commit.slice(0, 7),
    buildTime: __BUILD_TIME__,
  };
}
