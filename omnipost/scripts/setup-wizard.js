#!/usr/bin/env node
/**
 * OmniPost Universal Interactive Setup Wizard
 *
 * Guides any user or developer through setting up OmniPost in under 2 minutes:
 * - Generates secure random passkeys
 * - Configures Local Mode (zero config) or Supabase Cloud Mode
 * - Walks through social channel credentials with guided links
 * - Validates configuration and safely writes .env
 */

import readline from 'node:readline';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');
const ENV_PATH = path.join(ROOT_DIR, '.env');
const ENV_EXAMPLE_PATH = path.join(ROOT_DIR, '.env.example');

// Terminal Colors
const C = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  cyan: '\x1b[36m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  red: '\x1b[31m',
  white: '\x1b[37m'
};

function banner() {
  console.log(`
${C.cyan}${C.bold}================================================================${C.reset}
${C.bold}    🚀 OMNIPOST — UNIVERSAL SOCIAL PUBLISHING SETUP WIZARD    ${C.reset}
${C.cyan}================================================================${C.reset}
${C.dim}Publish to Instagram, Facebook, Threads, LinkedIn, YouTube & Pinterest.${C.reset}
`);
}

function generateRandomKey(prefix = 'key', len = 24) {
  return `${prefix}_${crypto.randomBytes(len).toString('hex')}`;
}

function parseEnv(content) {
  const result = {};
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx !== -1) {
      const key = trimmed.slice(0, eqIdx).trim();
      let val = trimmed.slice(eqIdx + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      result[key] = val;
    }
  }
  return result;
}

function stringifyEnv(existingEnv, newValues) {
  const merged = { ...existingEnv, ...newValues };
  let lines = [
    '# =================================================================',
    '# OmniPost Universal Social Automation & Publishing Engine',
    `# Configured via Setup Wizard on ${new Date().toISOString()}`,
    '# =================================================================',
    ''
  ];

  const sections = [
    {
      title: '1. CORE SYSTEM & SECURITY PASSKEYS',
      keys: ['PORT', 'CHAMBERS_ADMIN_SECRET_KEY', 'AUTOMATION_SECRET_KEY', 'SESSION_SECRET_KEY']
    },
    {
      title: '2. DATABASE CONFIGURATION (Supabase or Local Mode)',
      keys: ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'SUPABASE_ANON_KEY', 'SUPABASE_JWT_SECRET']
    },
    {
      title: '3. META GRAPH API (Facebook, Instagram, Threads)',
      keys: [
        'META_GRAPH_VERSION',
        'META_APP_ID',
        'META_APP_SECRET',
        'FACEBOOK_PAGE_ID',
        'FACEBOOK_PAGE_ACCESS_TOKEN',
        'INSTAGRAM_ACCOUNT_ID',
        'INSTAGRAM_ACCESS_TOKEN',
        'THREADS_USER_ID',
        'THREADS_ACCESS_TOKEN'
      ]
    },
    {
      title: '4. LINKEDIN PUBLISHING',
      keys: ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AUTHOR_URN']
    },
    {
      title: '5. PINTEREST PUBLISHING',
      keys: ['PINTEREST_ACCESS_TOKEN', 'PINTEREST_BOARD_ID']
    },
    {
      title: '6. N8N & YOUTUBE WORKFLOWS',
      keys: ['N8N_INTERNAL_URL', 'N8N_PUBLIC_URL', 'N8N_ENCRYPTION_KEY', 'N8N_WEBHOOK_SECRET']
    }
  ];

  const writtenKeys = new Set();

  for (const s of sections) {
    lines.push(`\n# -----------------------------------------------------------------`);
    lines.push(`# ${s.title}`);
    lines.push(`# -----------------------------------------------------------------`);
    for (const k of s.keys) {
      const val = merged[k] !== undefined ? merged[k] : '';
      lines.push(`${k}=${val}`);
      writtenKeys.add(k);
    }
  }

  // Any remaining keys
  const remaining = Object.keys(merged).filter(k => !writtenKeys.has(k));
  if (remaining.length > 0) {
    lines.push(`\n# -----------------------------------------------------------------`);
    lines.push(`# 7. ADDITIONAL SETTINGS`);
    lines.push(`# -----------------------------------------------------------------`);
    for (const k of remaining) {
      lines.push(`${k}=${merged[k]}`);
    }
  }

  return lines.join('\n') + '\n';
}

function prompt(rl, question, defaultValue = '') {
  return new Promise((resolve) => {
    const defaultHint = defaultValue ? ` ${C.dim}(default: ${defaultValue})${C.reset}` : '';
    rl.question(`${C.bold}${question}${defaultHint}:${C.reset} `, (answer) => {
      resolve(answer.trim() || defaultValue);
    });
  });
}

async function main() {
  banner();

  const isCheckOnly = process.argv.includes('--check');
  const isDefaultOnly = process.argv.includes('--defaults');

  let existingEnv = {};
  if (fs.existsSync(ENV_PATH)) {
    console.log(`${C.green}✓ Existing .env file found at: ${ENV_PATH}${C.reset}`);
    existingEnv = parseEnv(fs.readFileSync(ENV_PATH, 'utf-8'));
  } else if (fs.existsSync(ENV_EXAMPLE_PATH)) {
    console.log(`${C.yellow}ℹ No .env file found. Loading template from .env.example${C.reset}`);
    existingEnv = parseEnv(fs.readFileSync(ENV_EXAMPLE_PATH, 'utf-8'));
  }

  if (isCheckOnly) {
    console.log(`\n${C.bold}Configuration Status Check:${C.reset}`);
    const channels = [
      { name: 'Admin Security Key', ok: Boolean(existingEnv.CHAMBERS_ADMIN_SECRET_KEY) },
      { name: 'Automation Secret Key', ok: Boolean(existingEnv.AUTOMATION_SECRET_KEY) },
      { name: 'Supabase Database', ok: Boolean(existingEnv.SUPABASE_URL && existingEnv.SUPABASE_SERVICE_ROLE_KEY) },
      { name: 'Facebook Page', ok: Boolean(existingEnv.FACEBOOK_PAGE_ACCESS_TOKEN && existingEnv.FACEBOOK_PAGE_ID) },
      { name: 'Instagram', ok: Boolean(existingEnv.INSTAGRAM_ACCESS_TOKEN && existingEnv.INSTAGRAM_ACCOUNT_ID) },
      { name: 'Threads', ok: Boolean(existingEnv.THREADS_ACCESS_TOKEN && existingEnv.THREADS_USER_ID) },
      { name: 'LinkedIn', ok: Boolean(existingEnv.LINKEDIN_ACCESS_TOKEN && existingEnv.LINKEDIN_AUTHOR_URN) },
      { name: 'Pinterest', ok: Boolean(existingEnv.PINTEREST_ACCESS_TOKEN && existingEnv.PINTEREST_BOARD_ID) },
      { name: 'n8n Workflow Hub', ok: Boolean(existingEnv.N8N_INTERNAL_URL || existingEnv.N8N_PUBLIC_URL) }
    ];

    channels.forEach(c => {
      console.log(`  ${c.ok ? `${C.green}✓ Ready` : `${C.yellow}○ Unconfigured`}${C.reset} — ${c.name}`);
    });
    console.log('');
    process.exit(0);
  }

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  const updates = {};

  try {
    console.log(`${C.bold}STEP 1: Security & API Passkeys${C.reset}`);
    console.log(`${C.dim}These keys protect your studio dashboard, REST API, and webhook triggers.${C.reset}\n`);

    const defaultAdminKey = existingEnv.CHAMBERS_ADMIN_SECRET_KEY || generateRandomKey('chambers_admin');
    const adminKey = isDefaultOnly ? defaultAdminKey : await prompt(rl, 'Chambers / Admin Secret Key', defaultAdminKey);
    updates.CHAMBERS_ADMIN_SECRET_KEY = adminKey;

    const defaultAutoKey = existingEnv.AUTOMATION_SECRET_KEY || generateRandomKey('automation_key');
    const autoKey = isDefaultOnly ? defaultAutoKey : await prompt(rl, 'Automation / Webhook API Key', defaultAutoKey);
    updates.AUTOMATION_SECRET_KEY = autoKey;

    const defaultSessionKey = existingEnv.SESSION_SECRET_KEY || generateRandomKey('session', 32);
    updates.SESSION_SECRET_KEY = defaultSessionKey;

    console.log(`\n${C.bold}STEP 2: Storage & Database Mode${C.reset}`);
    console.log(`${C.dim}OmniPost supports zero-config Local Mode (runs out of the box) or Supabase Cloud Mode.${C.reset}`);
    console.log(`  1) Local Mode (Zero setup! Uses local JSON cache & local media storage)`);
    console.log(`  2) Supabase Cloud Mode (PostgreSQL database + Supabase Storage)`);

    const dbChoice = isDefaultOnly ? '1' : await prompt(rl, 'Choose Database Mode [1 or 2]', existingEnv.SUPABASE_URL ? '2' : '1');

    if (dbChoice === '2') {
      updates.SUPABASE_URL = await prompt(rl, 'Supabase URL (e.g. https://xyz.supabase.co)', existingEnv.SUPABASE_URL || '');
      updates.SUPABASE_SERVICE_ROLE_KEY = await prompt(rl, 'Supabase Service Role Key', existingEnv.SUPABASE_SERVICE_ROLE_KEY || '');
      updates.SUPABASE_ANON_KEY = await prompt(rl, 'Supabase Anon Key (optional)', existingEnv.SUPABASE_ANON_KEY || '');
    } else {
      console.log(`${C.green}✓ Running in Local Mode — no external database credentials required.${C.reset}`);
    }

    console.log(`\n${C.bold}STEP 3: Social Platform Credentials (Optional)${C.reset}`);
    console.log(`${C.dim}You can configure only the channels you want now, and add more anytime later.${C.reset}\n`);

    const configureSocial = isDefaultOnly ? 'n' : await prompt(rl, 'Would you like to configure social channels now? [y/N]', 'n');

    if (configureSocial.toLowerCase() === 'y') {
      console.log(`\n${C.cyan}--- LinkedIn ---${C.reset}`);
      console.log(`${C.dim}Get access token from: https://www.linkedin.com/developers/tools/oauth${C.reset}`);
      const liToken = await prompt(rl, 'LinkedIn Access Token (press Enter to skip)', existingEnv.LINKEDIN_ACCESS_TOKEN || '');
      if (liToken) {
        updates.LINKEDIN_ACCESS_TOKEN = liToken;
        updates.LINKEDIN_AUTHOR_URN = await prompt(rl, 'LinkedIn Author URN (e.g. urn:li:person:12345)', existingEnv.LINKEDIN_AUTHOR_URN || '');
      }

      console.log(`\n${C.cyan}--- Meta (Facebook, Instagram & Threads) ---${C.reset}`);
      console.log(`${C.dim}Get access tokens from: https://developers.facebook.com/tools/explorer/${C.reset}`);
      const fbToken = await prompt(rl, 'Facebook Page Access Token (press Enter to skip)', existingEnv.FACEBOOK_PAGE_ACCESS_TOKEN || '');
      if (fbToken) {
        updates.FACEBOOK_PAGE_ACCESS_TOKEN = fbToken;
        updates.FACEBOOK_PAGE_ID = await prompt(rl, 'Facebook Page ID', existingEnv.FACEBOOK_PAGE_ID || '');
      }

      const igToken = await prompt(rl, 'Instagram Access Token (press Enter to skip)', existingEnv.INSTAGRAM_ACCESS_TOKEN || '');
      if (igToken) {
        updates.INSTAGRAM_ACCESS_TOKEN = igToken;
        updates.INSTAGRAM_ACCOUNT_ID = await prompt(rl, 'Instagram Business Account ID', existingEnv.INSTAGRAM_ACCOUNT_ID || '');
      }

      console.log(`\n${C.cyan}--- Pinterest ---${C.reset}`);
      console.log(`${C.dim}Get access token from: https://developers.pinterest.com/apps/${C.reset}`);
      const pinToken = await prompt(rl, 'Pinterest Access Token (press Enter to skip)', existingEnv.PINTEREST_ACCESS_TOKEN || '');
      if (pinToken) {
        updates.PINTEREST_ACCESS_TOKEN = pinToken;
        updates.PINTEREST_BOARD_ID = await prompt(rl, 'Pinterest Board ID', existingEnv.PINTEREST_BOARD_ID || '');
      }
    } else {
      console.log(`${C.dim}Skipped social credentials. You can add them to .env anytime or via the web studio.${C.reset}`);
    }

    updates.PORT = existingEnv.PORT || '3300';

    // Backup existing .env if present
    if (fs.existsSync(ENV_PATH)) {
      const backupPath = path.join(ROOT_DIR, `.env.backup.${Date.now()}`);
      fs.copyFileSync(ENV_PATH, backupPath);
      console.log(`\n${C.dim}Created backup of previous .env at: ${backupPath}${C.reset}`);
    }

    // Write new .env
    const newContent = stringifyEnv(existingEnv, updates);
    fs.writeFileSync(ENV_PATH, newContent, 'utf-8');

    console.log(`\n${C.green}${C.bold}================================================================${C.reset}`);
    console.log(`${C.green}${C.bold}    ✓ OMNIPOST SETUP COMPLETED SUCCESSFULLY!                  ${C.reset}`);
    console.log(`${C.green}${C.bold}================================================================${C.reset}`);

    console.log(`
${C.bold}Your Access Credentials:${C.reset}
  - Web Studio URL:         ${C.cyan}http://localhost:3300${C.reset}
  - Studio Login Passcode:  ${C.green}${updates.CHAMBERS_ADMIN_SECRET_KEY}${C.reset}
  - Webhook / API Key:      ${C.green}${updates.AUTOMATION_SECRET_KEY}${C.reset}

${C.bold}To start OmniPost now:${C.reset}
  ${C.cyan}npm run dev${C.reset}          (starts both API and Web UI)
  ${C.dim}or${C.reset}
  ${C.cyan}docker compose up -d${C.reset} (starts all containers in background)

${C.bold}Developer Integration:${C.reset}
  Send a test webhook:
  ${C.dim}curl -X POST http://localhost:3300/api/webhook/publish \\
    -H "x-api-key: ${updates.AUTOMATION_SECRET_KEY}" \\
    -H "Content-Type: application/json" \\
    -d '{"title": "Hello World", "caption": "First post from OmniPost!", "platforms": ["linkedin"]}'${C.reset}
`);
  } finally {
    rl.close();
  }
}

main().catch((err) => {
  console.error(`${C.red}Setup failed:${C.reset}`, err.message);
  process.exit(1);
});
