/**
 * Atlassian Rovo MCP → mcp-remote stdio bridge for Chainlit.
 *
 * In Chainlit "Command" use (forward slashes; no unquoted backslashes):
 *   node chainlit-atlassian-mcp.cjs
 *
 * app.py sets the server process cwd to this repo so this path resolves. If it still fails,
 * use an absolute path to this file.
 *
 * Requires: JIRA_EMAIL + JIRA_MCP_API_TOKEN or JIRA_API_TOKEN in .env
 */
"use strict";

const { spawn } = require("child_process");
const path = require("path");

const projectRoot = __dirname;
process.chdir(projectRoot);

require("dotenv").config({ path: path.join(projectRoot, ".env") });

const email = process.env.JIRA_EMAIL;
const token = process.env.JIRA_MCP_API_TOKEN || process.env.JIRA_API_TOKEN;
if (!email || !token) {
  console.error(
    "chainlit-atlassian-mcp: set JIRA_EMAIL and JIRA_MCP_API_TOKEN (or JIRA_API_TOKEN) in .env",
  );
  process.exit(1);
}

const url = process.env.ATLASSIAN_MCP_URL || "https://mcp.atlassian.com/v1/mcp";
const b64 = Buffer.from(`${email}:${token}`, "utf8").toString("base64");
const header = `Authorization: Basic ${b64}`;

const args = ["-y", "mcp-remote@latest", url, "--header", header];
const isWin = process.platform === "win32";

const child = spawn(isWin ? "npx.cmd" : "npx", args, {
  stdio: "inherit",
  shell: false,
  windowsHide: true,
});

child.on("error", (err) => {
  console.error(err);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code ?? 0);
});
