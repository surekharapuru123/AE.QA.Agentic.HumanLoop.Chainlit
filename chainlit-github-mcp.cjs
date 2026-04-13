/**
 * GitHub Copilot MCP → mcp-remote stdio bridge for Chainlit.
 *
 * In Chainlit "Command" use (forward slashes; no unquoted backslashes):
 *   node chainlit-github-mcp.cjs
 *
 * app.py sets the server process cwd to this repo so this path resolves. If it still fails,
 * use an absolute path to this file.
 *
 * Requires: `npm install` in this repo (devDependency `mcp-remote`).
 * Requires: GITHUB_MCP_AUTHORIZATION or GITHUB_TOKEN (or GH_TOKEN) in .env
 * Optional: GITHUB_MCP_URL (default https://api.githubcopilot.com/mcp/)
 *
 * Header sent to the remote matches Cursor `mcp.json`: Authorization value is used as-is
 * (e.g. raw `ghp_…` or `Bearer ghp_…`).
 *
 * If `mcp-remote` fails against Copilot (OAuth discovery), use Chainlit remote HTTP + header
 * instead — see chat command `/github-mcp` Option A.
 */
"use strict";

const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const projectRoot = __dirname;
process.chdir(projectRoot);

require("dotenv").config({ path: path.join(projectRoot, ".env") });

const url = (process.env.GITHUB_MCP_URL || "https://api.githubcopilot.com/mcp/").trim();
const auth = (
  process.env.GITHUB_MCP_AUTHORIZATION ||
  process.env.GITHUB_TOKEN ||
  process.env.GH_TOKEN ||
  ""
).trim();

if (!auth) {
  console.error(
    "chainlit-github-mcp: set GITHUB_MCP_AUTHORIZATION or GITHUB_TOKEN (or GH_TOKEN) in .env",
  );
  process.exit(1);
}

const header = `Authorization: ${auth}`;

const mcpRemoteProxy = path.join(
  projectRoot,
  "node_modules",
  "mcp-remote",
  "dist",
  "proxy.js",
);
if (!fs.existsSync(mcpRemoteProxy)) {
  console.error(
    "chainlit-github-mcp: run `npm install` in this repo (devDependency `mcp-remote`).",
  );
  process.exit(1);
}

const args = [mcpRemoteProxy, url, "--header", header];
const child = spawn(process.execPath, args, {
  stdio: "inherit",
  shell: false,
  windowsHide: false,
});

child.on("error", (err) => {
  console.error(err);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code ?? 0);
});
