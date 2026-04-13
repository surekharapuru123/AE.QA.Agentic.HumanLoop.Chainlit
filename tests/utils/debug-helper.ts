/**
 * Debugging utility for headless Playwright tests
 * Provides enhanced logging, DOM inspection, and network monitoring
 */

import { Page, BrowserContext } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const DEBUG_DIR = 'debug-logs';

// Ensure debug directory exists
if (!fs.existsSync(DEBUG_DIR)) {
  fs.mkdirSync(DEBUG_DIR, { recursive: true });
}

export class DebugHelper {
  private page: Page;
  private debugLogs: string[] = [];
  private testName: string = '';

  constructor(page: Page, testName: string = 'test') {
    this.page = page;
    this.testName = testName.replace(/[^a-z0-9]/gi, '_').toLowerCase();
    this.setupConsoleLogging();
  }

  /**
   * Capture all console messages (logs, errors, warnings)
   */
  private setupConsoleLogging() {
    this.page.on('console', (msg) => {
      const logEntry = `[${new Date().toISOString()}] [${msg.type().toUpperCase()}] ${msg.text()}`;
      console.log(logEntry);
      this.debugLogs.push(logEntry);
    });

    this.page.on('pageerror', (error) => {
      const errorEntry = `[${new Date().toISOString()}] [PAGE_ERROR] ${error.message}`;
      console.error(errorEntry);
      this.debugLogs.push(errorEntry);
    });

    this.page.on('requestfailed', (request) => {
      const failEntry = `[${new Date().toISOString()}] [REQUEST_FAILED] ${request.method()} ${request.url()} - ${request.failure()?.errorText}`;
      console.warn(failEntry);
      this.debugLogs.push(failEntry);
    });
  }

  /**
   * Log message with timestamp
   */
  log(message: string, data?: any) {
    const entry = `[${new Date().toISOString()}] ${message}`;
    console.log(entry, data || '');
    this.debugLogs.push(entry);
  }

  /**
   * Dump entire DOM for inspection
   */
  async dumpDOM(filename?: string) {
    const html = await this.page.content();
    const fname = filename || `dom-dump-${Date.now()}.html`;
    const filepath = path.join(DEBUG_DIR, fname);
    fs.writeFileSync(filepath, html);
    this.log(`DOM dumped to: ${filepath}`);
    return filepath;
  }

  /**
   * Get specific element details
   */
  async inspectElement(selector: string) {
    try {
      const element = this.page.locator(selector).first();
      const exists = await element.isVisible().catch(() => false);
      
      if (!exists) {
        this.log(`Element not visible: ${selector}`);
        return null;
      }

      const boundingBox = await element.boundingBox();
      const html = await element.evaluate((el) => el.outerHTML);
      const text = await element.textContent();
      const attrs = await element.evaluate((el) => 
        Object.fromEntries(
          Array.from(el.attributes).map((attr) => [attr.name, attr.value])
        )
      );

      const details = {
        selector,
        visible: true,
        boundingBox,
        text: text?.trim(),
        attributes: attrs,
        html: html?.substring(0, 500), // First 500 chars
      };

      this.log(`Element inspection: ${selector}`, details);
      return details;
    } catch (error) {
      this.log(`Error inspecting element ${selector}: ${error}`);
      return null;
    }
  }

  /**
   * Capture current page state
   */
  async capturePageState(stepName: string) {
    const state = {
      url: this.page.url(),
      title: await this.page.title(),
      timestamp: new Date().toISOString(),
      stepName,
    };

    this.log(`Page State - ${stepName}`, state);

    // Save screenshot
    try {
      const screenshotPath = path.join(
        DEBUG_DIR,
        `screenshot-${stepName}-${Date.now()}.png`
      );
      await this.page.screenshot({ path: screenshotPath, fullPage: true });
      this.log(`Screenshot saved: ${screenshotPath}`);
    } catch (error) {
      this.log(`Error capturing screenshot: ${error}`);
    }

    return state;
  }

  /**
   * Monitor network requests
   */
  setupNetworkLogging() {
    this.page.on('request', (request) => {
      const req = `[REQUEST] ${request.method()} ${request.url()}`;
      this.log(req);
    });

    this.page.on('response', (response) => {
      const res = `[RESPONSE] ${response.status()} ${response.url()}`;
      console.log(res);
      this.debugLogs.push(res);
    });
  }

  /**
   * Wait for element and log if timeout
   */
  async waitForElementWithLogging(selector: string, timeout: number = 5000) {
    this.log(`Waiting for element: ${selector}`);
    try {
      await this.page.locator(selector).waitFor({ timeout });
      this.log(`Element found: ${selector}`);
      return true;
    } catch (error) {
      this.log(`Timeout waiting for element: ${selector} (${timeout}ms)`);
      await this.dumpDOM(`timeout-${selector.replace(/[^a-z0-9]/gi, '_')}.html`);
      throw error;
    }
  }

  /**
   * Evaluate JavaScript and log results
   */
  async evaluateWithLogging(expression: string, description?: string) {
    try {
      const result = await this.page.evaluate(expression);
      this.log(`Eval ${description || 'expression'}: Success`, result);
      return result;
    } catch (error) {
      this.log(`Eval ${description || 'expression'}: Failed`, error);
      throw error;
    }
  }

  /**
   * Get all visible text content
   */
  async getAllText() {
    const text = await this.page.evaluate(() => document.body.innerText);
    this.log('Page Text Content', text?.substring(0, 1000));
    return text;
  }

  /**
   * Save debug logs to file
   */
  saveDebugLogs() {
    const filename = `debug-${this.testName}-${Date.now()}.log`;
    const filepath = path.join(DEBUG_DIR, filename);
    fs.writeFileSync(filepath, this.debugLogs.join('\n'));
    this.log(`Debug logs saved to: ${filepath}`);
    return filepath;
  }

  /**
   * Print current debug state
   */
  printDebugState() {
    console.log('\n=== DEBUG STATE ===');
    console.log(`Test: ${this.testName}`);
    console.log(`URL: ${this.page.url()}`);
    console.log(`Debug Logs (last 10):`);
    console.log(this.debugLogs.slice(-10).join('\n'));
    console.log('==================\n');
  }
}

/**
 * Global debug helper instance
 */
let debugHelper: DebugHelper | null = null;

export function initDebugHelper(page: Page, testName: string): DebugHelper {
  debugHelper = new DebugHelper(page, testName);
  return debugHelper;
}

export function getDebugHelper(): DebugHelper {
  if (!debugHelper) {
    throw new Error('DebugHelper not initialized. Call initDebugHelper first.');
  }
  return debugHelper;
}
