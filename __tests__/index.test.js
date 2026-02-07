/**
 * Advanced Voice Plugin Tests
 *
 * These tests verify that the plugin exports correctly and
 * has the expected structure for OpenClaw SDK compatibility.
 */

import { jest } from '@jest/globals';
import advancedVoiceAdapter from '../index.js';

describe('Advanced Voice Plugin', () => {
  test('plugin should export adapter with required fields', () => {
    expect(advancedVoiceAdapter).toBeDefined();
    expect(advancedVoiceAdapter.id).toBe('advanced-voice');
    expect(advancedVoiceAdapter.name).toBe('@openclaw/advanced-voice');
    expect(advancedVoiceAdapter.register).toBeDefined();
  });

  test('register function should accept api object', () => {
    const mockApi = {
      logger: {
        info: jest.fn(),
        error: jest.fn(),
        warn: jest.fn(),
      },
      registerService: jest.fn(),
      registerTool: jest.fn(),
    };

    expect(() => advancedVoiceAdapter.register(mockApi)).not.toThrow();
    expect(mockApi.registerService).toHaveBeenCalled();
  });

  test('plugin should register advanced_voice_call tool', () => {
    const mockApi = {
      logger: {
        info: jest.fn(),
        error: jest.fn(),
        warn: jest.fn(),
      },
      registerService: jest.fn(),
      registerTool: jest.fn(),
    };

    advancedVoiceAdapter.register(mockApi);

    const toolCalls = mockApi.registerTool.mock.calls;
    expect(toolCalls.length).toBeGreaterThan(0);
    expect(toolCalls[0][0].name).toBe('advanced_voice_call');
  });
});
