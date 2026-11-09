#!/usr/bin/env node
/**
 * VBL Law Chambers - Google Drive & Local Vault Folder Organizer
 * Ensures every client will submission is isolated into its own dedicated subfolder
 * named: "[ReferenceID] - [ClientFullName]"
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const SUBMISSIONS_FILE = path.join(__dirname, '..', 'web', 'data', 'submissions.json');
const UPLOADS_DIR = path.join(__dirname, '..', 'web', 'uploads');
const GOOGLE_DRIVE_VAULT_ROOT_ID = '1Q171pLkFgucgHO0bJ1lRWlxC3en-tHZz';
const GOOGLE_DRIVE_VAULT_URL = `https://drive.google.com/drive/folders/${GOOGLE_DRIVE_VAULT_ROOT_ID}`;

console.log('================================================================');
console.log('🏛️  VBL LAW CHAMBERS - CLIENT VAULT & DRIVE FOLDER ORGANIZER');
console.log(`📂 Vault Root Folder ID: ${GOOGLE_DRIVE_VAULT_ROOT_ID}`);
console.log('================================================================\n');

if (!fs.existsSync(UPLOADS_DIR)) {
  fs.mkdirSync(UPLOADS_DIR, { recursive: true });
}

if (!fs.existsSync(SUBMISSIONS_FILE)) {
  console.error(`❌ Submissions file not found at: ${SUBMISSIONS_FILE}`);
  process.exit(1);
}

const rawData = fs.readFileSync(SUBMISSIONS_FILE, 'utf-8');
let submissions = [];
try {
  submissions = JSON.parse(rawData);
} catch (err) {
  console.error('❌ Failed to parse submissions.json:', err.message);
  process.exit(1);
}

console.log(`Found ${submissions.length} submission records in chambers registry.\n`);

let updatedCount = 0;

submissions = submissions.map((sub, index) => {
  const cleanName = (sub.fullName || 'Client').replace(/[/\\?%*:|"<>]/g, '').trim() || 'Client';
  const folderName = `${sub.refId} - ${cleanName}`;
  const clientDir = path.join(UPLOADS_DIR, folderName);

  if (!fs.existsSync(clientDir)) {
    fs.mkdirSync(clientDir, { recursive: true });
    console.log(`📁 Created local vault subfolder: ${folderName}`);
  }

  // Update record metadata
  let recordModified = false;
  if (!sub.folderName || sub.folderName !== folderName) {
    sub.folderName = folderName;
    recordModified = true;
  }
  if (!sub.driveFolderName || sub.driveFolderName !== folderName) {
    sub.driveFolderName = folderName;
    recordModified = true;
  }
  if (!sub.driveFolderUrl) {
    sub.driveFolderUrl = GOOGLE_DRIVE_VAULT_URL;
    recordModified = true;
  }

  // Update documents inside this submission
  if (Array.isArray(sub.documents)) {
    sub.documents = sub.documents.map((doc, docIdx) => {
      let docModified = false;
      if (!doc.folderName) {
        doc.folderName = folderName;
        docModified = true;
      }
      if (!doc.driveFolderName) {
        doc.driveFolderName = folderName;
        docModified = true;
      }
      if (!doc.driveFolderUrl) {
        doc.driveFolderUrl = GOOGLE_DRIVE_VAULT_URL;
        docModified = true;
      }
      if (docModified) recordModified = true;
      return doc;
    });
  }

  if (recordModified) updatedCount++;

  console.log(`[${index + 1}/${submissions.length}] Record: ${sub.refId}`);
  console.log(`     Client: ${sub.fullName}`);
  console.log(`     Drive Subfolder Name: "${folderName}"`);
  console.log(`     Local Path: ${clientDir}`);
  console.log(`     Drive Vault: ${sub.driveFolderUrl}\n`);

  return sub;
});

// Save updated submissions
fs.writeFileSync(SUBMISSIONS_FILE, JSON.stringify(submissions, null, 2), 'utf-8');

console.log('----------------------------------------------------------------');
console.log(`✅ Organization complete. All ${submissions.length} client folders structured successfully.`);
console.log(`📁 Local upload folders verified under: ${UPLOADS_DIR}`);
console.log(`☁️  Google Drive target: ${GOOGLE_DRIVE_VAULT_URL}`);
console.log('================================================================\n');
