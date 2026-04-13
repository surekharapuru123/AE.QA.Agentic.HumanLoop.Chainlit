import Anthropic from "@anthropic-ai/sdk";
import OpenAI from "openai";

export interface ToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface ToolCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResult {
  tool_use_id: string;
  content: string;
  is_error?: boolean;
}

export interface LLMResponse {
  text: string | null;
  toolCalls: ToolCall[];
  stopReason: "end_turn" | "tool_use" | "max_tokens" | "stop";
}

const SENSITIVE_KEYS = ["password", "token", "apiKey", "api_key", "secret"];

/** Cap tool results sent back into the model to avoid context_length_exceeded (e.g. repeated list_results). */
const MAX_TOOL_RESULT_CHARS_FOR_LLM = 12_000;

function truncateToolResultForLLM(result: string): string {
  if (result.length <= MAX_TOOL_RESULT_CHARS_FOR_LLM) {
    return result;
  }
  const note = `\n\n[truncated: ${result.length} chars → ${MAX_TOOL_RESULT_CHARS_FOR_LLM} max for model context]`;
  const headLen = MAX_TOOL_RESULT_CHARS_FOR_LLM - note.length;
  return result.slice(0, Math.max(0, headLen)) + note;
}

function sanitizeForLog(obj: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    const lower = k.toLowerCase();
    if (SENSITIVE_KEYS.some((s) => lower.includes(s))) {
      out[k] = "[REDACTED]";
    } else {
      out[k] = typeof v === "object" && v !== null && !Array.isArray(v)
        ? sanitizeForLog(v as Record<string, unknown>)
        : v;
    }
  }
  return out;
}

function logToolCall(name: string, input: Record<string, unknown>): void {
  const safe = sanitizeForLog(input);
  const preview = JSON.stringify(safe).slice(0, 200);
  console.log(`[Tool] Calling: ${name}(${preview}${preview.length >= 200 ? "…" : ""})`);
}

function logToolResult(name: string, result: string): void {
  const size = result.length;
  const preview = result.slice(0, 150).replace(/\s+/g, " ");
  console.log(`[Tool] Result: ${name} -> ${size} chars${size > 0 ? ` | preview: ${preview}…` : ""}`);
}

type AnthropicMessage = Anthropic.MessageParam;
type OpenAIMessage = OpenAI.Chat.ChatCompletionMessageParam;

export interface AgentLoopOptions {
  /** If set, the loop will not finish until each tool has been invoked at least once (e.g. automation must call push_files). */
  requiredTools?: string[];
  /**
   * Optional per-tool gate: if present, that tool only counts toward `requiredTools` when the predicate returns true
   * (e.g. push_files must return JSON with commit_sha, not a validation { error }).
   */
  requiredToolSuccessCheck?: Partial<Record<string, (result: string) => boolean>>;
}

export class LLMClient {
  private provider: "anthropic" | "openai";
  private model: string;
  private anthropic?: Anthropic;
  private openai?: OpenAI;

  constructor() {
    this.provider =
      (process.env.LLM_PROVIDER as "anthropic" | "openai") || "openai";

    if (this.provider === "anthropic") {
      this.model = process.env.LLM_MODEL || "claude-sonnet-4-20250514";
      this.anthropic = new Anthropic({
        apiKey: process.env.ANTHROPIC_API_KEY,
      });
    } else {
      this.model = process.env.LLM_MODEL || "gpt-4o";
      this.openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
    }
  }

  async runAgentLoop(
    systemPrompt: string,
    userPrompt: string,
    tools: ToolDefinition[],
    executeTool: (name: string, input: Record<string, unknown>) => Promise<string>,
    options?: AgentLoopOptions
  ): Promise<string> {
    if (this.provider === "anthropic") {
      return this.runAnthropicLoop(
        systemPrompt,
        userPrompt,
        tools,
        executeTool,
        options
      );
    }
    return this.runOpenAILoop(systemPrompt, userPrompt, tools, executeTool, options);
  }

  private async runAnthropicLoop(
    systemPrompt: string,
    userPrompt: string,
    tools: ToolDefinition[],
    executeTool: (name: string, input: Record<string, unknown>) => Promise<string>,
    options?: AgentLoopOptions
  ): Promise<string> {
    const client = this.anthropic!;
    const anthropicTools: Anthropic.Tool[] = tools.map((t) => ({
      name: t.name,
      description: t.description,
      input_schema: t.input_schema as Anthropic.Tool["input_schema"],
    }));

    const messages: AnthropicMessage[] = [
      { role: "user", content: userPrompt },
    ];

    const required = options?.requiredTools ?? [];
    const calledTools = new Set<string>();

    const MAX_ITERATIONS = 50;
    for (let i = 0; i < MAX_ITERATIONS; i++) {
      console.log(`[LLM] Anthropic iteration ${i + 1}...`);
      const response = await client.messages.create({
        model: this.model,
        max_tokens: 16384,
        temperature: 0,
        system: systemPrompt,
        tools: anthropicTools.length > 0 ? anthropicTools : undefined,
        messages,
      });

      const textBlocks = response.content
        .filter((b): b is Anthropic.TextBlock => b.type === "text")
        .map((b) => b.text);
      const toolBlocks = response.content.filter(
        (b): b is Anthropic.ToolUseBlock => b.type === "tool_use"
      );

      if (response.stop_reason === "end_turn" || toolBlocks.length === 0) {
        const missing = required.filter((t) => !calledTools.has(t));
        if (missing.length > 0 && i < MAX_ITERATIONS - 1) {
          console.warn(
            `[LLM] Model ended turn without tools; missing required: ${missing.join(", ")} — prompting continue`
          );
          messages.push({ role: "assistant", content: response.content });
          messages.push({
            role: "user",
            content:
              `You must continue: call ${missing.join(" and ")} before finishing. ` +
              `For push_files, include the full contents of every generated .spec.ts and .page.ts file on the branch you created. ` +
              `Then call update_case and create_pull_request as required by your instructions. ` +
              `Do not output final JSON until push_files has succeeded.`,
          });
          continue;
        }
        const finalText = textBlocks.join("\n");
        console.log(`[LLM] Agent completed after ${i + 1} iterations.`);
        return finalText;
      }

      messages.push({ role: "assistant", content: response.content });

      const toolResults: Anthropic.ToolResultBlockParam[] = [];
      for (const block of toolBlocks) {
        const input = block.input as Record<string, unknown>;
        logToolCall(block.name, input);
        try {
          const result = await executeTool(block.name, input);
          const successCheck = options?.requiredToolSuccessCheck?.[block.name];
          if (successCheck && !successCheck(result)) {
            console.warn(
              `[LLM] ${block.name} did not satisfy success gate — still required before finish`
            );
          } else {
            calledTools.add(block.name);
          }
          logToolResult(block.name, result);
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: truncateToolResultForLLM(result),
          });
        } catch (err) {
          const errMsg =
            err instanceof Error ? err.message : String(err);
          console.error(`[Tool] Error in ${block.name}: ${errMsg}`);
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: `Error: ${errMsg}`,
            is_error: true,
          });
        }
      }
      messages.push({ role: "user", content: toolResults });
    }

    throw new Error(`Agent exceeded max iterations (${MAX_ITERATIONS})`);
  }

  private async runOpenAILoop(
    systemPrompt: string,
    userPrompt: string,
    tools: ToolDefinition[],
    executeTool: (name: string, input: Record<string, unknown>) => Promise<string>,
    options?: AgentLoopOptions
  ): Promise<string> {
    const client = this.openai!;
    const hasTools = tools.length > 0;
    const openaiTools: OpenAI.Chat.ChatCompletionTool[] = tools.map((t) => ({
      type: "function" as const,
      function: {
        name: t.name,
        description: t.description,
        parameters: t.input_schema,
      },
    }));

    const messages: OpenAIMessage[] = [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ];

    const required = options?.requiredTools ?? [];
    const calledTools = new Set<string>();

    const MAX_ITERATIONS = 50;
    for (let i = 0; i < MAX_ITERATIONS; i++) {
      console.log(`[LLM] OpenAI iteration ${i + 1}...`);

      const requestParams: OpenAI.Chat.ChatCompletionCreateParamsNonStreaming = {
        model: this.model,
        max_tokens: 16384,
        temperature: 0,
        messages,
      };

      if (hasTools) {
        requestParams.tools = openaiTools;
        requestParams.parallel_tool_calls = false;
      }

      const response = await client.chat.completions.create(requestParams);

      const choice = response.choices[0];
      if (!choice) throw new Error("No response from OpenAI");

      const msg = choice.message;
      messages.push(msg);

      if (!msg.tool_calls || msg.tool_calls.length === 0) {
        const missing = required.filter((t) => !calledTools.has(t));
        if (missing.length > 0 && i < MAX_ITERATIONS - 1) {
          console.warn(
            `[LLM] Model stopped without tool calls; missing required: ${missing.join(", ")} — prompting continue`
          );
          messages.push({
            role: "user",
            content:
              `You must continue: call ${missing.join(" and ")} before finishing. ` +
              `For push_files, include the full contents of every generated .spec.ts and .page.ts file on the branch you created with create_branch. ` +
              `Then call update_case for each automatable case and create_pull_request. ` +
              `Do not output final JSON until push_files has succeeded.`,
          });
          continue;
        }
        console.log(`[LLM] Agent completed after ${i + 1} iterations.`);
        return msg.content || "";
      }

      for (const tc of msg.tool_calls) {
        const fnName = tc.function.name;
        let args: Record<string, unknown> = {};
        try {
          args = JSON.parse(tc.function.arguments);
        } catch (parseErr) {
          const parseMsg = parseErr instanceof Error ? parseErr.message : String(parseErr);
          console.error(`[Tool] Failed to parse arguments for ${fnName}: ${parseMsg}`);
          console.error(`[Tool] Raw arguments: ${tc.function.arguments.slice(0, 500)}`);
          messages.push({
            role: "tool",
            tool_call_id: tc.id,
            content: `Error: Failed to parse tool arguments — ${parseMsg}. Raw: ${tc.function.arguments.slice(0, 200)}`,
          });
          continue;
        }
        logToolCall(fnName, args);
        let result: string;
        try {
          result = await executeTool(fnName, args);
          const successCheck = options?.requiredToolSuccessCheck?.[fnName];
          if (successCheck && !successCheck(result)) {
            console.warn(
              `[LLM] ${fnName} did not satisfy success gate — still required before finish`
            );
          } else {
            calledTools.add(fnName);
          }
          logToolResult(fnName, result);
        } catch (err) {
          const errMsg =
            err instanceof Error ? err.message : String(err);
          console.error(`[Tool] Error in ${fnName}: ${errMsg}`);
          result = `Error: ${errMsg}`;
        }
        messages.push({
          role: "tool",
          tool_call_id: tc.id,
          content: truncateToolResultForLLM(result),
        });
      }
    }

    throw new Error(`Agent exceeded max iterations (${MAX_ITERATIONS})`);
  }
}
