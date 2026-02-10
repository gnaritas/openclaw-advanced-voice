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
 * @version 1.0.0
 *
 * ⚠️  STICKY NOTE FOR LLM:
 *     This plugin spawns child processes (watchdog.py, tunnel).
 *     If you modify onLoad/onUnload, TEST THAT:
 *     - Watchdog starts correctly
 *     - Tunnel stays alive during operation
 *     - Processes clean up properly on exit (no zombies)
 *     Run: npm test
 */

import { spawn } from 'child_process';
import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Plugin entry point
 */
function advancedVoicePlugin(config = {}) {
  const pluginConfig = {
    enabled: config.enabled ?? true,
    port: config.port ?? 8001,
    provider: config.provider ?? 'twilio',
    twilio: config.twilio ?? {},
    openai: config.openai ?? {},
    security: config.security ?? {
      challenge: config.security?.challenge || process.env.SECURITY_CHALLENGE,
      apiKey: config.apiKey || process.env.VOICE_API_KEY
    },
    logging: config.logging ?? {
      transcripts: true,
      memoryPath: '~/clawd/memory'
    },
    prompts: config.prompts ?? {
      inbound: join(__dirname, 'prompts/jarvis-base.txt'),
      outbound: join(__dirname, 'prompts/jarvis-outbound.txt')
    }
  };

  let watchdogProcess = null;

  return {
    id: 'advanced-voice',
    name: '@openclaw/advanced-voice',
    description: 'Advanced voice calling with System 1/2 architecture',
    version: '1.0.0',

    async onLoad(ctx) {
      ctx.log.info('[advanced-voice] Plugin loaded');

      if (!pluginConfig.enabled) {
        ctx.log.info('[advanced-voice] Plugin disabled in config');
        return;
      }

      // Validate watchdog script
      const watchdogPath = join(__dirname, 'watchdog.py');
      if (!existsSync(watchdogPath)) {
        ctx.log.error('[advanced-voice] watchdog.py not found');
        return;
      }

      // Start watchdog (which manages tunnel + server)
      ctx.log.info('[advanced-voice] Starting watchdog (tunnel + server manager)');

      // Pass plugin config as environment variables to watchdog/server
      const childEnv = {
        ...process.env,
        PORT: String(pluginConfig.port),
        TWILIO_ACCOUNT_SID: pluginConfig.twilio.accountSid || '',
        TWILIO_AUTH_TOKEN: pluginConfig.twilio.authToken || '',
        TWILIO_NUMBER: pluginConfig.twilio.fromNumber || '',
        OPENAI_API_KEY: pluginConfig.openai.apiKey || '',
        VOICE_API_KEY: pluginConfig.security.apiKey || '',
        SECURITY_CHALLENGE: pluginConfig.security.challenge || '',
        GATEWAY_URL: `http://127.0.0.1:18789/v1/chat/completions`,
        GATEWAY_TOKEN: process.env.OPENCLAW_TOKEN || '',
      };

      watchdogProcess = spawn('python3', ['-u', watchdogPath], {
        cwd: __dirname,
        env: childEnv,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: false  // Keep it attached to gateway lifecycle
      });

      watchdogProcess.stdout.on('data', (data) => {
        const lines = data.toString().trim().split('\n');
        lines.forEach(line => {
          if (line) ctx.log.info(`[watchdog] ${line}`);
        });
      });

      watchdogProcess.stderr.on('data', (data) => {
        const lines = data.toString().trim().split('\n');
        lines.forEach(line => {
          if (line && !line.includes('NotOpenSSLWarning')) {
            ctx.log.error(`[watchdog] ${line}`);
          }
        });
      });

      watchdogProcess.on('exit', (code, signal) => {
        if (code !== 0 && code !== null) {
          ctx.log.warn(`[watchdog] Exited with code ${code} signal ${signal}`);
        }
        watchdogProcess = null;
      });

      ctx.log.info('[advanced-voice] Watchdog started (managing tunnel + server)');
    },

    async onUnload(ctx) {
      if (watchdogProcess) {
        ctx.log.info('[advanced-voice] Stopping watchdog (will clean up tunnel + server)');
        watchdogProcess.kill('SIGTERM');
        
        // Give it a moment to clean up gracefully
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        // Force kill if still alive
        if (watchdogProcess && !watchdogProcess.killed) {
          watchdogProcess.kill('SIGKILL');
        }
        
        watchdogProcess = null;
        ctx.log.info('[advanced-voice] Watchdog stopped');
      }
    },

    // Tool registration — agent uses this to make outbound calls
    tools: [
      {
        name: 'advanced_voice_call',
        description: 'Make an outbound voice call with a specific mission. Waits for the call to complete and returns the mission outcome.',
        parameters: {
          type: 'object',
          properties: {
            to: {
              type: 'string',
              description: 'Phone number to call (E.164 format: +1234567890)'
            },
            mission: {
              type: 'string',
              description: 'The specific reason for this call. What should the voice agent accomplish? (e.g., "Tell Ramon his 3pm meeting was cancelled", "Ask about dinner plans tonight")'
            },
            role: {
              type: 'string',
              description: 'Role/persona for the voice agent (default: "personal assistant")',
              default: 'personal assistant'
            }
          },
          required: ['to', 'mission']
        },
        async handler(params, ctx) {
          const { to, mission, role = 'personal assistant' } = params;

          // Initiate the call
          const response = await fetch(`http://localhost:${pluginConfig.port}/call/number/${to}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Voice-Key': pluginConfig.security.apiKey
            },
            body: JSON.stringify({ mission, role, agent_timezone: 'America/Los_Angeles' })
          });

          if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to initiate call: ${error}`);
          }

          const callInfo = await response.json();
          const callSid = callInfo.call_sid;

          // Poll for mission result — call may take minutes
          const MAX_WAIT_MS = 5 * 60 * 1000; // 5 minutes
          const POLL_MS = 5000;               // check every 5 seconds
          const startTime = Date.now();

          while (Date.now() - startTime < MAX_WAIT_MS) {
            await new Promise(r => setTimeout(r, POLL_MS));

            try {
              const poll = await fetch(
                `http://localhost:${pluginConfig.port}/call/${callSid}/result`,
                { headers: { 'X-Voice-Key': pluginConfig.security.apiKey } }
              );
              if (poll.ok) {
                const result = await poll.json();

                if (result.status === 'completed') {
                  return {
                    success: result.success,
                    callSid,
                    to: callInfo.to,
                    outcome: result.outcome,
                    data: result.data || {},
                    next_steps: result.next_steps || ''
                  };
                }

                if (result.status === 'failed' || result.status === 'ended_without_result') {
                  return {
                    success: false,
                    callSid,
                    to: callInfo.to,
                    outcome: result.reason || 'Call ended without mission result',
                    data: {},
                    next_steps: 'Retry or find alternative approach'
                  };
                }
                // still in progress — keep polling
              }
            } catch (_) { /* poll error, keep trying */ }
          }

          // Timed out waiting
          return {
            success: false,
            callSid,
            to: callInfo.to,
            outcome: 'Timed out waiting for call to complete (5 min)',
            data: {},
            next_steps: 'Check call logs'
          };
        }
      }
    ],

    // Config schema for openclaw.json validation
    configSchema: {
      type: 'object',
      properties: {
        enabled: { type: 'boolean', default: true },
        port: { type: 'number', default: 8001 },
        provider: { type: 'string', enum: ['twilio'], default: 'twilio' },
        twilio: {
          type: 'object',
          properties: {
            accountSid: { type: 'string' },
            authToken: { type: 'string' },
            fromNumber: { type: 'string', pattern: '^\\+[1-9]\\d{1,14}$' }
          },
          required: ['accountSid', 'authToken', 'fromNumber']
        },
        openai: {
          type: 'object',
          properties: {
            apiKey: { type: 'string' }
          },
          required: ['apiKey']
        },
        security: {
          type: 'object',
          required: ['challenge', 'apiKey'],
          properties: {
            challenge: { 
              type: 'string',
              description: 'Secret passphrase for inbound call authentication (required - no default)'
            },
            apiKey: { type: 'string' }
          }
        },
        logging: {
          type: 'object',
          properties: {
            transcripts: { type: 'boolean', default: true },
            memoryPath: { type: 'string', default: '~/clawd/memory' }
          }
        }
      },
      required: ['twilio', 'openai']
    }
  };
}


// --- SDK adapter: bridges onLoad/onUnload to register(api) ---
const advancedVoiceAdapter = {
  id: 'advanced-voice',
  name: '@openclaw/advanced-voice',
  description: 'Advanced voice calling with System 1/2 architecture',

  register(api) {
    // Get plugin config from OpenClaw (passed via api.config)
    const pluginCfg = api.config || {};
    const _plugin = advancedVoicePlugin(pluginCfg);

    const ctx = {
      log: {
        info: (...a) => api.logger.info?.(...a),
        error: (...a) => api.logger.error?.(...a),
        warn: (...a) => api.logger.warn?.(...a),
      }
    };

    api.registerService({
      id: "advanced-voice",
      start: async () => { await _plugin.onLoad(ctx); },
      stop: async () => { await _plugin.onUnload(ctx); },
    });

    // Register tools
    for (const tool of (_plugin.tools || [])) {
      api.registerTool({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        async execute(params) { return tool.handler(params, ctx); },
      });
    }

    api.logger.info?.("[advanced-voice] Plugin registered (service + tool)");
  },
};

export default advancedVoiceAdapter;
