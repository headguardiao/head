const LEVELS = { error: 0, warn: 1, info: 2, debug: 3 };

function currentLevel() {
  return LEVELS[process.env.LOG_LEVEL || 'info'] ?? LEVELS.info;
}

function log(level, message) {
  if (LEVELS[level] > currentLevel()) return;
  const line = `${new Date().toISOString()} ${level.toUpperCase()} ${message}`;
  if (level === 'error') console.error(line);
  else if (level === 'warn') console.warn(line);
  else console.log(line);
}

export const logger = {
  error: (msg) => log('error', msg),
  warn: (msg) => log('warn', msg),
  info: (msg) => log('info', msg),
  debug: (msg) => log('debug', msg),
};
