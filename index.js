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
export default function advancedVoicePlugin(config = {}) {
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
      
      watchdogProcess = spawn('python3', ['-u', watchdogPath], {
        cwd: __dirname,
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

    // Tool registration (optional - for agent to initiate calls)
    tools: [
      {
        name: 'advanced_voice_call',
        description: 'Initiate an advanced voice call with full System 2 integration',
        parameters: {
          type: 'object',
          properties: {
            to: {
              type: 'string',
              description: 'Phone number to call (E.164 format: +1234567890)'
            },
            message: {
              type: 'string',
              description: 'Optional custom prompt/instructions for the call'
            },
            mode: {
              type: 'string',
              enum: ['outbound', 'notify'],
              description: 'Call mode: outbound (conversation) or notify (one-way message)',
              default: 'outbound'
            }
          },
          required: ['to']
        },
        async handler(params, ctx) {
          const { to, message, mode = 'outbound' } = params;

          // Call the voice server API
          const response = await fetch(`http://localhost:${pluginConfig.port}/call/number/${to}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Voice-Key': pluginConfig.security.apiKey
            },
            body: JSON.stringify({
              message: message || '',
              agent_timezone: 'America/Los_Angeles'
            })
          });

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
            status: result.status
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
