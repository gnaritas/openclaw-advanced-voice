/**
 * @openclaw/advanced-voice - OpenClaw Plugin
 * 
 * Advanced voice calling system with:
 * - System 1 (OpenAI Realtime) + System 2 (OpenClaw backend) architecture
 * - Passphrase security challenge for inbound calls
 * - Full transcript logging to memory/
 * - Externalized prompts in files
 * - Unified Mind narrative bridge
 * 
 * @version 1.1.0
 */

import { spawn } from 'child_process';
import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const advancedVoicePlugin = {
  id: "advanced-voice",
  name: "@openclaw/advanced-voice",
  description: "Advanced voice calling with System 1/2 architecture",

  register(api) {
    api.logger.info?.("[advanced-voice] Plugin registering");

    let watchdogProcess = null;
    const PORT = process.env.PORT || "8001";

    const startWatchdog = () => {
      const watchdogPath = join(__dirname, "watchdog.py");
      if (!existsSync(watchdogPath)) {
        api.logger.error?.("[advanced-voice] watchdog.py not found");
        return;
      }

      api.logger.info?.("[advanced-voice] Starting watchdog (tunnel + server manager)");

      watchdogProcess = spawn("python3", ["-u", watchdogPath], {
        cwd: __dirname,
        env: { ...process.env },
        stdio: ["ignore", "pipe", "pipe"],
        detached: false,
      });

      watchdogProcess.stdout.on("data", (data) => {
        const lines = data.toString().trim().split("\n");
        lines.forEach((line) => {
          if (line) api.logger.info?.(`[watchdog] ${line}`);
        });
      });

      watchdogProcess.stderr.on("data", (data) => {
        const lines = data.toString().trim().split("\n");
        lines.forEach((line) => {
          if (line && !line.includes("NotOpenSSLWarning")) {
            api.logger.error?.(`[watchdog] ${line}`);
          }
        });
      });

      watchdogProcess.on("exit", (code, signal) => {
        if (code !== 0 && code !== null) {
          api.logger.warn?.(
            `[watchdog] Exited with code ${code} signal ${signal}`
          );
        }
        watchdogProcess = null;
      });

      api.logger.info?.("[advanced-voice] Watchdog started");
    };

    const stopWatchdog = async () => {
      if (watchdogProcess) {
        api.logger.info?.("[advanced-voice] Stopping watchdog");
        watchdogProcess.kill("SIGTERM");
        await new Promise((resolve) => setTimeout(resolve, 2000));
        if (watchdogProcess && !watchdogProcess.killed) {
          watchdogProcess.kill("SIGKILL");
        }
        watchdogProcess = null;
        api.logger.info?.("[advanced-voice] Watchdog stopped");
      }
    };

    // Register as a service
    api.registerService({
      id: "advanced-voice",
      start: async () => {
        startWatchdog();
      },
      stop: async () => {
        await stopWatchdog();
      },
    });

    // Register the call tool
    api.registerTool({
      name: "advanced_voice_call",
      description:
        "Initiate an advanced voice call with full System 2 integration",
      parameters: {
        type: "object",
        properties: {
          to: {
            type: "string",
            description: "Phone number to call (E.164 format: +1234567890)",
          },
          message: {
            type: "string",
            description: "Optional custom prompt/instructions for the call",
          },
          mode: {
            type: "string",
            enum: ["outbound", "notify"],
            description:
              'Call mode: outbound (conversation) or notify (one-way message)',
            default: "outbound",
          },
        },
        required: ["to"],
      },
      async execute(params) {
        const { to, message, mode = "outbound" } = params;
        const apiKey =
          process.env.VOICE_API_KEY || "";

        const response = await fetch(
          `http://localhost:${PORT}/call/number/${to}`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Voice-Key": apiKey,
            },
            body: JSON.stringify({
              message: message || "",
              agent_timezone: "America/Los_Angeles",
            }),
          }
        );

        if (!response.ok) {
          const error = await response.text();
          throw new Error(`Voice call failed: ${error}`);
        }

        const result = await response.json();
        return {
          success: true,
          callSid: result.call_sid,
          to: result.to,
          from: result.from,
          status: result.status,
        };
      },
    });

    api.logger.info?.("[advanced-voice] Plugin registered (service + tool)");
  },
};

export default advancedVoicePlugin;
