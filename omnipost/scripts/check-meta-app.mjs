import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '../.env') });

const appId = process.env.FACEBOOK_APP_ID || '4446798632297061';
const appSecret = process.env.FACEBOOK_APP_SECRET;
if (!appSecret) {
  console.error('FACEBOOK_APP_SECRET missing from automation/.env.');
  console.error('It is deliberately NOT hardcoded here: this file sits in a tracked directory.');
  process.exit(2);
}
const appToken = `${appId}|${appSecret}`;

console.log(`Checking Meta App: ${appId}...`);

async function checkApp() {
  try {
    // 1. Basic App Info
    const url = `https://graph.facebook.com/v21.0/${appId}?access_token=${encodeURIComponent(appToken)}&fields=id,name,category,link,contact_email,website_url,privacy_policy_url,terms_of_service_url`;
    const res = await fetch(url);
    const data = await res.json();
    console.log('\n--- Meta App Details ---');
    console.log(JSON.stringify(data, null, 2));

    // 2. Token Debug / Validation
    const debugUrl = `https://graph.facebook.com/debug_token?input_token=${encodeURIComponent(appToken)}&access_token=${encodeURIComponent(appToken)}`;
    const debugRes = await fetch(debugUrl);
    const debugData = await debugRes.json();
    console.log('\n--- Token Debug Data ---');
    console.log(JSON.stringify(debugData, null, 2));

    // 3. Check App Permissions / Review Status (Permissions granted to App)
    const permsUrl = `https://graph.facebook.com/v21.0/${appId}/permissions?access_token=${encodeURIComponent(appToken)}`;
    const permsRes = await fetch(permsUrl);
    const permsData = await permsRes.json();
    console.log('\n--- App Permissions / Features ---');
    console.log(JSON.stringify(permsData, null, 2));

    // 4. Check Roles / Admins
    const rolesUrl = `https://graph.facebook.com/v21.0/${appId}/roles?access_token=${encodeURIComponent(appToken)}`;
    const rolesRes = await fetch(rolesUrl);
    const rolesData = await rolesRes.json();
    console.log('\n--- App Roles ---');
    console.log(JSON.stringify(rolesData, null, 2));

  } catch (err) {
    console.error('API check failed:', err);
  }
}

checkApp();
