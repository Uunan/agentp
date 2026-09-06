#!/usr/bin/env node

const { spawn, spawnSync } = require('child_process');
const path = require('path');

const packageRoot = path.resolve(__dirname, '..');

function findPython() {
  const candidates = process.platform === 'win32'
    ? ['python', 'py', 'python3']
    : ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      const res = spawnSync(cmd, ['--version'], { stdio: 'ignore' });
      if (res.status === 0) return cmd;
    } catch (e) {}
  }
  return null;
}

const py = findPython();
if (!py) {
  console.error('[31;1m[AgentP Error][0m Python 3 was not found. Please install Python 3.10+ on your system.');
  console.error('Download link: https://www.python.org/downloads/');
  process.exit(1);
}

const args = ['-m', 'agentp.main', ...process.argv.slice(2)];

const child = spawn(py, args, {
  cwd: packageRoot,
  stdio: 'inherit',
  env: process.env
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 0);
  }
});
