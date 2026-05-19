export function getHealthStatus(): { status: 'healthy'; uptime: number; environment: string } {
  return {
    status: 'healthy',
    uptime: performance.now(),
    environment: import.meta.env.MODE,
  };
}
