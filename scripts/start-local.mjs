import { spawn } from "node:child_process";
import { closeSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createConnection } from "node:net";
import path from "node:path";

const root = fileURLToPath(new URL("..", import.meta.url));
const logDirectory = path.join(root, ".logs");
mkdirSync(logDirectory, { recursive: true });

async function start(command, args, name, environment = {}, cwd = root) {
  const stdout = openSync(path.join(logDirectory, `${name}.log`), "w");
  const stderr = openSync(path.join(logDirectory, `${name}.err.log`), "w");
  const childEnvironment = Object.fromEntries(
    Object.entries(process.env).filter(([key]) => key.toLowerCase() !== "path"),
  );
  childEnvironment.Path = process.env.PATH ?? process.env.Path ?? "";
  const child = spawn(command, args, {
    cwd,
    detached: true,
    env: { ...childEnvironment, ...environment },
    shell: false,
    stdio: ["ignore", stdout, stderr],
    windowsHide: true,
  });
  await new Promise((resolve, reject) => {
    child.once("spawn", resolve);
    child.once("error", reject);
  });
  await new Promise((resolve) => setTimeout(resolve, 500));
  if (child.exitCode !== null) {
    throw new Error(`${name} 启动失败，退出码 ${child.exitCode}`);
  }
  closeSync(stdout);
  closeSync(stderr);
  return child;
}

function portIsOpen(port) {
  return new Promise((resolve) => {
    const socket = createConnection({ host: "127.0.0.1", port });
    socket.setTimeout(400);
    socket.once("connect", () => { socket.destroy(); resolve(true); });
    socket.once("error", () => resolve(false));
    socket.once("timeout", () => { socket.destroy(); resolve(false); });
  });
}

const python = process.platform === "win32"
  ? path.join(root, ".venv", "Scripts", "python.exe")
  : path.join(root, ".venv", "bin", "python");
const next = path.join(root, "apps", "web", "node_modules", "next", "dist", "bin", "next");
const webCommand = process.execPath;
const webArguments = [next, "dev", "--hostname", "127.0.0.1", "--port", "3100"];

const web = await portIsOpen(3100) ? null : await start(
  webCommand,
  webArguments,
  "frontend-3100",
  {},
  path.join(root, "apps", "web"),
);
const api = await portIsOpen(8010) ? null : await start(
  python,
  ["-m", "uvicorn", "mystery_atlas_api.main:app", "--host", "127.0.0.1", "--port", "8010"],
  "api",
  { PYTHONNOUSERSITE: "1" },
);

writeFileSync(
  path.join(logDirectory, "local-dev-processes.json"),
  `${JSON.stringify({ apiPid: api?.pid ?? null, webPid: web?.pid ?? null }, null, 2)}\n`,
);

api?.unref();
web?.unref();

console.log("谜案经纬本地服务已启动");
console.log("Web: http://127.0.0.1:3100");
console.log("API: http://127.0.0.1:8010/docs");
